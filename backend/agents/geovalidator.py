"""Agent 6: GeoValidator – GPS Location & Visual Verification.

- Extracts GPS from photo EXIF metadata
- Geocodes declared property address → coordinates via Mapy.cz
- Computes haversine distance between photo GPS and property GPS
- Fetches panorama image from Mapy.cz for the property location
- Sends the uploaded street/front photo + panorama to Gemini
  for visual comparison and returns human-readable analysis
"""
import base64
import json
import math
import os
import httpx

from google import genai
from google.genai import types

from agents.base import BaseAgent, AgentResult, AgentStatus
from config import GEMINI_API_KEY, GEMINI_MODEL, MAPY_CZ_API_KEY, UPLOAD_DIR

# Max distance in meters before a photo is flagged
DISTANCE_THRESHOLD_WARN = 500   # 500 m warning
DISTANCE_THRESHOLD_FAIL = 2000  # 2 km fail

MAPY_API_BASE = "https://api.mapy.com"

COMPARISON_PROMPT = """Jsi expert na vizuální porovnávání nemovitostí.

Dostáváš DVĚ fotografie:
1. **Nahrané foto** – fotka rodinného domu dodaná klientem (pohled z ulice / přední fasáda).
2. **Panorama z Mapy.cz** – automaticky stažená panorama (street view) ze souřadnic nemovitosti.

TVŮJ ÚKOL:
Porovnej obě fotky a popiš, co vidíš. Odpovídej česky, srozumitelně, jako kolega analytik.

STRUKTURA ODPOVĚDI (JSON):
{
  "match_verdict": "shoda" | "možná_shoda" | "neshoda",
  "confidence": 0.0-1.0,
  "comparison_text": "Podrobný popis srovnání – co je na obou fotkách společné, co se liší. Piš 3-5 vět.",
  "matching_features": ["barva fasády", "tvar střechy", ...],
  "differing_features": ["jiný úhel pohledu", ...],
  "notes": "Případné poznámky (roční období, rekonstrukce, jiný úhel atd.)"
}

PRAVIDLA:
- Pokud panorama ukazuje jiný dům nebo je zjevně jiná lokace → "neshoda".
- Pokud se barva, tvar, střecha a celkový dojem shodují → "shoda".
- Pokud jsou podobné ale nejsi si jistý (jiný úhel, roční období) → "možná_shoda".
- Vždy popiš KONKRÉTNĚ co vidíš na obou fotkách.
- Odpovídej POUZE v JSON.
"""

FRONT_PHOTO_SELECTION_PROMPT = """Jsi expert na klasifikaci fotografií nemovitostí.

TVŮJ ÚKOL: Ze sady fotografií vyber tu jednu, která NEJLÉPE ukazuje PŘEDNÍ FASÁDU / POHLED Z ULICE na rodinný dům.

PRAVIDLA:
- VŽDY vyber fotografii exteriéru domu – pohled zvenku na budovu.
- Ideálně přední fasádu (vstupní dveře, přední stěna domu viditelná z ulice).
- Pokud přední fasáda není k dispozici, vyber boční nebo zadní exteriér.
- NIKDY nevyber interiérovou fotku (kuchyň, obývák, ložnice, koupelna, chodba).
- NIKDY nevyber detail (zblízka okno, střecha, zeď) – musí být vidět celý dům nebo jeho podstatná část.
- NIKDY nevyber fotku pozemku/zahrady bez viditelného domu.
- Pokud ŽÁDNÁ fotka neukazuje exteriér domu, vrať "photo_id": null.

Vrať POUZE JSON:
{
  "photo_id": "ID vybrané fotky nebo null",
  "reason": "Krátké zdůvodnění výběru"
}
"""


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance in meters between two GPS points."""
    R = 6_371_000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class GeoValidatorAgent(BaseAgent):
    """Agent 6: GeoValidator – GPS + visual panorama comparison."""

    def __init__(self):
        super().__init__(
            name="GeoValidator",
            description="Ověření GPS lokace fotek vs. adresa nemovitosti + vizuální porovnání s panoramou (Mapy.cz)",
            system_prompt=COMPARISON_PROMPT,
        )
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

    # ─── Main entry ────────────────────────────────────────────────────
    async def run(self, context: dict) -> AgentResult:
        images = context.get("images", [])
        property_address = context.get("property_address", "")
        property_lat = context.get("property_lat")
        property_lon = context.get("property_lon")
        session_id = context.get("session_id", "unknown")
        has_pdf_photos = context.get("has_pdf_photos", False)

        # Guardian classifications (used to find the street-facing photo)
        guardian_result = context.get("agent_results", {}).get("Guardian")
        guardian_classifications = []
        if guardian_result and guardian_result.details:
            guardian_classifications = guardian_result.details.get("classifications", [])

        if not MAPY_CZ_API_KEY:
            self.log("Mapy.cz API klíč není nastaven.", "error")
            return AgentResult(
                status=AgentStatus.WARN,
                summary="GeoValidace nedostupná – chybí API klíč Mapy.cz.",
                warnings=["API klíč pro Mapy.cz není nastaven."],
            )

        headers = {"X-Mapy-Api-Key": MAPY_CZ_API_KEY}

        # ── Step 1: Geocode address → coordinates ──────────────────────
        if property_address and (property_lat is None or property_lon is None):
            self.log(f"Geocoduji adresu: {property_address}", "thinking")
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get(
                        f"{MAPY_API_BASE}/v1/geocode",
                        params={"query": property_address, "lang": "cs", "limit": 1},
                        headers=headers,
                        timeout=10,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        pos = items[0].get("position", {})
                        property_lat = pos.get("lat")
                        property_lon = pos.get("lon")
                        resolved_name = items[0].get("name", "")
                        self.log(f"Adresa nalezena: {resolved_name} ({property_lat}, {property_lon})")
                    else:
                        self.log("Adresu se nepodařilo najít.", "warn")
            except Exception as e:
                self.log(f"Chyba geocodingu: {e}", "error")

        if property_lat is None or property_lon is None:
            self.log("Chybí souřadnice nemovitosti.", "warn")
            return AgentResult(
                status=AgentStatus.WARN,
                summary="Nelze ověřit lokaci – chybí GPS souřadnice nemovitosti nebo adresa.",
                warnings=["Nebyla zadána adresa ani souřadnice nemovitosti."],
            )

        # ── Step 2: Collect GPS from photos ────────────────────────────
        photos_with_gps = []
        photos_without_gps = []

        for img in images:
            meta = img.get("metadata", {})
            lat = meta.get("gps_latitude")
            lon = meta.get("gps_longitude")
            if lat is not None and lon is not None:
                photos_with_gps.append({
                    "photo_id": img["id"],
                    "lat": lat,
                    "lon": lon,
                    "processed_path": img.get("processed_path", ""),
                })
            else:
                photos_without_gps.append(img["id"])

        self.log(f"Fotek s GPS: {len(photos_with_gps)}, bez GPS: {len(photos_without_gps)}")

        # ── Step 3: Distance calculation + reverse geocoding ───────────
        self.log("Měřím vzdálenosti a identifikuji lokace fotek...", "thinking")
        photo_results = []
        warnings = []
        errors = []
        max_distance = 0

        async with httpx.AsyncClient() as http_client:
            for photo in photos_with_gps:
                distance = haversine(property_lat, property_lon, photo["lat"], photo["lon"])
                max_distance = max(max_distance, distance)

                photo_address = None
                photo_location = ""
                try:
                    resp = await http_client.get(
                        f"{MAPY_API_BASE}/v1/rgeocode",
                        params={"lat": photo["lat"], "lon": photo["lon"], "lang": "cs"},
                        headers=headers,
                        timeout=10,
                    )
                    resp.raise_for_status()
                    rdata = resp.json()
                    ritems = rdata.get("items", [])
                    if ritems:
                        photo_address = ritems[0].get("name", "")
                        photo_location = ritems[0].get("location", "")
                except Exception as e:
                    self.log(f"Reverse geocode chyba ({photo['photo_id']}): {e}", "warn")

                entry = {
                    "photo_id": photo["photo_id"],
                    "photo_gps": {"lat": photo["lat"], "lon": photo["lon"]},
                    "photo_address": photo_address,
                    "photo_location": photo_location,
                    "distance_m": round(distance, 1),
                    "status": "ok",
                }

                if distance > DISTANCE_THRESHOLD_FAIL:
                    entry["status"] = "fail"
                    errors.append(f"Foto {photo['photo_id']}: {distance:.0f} m od nemovitosti – {photo_address or '?'}")
                    self.log(f"FAIL: {photo['photo_id']} je {distance:.0f} m daleko!", "error")
                elif distance > DISTANCE_THRESHOLD_WARN:
                    entry["status"] = "warn"
                    warnings.append(f"Foto {photo['photo_id']}: {distance:.0f} m od nemovitosti")
                    self.log(f"WARN: {photo['photo_id']} je {distance:.0f} m daleko.")
                else:
                    self.log(f"OK: {photo['photo_id']} – {distance:.0f} m")

                photo_results.append(entry)

        # ── Step 4: Reverse geocode property ───────────────────────────
        property_address_resolved = property_address
        try:
            async with httpx.AsyncClient() as http_client:
                resp = await http_client.get(
                    f"{MAPY_API_BASE}/v1/rgeocode",
                    params={"lat": property_lat, "lon": property_lon, "lang": "cs"},
                    headers=headers,
                    timeout=10,
                )
                resp.raise_for_status()
                rdata = resp.json()
                ritems = rdata.get("items", [])
                if ritems:
                    property_address_resolved = ritems[0].get("name", property_address)
        except Exception:
            pass

        # ── Step 5: Fetch panorama + visual comparison ─────────────────
        panorama_path = None
        panorama_url = None
        visual_comparison = None
        front_photo_id = None
        front_photo_path = None

        # Pick the best street-facing photo using AI
        front_photo_path, front_photo_id = await self._find_front_photo(
            guardian_classifications, images,
        )

        if front_photo_path:
            self.log(f"Přední/uliční foto nalezena: {front_photo_id}", "info")
        else:
            self.log("Žádná exteriérová fotka domu nebyla nalezena – vizuální porovnání není možné.", "warn")

        # Fetch panorama from Mapy.cz
        if property_lat is not None and property_lon is not None:
            self.log("Stahuji panoramu z Mapy.cz...", "thinking")
            try:
                async with httpx.AsyncClient() as http_client:
                    pano_resp = await http_client.get(
                        f"{MAPY_API_BASE}/v1/static/pano",
                        params={
                            "lon": property_lon,
                            "lat": property_lat,
                            "width": 800,
                            "height": 450,
                            "yaw": "point",
                            "radius": 100,
                            "lang": "cs",
                        },
                        headers=headers,
                        timeout=15,
                    )

                    if pano_resp.status_code == 200 and pano_resp.headers.get("content-type", "").startswith("image"):
                        # Save panorama
                        session_dir = os.path.join(UPLOAD_DIR, session_id)
                        os.makedirs(session_dir, exist_ok=True)
                        panorama_path = os.path.join(session_dir, "panorama_mapy.jpg")
                        with open(panorama_path, "wb") as f:
                            f.write(pano_resp.content)
                        panorama_url = f"/uploads/{session_id}/panorama_mapy.jpg"
                        self.log(f"Panorama stažena ({len(pano_resp.content)} B)")
                    else:
                        self.log(f"Panorama nedostupná (status {pano_resp.status_code})", "warn")
            except Exception as e:
                self.log(f"Chyba stahování panoramy: {e}", "warn")

        # Visual comparison via Gemini
        if panorama_path and front_photo_path and self.client:
            visual_comparison = await self._compare_visually(
                front_photo_path, panorama_path, front_photo_id,
            )

        # ── Step 6: Determine final status ─────────────────────────────
        if len(photos_without_gps) > len(photos_with_gps):
            if has_pdf_photos and property_address:
                self.log("Fotografie zřejmě pocházejí z PDF (bez GPS). Pro ověření se spoléhám na adresu z formuláře.", "info")
            else:
                warnings.append(f"Většina fotek ({len(photos_without_gps)}/{len(images)}) nemá GPS metadata.")

        if errors:
            status = AgentStatus.FAIL
        elif warnings:
            status = AgentStatus.WARN
        else:
            status = AgentStatus.SUCCESS

        # Build human-readable summary
        ok_count = sum(1 for p in photo_results if p["status"] == "ok")
        warn_count = sum(1 for p in photo_results if p["status"] == "warn")
        fail_count = sum(1 for p in photo_results if p["status"] == "fail")

        comparison_verdict = ""
        if visual_comparison:
            v = visual_comparison.get("match_verdict", "")
            verdict_map = {"shoda": "vizuální shoda ✓", "možná_shoda": "možná shoda ⚠", "neshoda": "neshoda ✗"}
            comparison_verdict = f" | Porovnání s panoramou: {verdict_map.get(v, v)}"

        summary = (
            f"GPS: {ok_count} OK, {warn_count} varování, {fail_count} chyb "
            f"z {len(photos_with_gps)} fotek (max {max_distance:.0f} m)"
            f"{comparison_verdict}"
        )

        self.log(f"Výsledek: {status.value} – {summary}")

        return AgentResult(
            status=status,
            summary=summary,
            details={
                "property_gps": {"lat": property_lat, "lon": property_lon},
                "property_address": property_address_resolved,
                "photos_total": len(images),
                "photos_with_gps": len(photos_with_gps),
                "photos_without_gps": len(photos_without_gps),
                "photo_results": photo_results,
                "max_distance_m": round(max_distance, 1),
                "threshold_warn_m": DISTANCE_THRESHOLD_WARN,
                "threshold_fail_m": DISTANCE_THRESHOLD_FAIL,
                # Visual comparison data
                "panorama_url": panorama_url,
                "front_photo_id": front_photo_id,
                "visual_comparison": visual_comparison,
            },
            warnings=warnings,
            errors=errors,
        )

    # ─── Find the front/street-facing photo ────────────────────────────
    async def _find_front_photo(self, classifications: list, images: list) -> tuple:
        """Find the best street-facing exterior photo.

        Strategy (two-tiered for reliability):
        1. Try Guardian's classifications (EXTERIER_PREDNI > EXTERIER_BOCNI > EXTERIER_ZADNI)
        2. If Guardian didn't find one, use a dedicated Gemini call to pick the best exterior photo
           from ALL images — this guarantees we never accidentally pick an interior shot.
        """
        # ── Tier 1: Guardian classifications ──
        target_categories = ["EXTERIER_PREDNI", "EXTERIER_BOCNI", "EXTERIER_ZADNI"]

        for cat in target_categories:
            for cl in classifications:
                cats = cl.get("categories", [])
                if cat in cats:
                    pid = cl.get("photo_id")
                    for img in images:
                        if img.get("id") == pid:
                            self.log(f"Guardian klasifikace: {pid} → {cat}")
                            return img.get("processed_path"), pid

        # ── Tier 2: Dedicated AI selection ──
        # Guardian didn't identify a front photo or hasn't run — use AI to pick
        self.log("Guardian nemá vhodnou klasifikaci, vybírám přední foto pomocí AI...", "thinking")
        if not self.client or not images:
            return None, None

        try:
            parts = [f"Máš {len(images)} fotografií. Vyber tu, která nejlépe ukazuje PŘEDNÍ EXTERIÉR rodinného domu (pohled z ulice).\n\n"]

            for img in images:
                try:
                    with open(img["processed_path"], "rb") as f:
                        image_bytes = f.read()
                    parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                    parts.append(f"Photo ID: {img['id']}\n")
                except Exception:
                    continue

            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=FRONT_PHOTO_SELECTION_PROMPT,
                    response_mime_type="application/json",
                    max_output_tokens=300,
                ),
            )

            result = json.loads(response.text)
            selected_id = result.get("photo_id")
            reason = result.get("reason", "")

            if selected_id:
                self.log(f"AI vybrala foto: {selected_id} – {reason}")
                for img in images:
                    if img.get("id") == selected_id:
                        return img.get("processed_path"), selected_id

            self.log("AI nenašla vhodnou exteriérovou fotku.", "warn")
            return None, None

        except Exception as e:
            self.log(f"Chyba AI výběru fotky: {e}", "warn")
            return None, None

    # ─── Visual comparison via Gemini ──────────────────────────────────
    async def _compare_visually(
        self, uploaded_path: str, panorama_path: str, photo_id: str | None,
    ) -> dict | None:
        """Send both images to Gemini for visual comparison."""
        try:
            self.log("Vizuální porovnání přes Gemini...", "thinking")

            with open(uploaded_path, "rb") as f:
                uploaded_bytes = f.read()
            with open(panorama_path, "rb") as f:
                panorama_bytes = f.read()

            parts = [
                "Porovnej tyto dvě fotografie rodinného domu:\n\n",
                "FOTO 1 – Nahrané foto klientem:\n",
                types.Part.from_bytes(data=uploaded_bytes, mime_type="image/jpeg"),
                "\n\nFOTO 2 – Panorama z Mapy.cz:\n",
                types.Part.from_bytes(data=panorama_bytes, mime_type="image/jpeg"),
                "\n\nPorovnej, zda obě fotky ukazují stejnou nemovitost.",
            ]

            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    response_mime_type="application/json",
                    max_output_tokens=1500,
                ),
            )

            result = json.loads(response.text)
            self.log(f"Vizuální verdikt: {result.get('match_verdict', '?')} "
                     f"(confidence: {result.get('confidence', '?')})")
            return result

        except Exception as e:
            self.log(f"Chyba vizuálního porovnání: {e}", "warn")
            return None
