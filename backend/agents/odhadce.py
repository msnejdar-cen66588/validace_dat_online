"""Agent 8: Odhadce (Tržní ocenění) – Porovnávací metoda.

Strategie:
1. Načte reálné inzeráty rodinných domů ze sreality.cz API (s obrázky a funkčními URL).
2. Předá tyto reálné vzorky Gemini, který přidělí korekční koeficienty K1–K8.
3. Výsledek obsahuje reálné obrázky, funkční odkaz na inzerát a AI komentáře.
"""
import json
import os
import re

import httpx
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient
from config import GEMINI_API_KEY, GEMINI_MODEL, UPLOAD_DIR


# ── Prompt pro AI – přesný výpočet NHZP porovnávací metodou ─────────────────
COEFFICIENT_PROMPT = """Jsi soudní znalec a bankovní odhadce nemovitostí s 20letou praxí v ČR.
Provádíš ocenění rodinného domu POROVNÁVACÍ METODOU (NHZP) přesně dle české
metodiky znaleckých posudků.

Dostaneš:
- Parametry oceňovaného domu (adresa, plocha, stav, atd.)
- Fotografie oceňovaného domu (pokud jsou k dispozici) – PEČLIVĚ je analyzuj
  pro posouzení technického stavu, kvality provedení, stáří, vybavení
- Seznam kandidátních vzorků ze sreality.cz s cenami

═══ PŘESNÝ POSTUP VÝPOČTU ═══

KROK 1 – VÝBĚR VZORKŮ:
Z kandidátů vyber přesně 3 NEJPODOBNĚJŠÍ vzorky. Kritéria výběru (v pořadí priority):
a) Velikost domu (m²) – co nejbližší k oceňovanému
b) Stav a stáří – přednost podobnému technickému stavu
c) Lokalita – přednost bližší poloze
Nevhodné kandidáty (odlišný charakter, příliš velký/malý) VYNECH.

KROK 2 – KOEFICIENTY K1–K8 (pro KAŽDÝ vybraný vzorek):
Koeficienty vyjadřují poměr VZORKU k NAŠEMU domu:
• K = 1.00 → vlastnost je shodná
• K < 1.00 → vzorek je v této vlastnosti LEPŠÍ než náš dům
  (= jeho cena je částečně díky této lepší vlastnosti, proto snížíme upravenou JC)
• K > 1.00 → vzorek je v této vlastnosti HORŠÍ než náš dům
  (= jeho cenu lze navýšit, protože náš dům je v tomto lepší)

POVINNÉ ROZSAHY (STRIKTNĚ dodržuj!):
• K1 (Redukce pramene ceny) = VŽDY 0.85 pro inzerátové ceny
  (inzerce je typicky o ~15 % nad skutečnou prodejní cenou)
• K2 (Velikost objektu):   0.90 – 1.10
  Menší vzorek → K2 > 1.0; Větší vzorek → K2 < 1.0
• K3 (Poloha):             0.90 – 1.10
  Lepší lokalita vzorku → K3 < 1.0; Horší → K3 > 1.0
• K4 (Provedení/vybavení): 0.85 – 1.15
  Luxusnější vzorek → K4 < 1.0; Skromnější → K4 > 1.0
• K5 (Celkový stav):       0.80 – 1.20
  Lepší stav vzorku → K5 < 1.0; Horší stav → K5 > 1.0
• K6 (Vliv pozemku):       0.90 – 1.10
  Větší/lepší pozemek vzorku → K6 < 1.0
• K7 (Úvaha znalce):       0.95 – 1.05
  Drobná korekce dle celkového dojmu
• K8 (Energ. náročnost):   0.95 – 1.05

⚠️ KRITICKÉ PRAVIDLO: K1 musí být VŽDY 0.85! Toto je standardní redukce za
inzerční cenu. Nikdy nedávej K1 = 1.00.

KROK 3 – VÝPOČET (proveď přesně!):
Pro každý vzorek i:
  1. JC_i = cena_vzorku_i / plocha_vzorku_i  (jednotková cena Kč/m²)
  2. IO_i = K1 × K2 × K3 × K4 × K5 × K6 × K7 × K8  (index odlišnosti)
  3. Upravena_JC_i = JC_i × IO_i

NHZP = průměr(Upravena_JC_1, ..., Upravena_JC_n) × plocha_oceňovaného_domu

⚠️ KONTROLA VÝSLEDKU:
- NHZP pro běžný RD v ČR (80–200 m²) by měla být typicky 2 000 000 – 15 000 000 Kč
- Pokud IO vyjde nad 1.05 či pod 0.60, zkontroluj koeficienty – něco je špatně
- Výsledná NHZP NESMÍ být vyšší než nejvyšší cena ze vzorků (po K1 redukci)

═══ VÝSTUPNÍ FORMÁT ═══
Vrať POUZE validní JSON (BEZ Markdown, BEZ ```json):
{
  "nhzp_czk": <celé číslo – výsledná NHZP vypočtená vzorcem výše>,
  "duvod": "<2–3 věty: proč tyto vzorky, komentář k trhu v lokalitě>",
  "plocha_ocenovaneho": <plocha našeho domu v m²>,
  "vzorky": [
    {
      "id": <id z vstupu>,
      "jc": <jednotková cena Kč/m²>,
      "io": <index odlišnosti – součin K1..K8, zaokrouhlený na 4 des. místa>,
      "upravena_jc": <JC × IO, zaokrouhleno na celé Kč>,
      "koeficienty": {"k1": 0.85, "k2": ..., "k3": ..., "k4": ..., "k5": ..., "k6": ..., "k7": ..., "k8": ...},
      "oduvodneni_koeficientu": "<stručné zdůvodnění pro každý K, který se liší od 1.00>"
    }
  ]
}"""


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

        # ── Načti reálné vzorky ze sreality (GPS + velikost) ─────────────────
        self.log("Geokuduji adresu nemovitosti...", "thinking")
        floor_area_int = int(re.sub(r"[^0-9]", "", str(floor_area)) or "120") or 120
        coords = await _geocode_address(address)

        raw_samples: list[dict] = []
        if coords:
            lat, lon = coords
            for radius in (2, 5):
                self.log(f"Hledám RD do {radius} km od {address}...", "thinking")
                raw_samples = await _fetch_sreality_samples(lat, lon, floor_area_int, radius_km=radius, count=10)
                if len(raw_samples) >= 3:
                    break

        if len(raw_samples) < 3:
            msg = "Pro zpracování online ocenění je v okruhu do 5 km od nemovitosti málo srovnatelných vzorků."
            self.log(msg, "warn")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary=msg,
                errors=[msg]
            )

        if not raw_samples:
            return AgentResult(
                status=AgentStatus.FAIL,
                summary="Nepodařilo se načíst vzorky ze sreality.cz.",
                errors=["Sreality API nedostupné nebo žádné inzeráty."]
            )

        self.log(f"Nalezeno {len(raw_samples)} kandidátů, AI vybírá nejpodobnější a počítá NHZP...", "info")

        # ── Příprava fotek oceňované nemovitosti pro AI ──────────────────────
        contents_parts: list = []
        images_data = context.get("images") or []
        photos_sent = 0
        for img_info in images_data[:4]:  # max 4 photos
            img_path = img_info.get("processed_path", "")
            if img_path and os.path.exists(img_path):
                try:
                    with open(img_path, "rb") as f:
                        img_bytes = f.read()
                    # Use Gemini Part format for inline image
                    from google.genai import types as genai_types
                    contents_parts.append(
                        genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg")
                    )
                    photos_sent += 1
                except Exception:
                    pass

        if photos_sent > 0:
            self.log(f"Odesílám {photos_sent} fotek oceňované nemovitosti k analýze AI...", "info")

        # ── Prompt pro AI ────────────────────────────────────────────────────
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
            f"- Vytápění: {heating}\n"
        )
        if photos_sent > 0:
            prompt_text += (
                f"\nK tomuto domu jsou přiloženy {photos_sent} fotografie výše. "
                f"PEČLIVĚ je analyzuj pro posouzení technického stavu, kvality "
                f"provedení a vybavení. Tyto poznatky MUSÍ ovlivnit koeficienty K4 a K5.\n"
            )
        prompt_text += (
            f"\nKandidáti ze sreality.cz (seřazeni od nejbližší lokality):\n{vzorky_text}\n\n"
            f"PROVEĎ PŘESNÝ VÝPOČET NHZP dle instrukcí. "
            f"Plocha oceňovaného domu je {floor_area_int} m². "
            f"K1 MUSÍ být 0.85 u všech vzorků. "
            f"Vrať POUZE čistý JSON dle instrukce."
        )

        # Build content list: photos first, then text
        contents_parts.append(prompt_text)

        try:
            response_text = await self.client.generate_content(
                system_instruction=self.system_prompt,
                contents=contents_parts,
                response_mime_type="application/json",
                max_output_tokens=2000,
                temperature=0.3,  # Low temperature for precise calculation
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

            # ── Extract or compute NHZP ──────────────────────────────────────
            nhzp = result_json.get("nhzp_czk") or result_json.get("zakladni_odhad_czk") or 0

            # ALWAYS recompute NHZP from coefficients to ensure correctness
            computed_nhzp = self._compute_nhzp(
                result_json.get("vzorky", []),
                raw_samples,
                floor_area_int,
            )

            if computed_nhzp > 0:
                # Use computed value – AI's arithmetic can be wrong
                nhzp = computed_nhzp
            elif nhzp <= 0:
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

            # ── Zastropování podle skutečně VYUŽITÝCH vzorků ──────────────────
            ai_vzorky_by_id = {v["id"]: v for v in result_json.get("vzorky", [])}
            selected_ids = set(ai_vzorky_by_id.keys())
            
            selected_raw = [s for s in raw_samples if s["id"] in selected_ids]
            if not selected_raw:
                selected_raw = raw_samples

            # Cap at max sample price (after K1 reduction is implied by 1.15)
            max_sample_price = max((s["cena_czk"] for s in selected_raw), default=0)
            max_reasonable = int(max_sample_price * 1.15)  # Allow 15% above max sample
            if nhzp > max_reasonable and max_reasonable > 0:
                warnings.append(
                    f"NHZP {nhzp:,.0f} Kč překračovala max. cenu vybraného vzorku ({max_sample_price:,.0f} Kč). "
                    f"Zastropováno na {max_reasonable:,.0f} Kč."
                )
                nhzp = max_reasonable

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

                # Sanitize coefficients
                koef = ai.get("koeficienty", {})
                sanitized_koef = self._sanitize_coefficients(koef)

                merged_vzorky.append({
                    "id": s["id"],
                    "adresa": s["adresa"],
                    "cena_czk": s["cena_czk"],
                    "velikost_domu_m2": s["velikost_domu_m2"],
                    "velikost_pozemku_m2": s.get("velikost_pozemku_m2", 0),
                    "stav": s.get("stav", ""),
                    "zdroj_url": s["zdroj_url"],
                    "obrazek_url": proxy_img,
                    "koeficienty": sanitized_koef,
                    "jc": ai.get("jc", 0),
                    "io": ai.get("io", 0),
                    "upravena_jc": ai.get("upravena_jc", 0),
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
        """Sanitize coefficients to strict ranges."""
        RANGES = {
            "k1": (0.80, 0.90),
            "k2": (0.90, 1.10),
            "k3": (0.90, 1.10),
            "k4": (0.85, 1.15),
            "k5": (0.80, 1.20),
            "k6": (0.90, 1.10),
            "k7": (0.95, 1.05),
            "k8": (0.95, 1.05),
        }
        sanitized = {}
        for k in ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8"]:
            raw = koef.get(k, 1.0 if k != "k1" else 0.85)
            try:
                val = float(str(raw).replace(",", "."))
                # Guard against AI returning percentages (e.g. 85 instead of 0.85)
                if val > 5.0:
                    val = val / 100.0
                lo, hi = RANGES.get(k, (0.80, 1.20))
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
        """Compute NHZP from coefficients using the exact porovnávací metoda formula."""
        total_upravena_jc = 0
        count_ok = 0

        for v in ai_vzorky:
            sid = v.get("id")
            src = next((s for s in raw_samples if s["id"] == sid), None)
            if not src or not src.get("cena_czk"):
                continue

            sample_area = max(src.get("velikost_domu_m2") or floor_area_int, 10)
            jc = src["cena_czk"] / sample_area  # Unit price Kč/m²

            # Compute IO = product of K1..K8
            io = 1.0
            koef = v.get("koeficienty") or {}
            for k in ["k1", "k2", "k3", "k4", "k5", "k6", "k7", "k8"]:
                raw_k = koef.get(k, 1.0 if k != "k1" else 0.85)
                try:
                    num = float(str(raw_k).replace(",", "."))
                    if num > 5.0:
                        num = num / 100.0
                    num = max(0.50, min(num, 1.50))  # Wide guard
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
