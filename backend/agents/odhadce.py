"""Agent 8: Odhadce (Tržní ocenění) – Porovnávací metoda.

Strategie:
1. Načte reálné inzeráty rodinných domů ze sreality.cz API (s obrázky a funkčními URL).
2. Předá tyto reálné vzorky Gemini, který přidělí korekční koeficienty K1–K8.
3. Výsledek obsahuje reálné obrázky, funkční odkaz na inzerát a AI komentáře.
"""
import json
import re

import httpx
from google import genai
from google.genai import types

from agents.base import BaseAgent, AgentResult, AgentStatus
from config import GEMINI_API_KEY, GEMINI_MODEL


# ── Prompt pro Gemini – výběr nejpodobnějších + přiřazení koeficientů ───────
COEFFICIENT_PROMPT = """Jsi expertní bankovní odhadce nemovitostí v ČR.
Dostaneš parametry oceňovaného rodinného domu a SEZNAM KANDIDÁTŮ ze sreality.cz.

KROK 1 – VÝBĚR: Z kandidátů vyber právě 3 (max 5) NEJPODOBNĚJŠÍ vzorky dle:
- Velikost objektu (m²) – co nejbližší k oceňované nemovitosti
- Stav nemovitosti – přednost stejnému nebo podobnému stavu
- Poloha – přednost bližší lokalitě (id s nižším číslem = nalezeno dříve v bližším okruhu)
Candidáty, kteří jsou nevhodní (příliš velcí/malí, jiný charakter), VYNECH.

KROK 2 – KOEFICIENTY: Ke každému vybranému vzorku přiřaď 8 koeficientů (K1–K8).
Metodika (vzorek vs. náš dům):
- K = 1.00 → vlastnost totožná
- K < 1.00 → vzorek je LEPŠÍ (snižuje upravenou cenu)
- K > 1.00 → vzorek je HORŠÍ (zvyšuje upravenou cenu)
Rozsahy:
- K1 (Redukce pramene ceny): 0.80–0.90 (standardně 0.85 pro inzerci)
- K2 (Velikost objektu): 0.90–1.10
- K3 (Poloha): 0.90–1.10
- K4 (Provedení a vybavení): 0.90–1.10
- K5 (Celkový stav): 0.85–1.15
- K6 (Vliv pozemku): 0.90–1.10
- K7 (Úvaha zpracovatele): 0.95–1.05
- K8 (Energetická náročnost): 0.90–1.10

Vrať POUZE validní JSON (bez Markdown):
{
  "zakladni_odhad_czk": <číslo>,
  "duvod_odhadu": "<stručný komentář: proč tyto vzorky, trh v lokalitě>",
  "vzorky": [
    {
      "id": <id z vstupu – pouze vybrané>,
      "koeficienty": {"k1": 0.85, "k2": 1.00, "k3": 1.00, "k4": 1.00, "k5": 1.00, "k6": 1.00, "k7": 1.00, "k8": 1.00},
      "oduvodneni_koeficientu": "<zdůvodnění odlišností>"
    }
  ]
}
"""


# ── Mapování okresu na district_id sreality ───────────────────────────────────
# Klíč = lowercase název; hodnota = locality_district_id
DISTRICT_MAP: dict[str, int] = {
    # Jihomoravský kraj
    "brno-město": 72, "brno city": 72, "brno": 72,
    "brno-venkov": 73, "ivančice": 73, "oslavany": 73, "rosice": 73, "zastávka": 73,
    "blansko": 74, "hodonín": 75, "vyškov": 76, "znojmo": 77,
    # Praha
    "praha": 10, "prague": 10,
    # Jihočeský kraj
    "české budějovice": 2, "český krumlov": 3, "jindřichův hradec": 4,
    "písek": 5, "prachatice": 6, "strakonice": 7, "tábor": 8,
    # Plzeňský kraj
    "domažlice": 11, "klatovy": 12, "plzeň-město": 13, "plzeň-jih": 14,
    "plzeň-sever": 15, "rokycany": 16, "tachov": 17,
    # Karlovarský kraj
    "cheb": 18, "karlovy vary": 19, "sokolov": 20,
    # Ústecký kraj
    "děčín": 21, "chomutov": 22, "litoměřice": 23, "louny": 24,
    "most": 25, "teplice": 26, "ústí nad labem": 27,
    # Liberecký kraj
    "česká lípa": 28, "jablonec nad nisou": 29, "liberec": 30, "semily": 31,
    # Královéhradecký kraj
    "hradec králové": 32, "jičín": 33, "náchod": 34, "rychnov nad kněžnou": 35, "trutnov": 36,
    # Pardubický kraj
    "chrudim": 37, "pardubice": 38, "svitavy": 39, "ústí nad orlicí": 40,
    # Kraj vysočina
    "havlíčkův brod": 41, "jihlava": 42, "pelhřimov": 43, "třebíč": 44, "žďár nad sázavou": 45,
    # Středočeský kraj
    "benešov": 46, "beroun": 47, "kladno": 48, "kolín": 49, "kutná hora": 50,
    "mělník": 51, "mladá boleslav": 52, "nymburk": 53, "praha-východ": 54,
    "praha-západ": 55, "příbram": 56, "rakovník": 57,
    # Olomoucký kraj
    "jeseník": 58, "olomouc": 59, "prostějov": 60, "přerov": 61, "šumperk": 62,
    # Moravskoslezský kraj
    "bruntál": 63, "frýdek-místek": 64, "karviná": 65, "nový jičín": 66,
    "opava": 67, "ostrava-město": 68,
    # Zlínský kraj
    "kroměříž": 69, "uherské hradiště": 70, "vsetín": 71, "zlín": 78,
}


async def _geocode_address(address: str) -> tuple[float, float] | None:
    """Geocode address to (lat, lon) using Nominatim (free OpenStreetMap API)."""
    params = {
        "q": address + ", Česká republika",
        "format": "json",
        "limit": 1,
        "countrycodes": "cz",
    }
    headers = {"User-Agent": "OnlineOceneni/1.0 (valuation-tool)"}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get("https://nominatim.openstreetmap.org/search",
                                    params=params, headers=headers)
            resp.raise_for_status()
            results = resp.json()
            if results:
                return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"Nominatim geocoding error: {e}")
    return None


async def _fetch_sreality_samples(
    lat: float | None,
    lon: float | None,
    floor_area_m2: int,
    radius_km: int = 5,
    count: int = 5,
) -> list[dict]:
    """Načte reálné inzeráty RD ze sreality.cz API filtrované GPS a plochou."""

    # Velikostní rozsah: plocha ±50 % (min 40 m², max 400 m²)
    size_min = max(40, int(floor_area_m2 * 0.5))
    size_max = min(400, int(floor_area_m2 * 1.5))

    params: dict = {
        "category_main_cb": 2,    # nemovitosti
        "category_sub_cb": 37,    # rodinné domy
        "category_type_cb": 1,    # prodej
        "usable_area_min": size_min,
        "usable_area_max": size_max,
        "per_page": count,
        "sort": 0,
    }
    if lat and lon:
        params["locality_gps_lat"] = round(lat, 6)
        params["locality_gps_lon"] = round(lon, 6)
        params["locality_gps_radius"] = radius_km

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.sreality.cz/",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get("https://www.sreality.cz/api/cs/v2/estates",
                                    params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"Sreality fetch error: {e}")
        return []

    estates = data.get("_embedded", {}).get("estates", [])
    results = []
    for i, e in enumerate(estates, 1):
        seo = e.get("seo", {})
        hash_id = e.get("hash_id")
        locality_slug = seo.get("locality", "")
        zdroj_url = (
            f"https://www.sreality.cz/detail/prodej/dum/rodinny/{locality_slug}/{hash_id}"
            if hash_id else None
        )

        images = e.get("_links", {}).get("images", [])
        raw_img = images[0].get("href") if images else None
        # Větší rozlišení
        obrazek_url = re.sub(r"fl=res,\d+,\d+", "fl=res,800,600", raw_img) if raw_img else None

        name = e.get("name", "")
        m2_matches = re.findall(r"(\d+)\s*m²", name)
        size_m2 = int(m2_matches[0]) if m2_matches else floor_area_m2
        land_m2 = int(m2_matches[1]) if len(m2_matches) > 1 else 0

        # Lidsky čitelná adresa ze seo.locality slugu
        def slug_to_address(slug: str) -> str:
            parts = [p for p in slug.split("-") if p]
            unique: list[str] = []
            for p in parts:
                if not unique or p != unique[-1]:
                    unique.append(p)
            return ", ".join(w.capitalize() for w in unique if w)

        adresa = slug_to_address(locality_slug) if locality_slug else name

        price = e.get("price_czk", {}).get("value_raw", 0) or 0
        if price <= 1:
            continue

        results.append({
            "id": i,
            "adresa": adresa,
            "cena_czk": price,
            "velikost_domu_m2": size_m2,
            "velikost_pozemku_m2": land_m2,
            "zdroj_url": zdroj_url,
            "obrazek_url": obrazek_url,
        })

    return results


class OdhadceAgent(BaseAgent):
    """Agent 8: Odhadce – určuje NHZP porovnávací metodou s reálnými vzorky ze sreality.cz."""

    def __init__(self):
        super().__init__(
            name="Odhadce",
            description="Určuje tržní hodnotu nemovitosti (NHZP) porovnávací metodou – reálné vzorky ze sreality.cz + AI koeficienty.",
            system_prompt=COEFFICIENT_PROMPT,
        )
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

    async def run(self, context: dict) -> AgentResult:
        self.log("Zahajuji odhad obvyklé tržní ceny (NHZP)...", "info")

        if not self.client:
            self.log("Chybí Gemini API klíč.", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary="Odhadce nedostupný (chybí API).",
                errors=["Gemini API klíč nenalezen."]
            )

        # ── Vstupní parametry ─────────────────────────────────────────────────
        prop_data = context.get("property_data") or {}
        address = context.get("property_address") or prop_data.get("adresa") or "Česká republika"
        floor_area = prop_data.get("celkova_podlahova_plocha") or "Neznámá"
        condition = prop_data.get("stav_rodinneho_domu") or "Neznámý stav"
        roof = prop_data.get("typ_strechy") or "Neznámá střecha"
        heating = prop_data.get("typ_vytapeni") or "Neznámé vytápění"

        overrides = context.get("valuation_overrides") or {}
        address = overrides.get("adresa") or address
        floor_area = overrides.get("plocha") or floor_area
        condition = overrides.get("stav") or condition
        land_area = overrides.get("pozemek") or prop_data.get("plocha_pozemku") or "Neznámá"

        # ── Načti reálné vzorky ze sreality (GPS + velikost) ─────────────────
        self.log("Geokuduji adresu nemovitosti...", "thinking")
        floor_area_int = int(re.sub(r"[^0-9]", "", str(floor_area)) or "120") or 120
        coords = await _geocode_address(address)

        raw_samples: list[dict] = []
        if coords:
            lat, lon = coords
            # Progresivní rozšiřování okruhu: 2 → 5 → 10 → 15 → 30 km
            for radius in (2, 5, 10, 15, 30):
                self.log(f"Hledám RD do {radius} km od {address}...", "thinking")
                # Fetch 10 candidates per pass so Gemini can pick the best 3–5
                raw_samples = await _fetch_sreality_samples(lat, lon, floor_area_int, radius_km=radius, count=10)
                if len(raw_samples) >= 3:
                    break
        
        # Fallback bez GPS – celá ČR s filtrem velikosti
        if len(raw_samples) < 3:
            self.log("Rozšiřuji hledání na celou ČR (filtr velikosti)...", "info")
            raw_samples = await _fetch_sreality_samples(None, None, floor_area_int, count=10)

        if not raw_samples:
            return AgentResult(
                status=AgentStatus.FAIL,
                summary="Nepodařilo se načíst vzorky ze sreality.cz.",
                errors=["Sreality API nedostupné nebo žádné inzeráty."]
            )

        self.log(f"Nalezeno {len(raw_samples)} kandidátů, AI vybírá nejpodobnější a přiřazuje koeficienty...", "info")

        # ── Prompt pro Gemini – výběr + koeficienty ──────────────────────────
        vzorky_text = json.dumps(
            [{
                "id": s["id"],
                "adresa": s["adresa"],
                "cena_czk": s["cena_czk"],
                "velikost_domu_m2": s["velikost_domu_m2"],
                "velikost_pozemku_m2": s["velikost_pozemku_m2"],
            } for s in raw_samples],
            ensure_ascii=False, indent=2
        )

        prompt_text = (
            f"Parametry oceňovaného rodinného domu:\n"
            f"- Adresa: {address}\n"
            f"- Podlahová/Užitná plocha: {floor_area} m²\n"
            f"- Plocha pozemku: {land_area} m²\n"
            f"- Stav: {condition}\n"
            f"- Střecha: {roof}\n"
            f"- Vytápění: {heating}\n\n"
            f"Kandidáti ze sreality.cz (seřazeni od nejbližší lokality):\n{vzorky_text}\n\n"
            f"Vyber 3–5 NEJPODOBNĚJŠÍCH kandidátů (dle velikosti, stavu a polohy), "
            f"přiřaď jim K1–K8 a vypočítej zakladni_odhad_czk. "
            f"Vrať POUZE čistý JSON dle instrukce."
        )

        try:
            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    response_mime_type="application/json",
                    max_output_tokens=1500,
                ),
            )

            # Strip markdown wrapping if present
            raw_text = response.text.strip()
            for prefix in ("```json", "```"):
                if raw_text.startswith(prefix):
                    raw_text = raw_text[len(prefix):]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            result_json = json.loads(raw_text)
            zakladni_odhad = result_json.get("zakladni_odhad_czk", 0)

            # ── Fallback: pokud AI vynechala odhad, spočítáme ho matematicky ─
            if not zakladni_odhad:
                total_jc = 0
                count_ok = 0
                for v in result_json.get("vzorky", []):
                    sid = v.get("id")
                    src = next((s for s in raw_samples if s["id"] == sid), None)
                    if not src or not src["cena_czk"]:
                        continue
                    io = 1.0
                    for k, kv in (v.get("koeficienty") or {}).items():
                        try:
                            num = float(str(kv).replace(",", "."))
                            io *= max(0.55, min(num, 1.45))
                        except (ValueError, TypeError):
                            pass
                    area = max(src["velikost_domu_m2"] or floor_area_int, 10)
                    total_jc += (src["cena_czk"] / area) * io
                    count_ok += 1
                if count_ok:
                    zakladni_odhad = round((total_jc / count_ok) * floor_area_int)

            odhad_m = zakladni_odhad / 1_000_000

            # ── Merge koeficientů od AI zpět do reálných vzorků ──────────────
            # Only keep the samples that Gemini selected (by id)
            ai_vzorky_by_id = {v["id"]: v for v in result_json.get("vzorky", [])}
            selected_ids = set(ai_vzorky_by_id.keys())
            import os
            backend_url = os.getenv("BACKEND_URL", "https://validace-rd-backend.onrender.com")
            merged_vzorky = []
            for s in raw_samples:
                if s["id"] not in selected_ids:
                    continue  # AI tenhle kandidát nevybrala
                ai = ai_vzorky_by_id.get(s["id"], {})
                raw_img = s["obrazek_url"]
                proxy_img = f"{backend_url}/api/proxy-image?url={raw_img}" if raw_img else None
                merged_vzorky.append({
                    "id": s["id"],
                    "adresa": s["adresa"],
                    "cena_czk": s["cena_czk"],
                    "velikost_domu_m2": s["velikost_domu_m2"],
                    "velikost_pozemku_m2": s.get("velikost_pozemku_m2", 0),
                    "stav": s.get("stav", ""),
                    "zdroj_url": s["zdroj_url"],
                    "obrazek_url": proxy_img,
                    "koeficienty": ai.get("koeficienty", {}),
                    "oduvodneni_koeficientu": ai.get("oduvodneni_koeficientu", ""),
                })

            self.log(f"Odhad dokončen: {odhad_m:.1f} mil. Kč", "info")
            return AgentResult(
                status=AgentStatus.SUCCESS,
                summary=f"Odhadní cena: {odhad_m:.2f} mil. Kč. Vzorky z reálné inzerce.",
                details={
                    "odhad_czk": zakladni_odhad,
                    "duvod": result_json.get("duvod_odhadu", ""),
                    "vzorky": merged_vzorky,
                    "analyzed_params": {
                        "address": address,
                        "area": floor_area,
                        "condition": condition,
                    }
                }
            )

        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print(f"OdhadceAgent error: {tb}")
            self.log(f"Chyba při tvorbě odhadu: {e}", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary="Odhad se nepodařilo dokončit.",
                errors=[str(e)]
            )
