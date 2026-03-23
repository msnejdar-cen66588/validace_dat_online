"""Agent 8: Odhadce (Tržní ocenění) – Porovnávací metoda.

Strategie:
1. Načte reálné inzeráty rodinných domů ze sreality.cz API (s obrázky a funkčními URL).
2. Pro každý vzorek stáhne DETAIL se strukturovanými daty (plocha, stav, rok, pozemek).
3. Předá vzorky + fotky vzorků i oceňovaného domu AI, která přidělí korekční koeficienty K1–K8.
4. Backend přesně dopočítá NHZP z koeficientů (AI jen koeficienty, nepočítá NHZP).
"""
import json
import math
import os
import re

import httpx
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient
from config import GEMINI_API_KEY, GEMINI_MODEL, UPLOAD_DIR


# ── Povinné rozsahy koeficientů (sdílené mezi sanitize i compute) ─────────────
COEFFICIENT_RANGES = {
    "k1": (0.80, 0.90),   # Redukce pramene ceny (vždy ~0.85 for inzerce)
    "k2": (0.90, 1.10),   # Velikost objektu
    "k3": (0.90, 1.10),   # Poloha
    "k4": (0.85, 1.15),   # Provedení / vybavení
    "k5": (0.80, 1.20),   # Celkový stav
    "k6": (0.90, 1.10),   # Vliv pozemku
    "k7": (0.95, 1.05),   # Úvaha znalce
    "k8": (0.95, 1.05),   # Energetická náročnost
}


# ── Prompt pro AI – přesný výpočet NHZP porovnávací metodou ─────────────────
COEFFICIENT_PROMPT = """Jsi soudní znalec a bankovní odhadce nemovitostí s 20letou praxí v ČR.
Provádíš ocenění rodinného domu POROVNÁVACÍ METODOU (NHZP) přesně dle české
metodiky znaleckých posudků.

Dostaneš:
- Parametry oceňovaného domu (adresa, plocha, stav, atd.)
- Fotografie oceňovaného domu – PEČLIVĚ je analyzuj pro posouzení
  technického stavu, kvality provedení, stáří, vybavení
- Seznam kandidátních vzorků ze sreality.cz SE STRUKTUROVANÝMI daty
  (plocha, stav, rok stavby, pozemek, typ domu)
- U každého vzorku jeho FOTOGRAFII – porovnej vizuálně stav vzorku
  se stavem oceňovaného domu

═══ PŘESNÝ POSTUP ═══

KROK 1 – VÝBĚR VZORKŮ:
Z kandidátů vyber přesně 3 NEJPODOBNĚJŠÍ vzorky. Kritéria výběru (v pořadí priority):
a) Velikost domu (m²) – co nejbližší k oceňovanému
b) Stav a stáří – přednost podobnému technickému stavu (využij data i fotky!)
c) Lokalita – přednost bližší poloze
Nevhodné kandidáty (odlišný charakter, příliš velký/malý) VYNECH.

KROK 2 – KOEFICIENTY K1–K8 (pro KAŽDÝ vybraný vzorek):
Koeficienty vyjadřují poměr VZORKU k NAŠEMU domu:
• K = 1.00 → vlastnost je shodná
• K < 1.00 → vzorek je v této vlastnosti LEPŠÍ než náš dům
• K > 1.00 → vzorek je v této vlastnosti HORŠÍ než náš dům

POVINNÉ ROZSAHY (STRIKTNĚ dodržuj!):
• K1 (Redukce pramene ceny) = VŽDY 0.85 pro inzerátové ceny
• K2 (Velikost objektu):   0.90 – 1.10
• K3 (Poloha):             0.90 – 1.10
• K4 (Provedení/vybavení): 0.85 – 1.15
  → POROVNEJ fotky vzorku vs. oceňovaného domu!
• K5 (Celkový stav):       0.80 – 1.20
  → POROVNEJ fotky vzorku vs. oceňovaného domu + využij pole "stav" vzorku!
• K6 (Vliv pozemku):       0.90 – 1.10
• K7 (Úvaha znalce):       0.95 – 1.05
• K8 (Energ. náročnost):   0.95 – 1.05

⚠️ K1 musí být VŽDY 0.85! Toto je standardní redukce za inzerční cenu.

⚠️ NEPOČÍTEJ NHZP! Výpočet provede backend. Ty vrátíš POUZE koeficienty.

═══ VÝSTUPNÍ FORMÁT ═══
Vrať POUZE validní JSON (BEZ Markdown, BEZ ```json):
{
  "duvod": "<2–3 věty: proč tyto vzorky, komentář k trhu v lokalitě>",
  "vzorky": [
    {
      "id": <id z vstupu>,
      "koeficienty": {"k1": 0.85, "k2": ..., "k3": ..., "k4": ..., "k5": ..., "k6": ..., "k7": ..., "k8": ...},
      "oduvodneni_koeficientu": "<stručné zdůvodnění pro každý K, který se liší od 1.00>"
    }
  ]
}"""


# ── Mapování okresu na district_id sreality ───────────────────────────────────
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


def _find_district_id(address: str) -> int | None:
    """Try to match address to a district_id using DISTRICT_MAP."""
    addr_lower = address.lower()
    # Try longest keys first for better matching
    for key in sorted(DISTRICT_MAP.keys(), key=len, reverse=True):
        if key in addr_lower:
            return DISTRICT_MAP[key]
    return None


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
    count: int = 8,
    district_id: int | None = None,
) -> list[dict]:
    """Načte reálné inzeráty RD ze sreality.cz API filtrované GPS a plochou."""

    # Velikostní rozsah: plocha ±40 % (min 40 m², max 400 m²)
    size_min = max(40, int(floor_area_m2 * 0.6))
    size_max = min(400, int(floor_area_m2 * 1.4))

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
    elif district_id:
        params["locality_district_id"] = district_id

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
        obrazek_url = re.sub(r"fl=res,\d+,\d+", "fl=res,800,600", raw_img) if raw_img else None

        name = e.get("name", "")

        # Lidsky čitelná adresa
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

        # Parse plocha z názvu jako záloha (bude přepsána z detailu)
        m2_matches = re.findall(r"(\d+)\s*m²", name)
        size_m2 = int(m2_matches[0]) if m2_matches else 0
        land_m2 = int(m2_matches[1]) if len(m2_matches) > 1 else 0

        results.append({
            "id": i,
            "hash_id": hash_id,
            "adresa": adresa,
            "cena_czk": price,
            "velikost_domu_m2": size_m2,
            "velikost_pozemku_m2": land_m2,
            "stav": "",
            "rok_stavby": "",
            "typ_domu": "",
            "pocet_podlazi": "",
            "zdroj_url": zdroj_url,
            "obrazek_url": obrazek_url,
        })

    return results


async def _fetch_sample_detail(hash_id: int | str) -> dict:
    """Fetch structured detail data for a single estate from Sreality detail API."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": "https://www.sreality.cz/",
    }
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(
                f"https://www.sreality.cz/api/cs/v2/estates/{hash_id}",
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"Sreality detail fetch error for {hash_id}: {e}")
        return {}

    items = data.get("items", [])
    detail = {}
    for item in items:
        name = (item.get("name") or "").strip()
        value = item.get("value")
        name_lower = name.lower()

        if "užitná" in name_lower and "ploch" in name_lower:
            try:
                detail["usable_area"] = int(re.sub(r"[^\d]", "", str(value)))
            except (ValueError, TypeError):
                pass
        elif "celková plocha" == name_lower or "celková ploch" in name_lower:
            if "usable_area" not in detail:
                try:
                    detail["usable_area"] = int(re.sub(r"[^\d]", "", str(value)))
                except (ValueError, TypeError):
                    pass
        elif "plocha pozemku" in name_lower:
            try:
                detail["land_area"] = int(re.sub(r"[^\d]", "", str(value)))
            except (ValueError, TypeError):
                pass
        elif "stav objektu" in name_lower or "stav" == name_lower:
            detail["condition"] = str(value).strip()
        elif "rok kolaudace" in name_lower or "rok dokončení" in name_lower:
            try:
                detail["year_built"] = str(value).strip()
            except (ValueError, TypeError):
                pass
        elif "typ domu" in name_lower or "poloha domu" in name_lower:
            detail["house_type"] = str(value).strip()
        elif "podlaží" in name_lower:
            detail["floors"] = str(value).strip()

    return detail


async def _download_image_bytes(url: str, max_bytes: int = 200_000) -> bytes | None:
    """Download image from URL and return bytes (for AI). Limits size to save RAM."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.sreality.cz/",
    }
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.content
            if len(data) > max_bytes:
                return None  # Too large, skip
            return data
    except Exception:
        return None


class OdhadceAgent(BaseAgent):
    """Agent 8: Odhadce – určuje NHZP porovnávací metodou s reálnými vzorky ze sreality.cz."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="Odhadce",
            description="Určuje tržní hodnotu nemovitosti (NHZP) porovnávací metodou – reálné vzorky ze sreality.cz + AI koeficienty.",
            system_prompt=COEFFICIENT_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        self.log("Zahajuji odhad obvyklé tržní ceny (NHZP)...", "info")

        if not self.client:
            self.log("Chybí API klíč.", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary="Odhadce nedostupný (chybí API).",
                errors=["API klíč nenalezen."]
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

        floor_area_int = int(re.sub(r"[^0-9]", "", str(floor_area)) or "120") or 120

        # ── Geokódování + DISTRICT_MAP fallback ──────────────────────────────
        self.log("Geokuduji adresu nemovitosti...", "thinking")
        coords = await _geocode_address(address)
        district_id = None

        if not coords:
            self.log("GPS geokódování selhalo, zkouším okres z adresy...", "warn")
            district_id = _find_district_id(address)
            if district_id:
                self.log(f"Nalezen okres (district_id={district_id}), hledám vzorky dle okresu.", "info")
            else:
                self.log("Nepodařilo se identifikovat okres z adresy.", "warn")

        # ── Načti reálné vzorky ze sreality (GPS + velikost) ─────────────────
        raw_samples: list[dict] = []
        if coords:
            lat, lon = coords
            for radius in (2, 5):
                self.log(f"Hledám RD do {radius} km od {address}...", "thinking")
                raw_samples = await _fetch_sreality_samples(lat, lon, floor_area_int, radius_km=radius, count=8)
                if len(raw_samples) >= 3:
                    break
        elif district_id:
            self.log(f"Hledám RD v okrese (fallback)...", "thinking")
            raw_samples = await _fetch_sreality_samples(None, None, floor_area_int, district_id=district_id, count=8)

        if len(raw_samples) < 3:
            msg = "Pro zpracování online ocenění je v okruhu do 5 km od nemovitosti málo srovnatelných vzorků."
            self.log(msg, "warn")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary=msg,
                errors=[msg]
            )

        # ── Stáhni detaily vzorků (strukturovaná data) ───────────────────────
        self.log(f"Stahuji detaily {len(raw_samples)} vzorků ze Sreality...", "thinking")
        import asyncio
        detail_tasks = []
        for s in raw_samples:
            if s.get("hash_id"):
                detail_tasks.append(_fetch_sample_detail(s["hash_id"]))
            else:
                detail_tasks.append(asyncio.coroutine(lambda: {})())

        details = await asyncio.gather(*detail_tasks, return_exceptions=True)

        for s, detail in zip(raw_samples, details):
            if isinstance(detail, Exception) or not isinstance(detail, dict):
                continue
            # Přepiš data z detailu (strukturovaná → přesná)
            if detail.get("usable_area") and detail["usable_area"] > 0:
                s["velikost_domu_m2"] = detail["usable_area"]
            if detail.get("land_area") and detail["land_area"] > 0:
                s["velikost_pozemku_m2"] = detail["land_area"]
            if detail.get("condition"):
                s["stav"] = detail["condition"]
            if detail.get("year_built"):
                s["rok_stavby"] = detail["year_built"]
            if detail.get("house_type"):
                s["typ_domu"] = detail["house_type"]
            if detail.get("floors"):
                s["pocet_podlazi"] = detail["floors"]

        # Filtruj vzorky bez validní plochy (dosadíme z názvu nebo skipneme)
        for s in raw_samples:
            if not s["velikost_domu_m2"] or s["velikost_domu_m2"] <= 0:
                s["velikost_domu_m2"] = floor_area_int  # fallback
        
        enriched_count = sum(1 for s in raw_samples if s.get("stav"))
        self.log(f"Detail stažen: {enriched_count}/{len(raw_samples)} vzorků má strukturovaná data (stav, rok...).", "info")

        # ── Příprava fotek oceňované nemovitosti pro AI ──────────────────────
        from google.genai import types as genai_types
        contents_parts: list = []
        images_data = context.get("images") or []
        photos_sent = 0

        contents_parts.append("=== FOTOGRAFIE OCEŇOVANÉHO DOMU ===\n")
        for img_info in images_data[:4]:  # max 4 photos
            img_path = img_info.get("processed_path", "")
            if img_path and os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as f:
                        img_bytes = f.read()
                    contents_parts.append(
                        genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                    )
                    photos_sent += 1
                except Exception:
                    pass

        if photos_sent > 0:
            self.log(f"Odesílám {photos_sent} fotek oceňované nemovitosti k analýze AI...", "info")

        # ── Stáhni fotky vzorků pro AI ──────────────────────────────────
        sample_photos_sent = 0
        contents_parts.append("\n=== FOTOGRAFIE VZORKŮ ZE SREALITY ===\n")
        
        photo_tasks = []
        for s in raw_samples[:5]:  # max 5 sample photos
            url = s.get("obrazek_url")
            if url:
                photo_tasks.append(_download_image_bytes(url))
            else:
                photo_tasks.append(asyncio.coroutine(lambda: None)())

        sample_photos = await asyncio.gather(*photo_tasks, return_exceptions=True)

        for s, photo_data in zip(raw_samples[:5], sample_photos):
            if isinstance(photo_data, bytes) and photo_data:
                contents_parts.append(f"Fotografie vzorku #{s['id']} ({s['adresa']}):")
                contents_parts.append(
                    genai_types.Part.from_bytes(data=photo_data, mime_type="image/jpeg")
                )
                sample_photos_sent += 1

        if sample_photos_sent > 0:
            self.log(f"Odesílám {sample_photos_sent} fotek vzorků pro vizuální porovnání.", "info")

        # ── Prompt pro AI ────────────────────────────────────────────────────
        vzorky_text = json.dumps(
            [{
                "id": s["id"],
                "adresa": s["adresa"],
                "cena_czk": s["cena_czk"],
                "velikost_domu_m2": s["velikost_domu_m2"],
                "velikost_pozemku_m2": s["velikost_pozemku_m2"],
                "stav": s.get("stav") or "neznámý",
                "rok_stavby": s.get("rok_stavby") or "neznámý",
                "typ_domu": s.get("typ_domu") or "neznámý",
            } for s in raw_samples],
            ensure_ascii=False, indent=2
        )

        prompt_text = (
            f"\nParametry oceňovaného rodinného domu:\n"
            f"- Adresa: {address}\n"
            f"- Podlahová/Užitná plocha: {floor_area} m²\n"
            f"- Plocha pozemku: {land_area} m²\n"
            f"- Stav: {condition}\n"
            f"- Střecha: {roof}\n"
            f"- Vytápění: {heating}\n"
        )
        if photos_sent > 0:
            prompt_text += (
                f"\nK oceňovanému domu jsou přiloženy {photos_sent} fotografie výše. "
                f"PEČLIVĚ je analyzuj pro posouzení technického stavu, kvality "
                f"provedení a vybavení. Tyto poznatky MUSÍ ovlivnit koeficienty K4 a K5.\n"
            )
        if sample_photos_sent > 0:
            prompt_text += (
                f"\nK vzorkům jsou přiloženy {sample_photos_sent} fotografie výše. "
                f"POROVNEJ vizuálně stav vzorků se stavem oceňovaného domu "
                f"při stanovování koeficientů K4 a K5.\n"
            )
        prompt_text += (
            f"\nKandidáti ze sreality.cz (s detailními strukturovanými daty):\n{vzorky_text}\n\n"
            f"Vyber 3 nejpodobnější vzorky a PŘIŘAĎ koeficienty K1–K8 dle instrukcí. "
            f"K1 MUSÍ být 0.85 u všech vzorků. "
            f"NEPOČÍTEJ NHZP – vrať POUZE koeficienty v JSON formátu."
        )

        # Build content list: photos first, then text
        contents_parts.append(prompt_text)

        self.log(f"Kandidátů: {len(raw_samples)}, AI vybírá nejpodobnější a stanovuje koeficienty...", "info")

        try:
            response_text = await self.client.generate_content(
                system_instruction=self.system_prompt,
                contents=contents_parts,
                response_mime_type="application/json",
                max_output_tokens=3500,
                temperature=0.3,
            )

            # Strip markdown wrapping if present
            raw_text = response_text.strip()
            for prefix in ("```json", "```"):
                if raw_text.startswith(prefix):
                    raw_text = raw_text[len(prefix):]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            result_json = json.loads(raw_text)

            # ── Compute NHZP from coefficients (backend is authoritative) ────
            ai_vzorky = result_json.get("vzorky", [])
            
            # Validate: at least 1 sample returned
            if not ai_vzorky:
                return AgentResult(
                    status=AgentStatus.FAIL,
                    summary="AI nevrátila žádné vzorky s koeficienty.",
                    errors=["AI odpověď neobsahuje pole 'vzorky'."]
                )

            nhzp = self._compute_nhzp(ai_vzorky, raw_samples, floor_area_int)

            if nhzp <= 0:
                return AgentResult(
                    status=AgentStatus.FAIL,
                    summary="AI nedokázala vypočítat NHZP.",
                    errors=["Výpočet NHZP selhal."]
                )

            # ── Sanity checks ────────────────────────────────────────────────
            warnings = []
            if nhzp > 25_000_000:
                warnings.append(f"NHZP {nhzp:,.0f} Kč je neobvykle vysoká pro běžný RD.")
            if nhzp < 500_000:
                warnings.append(f"NHZP {nhzp:,.0f} Kč je neobvykle nízká.")

            # Cap at max selected sample price × 1.15
            ai_vzorky_by_id = {v["id"]: v for v in ai_vzorky}
            selected_ids = set(ai_vzorky_by_id.keys())
            selected_raw = [s for s in raw_samples if s["id"] in selected_ids]
            if not selected_raw:
                selected_raw = raw_samples

            max_sample_price = max((s["cena_czk"] for s in selected_raw), default=0)
            max_reasonable = int(max_sample_price * 1.15)
            if nhzp > max_reasonable and max_reasonable > 0:
                warnings.append(
                    f"NHZP {nhzp:,.0f} Kč překračovala max. cenu vybraného vzorku ({max_sample_price:,.0f} Kč). "
                    f"Zastropováno na {max_reasonable:,.0f} Kč."
                )
                nhzp = max_reasonable

            # Floor check: should not be below 30% of min sample price
            min_sample_price = min((s["cena_czk"] for s in selected_raw), default=0)
            min_reasonable = int(min_sample_price * 0.30)
            if nhzp < min_reasonable and min_reasonable > 0:
                warnings.append(
                    f"NHZP {nhzp:,.0f} Kč byla pod 30 % min. ceny vzorku ({min_sample_price:,.0f} Kč). "
                    f"Dno nastaveno na {min_reasonable:,.0f} Kč."
                )
                nhzp = min_reasonable

            odhad_m = nhzp / 1_000_000

            # ── Merge AI coefficients back into real samples ──────────────────
            backend_url = os.getenv("BACKEND_URL", "https://validace-rd-backend.onrender.com")
            merged_vzorky = []
            for s in raw_samples:
                if s["id"] not in selected_ids:
                    continue
                ai = ai_vzorky_by_id.get(s["id"], {})
                raw_img = s["obrazek_url"]
                proxy_img = f"{backend_url}/api/proxy-image?url={raw_img}" if raw_img else None

                koef = ai.get("koeficienty", {})
                sanitized_koef = self._sanitize_coefficients(koef)

                # Compute per-sample values for display
                sample_area = max(s.get("velikost_domu_m2") or floor_area_int, 10)
                jc = s["cena_czk"] / sample_area
                io = 1.0
                for k in ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8"]:
                    io *= sanitized_koef[k]

                merged_vzorky.append({
                    "id": s["id"],
                    "adresa": s["adresa"],
                    "cena_czk": s["cena_czk"],
                    "velikost_domu_m2": s["velikost_domu_m2"],
                    "velikost_pozemku_m2": s.get("velikost_pozemku_m2", 0),
                    "stav": s.get("stav", ""),
                    "rok_stavby": s.get("rok_stavby", ""),
                    "typ_domu": s.get("typ_domu", ""),
                    "zdroj_url": s["zdroj_url"],
                    "obrazek_url": proxy_img,
                    "koeficienty": sanitized_koef,
                    "jc": round(jc),
                    "io": round(io, 4),
                    "upravena_jc": round(jc * io),
                    "oduvodneni_koeficientu": ai.get("oduvodneni_koeficientu", ""),
                })

            self.log(f"Odhad dokončen: {odhad_m:.1f} mil. Kč", "info")
            return AgentResult(
                status=AgentStatus.SUCCESS,
                summary=f"Odhadní cena: {odhad_m:.2f} mil. Kč. Vzorky z reálné inzerce.",
                details={
                    "odhad_czk": nhzp,
                    "duvod": result_json.get("duvod", result_json.get("duvod_odhadu", "")),
                    "vzorky": merged_vzorky,
                    "plocha_ocenovaneho": floor_area_int,
                    "analyzed_params": {
                        "address": address,
                        "area": floor_area,
                        "condition": condition,
                    }
                },
                warnings=warnings,
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

    @staticmethod
    def _sanitize_coefficients(koef: dict) -> dict:
        """Sanitize coefficients to strict ranges (shared with frontend)."""
        sanitized = {}
        for k in ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8"]:
            raw = koef.get(k, 1.0 if k != "k1" else 0.85)
            try:
                val = float(str(raw).replace(",", "."))
                # Guard against AI returning percentages (e.g. 85 instead of 0.85)
                if val > 5.0:
                    val = val / 100.0
                lo, hi = COEFFICIENT_RANGES.get(k, (0.80, 1.20))
                val = max(lo, min(val, hi))
            except (ValueError, TypeError):
                val = 0.85 if k == "k1" else 1.0
            sanitized[k] = round(val, 2)
        return sanitized

    @staticmethod
    def _compute_nhzp(
        ai_vzorky: list[dict],
        raw_samples: list[dict],
        floor_area_int: int,
    ) -> int:
        """Compute NHZP from coefficients using the exact porovnávací metoda formula.
        
        Uses the SAME coefficient ranges as _sanitize_coefficients for consistency.
        """
        total_upravena_jc = 0
        count_ok = 0

        for v in ai_vzorky:
            sid = v.get("id")
            src = next((s for s in raw_samples if s["id"] == sid), None)
            if not src or not src.get("cena_czk"):
                continue

            sample_area = max(src.get("velikost_domu_m2") or floor_area_int, 10)
            jc = src["cena_czk"] / sample_area  # Unit price Kč/m²

            # Compute IO = product of K1..K8 (using same ranges as sanitize)
            io = 1.0
            koef = v.get("koeficienty") or {}
            for k in ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8"]:
                raw_k = koef.get(k, 1.0 if k != "k1" else 0.85)
                try:
                    num = float(str(raw_k).replace(",", "."))
                    if num > 5.0:
                        num = num / 100.0
                    lo, hi = COEFFICIENT_RANGES.get(k, (0.80, 1.20))
                    num = max(lo, min(num, hi))
                except (ValueError, TypeError):
                    num = 0.85 if k == "k1" else 1.0
                io *= num

            upravena_jc = jc * io
            total_upravena_jc += upravena_jc
            count_ok += 1

        if count_ok == 0:
            return 0

        avg_upravena_jc = total_upravena_jc / count_ok
        nhzp = round(avg_upravena_jc * floor_area_int)
        return nhzp
