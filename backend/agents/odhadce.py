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
import statistics

import httpx
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import UPLOAD_DIR


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


# ── Průměrné ceny za m² dle okresů (ČSÚ data 2024, Kč/m² užitné plochy RD) ──
# Slouží jako benchmark / kontrolní mechanismus pro NHZP
BENCHMARK_CZK_PER_M2: dict[str, int] = {
    # Praha a okolí
    "praha": 95000, "praha-východ": 68000, "praha-západ": 70000,
    # Jihomoravský kraj
    "brno-město": 62000, "brno": 62000, "brno-venkov": 42000,
    "blansko": 32000, "hodonín": 25000, "vyškov": 33000, "znojmo": 26000,
    # Středočeský kraj
    "benešov": 38000, "beroun": 45000, "kladno": 42000, "kolín": 35000,
    "kutná hora": 30000, "mělník": 38000, "mladá boleslav": 40000,
    "nymburk": 38000, "příbram": 32000, "rakovník": 30000,
    # Plzeňský kraj
    "plzeň-město": 48000, "plzeň-jih": 35000, "plzeň-sever": 32000,
    "domažlice": 26000, "klatovy": 28000, "rokycany": 33000, "tachov": 22000,
    # Karlovarský kraj
    "cheb": 22000, "karlovy vary": 28000, "sokolov": 18000,
    # Ústecký kraj
    "děčín": 18000, "chomutov": 16000, "litoměřice": 28000, "louny": 20000,
    "most": 14000, "teplice": 20000, "ústí nad labem": 18000,
    # Liberecký kraj
    "česká lípa": 24000, "jablonec nad nisou": 30000, "liberec": 32000, "semily": 28000,
    # Královéhradecký kraj
    "hradec králové": 40000, "jičín": 30000, "náchod": 26000,
    "rychnov nad kněžnou": 26000, "trutnov": 30000,
    # Pardubický kraj
    "chrudim": 30000, "pardubice": 38000, "svitavy": 24000, "ústí nad orlicí": 26000,
    # Kraj Vysočina
    "havlíčkův brod": 26000, "jihlava": 32000, "pelhřimov": 26000,
    "třebíč": 24000, "žďár nad sázavou": 28000,
    # Jihočeský kraj
    "české budějovice": 40000, "český krumlov": 32000, "jindřichův hradec": 24000,
    "písek": 30000, "prachatice": 24000, "strakonice": 26000, "tábor": 32000,
    # Olomoucký kraj
    "jeseník": 18000, "olomouc": 38000, "prostějov": 30000, "přerov": 26000, "šumperk": 22000,
    # Moravskoslezský kraj
    "bruntál": 16000, "frýdek-místek": 30000, "karviná": 16000,
    "nový jičín": 28000, "opava": 26000, "ostrava-město": 28000,
    # Zlínský kraj
    "kroměříž": 30000, "uherské hradiště": 30000, "vsetín": 26000, "zlín": 35000,
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
Z kandidátů vyber přesně 5 NEJPODOBNĚJŠÍCH vzorků. Kritéria výběru (v pořadí priority):
a) Velikost domu (m²) – co nejbližší k oceňovanému
b) Stav a stáří – přednost podobnému technickému stavu (využij data i fotky!)
c) Lokalita – přednost bližší poloze
Nevhodné kandidáty (odlišný charakter, příliš velký/malý) VYNECH.
Pokud je kandidátů méně než 5, vyber všechny vhodné (minimum 3).

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


# ── Skupiny okresů dle krajů (pro multi-district proximity search) ─────────────
# Sdružuje district_id ze Sreality do regionů, aby se prohledávaly i sousední okresy.
_REGION_GROUPS: list[list[int]] = [
    [2, 3, 4, 5, 6, 7, 8],                         # Jihočeský kraj
    [10, 54, 55],                                    # Praha + Praha-východ/západ
    [11, 12, 13, 14, 15, 16, 17],                   # Plzeňský kraj
    [18, 19, 20],                                    # Karlovarský kraj
    [21, 22, 23, 24, 25, 26, 27],                   # Ústecký kraj
    [28, 29, 30, 31],                                # Liberecký kraj
    [32, 33, 34, 35, 36],                            # Královéhradecký kraj
    [37, 38, 39, 40],                                # Pardubický kraj
    [41, 42, 43, 44, 45],                            # Kraj Vysočina
    [46, 47, 48, 49, 50, 51, 52, 53, 56, 57],      # Středočeský kraj
    [58, 59, 60, 61, 62],                            # Olomoucký kraj
    [63, 64, 65, 66, 67, 68],                        # Moravskoslezský kraj
    [72, 73, 74, 75, 76, 77],                        # Jihomoravský kraj
    [69, 70, 71, 78],                                # Zlínský kraj
]


def _get_region_district_ids(primary_district_id: int) -> list[int]:
    """Vrátí všechny district_id ve stejném kraji. Primární okres je první."""
    for group in _REGION_GROUPS:
        if primary_district_id in group:
            return [primary_district_id] + [d for d in group if d != primary_district_id]
    return [primary_district_id]


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


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two GPS points in km using the haversine formula."""
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def _fetch_sreality_samples(
    lat: float | None,
    lon: float | None,
    floor_area_m2: int,
    radius_km: int = 5,
    max_km: int = 50,
    count: int = 20,
    district_id: int | None = None,
) -> list[dict]:
    """Načte reálné inzeráty RD ze sreality.cz API.

    Sreality GPS filtr (locality_gps_*) přestal fungovat – API ho ignoruje
    a vrací domy z celé ČR. Proto VŽDY filtrujeme přes district_id.
    GPS souřadnice používáme pouze pro výpočet vzdálenosti a řazení výsledků.
    """

    # Velikostní rozsah: plocha ±50 % (min 40 m², max 500 m²)
    size_min = max(40, int(floor_area_m2 * 0.5))
    size_max = min(500, int(floor_area_m2 * 1.5))

    params: dict = {
        "category_main_cb": 2,    # nemovitosti
        "category_sub_cb": 37,    # rodinné domy
        "category_type_cb": 1,    # prodej
        "usable_area_min": size_min,
        "usable_area_max": size_max,
        "per_page": count,
        "sort": 0,
    }

    # ALWAYS use district_id — GPS params on Sreality API are broken (ignored)
    if district_id:
        params["locality_district_id"] = district_id
    # No GPS params — they don't work on Sreality anymore

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
        if raw_img:
            # Fix image URL to get a working CDN preview
            obrazek_url = re.sub(r"fl=res,\d+,\d+", "fl=res,400,300", raw_img)
            obrazek_url = re.sub(r"/\d+x\d+/", "/400x300/", obrazek_url)
        else:
            obrazek_url = None

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

        # GPS z list API
        gps = e.get("gps", {})
        gps_lat = gps.get("lat")
        gps_lon = gps.get("lon")

        # Compute distance for sorting (no hard cutoff — district filter handles locality)
        distance_km = None
        if lat and lon and gps_lat and gps_lon:
            distance_km = _haversine_km(lat, lon, gps_lat, gps_lon)

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
            "gps": {"lat": gps_lat, "lon": gps_lon} if gps_lat and gps_lon else None,
            "distance_km": round(distance_km, 1) if distance_km is not None else None,
        })

    # Sort by distance so AI gets closest samples first
    results.sort(key=lambda x: x.get("distance_km") or 999)
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

    async def _fetch_nearby_samples(
        self,
        lat: float | None,
        lon: float | None,
        floor_area_m2: int,
        district_id: int | None,
        total_count: int = 20,
    ) -> list[dict]:
        """Prohledá okolní okresy v celém kraji a vrátí vzorky seřazené dle GPS vzdálenosti.

        1. Najde všechny okresy ve stejném kraji (regionu)
        2. Paralelně stáhne nabídky z každého okresu
        3. Sloučí, deduplikuje (hash_id), seřadí dle vzdálenosti
        4. Vrátí top `total_count` nejbližších vzorků
        """
        import asyncio

        if not district_id:
            # Bez okresu - fetch bez lokalizačního filtru
            self.log("Bez okresu: hledám RD bez lokalizačního filtru...", "warn")
            return await _fetch_sreality_samples(lat, lon, floor_area_m2, count=total_count)

        # Najdi všechny okresy v tomto kraji
        all_districts = _get_region_district_ids(district_id)
        self.log(
            f"Prohledávám {len(all_districts)} okresů v kraji "
            f"(primární: {district_id}, celkem: {all_districts})...", "thinking"
        )

        # Paralelní fetch ze všech okresů (sem=3 aby se API nepřetížilo)
        sem = asyncio.Semaphore(3)

        async def _fetch_from_district(did: int, count: int) -> list[dict]:
            async with sem:
                return await _fetch_sreality_samples(
                    lat, lon, floor_area_m2, district_id=did, count=count
                )

        tasks = []
        for i, did in enumerate(all_districts):
            # Primární okres → více výsledků, ostatní méně
            count = 15 if i == 0 else 10
            tasks.append(_fetch_from_district(did, count))

        results_per_district = await asyncio.gather(*tasks)

        # Sloučit a deduplikovat podle hash_id
        seen_hashes: set = set()
        merged: list[dict] = []
        for samples in results_per_district:
            for s in samples:
                hid = s.get("hash_id")
                if hid and hid in seen_hashes:
                    continue
                if hid:
                    seen_hashes.add(hid)
                merged.append(s)

        # Seřadit dle GPS vzdálenosti (nejbližší první)
        merged.sort(key=lambda x: x.get("distance_km") or 999)

        # Přeřadit ID sekvenčně
        for i, s in enumerate(merged, 1):
            s["id"] = i

        self.log(
            f"Nalezeno {len(merged)} kandidátů z {len(all_districts)} okresů, "
            f"vracím {min(len(merged), total_count)} nejbližších.", "info"
        )
        return merged[:total_count]

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

        # ── Geokódování + DISTRICT_MAP ─────────────────────────────────────────
        self.log("Geokuduji adresu nemovitosti...", "thinking")
        coords = await _geocode_address(address)
        district_id = _find_district_id(address)

        if coords:
            self.log(f"GPS lokalizace úspěšná: {coords[0]:.4f}, {coords[1]:.4f}", "info")
        else:
            self.log("GPS geokódování selhalo, použiji pouze okres.", "warn")

        if district_id:
            self.log(f"Nalezen okres (district_id={district_id}).", "info")
        else:
            self.log("Nepodařilo se identifikovat okres z adresy.", "warn")

        # ── Načti reálné vzorky ze sreality (multi-district, řazené dle GPS) ──
        lat, lon = coords if coords else (None, None)
        raw_samples = await self._fetch_nearby_samples(
            lat, lon, floor_area_int, district_id, total_count=20
        )

        if len(raw_samples) < 3:
            msg = "Pro zpracování online ocenění se nepodařilo najít dostatek srovnatelných vzorků."
            self.log(msg, "warn")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary=msg,
                errors=[msg]
            )

        # ── Stáhni detaily vzorků – omezená paralelizace (sem=3 pro RAM) ──
        self.log(f"Stahuji detaily {len(raw_samples)} vzorků ze Sreality...", "thinking")
        import asyncio
        sem_detail = asyncio.Semaphore(3)

        async def _fetch_detail_limited(s):
            if not s.get("hash_id"):
                return
            async with sem_detail:
                try:
                    detail = await _fetch_sample_detail(s["hash_id"])
                    if isinstance(detail, dict):
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
                except Exception:
                    pass

        await asyncio.gather(*[_fetch_detail_limited(s) for s in raw_samples])

        # Fallback plochy
        for s in raw_samples:
            if not s["velikost_domu_m2"] or s["velikost_domu_m2"] <= 0:
                s["velikost_domu_m2"] = floor_area_int

        # Count enriched samples (for confidence scoring later)
        enriched_count = sum(1 for s in raw_samples if s.get("stav"))

        # ── Příprava fotek oceňované nemovitosti pro AI ──────────────────────
        # Simple image container that LLMClient can handle for both Gemini and OpenAI
        class _ImagePart:
            """Lightweight image container compatible with LLMClient's content handling."""
            def __init__(self, data: bytes, mime_type: str = "image/jpeg"):
                self.data = data
                self.mime_type = mime_type

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
                        _ImagePart(data=img_bytes, mime_type="image/jpeg")
                    )
                    photos_sent += 1
                except Exception:
                    pass

        if photos_sent > 0:
            self.log(f"Odesílám {photos_sent} fotek oceňované nemovitosti k analýze AI...", "info")

        # ── Stáhni fotky vzorků pro AI (sem=2 pro RAM) ──
        sample_photos_sent = 0
        contents_parts.append("\n=== FOTOGRAFIE VZORKŮ ZE SREALITY ===\n")
        sem_photo = asyncio.Semaphore(2)
        photo_results: list[tuple] = []

        async def _dl_photo(s):
            url = s.get("obrazek_url")
            if not url:
                return (s, None)
            async with sem_photo:
                try:
                    data = await _download_image_bytes(url)
                    return (s, data)
                except Exception:
                    return (s, None)

        photo_results = await asyncio.gather(*[_dl_photo(s) for s in raw_samples[:5]])

        for s, photo_data in photo_results:
            if isinstance(photo_data, bytes) and photo_data:
                contents_parts.append(f"Fotografie vzorku #{s['id']} ({s['adresa']}):")
                contents_parts.append(
                    _ImagePart(data=photo_data, mime_type="image/jpeg")
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
            f"Vyber 5 nejpodobnějších vzorků a PŘIŘAĎ koeficienty K1–K8 dle instrukcí. "
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
                max_output_tokens=8000,
                temperature=0.3,
            )

            result_json = robust_json_parse(response_text)

            # ── Compute NHZP from coefficients (backend is authoritative) ────
            ai_vzorky = result_json.get("vzorky", [])
            
            # Validate: at least 1 sample returned
            if not ai_vzorky:
                return AgentResult(
                    status=AgentStatus.FAIL,
                    summary="AI nevrátila žádné vzorky s koeficienty.",
                    errors=["AI odpověď neobsahuje pole 'vzorky'."]
                )

            nhzp_result = self._compute_nhzp(ai_vzorky, raw_samples, floor_area_int)
            nhzp = nhzp_result["nhzp"]
            nhzp_min = nhzp_result["nhzp_min"]
            nhzp_max = nhzp_result["nhzp_max"]

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

            # ── Benchmark ────────────────────────────────────────────────────
            benchmark = self._get_benchmark(address)
            if benchmark:
                self.log(f"Benchmark okres {benchmark['okres']}: {benchmark['czk_per_m2']:,} Kč/m²", "info")

            # ── Confidence score ─────────────────────────────────────────────
            confidence = self._compute_confidence(
                selected_raw, floor_area_int,
                has_coords=coords is not None,
                enriched_count=enriched_count,
            )
            self.log(f"Confidence score: {confidence['score']} %", "info")

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
                    "gps": s.get("gps"),
                    "distance_km": s.get("distance_km"),
                })

            self.log(f"Odhad dokončen: {odhad_m:.1f} mil. Kč (rozmezí {nhzp_min/1e6:.1f}–{nhzp_max/1e6:.1f} mil.)", "info")
            return AgentResult(
                status=AgentStatus.SUCCESS,
                summary=f"Odhadní cena: {odhad_m:.2f} mil. Kč (rozmezí {nhzp_min/1e6:.2f}–{nhzp_max/1e6:.2f} mil.). {len(merged_vzorky)} vzorků, confidence {confidence['score']} %.",
                details={
                    "odhad_czk": nhzp,
                    "odhad_min": nhzp_min,
                    "odhad_max": nhzp_max,
                    "duvod": result_json.get("duvod", result_json.get("duvod_odhadu", "")),
                    "vzorky": merged_vzorky,
                    "plocha_ocenovaneho": floor_area_int,
                    "property_gps": {"lat": coords[0], "lon": coords[1]} if coords else None,
                    "benchmark": benchmark,
                    "confidence": confidence,
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
    ) -> dict:
        """Compute NHZP from coefficients using the exact porovnávací metoda formula.
        
        Returns dict with:
          nhzp: median-based estimate
          nhzp_min: lowest adjusted unit price × area
          nhzp_max: highest adjusted unit price × area
          upravene_jc: list of per-sample adjusted unit prices
        """
        upravene_jc_list = []

        for v in ai_vzorky:
            sid = v.get("id")
            src = next((s for s in raw_samples if s["id"] == sid), None)
            if not src or not src.get("cena_czk"):
                continue

            sample_area = max(src.get("velikost_domu_m2") or floor_area_int, 10)
            jc = src["cena_czk"] / sample_area

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

            upravene_jc_list.append(jc * io)

        if not upravene_jc_list:
            return {"nhzp": 0, "nhzp_min": 0, "nhzp_max": 0, "upravene_jc": []}

        # Use MEDIAN for robustness against outliers
        median_jc = statistics.median(upravene_jc_list)
        nhzp = round(median_jc * floor_area_int)
        # Price range: ±15 % from median (realistic interval, not raw min/max)
        nhzp_min = round(nhzp * 0.85)
        nhzp_max = round(nhzp * 1.15)

        return {
            "nhzp": nhzp,
            "nhzp_min": nhzp_min,
            "nhzp_max": nhzp_max,
            "upravene_jc": [round(x) for x in upravene_jc_list],
        }

    @staticmethod
    def _compute_confidence(
        samples: list[dict],
        floor_area_int: int,
        has_coords: bool,
        enriched_count: int,
        has_historical: bool = False,
    ) -> dict:
        """Compute confidence score 0–100 based on input quality.
        
        Returns dict with score and factors list.
        """
        score = 0
        factors = []

        # +25 for GPS coords found
        if has_coords:
            score += 25
            factors.append({"label": "GPS lokalizace úspěšná", "points": 25})
        else:
            factors.append({"label": "GPS lokalizace selhala", "points": 0})

        # +25 for ≥5 samples
        n = len(samples)
        if n >= 5:
            score += 25
            factors.append({"label": f"Dostatek vzorků ({n})", "points": 25})
        elif n >= 3:
            pts = round(25 * n / 5)
            score += pts
            factors.append({"label": f"Vzorků: {n}/5", "points": pts})
        else:
            factors.append({"label": f"Nedostatek vzorků ({n})", "points": 0})

        # +15 for >50% samples with detail data (stav)
        if n > 0:
            pct = enriched_count / n
            if pct > 0.5:
                score += 15
                factors.append({"label": "Detailní data vzorků >50 %", "points": 15})
            else:
                pts = round(15 * pct)
                score += pts
                factors.append({"label": f"Detailní data vzorků: {round(pct*100)} %", "points": pts})

        # +10 for price spread <30%
        prices = [s["cena_czk"] for s in samples if s.get("cena_czk")]
        if len(prices) >= 2:
            spread = (max(prices) - min(prices)) / statistics.mean(prices)
            if spread < 0.30:
                score += 10
                factors.append({"label": f"Cenový rozptyl nízký ({round(spread*100)} %)", "points": 10})
            elif spread < 0.50:
                score += 5
                factors.append({"label": f"Cenový rozptyl střední ({round(spread*100)} %)", "points": 5})
            else:
                factors.append({"label": f"Cenový rozptyl vysoký ({round(spread*100)} %)", "points": 0})

        # +10 for samples within 3km (check if GPS available)
        samples_with_gps = [s for s in samples if s.get("gps")]
        if samples_with_gps:
            score += 10
            factors.append({"label": "Vzorky s GPS lokalizací", "points": 10})
        else:
            factors.append({"label": "Vzorky bez GPS dat", "points": 0})

        # +15 for historical data from LV
        if has_historical:
            score += 15
            factors.append({"label": "Historická data z LV", "points": 15})
        else:
            factors.append({"label": "Bez historických dat z LV", "points": 0})

        return {
            "score": min(score, 100),
            "factors": factors,
        }

    @staticmethod
    def _get_benchmark(address: str) -> dict | None:
        """Lookup average price per m² for the district from the benchmark table."""
        addr_lower = address.lower()
        for key in sorted(BENCHMARK_CZK_PER_M2.keys(), key=len, reverse=True):
            if key in addr_lower:
                return {
                    "okres": key.title(),
                    "czk_per_m2": BENCHMARK_CZK_PER_M2[key],
                }
        return None

