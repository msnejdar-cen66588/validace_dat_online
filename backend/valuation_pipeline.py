"""Valuation Pipeline – 4-step sub-agent orchestrator for NHZP market valuation.

Steps:
1. SběračVzorků  – Apify data fetch, geocode, filter
2. AnalytikVzorků – AI selects top 5 samples (text only, no photos)
3. KoeficientovýZnalec – AI photo+data comparison → K1–K8
4. CenovýKalkulátor – Backend NHZP math, confidence, benchmarks
"""
import asyncio
import gc
import json
import os
import re
import time
from typing import Optional

from fastapi import WebSocket

from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from agents.odhadce import (
    _geocode_address, _find_district_id, _fetch_apify_samples,
    _download_image_bytes, _haversine_km,
    COEFFICIENT_RANGES, BENCHMARK_CZK_PER_M2,
)
from config import UPLOAD_DIR


# ── Step definitions for frontend ─────────────────────────────────────────────
VALUATION_STEPS = [
    {"key": "collector", "icon": "📡", "label": "Sběrač vzorků",
     "desc": "Stahování reálných inzerátů z realitních portálů a geokódování adresy."},
    {"key": "analyst", "icon": "🔎", "label": "Analytik vzorků",
     "desc": "AI vybírá nejpodobnější vzorky podle velikosti, stavu a lokality."},
    {"key": "coefficients", "icon": "⚖️", "label": "Koeficientový znalec",
     "desc": "AI porovnává fotografie a data, stanovuje korekční koeficienty K1–K8."},
    {"key": "calculator", "icon": "🧮", "label": "Cenový kalkulátor",
     "desc": "Výpočet tržní hodnoty (NHZP), confidence score a benchmarky."},
]


# ── AI Prompts ────────────────────────────────────────────────────────────────

ANALYST_PROMPT = """Jsi soudní znalec s 20letou praxí v ocenění nemovitostí v ČR.
Tvým úkolem je VYBRAT 5 nejpodobnějších vzorků z kandidátů pro porovnávací metodu (NHZP).

Dostaneš parametry oceňovaného domu a seznam kandidátních vzorků.

KRITÉRIA VÝBĚRU (v pořadí priority):
1. Velikost domu (m²) – co nejbližší k oceňovanému
2. Stav a stáří – podobný technický stav a rok stavby
3. Lokalita – přednost bližší poloze (vzdálenost v km je uvedena)
4. Typ domu – přednost stejnému typu (řadový, samostatný, dvojdomek)

PRAVIDLA:
- Vyber přesně 5 vzorků (nebo všechny, pokud je jich méně)
- Minimum 3 vzorky
- Odmítni vzorky s odlišným charakterem (byt vs dům, příliš velký rozdíl v ploše)
- Pro každý vybraný vzorek uveď SKÓRE PODOBNOSTI (0-100) a zdůvodnění

Vrať POUZE validní JSON:
{
  "selected_ids": [1, 3, 5, 7, 9],
  "reasoning": "<2-3 věty o trhu v lokalitě a strategii výběru>",
  "samples": [
    {"id": 1, "similarity_score": 85, "why": "<proč je tento vzorek vhodný>"},
    ...
  ]
}"""

COEFFICIENT_PROMPT = """Jsi soudní znalec a bankovní odhadce nemovitostí s 20letou praxí v ČR.
Stanovuješ korekční koeficienty K1–K8 pro porovnávací metodu (NHZP).

Dostaneš:
- Parametry oceňovaného domu + jeho FOTOGRAFIE
- 5 vybraných vzorků ze sreality.cz s jejich daty
- U některých vzorků FOTOGRAFIE – PEČLIVĚ je porovnej s oceňovaným domem

KOEFICIENTY vyjadřují poměr VZORKU k NAŠEMU domu:
• K = 1.00 → vlastnost je shodná
• K < 1.00 → vzorek je v této vlastnosti LEPŠÍ než náš dům
• K > 1.00 → vzorek je v této vlastnosti HORŠÍ než náš dům

POVINNÉ ROZSAHY:
• K1 (Redukce pramene ceny) = VŽDY 0.90
• K2 (Velikost objektu):   0.50 – 2.00
• K3 (Poloha):             0.50 – 2.00
• K4 (Provedení/vybavení): 0.50 – 2.00 → POROVNEJ fotky!
• K5 (Celkový stav):       0.50 – 2.00 → POROVNEJ fotky + pole "stav"!
• K6 (Vliv pozemku):       0.50 – 2.00
• K7 (Úvaha znalce):       0.50 – 2.00
• K8 (Energ. náročnost):   0.50 – 2.00

Vrať POUZE validní JSON:
{
  "vzorky": [
    {
      "id": <id>,
      "koeficienty": {"k1": 0.90, "k2": ..., "k3": ..., "k4": ..., "k5": ..., "k6": ..., "k7": ..., "k8": ...},
      "oduvodneni_koeficientu": "<zdůvodnění pro každý K ≠ 1.00>"
    }
  ]
}

⚠️ MUSÍŠ vrátit koeficienty pro KAŽDÝ vzorek! Pokud dostaneš 5 vzorků, vrať 5 objektů v poli "vzorky".
Každý vzorek MUSÍ mít vlastní sadu K1–K8 – NEKOPÍRUJ koeficienty z jiného vzorku!
⚠️ K1 = 0.90 u VŠECH vzorků, ale K2–K8 se MUSÍ lišit podle konkrétních vlastností každého vzorku."""


class ValuationPipeline:
    """Orchestrates 4-step valuation with WebSocket progress updates."""

    def __init__(self, session_id: str, model_name: str = "gemini", ws_registry: dict = None):
        self.session_id = session_id
        self.model_name = model_name
        self.ws_registry = ws_registry or {}
        self.current_step = 0

    def _get_connections(self) -> list[WebSocket]:
        """Look up WS connections from registry."""
        return self.ws_registry.get(self.session_id, [])

    async def broadcast(self, message: dict):
        connections = self._get_connections()
        print(f"[Valuation] Broadcasting {message.get('type', '?')} to {len(connections)} WS connections")
        for ws in connections:
            try:
                await ws.send_json(message)
            except Exception as e:
                print(f"[Valuation] WS send error: {e}")

    async def _notify_step(self, step_key: str, status: str, message: str = ""):
        print(f"[Valuation] Step {step_key} → {status}: {message}")
        await self.broadcast({
            "type": "valuation_step",
            "session_id": self.session_id,
            "step": step_key,
            "status": status,
            "message": message,
            "timestamp": time.time(),
        })

    async def run(self, context: dict) -> dict:
        """Run the full 4-step valuation pipeline."""
        start_time = time.time()
        print(f"[Valuation] Pipeline starting for session {self.session_id}, model={self.model_name}")

        await self.broadcast({
            "type": "valuation_start",
            "session_id": self.session_id,
            "steps": VALUATION_STEPS,
            "timestamp": start_time,
        })

        try:
            # ── Step 1: Collect Samples ──
            print("[Valuation] === Step 1: Collect Samples ===")
            await self._notify_step("collector", "processing", "Geokóduji adresu...")
            step1 = await self._step_collect(context)
            gc.collect()
            if step1.get("error"):
                print(f"[Valuation] Step 1 FAILED: {step1['error']}")
                await self._notify_step("collector", "fail", step1["error"])
                return self._fail_result(step1["error"], start_time)
            print(f"[Valuation] Step 1 OK: {len(step1['raw_samples'])} samples")
            await self._notify_step("collector", "success",
                f"Nalezeno {len(step1['raw_samples'])} kandidátů")

            # ── Step 2: Analyze & Select Samples ──
            print("[Valuation] === Step 2: Analyze Samples ===")
            await self._notify_step("analyst", "processing", "AI analyzuje kandidáty...")
            step2 = await self._step_analyze(context, step1)
            gc.collect()
            if step2.get("error"):
                print(f"[Valuation] Step 2 FAILED: {step2['error']}")
                await self._notify_step("analyst", "fail", step2["error"])
                return self._fail_result(step2["error"], start_time)
            print(f"[Valuation] Step 2 OK: {len(step2['selected_samples'])} selected")
            await self._notify_step("analyst", "success",
                f"Vybráno {len(step2['selected_samples'])} nejpodobnějších vzorků")

            # ── Step 3: Compute Coefficients ──
            print("[Valuation] === Step 3: Compute Coefficients ===")
            await self._notify_step("coefficients", "processing",
                "AI porovnává fotografie a stanovuje koeficienty...")
            step3 = await self._step_coefficients(context, step1, step2)
            gc.collect()
            if step3.get("error"):
                print(f"[Valuation] Step 3 FAILED: {step3['error']}")
                await self._notify_step("coefficients", "fail", step3["error"])
                return self._fail_result(step3["error"], start_time)
            print(f"[Valuation] Step 3 OK: {len(step3.get('ai_vzorky', []))} vzorky with coefficients")
            await self._notify_step("coefficients", "success",
                "Koeficienty K1–K8 stanoveny pro všechny vzorky")

            # ── Step 4: Calculate NHZP ──
            print("[Valuation] === Step 4: Calculate NHZP ===")
            await self._notify_step("calculator", "processing", "Počítám NHZP...")
            result = self._step_calculate(context, step1, step2, step3)
            print(f"[Valuation] Step 4 OK: NHZP = {result.get('details', {}).get('odhad_czk', '?')}")
            await self._notify_step("calculator", "success",
                f"Odhad: {result['details']['odhad_czk']/1e6:.2f} mil. Kč")

            total_time = round(time.time() - start_time, 2)
            result["details"]["total_time"] = total_time
            print(f"[Valuation] Pipeline COMPLETE in {total_time}s")

            await self.broadcast({
                "type": "valuation_complete",
                "session_id": self.session_id,
                "result": result,
                "timestamp": time.time(),
            })

            return result

        except Exception as e:
            import traceback
            print(f"[Valuation] Pipeline EXCEPTION: {e}")
            traceback.print_exc()
            return self._fail_result(str(e), start_time)

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 1: Collect Samples (no AI)
    # ══════════════════════════════════════════════════════════════════════════
    async def _step_collect(self, context: dict) -> dict:
        prop_data = context.get("property_data") or {}
        address = context.get("property_address") or prop_data.get("adresa") or "Česká republika"
        floor_area = prop_data.get("celkova_podlahova_plocha") or "Neznámá"
        condition = prop_data.get("stav_rodinneho_domu") or "Neznámý stav"

        overrides = context.get("valuation_overrides") or {}
        address = overrides.get("adresa") or address
        floor_area = overrides.get("plocha") or floor_area
        condition = overrides.get("stav") or condition
        land_area = overrides.get("pozemek") or prop_data.get("plocha_pozemku") or "Neznámá"
        roof = prop_data.get("typ_strechy") or "Neznámá"
        heating = prop_data.get("typ_vytapeni") or "Neznámé"

        floor_area_int = int(re.sub(r"[^0-9]", "", str(floor_area)) or "120") or 120

        # Geocode
        await self._notify_step("collector", "processing", "Geokóduji adresu...")
        coords = await _geocode_address(address)
        district_id = _find_district_id(address)
        lat, lon = coords if coords else (None, None)

        # Fetch from Apify
        await self._notify_step("collector", "processing",
            "Stahuji vzorky z realitních portálů...")
        raw_samples = await _fetch_apify_samples(lat, lon, floor_area_int, count=15)

        # Filter invalid prices
        valid = []
        for s in raw_samples:
            area = max(s.get("velikost_domu_m2") or floor_area_int, 10)
            jc = s["cena_czk"] / area
            if 10_000 <= jc <= 250_000:
                valid.append(s)
        raw_samples = valid

        # Fallback floor area
        for s in raw_samples:
            if not s["velikost_domu_m2"] or s["velikost_domu_m2"] <= 0:
                s["velikost_domu_m2"] = floor_area_int

        # Geocode samples that lack GPS (so they appear on the map)
        samples_needing_gps = [s for s in raw_samples if not s.get("gps")]
        if samples_needing_gps:
            await self._notify_step("collector", "processing",
                f"Geokóduji {len(samples_needing_gps[:5])} vzorků bez GPS...")
            for s in samples_needing_gps[:5]:  # max 5 to avoid rate limits
                try:
                    addr = s.get("adresa", "")
                    if addr:
                        gc = await _geocode_address(addr)
                        if gc:
                            s["gps"] = {"lat": gc[0], "lon": gc[1]}
                            if lat and lon:
                                s["distance_km"] = round(_haversine_km(lat, lon, gc[0], gc[1]), 1)
                        await asyncio.sleep(1.1)  # Nominatim rate limit
                except Exception:
                    pass

        if len(raw_samples) < 3:
            return {"error": "Nedostatek srovnatelných vzorků na trhu (minimum 3)."}

        return {
            "raw_samples": raw_samples,
            "address": address,
            "floor_area": floor_area,
            "floor_area_int": floor_area_int,
            "condition": condition,
            "land_area": land_area,
            "roof": roof,
            "heating": heating,
            "coords": coords,
            "district_id": district_id,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 2: AI Sample Selection (text only, no photos)
    # ══════════════════════════════════════════════════════════════════════════
    async def _step_analyze(self, context: dict, step1: dict) -> dict:
        client = LLMClient(model_name=self.model_name)

        samples_text = json.dumps([{
            "id": s["id"],
            "adresa": s["adresa"],
            "cena_czk": s["cena_czk"],
            "velikost_domu_m2": s["velikost_domu_m2"],
            "velikost_pozemku_m2": s.get("velikost_pozemku_m2", 0),
            "stav": s.get("stav") or "neznámý",
            "rok_stavby": s.get("rok_stavby") or "neznámý",
            "typ_domu": s.get("typ_domu") or "neznámý",
            "distance_km": s.get("distance_km"),
        } for s in step1["raw_samples"]], ensure_ascii=False, indent=2)

        prompt = (
            f"Parametry oceňovaného domu:\n"
            f"- Adresa: {step1['address']}\n"
            f"- Plocha: {step1['floor_area']} m²\n"
            f"- Stav: {step1['condition']}\n"
            f"- Pozemek: {step1['land_area']} m²\n\n"
            f"Kandidáti ({len(step1['raw_samples'])} ks):\n{samples_text}\n\n"
            f"Vyber 5 nejpodobnějších vzorků dle instrukcí."
        )

        try:
            resp = await client.generate_content(
                system_instruction=ANALYST_PROMPT,
                contents=[prompt],
                response_mime_type="application/json",
                max_output_tokens=2000,
                temperature=0.2,
            )
            del client
            result = robust_json_parse(resp)
            selected_ids = set(result.get("selected_ids", []))

            if not selected_ids:
                # Fallback: use first 5 by distance
                selected_ids = {s["id"] for s in step1["raw_samples"][:5]}

            selected = [s for s in step1["raw_samples"] if s["id"] in selected_ids]
            if len(selected) < 3:
                selected = step1["raw_samples"][:5]

            return {
                "selected_samples": selected,
                "selected_ids": {s["id"] for s in selected},
                "analyst_reasoning": result.get("reasoning", ""),
                "similarity_data": result.get("samples", []),
            }
        except Exception as e:
            # Fallback: pick top 5 by distance
            selected = step1["raw_samples"][:5]
            return {
                "selected_samples": selected,
                "selected_ids": {s["id"] for s in selected},
                "analyst_reasoning": f"Automatický výběr (AI selhala: {e})",
                "similarity_data": [],
            }

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 3: AI Coefficients with Photos
    # ══════════════════════════════════════════════════════════════════════════
    async def _step_coefficients(self, context: dict, step1: dict, step2: dict) -> dict:
        client = LLMClient(model_name=self.model_name)

        class _Img:
            def __init__(self, data: bytes, mime_type: str = "image/jpeg"):
                self.data = data
                self.mime_type = mime_type

        contents: list = []

        # Property photos (max 2)
        images_data = context.get("images") or []
        prop_photos = 0
        contents.append("=== FOTOGRAFIE OCEŇOVANÉHO DOMU ===\n")
        for img_info in images_data[:2]:
            path = img_info.get("processed_path", "")
            if path and os.path.exists(path):
                try:
                    with open(path, "rb") as f:
                        contents.append(_Img(data=f.read()))
                        prop_photos += 1
                except Exception:
                    pass

        await self._notify_step("coefficients", "processing",
            f"Odesílám {prop_photos} fotek oceňovaného domu...")

        # Sample photos (max 3)
        sample_photos = 0
        contents.append("\n=== FOTOGRAFIE VZORKŮ ===\n")
        sem = asyncio.Semaphore(2)

        async def _dl(s):
            url = s.get("obrazek_url")
            if not url:
                return (s, None)
            async with sem:
                try:
                    return (s, await _download_image_bytes(url))
                except Exception:
                    return (s, None)

        results = await asyncio.gather(*[_dl(s) for s in step2["selected_samples"][:3]])
        for s, data in results:
            if isinstance(data, bytes) and data:
                contents.append(f"Foto vzorku #{s['id']} ({s['adresa']}):")
                contents.append(_Img(data=data))
                sample_photos += 1

        await self._notify_step("coefficients", "processing",
            f"AI porovnává {prop_photos}+{sample_photos} fotek...")

        # Text data for all 5 selected samples
        vzorky_text = json.dumps([{
            "id": s["id"],
            "adresa": s["adresa"],
            "cena_czk": s["cena_czk"],
            "velikost_domu_m2": s["velikost_domu_m2"],
            "velikost_pozemku_m2": s.get("velikost_pozemku_m2", 0),
            "stav": s.get("stav") or "neznámý",
            "rok_stavby": s.get("rok_stavby") or "neznámý",
            "typ_domu": s.get("typ_domu") or "neznámý",
        } for s in step2["selected_samples"]], ensure_ascii=False, indent=2)

        prompt = (
            f"\nOceňovaný dům:\n"
            f"- Adresa: {step1['address']}\n"
            f"- Plocha: {step1['floor_area']} m²\n"
            f"- Pozemek: {step1['land_area']} m²\n"
            f"- Stav: {step1['condition']}\n"
            f"- Střecha: {step1['roof']}\n"
            f"- Vytápění: {step1['heating']}\n\n"
            f"Vybrané vzorky ({len(step2['selected_samples'])} ks):\n{vzorky_text}\n\n"
            f"Stanovi koeficienty K1–K8 pro KAŽDÝ vzorek. K1 MUSÍ být 0.90."
        )
        contents.append(prompt)

        try:
            resp = await client.generate_content(
                system_instruction=COEFFICIENT_PROMPT,
                contents=contents,
                response_mime_type="application/json",
                max_output_tokens=4000,
                temperature=0.3,
            )
            del contents
            del client
            gc.collect()

            result = robust_json_parse(resp)
            ai_vzorky = result.get("vzorky", [])
            if not ai_vzorky:
                return {"error": "AI nevrátila koeficienty."}

            # Ensure ALL samples have coefficients (fill missing with defaults)
            returned_ids = {v["id"] for v in ai_vzorky}
            for s in step2["selected_samples"]:
                if s["id"] not in returned_ids:
                    print(f"[Valuation] WARNING: AI skipped sample #{s['id']}, adding defaults")
                    ai_vzorky.append({
                        "id": s["id"],
                        "koeficienty": {"k1": 0.90, "k2": 1.0, "k3": 1.0, "k4": 1.0, "k5": 1.0, "k6": 1.0, "k7": 1.0, "k8": 1.0},
                        "oduvodneni_koeficientu": "Automatické výchozí hodnoty (AI nenastavila)"
                    })

            return {"ai_vzorky": ai_vzorky}
        except Exception as e:
            return {"error": f"Chyba AI koeficientů: {e}"}

    # ══════════════════════════════════════════════════════════════════════════
    # STEP 4: Calculate NHZP (no AI)
    # ══════════════════════════════════════════════════════════════════════════
    def _step_calculate(self, context: dict, step1: dict, step2: dict, step3: dict) -> dict:
        ai_vzorky = step3["ai_vzorky"]
        ai_by_id = {v["id"]: v for v in ai_vzorky}
        selected_ids = step2["selected_ids"]
        floor_area_int = step1["floor_area_int"]

        backend_url = os.getenv("BACKEND_URL", "https://validace-rd-backend.onrender.com")

        merged = []
        upravene_jc_list = []

        for s in step2["selected_samples"]:
            ai = ai_by_id.get(s["id"], {})
            koef = ai.get("koeficienty", {})
            sanitized = self._sanitize_coefficients(koef)

            area = max(s.get("velikost_domu_m2") or floor_area_int, 10)
            jc = s["cena_czk"] / area
            io = 1.0
            for k in ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8"]:
                io *= sanitized[k]

            upravene_jc_list.append(jc * io)

            raw_img = s.get("obrazek_url")
            proxy_img = f"{backend_url}/api/proxy-image?url={raw_img}" if raw_img else None

            merged.append({
                "id": s["id"],
                "adresa": s["adresa"],
                "cena_czk": s["cena_czk"],
                "velikost_domu_m2": s["velikost_domu_m2"],
                "velikost_pozemku_m2": s.get("velikost_pozemku_m2", 0),
                "stav": s.get("stav", ""),
                "rok_stavby": s.get("rok_stavby", ""),
                "typ_domu": s.get("typ_domu", ""),
                "zdroj_url": s.get("zdroj_url"),
                "obrazek_url": proxy_img,
                "koeficienty": sanitized,
                "jc": round(jc),
                "io": round(io, 4),
                "upravena_jc": round(jc * io),
                "oduvodneni_koeficientu": ai.get("oduvodneni_koeficientu", ""),
                "gps": s.get("gps"),
                "distance_km": s.get("distance_km"),
            })

        if not upravene_jc_list:
            return self._fail_result("Žádné vzorky pro výpočet.", time.time())

        import statistics
        mean_jc = statistics.mean(upravene_jc_list)
        nhzp_min = round(min(upravene_jc_list) * floor_area_int)
        nhzp_max = round(max(upravene_jc_list) * floor_area_int)
        # NHZP = exact midpoint of the range
        nhzp = round((nhzp_min + nhzp_max) / 2)

        # Warnings
        warnings = []
        if nhzp > 25_000_000:
            warnings.append(f"NHZP {nhzp:,.0f} Kč je neobvykle vysoká.")
        if nhzp < 500_000:
            warnings.append(f"NHZP {nhzp:,.0f} Kč je extrémně nízká.")

        # Benchmark
        benchmark = self._get_benchmark(step1["address"])

        # Confidence
        coords = step1.get("coords")
        enriched = sum(1 for s in step2["selected_samples"] if s.get("stav"))
        confidence = self._compute_confidence(
            step2["selected_samples"], floor_area_int,
            has_coords=coords is not None, enriched_count=enriched)

        return {
            "status": "success",
            "summary": f"Odhadní cena: {nhzp/1e6:.2f} mil. Kč ({nhzp_min/1e6:.2f}–{nhzp_max/1e6:.2f}). {len(merged)} vzorků, confidence {confidence['score']} %.",
            "details": {
                "odhad_czk": nhzp,
                "odhad_min": nhzp_min,
                "odhad_max": nhzp_max,
                "duvod": step2.get("analyst_reasoning", ""),
                "vzorky": merged,
                "plocha_ocenovaneho": floor_area_int,
                "property_gps": {"lat": coords[0], "lon": coords[1]} if coords else None,
                "benchmark": benchmark,
                "confidence": confidence,
                "analyzed_params": {
                    "address": step1["address"],
                    "area": step1["floor_area"],
                    "condition": step1["condition"],
                },
            },
            "warnings": warnings,
        }

    # ── Helpers (from OdhadceAgent) ───────────────────────────────────────────

    def _sanitize_coefficients(self, koef: dict) -> dict:
        sanitized = {}
        for k in ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8"]:
            raw = koef.get(k, 1.0 if k != "k1" else 0.90)
            try:
                val = float(str(raw).replace(",", "."))
                if val > 5.0:
                    val = val / 100.0
                lo, hi = COEFFICIENT_RANGES.get(k, (0.80, 1.20))
                val = max(lo, min(val, hi))
            except (ValueError, TypeError):
                val = 0.90 if k == "k1" else 1.0
            sanitized[k] = round(val, 2)
        return sanitized

    def _get_benchmark(self, address: str) -> dict | None:
        addr_lower = address.lower()
        for key in sorted(BENCHMARK_CZK_PER_M2.keys(), key=len, reverse=True):
            if key in addr_lower:
                return {"okres": key, "czk_per_m2": BENCHMARK_CZK_PER_M2[key]}
        return None

    def _compute_confidence(self, samples, floor_area, has_coords, enriched_count) -> dict:
        score = 50
        n = len(samples)
        if n >= 5: score += 15
        elif n >= 3: score += 10
        if has_coords: score += 10
        if enriched_count >= 3: score += 10
        elif enriched_count >= 1: score += 5

        import statistics
        areas = [s.get("velikost_domu_m2") or floor_area for s in samples]
        if areas:
            avg = statistics.mean(areas)
            diff = abs(floor_area - avg) / max(avg, 1)
            if diff < 0.15: score += 10
            elif diff < 0.30: score += 5

        distances = [s.get("distance_km") for s in samples if s.get("distance_km")]
        if distances:
            avg_d = statistics.mean(distances)
            if avg_d < 10: score += 10
            elif avg_d < 25: score += 5

        score = min(score, 100)
        level = "vysoká" if score >= 75 else "střední" if score >= 50 else "nízká"
        return {"score": score, "level": level}

    def _fail_result(self, error: str, start_time: float) -> dict:
        return {
            "status": "fail",
            "summary": error,
            "errors": [error],
            "details": {"total_time": round(time.time() - start_time, 2)},
        }
