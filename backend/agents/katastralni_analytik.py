"""Agent 7: KatastralniAnalytik – LV Risk Analysis + Ortofoto Building Detection.

- Parses uploaded LV (List Vlastnictví) PDF
- Identifies banking risks: liens, easements, alienation bans, executions
- Fetches parcel geometry via ČÚZK REST API
- Downloads ortofoto from ČÚZK WMS
- AI analysis of ortofoto for unregistered buildings/extensions
"""
import io
import json
import os
import httpx
from PIL import Image, ImageDraw, ImageFont

from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient
from config import GEMINI_API_KEY, GEMINI_MODEL, UPLOAD_DIR
from lv_parser import parse_lv, LVData

CUZK_WMS_ORTOFOTO = "https://ags.cuzk.gov.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer"

ORTOFOTO_ANALYSIS_PROMPT = """Jsi expert na analýzu leteckých/satelitních snímků nemovitostí pro účely bankovních ocenění.

Dostáváš ORTOFOTO z katastru nemovitostí České republiky.
Zároveň dostáváš informace o parcelách z Listu vlastnictví (čísla, výměry, druhy pozemků, zapsané stavby).

TVŮJ ÚKOL:
Analyzuj ortofoto a hledej STAVBY na pozemcích, které NEJSOU zakresleny v katastru.

PRAVIDLA PRO DETEKCI:
1. **Vedlejší stavba > 45 m²**: Pokud na pozemku vidíš budovu/stavbu, která NENÍ uvedena v LV jako součást pozemku
   → RIZIKO STŘEDNÍ: "Nezakreslená vedlejší stavba se zastavěnou plochou nad 45 m² – podmínka zákresu do KN"
   
2. **Přístavba k hlavní stavbě > 16 m²**: Pokud hlavní stavba na ortofoto vypadá větší než zastavěná plocha pozemku
   → RIZIKO STŘEDNÍ: "Nezakreslená přístavba k hlavní stavbě se zastavěnou plochou nad 16 m² – podmínka zákresu do KN"

3. Pokud NEVIDÍŠ žádné podezřelé stavby → buildings_detected bude prázdný seznam []

Pro KAŽDOU detekovanou stavbu uveď přibližnou pozici na obrázku jako bounding box v procentech (0-100):
- bbox_x: levý okraj v % šířky obrázku
- bbox_y: horní okraj v % výšky obrázku  
- bbox_w: šířka v % šířky obrázku
- bbox_h: výška v % výšky obrázku

ODPOVÍDEJ ČESKY, POUZE V JSON:
{
  "buildings_detected": [
    {
      "label": "Krátký popis (max 4 slova)",
      "description": "Podrobný popis stavby/přístavby",
      "estimated_area_m2": 60,
      "risk_level": "střední",
      "risk_description": "Popis rizika",
      "recommendation": "Doporučení",
      "bbox_x": 30,
      "bbox_y": 40,
      "bbox_w": 15,
      "bbox_h": 12
    }
  ],
  "overall_assessment": "Celkové hodnocení ortofota – co vidíte na pozemcích",
  "notes": "Případné poznámky"
}
"""

LV_RISK_ANALYSIS_PROMPT = """Jsi expert na právní analýzu listu vlastnictví pro účely bankovních hypotečních úvěrů.

Analyzuj následující data z Listu vlastnictví a identifikuj RIZIKA PRO BANKU.

TOTO JE SEZNAM RIZIK A JEJICH PŘESNÁ KLASIFIKACE ZÁVAŽNOSTI:

Tato 3 rizika MUSÍ BÝT VYSOKÉ ("severity": "vysoké"):
1. **Zástavní práva** – existující hypotéky, věřitelé, nesplacené dluhy
2. **Věcné břemeno užívání** – služebnosti užívání/bydlení třetích osob
3. **Zákazy zcizení** – blokace prodeje/převodu nemovitosti

Všechna ostatní rizika MUSÍ BÝT STŘEDNÍ ("severity": "střední"):
- Ostatní věcná břemena (vedení inženýrských sítí apod.)
- Exekuce/insolvence (nařízení exekuce, insolvenční řízení)
- Plomby (probíhající řízení v katastru)
- Spoluvlastnictví (více vlastníků, komplikované podíly)
- BPEJ/ZPF (pozemky v ZPF - omezení stavby)

8. **PŘÍSTUP K NEMOVITOSTI** – zhodnoť, zda je zajištěn právně bezpečný přístup:
   Přístup je ZAJIŠTĚNÝ pokud platí ALESPOŇ JEDNO:
   - Přístupová parcela je vedena v KN jako "ostatní plocha" / "komunikace" / "silnice"
   - Přístupová parcela je ve vlastnictví obce nebo státu (ČR, Správa silnic, Ředitelství silnic apod.)
   - Na přístupovou parcelu je zřízeno věcné břemeno přístupu / přechodu / průjezdu ve prospěch oceňované nemovitosti
   - Vlastník oceňované nemovitosti je spoluvlastníkem přístupové parcely
   
   Pokud ŽÁDNÁ z podmínek není splněna → RIZIKO STŘEDNÍ: "Nezajištěný přístup k nemovitosti"
   Pokud nelze přístup z dat LV jednoznačně posoudit → uveď jako poznámku

Pro každé riziko uveď:
- severity: "vysoké" (Zástava, VB užívání, Zákaz zcizení) / "střední" (vše ostatní)
- description: co přesně bylo nalezeno
- recommendation: doporučení pro banku

ODPOVÍDEJ ČESKY, POUZE V JSON:
{
  "risks": [
    {"severity": "...", "category": "...", "description": "...", "recommendation": "..."}
  ],
  "overall_risk_level": "vysoké" / "střední",
  "access_assessment": {
    "status": "zajištěný" / "nezajištěný" / "nelze posoudit",
    "reason": "Popis důvodu"
  },
  "summary": "Celkové shrnutí rizik pro banku, vypiš stručně co se našlo"
}
"""


class KatastralniAnalytikAgent(BaseAgent):
    """Agent 7: KatastralniAnalytik – LV + ortofoto analysis."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="KatastralniAnalytik",
            description="Analýza listu vlastnictví – rizika pro banku + ortofoto kontrola staveb",
            system_prompt=LV_RISK_ANALYSIS_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        lv_pdf_path = context.get("lv_pdf_path")
        selected_parcels = context.get("selected_parcels")  # list of parcel numbers
        session_id = context.get("session_id", "unknown")
        images = context.get("images", [])

        if not lv_pdf_path:
            self.log("List vlastnictví nebyl nahrán – přeskakuji.", "info")
            return AgentResult(
                status=AgentStatus.WARN,
                summary="List vlastnictví nebyl nahrán.",
                details={"skipped": True},
                warnings=["LV nebylo nahráno – analýza katastru přeskočena."],
            )

        # ── Step 1: Parse LV PDF ──
        self.log("Parsování Listu vlastnictví...", "thinking")
        try:
            with open(lv_pdf_path, "rb") as f:
                lv_bytes = f.read()
            lv_data = parse_lv(lv_bytes)
            self.log(f"LV {lv_data.lv_number} – kat.ú. {lv_data.kat_uzemi_nazev}: "
                     f"{len(lv_data.parcels)} parcel, {len(lv_data.owners)} vlastníků, "
                     f"{len(lv_data.encumbrances)} záznamů v sekci C")
        except Exception as e:
            self.log(f"Chyba parsování LV: {e}", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary=f"Chyba při čtení LV: {e}",
                errors=[str(e)],
            )

        # Filter parcels by user selection
        if selected_parcels:
            lv_data.parcels = [
                p for p in lv_data.parcels
                if p.parcel_number in selected_parcels
            ]
            self.log(f"Funkční celek: {len(lv_data.parcels)} vybraných parcel")

        # ── Step 2: AI Risk Analysis of LV ──
        self.log("AI analýza rizik z LV...", "thinking")
        lv_risks = None
        if self.client:
            lv_risks = await self._analyze_lv_risks(lv_data)

        # ── Step 3: Fetch parcel coordinates ──
        parcel_geometries = {}
        bbox = None
        if lv_data.kat_uzemi_kod and lv_data.parcels:
            self.log("Získávání souřadnic parcel...", "thinking")
            parcel_geometries, bbox = await self._fetch_parcel_geometries(lv_data, context)

        # ── Step 4: Download ortofoto ──
        ortofoto_path = None
        ortofoto_url = None
        if bbox:
            self.log("Stahování ortofota z ČÚZK WMS...", "thinking")
            # Use geocoded center for parcel flood-fill highlighting
            center = None
            if parcel_geometries:
                coords_list = [(g["lat"], g["lon"]) for g in parcel_geometries.values()
                               if "lat" in g and "lon" in g]
                if coords_list:
                    center = coords_list[0]
            if not center:
                center = ((bbox[1] + bbox[3]) / 2, (bbox[0] + bbox[2]) / 2)
            ortofoto_path, ortofoto_url = await self._download_ortofoto(
                bbox, session_id, center_coords=center,
                num_parcels=len(lv_data.parcels) if lv_data and lv_data.parcels else 1,
            )

        # ── Step 5: AI analysis of ortofoto ──
        ortofoto_analysis = None
        ortofoto_annotated_url = None
        if ortofoto_path and self.client:
            self.log("AI analýza ortofota – hledání nezakreslených staveb...", "thinking")
            ortofoto_analysis = await self._analyze_ortofoto(ortofoto_path, lv_data, images)

            # Annotate ortofoto with detected buildings
            if ortofoto_analysis and ortofoto_analysis.get("buildings_detected"):
                annotated_path = self._annotate_ortofoto(
                    ortofoto_path, ortofoto_analysis["buildings_detected"], session_id
                )
                if annotated_path:
                    ortofoto_annotated_url = f"/uploads/{session_id}/ortofoto_annotated.jpg"

        # ── Step 6: Build result ──
        warnings = []
        errors = []
        all_risks = []

        if lv_risks:
            all_risks.extend(lv_risks.get("risks", []))
        if ortofoto_analysis:
            for bd in ortofoto_analysis.get("buildings_detected", []):
                all_risks.append({
                    "severity": bd.get("risk_level", "střední"),
                    "category": "nezakreslená stavba",
                    "description": bd.get("risk_description", bd.get("description", "")),
                    "recommendation": bd.get("recommendation", ""),
                })

        high_risks = sum(1 for r in all_risks if r.get("severity") == "vysoké")
        medium_risks = sum(1 for r in all_risks if r.get("severity") == "střední")
        low_risks = sum(1 for r in all_risks if r.get("severity") == "nízké")

        if high_risks > 0:
            status = AgentStatus.FAIL
        elif medium_risks > 0:
            status = AgentStatus.WARN
        else:
            status = AgentStatus.SUCCESS

        overall_risk = lv_risks.get("overall_risk_level", "neznámé") if lv_risks else "neznámé"
        summary_text = (
            f"LV {lv_data.lv_number} – {lv_data.kat_uzemi_nazev}: "
            f"{high_risks} vysokých, {medium_risks} středních, {low_risks} nízkých rizik"
        )

        self.log(f"Výsledek: {summary_text}")

        return AgentResult(
            status=status,
            summary=summary_text,
            details={
                "lv_data": lv_data.to_dict(),
                "risks": all_risks,
                "overall_risk_level": overall_risk,
                "lv_risk_summary": lv_risks.get("summary", "") if lv_risks else "",
                "access_assessment": lv_risks.get("access_assessment") if lv_risks else None,
                "ortofoto_url": ortofoto_url,
                "ortofoto_annotated_url": ortofoto_annotated_url,
                "ortofoto_analysis": ortofoto_analysis,
                "parcel_geometries": parcel_geometries,
                "bbox": bbox,
            },
            warnings=[r["description"] for r in all_risks if r.get("severity") in ("vysoké", "střední")],
            errors=[r["description"] for r in all_risks if r.get("severity") == "vysoké"],
        )

    # ─── AI Risk Analysis ──────────────────────────────────────────────
    async def _analyze_lv_risks(self, lv_data: LVData) -> dict | None:
        """Use Gemini to analyze LV data for banking risks."""
        try:
            lv_summary = json.dumps(lv_data.to_dict(), ensure_ascii=False, indent=2)

            response_text = await self.client.generate_content(
                system_instruction=LV_RISK_ANALYSIS_PROMPT,
                contents=f"Analyzuj tento List vlastnictví a identifikuj rizika pro banku:\n\n{lv_summary}",
                response_mime_type="application/json",
                max_output_tokens=3000,
            )
            result = json.loads(response_text)
            self.log(f"LV rizika: {result.get('overall_risk_level', '?')}")
            return result
        except Exception as e:
            self.log(f"Chyba AI analýzy LV: {e}", "warn")
            return None

    # ─── Parcel Geocoding ─────────────────────────────────────────────────
    async def _fetch_parcel_geometries(self, lv_data: LVData, context: dict) -> tuple[dict, list | None]:
        """Get parcel coordinates using Mapy.cz geocoding (most reliable)."""
        geometries = {}
        all_coords = []

        # Primary: Geocode property address via Mapy.cz (proven reliable from GeoValidator)
        property_address = context.get("property_address", "")
        ku_name = lv_data.kat_uzemi_nazev
        obec = lv_data.obec

        geocode_query = property_address or (f"{ku_name}, {obec}" if ku_name else "")

        if geocode_query:
            try:
                from config import MAPY_CZ_API_KEY
                self.log(f"Geokódování: '{geocode_query}'", "thinking")

                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://api.mapy.cz/v1/geocode",
                        params={"query": geocode_query, "lang": "cs", "limit": "1"},
                        headers={"X-Mapy-Api-Key": MAPY_CZ_API_KEY},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("items", [])
                        if items:
                            pos = items[0].get("position", {})
                            lat = pos.get("lat")
                            lon = pos.get("lon")
                            if lat and lon:
                                all_coords.append((lat, lon))
                                self.log(f"Souřadnice nemovitosti: ({lat:.6f}, {lon:.6f})")

                                # Assign coords to first parcel as reference point
                                if lv_data.parcels:
                                    geometries[lv_data.parcels[0].parcel_number] = {
                                        "lat": lat, "lon": lon,
                                        "area_m2": lv_data.parcels[0].area_m2,
                                    }
            except Exception as e:
                self.log(f"Geokódování selhalo: {e}", "warn")

        if not all_coords:
            self.log("Nepodařilo se získat souřadnice nemovitosti", "warn")

        # Compute bounding box from coordinates
        bbox = None
        if all_coords:
            lats = [c[0] for c in all_coords]
            lons = [c[1] for c in all_coords]
            # Buffer based on total parcel area (~sqrt(area) meters → degrees)
            total_area = sum(p.area_m2 for p in lv_data.parcels if p.area_m2)
            buffer = max(0.0015, (total_area ** 0.5) / 111000 * 2.0)
            bbox = [
                min(lons) - buffer,
                min(lats) - buffer,
                max(lons) + buffer,
                max(lats) + buffer,
            ]
            self.log(f"BBox ortofota: buffer={buffer:.5f}° ({int(buffer * 111000)}m)")

        return geometries, bbox

    # ─── Ortofoto download ──────────────────────────────────────────────
    async def _download_ortofoto(self, bbox: list, session_id: str,
                                  center_coords: tuple = None,
                                  num_parcels: int = 1) -> tuple[str | None, str | None]:
        """Download ortofoto + katastr-style overlay (yellow lines, cyan parcel fill).

        Layers composited:
        1. Ortofoto (satellite image)
        2. Cyan semi-transparent fill for property parcels (flood-fill + neighbors)
        3. Yellow parcel boundaries + parcel numbers (katastr style)
        """
        CUZK_WMS_KM = "https://services.cuzk.gov.cz/wms/local-km-wms.asp"
        FILL_SIZE = 512  # Reduced resolution for flood-fill

        try:
            session_dir = os.path.join(UPLOAD_DIR, session_id)
            os.makedirs(session_dir, exist_ok=True)

            wms_bbox = f"{bbox[1]},{bbox[0]},{bbox[3]},{bbox[2]}"
            IMG_SIZE = 1024

            async with httpx.AsyncClient(timeout=30) as client:
                # 1) Ortofoto
                ortho_resp = await client.get(CUZK_WMS_ORTOFOTO, params={
                    "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
                    "LAYERS": "0", "CRS": "EPSG:4326", "BBOX": wms_bbox,
                    "WIDTH": str(IMG_SIZE), "HEIGHT": str(IMG_SIZE),
                    "FORMAT": "image/jpeg", "STYLES": "",
                })

                if ortho_resp.status_code != 200 or not ortho_resp.headers.get("content-type", "").startswith("image"):
                    self.log(f"Ortofoto nedostupné (status {ortho_resp.status_code})", "warn")
                    return None, None

                self.log(f"Ortofoto staženo ({len(ortho_resp.content)} B)")

                # 2) Boundary lines (used for flood-fill mask + yellow overlay)
                boundary_resp = await client.get(CUZK_WMS_KM, params={
                    "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
                    "LAYERS": "hranice_parcel",
                    "CRS": "EPSG:4326", "BBOX": wms_bbox,
                    "WIDTH": str(IMG_SIZE), "HEIGHT": str(IMG_SIZE),
                    "FORMAT": "image/png", "STYLES": "", "TRANSPARENT": "TRUE",
                })

                # 3) Parcel numbers
                nums_resp = await client.get(CUZK_WMS_KM, params={
                    "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
                    "LAYERS": "parcelni_cisla",
                    "CRS": "EPSG:4326", "BBOX": wms_bbox,
                    "WIDTH": str(IMG_SIZE), "HEIGHT": str(IMG_SIZE),
                    "FORMAT": "image/png", "STYLES": "", "TRANSPARENT": "TRUE",
                })

            ortho_img = Image.open(io.BytesIO(ortho_resp.content)).convert("RGBA")

            # ── Flood-fill parcel highlighting (center + neighbors) ──
            if center_coords and boundary_resp.status_code == 200 and \
               boundary_resp.headers.get("content-type", "").startswith("image"):
                try:
                    lat, lon = center_coords
                    bnd_img = Image.open(io.BytesIO(boundary_resp.content)).convert("RGBA")
                    bnd_small = bnd_img.resize((FILL_SIZE, FILL_SIZE), Image.LANCZOS)

                    alpha = bnd_small.split()[3]
                    mask = alpha.point(lambda p: 0 if p > 30 else 255)
                    del alpha, bnd_small

                    cx = int((lon - bbox[0]) / (bbox[2] - bbox[0]) * FILL_SIZE)
                    cy = int((bbox[3] - lat) / (bbox[3] - bbox[1]) * FILL_SIZE)
                    cx = max(0, min(cx, FILL_SIZE - 1))
                    cy = max(0, min(cy, FILL_SIZE - 1))

                    mask_data = mask.load()
                    seed = None
                    for r in range(0, 60):
                        for dx in range(-r, r + 1):
                            for dy in [-r, r] if abs(dx) < r else range(-r, r + 1):
                                px, py = cx + dx, cy + dy
                                if 0 <= px < FILL_SIZE and 0 <= py < FILL_SIZE:
                                    if mask_data[px, py] == 255:
                                        seed = (px, py)
                                        break
                            if seed:
                                break
                        if seed:
                            break

                    FILL_VAL = 128
                    filled_count = 0

                    if seed:
                        ImageDraw.floodfill(mask, seed, FILL_VAL, thresh=50)
                        filled_count = 1

                        # Neighbor expansion: fill adjacent parcels
                        if num_parcels > 1:
                            JUMP = 6
                            mask_data = mask.load()
                            neighbor_grid = {}
                            for x in range(FILL_SIZE):
                                for y in range(FILL_SIZE):
                                    if mask_data[x, y] == FILL_VAL:
                                        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
                                            nx, ny = x + dx, y + dy
                                            if 0 <= nx < FILL_SIZE and 0 <= ny < FILL_SIZE and mask_data[nx, ny] == 0:
                                                for jmp in range(JUMP, JUMP + 6, 2):
                                                    jx, jy = x + dx * jmp, y + dy * jmp
                                                    if 0 <= jx < FILL_SIZE and 0 <= jy < FILL_SIZE and mask_data[jx, jy] == 255:
                                                        gk = (jx // 16, jy // 16)
                                                        if gk not in neighbor_grid:
                                                            neighbor_grid[gk] = [jx, jy, 0]
                                                        neighbor_grid[gk][2] += 1
                                                        break

                            sorted_neighbors = sorted(neighbor_grid.values(), key=lambda v: v[2], reverse=True)
                            for sx, sy, _ in sorted_neighbors[:num_parcels - 1]:
                                mask_data = mask.load()
                                if mask_data[sx, sy] == 255:
                                    ImageDraw.floodfill(mask, (sx, sy), FILL_VAL, thresh=50)
                                    filled_count += 1

                        fill_alpha = mask.point(lambda p: 80 if p == FILL_VAL else 0)
                        fill_alpha = fill_alpha.resize(ortho_img.size, Image.LANCZOS)
                        del mask

                        cyan = Image.new("RGBA", ortho_img.size, (0, 255, 255, 0))
                        cyan.putalpha(fill_alpha)
                        del fill_alpha

                        ortho_img = Image.alpha_composite(ortho_img, cyan)
                        del cyan
                        self.log(f"✓ {filled_count} parcel zvýrazněno (z {num_parcels} vybraných)")
                    else:
                        del mask
                        self.log("Seed pro flood-fill nenalezen", "warn")

                except Exception as e:
                    self.log(f"Chyba zvýraznění parcel: {e}", "warn")

            # ── Yellow boundary lines (katastr style) ──
            try:
                if boundary_resp.status_code == 200 and \
                   boundary_resp.headers.get("content-type", "").startswith("image"):
                    bnd_full = Image.open(io.BytesIO(boundary_resp.content)).convert("RGBA")
                    if bnd_full.size != ortho_img.size:
                        bnd_full = bnd_full.resize(ortho_img.size, Image.LANCZOS)
                    bnd_alpha = bnd_full.split()[3]
                    del bnd_full
                    yellow_lines = Image.new("RGBA", ortho_img.size, (255, 255, 0, 0))
                    yellow_lines.putalpha(bnd_alpha)
                    del bnd_alpha
                    ortho_img = Image.alpha_composite(ortho_img, yellow_lines)
                    del yellow_lines
            except Exception as e:
                self.log(f"Chyba překrytí hranic: {e}", "warn")

            # ── Yellow parcel numbers ──
            try:
                if nums_resp.status_code == 200 and \
                   nums_resp.headers.get("content-type", "").startswith("image"):
                    nums_img = Image.open(io.BytesIO(nums_resp.content)).convert("RGBA")
                    if nums_img.size != ortho_img.size:
                        nums_img = nums_img.resize(ortho_img.size, Image.LANCZOS)
                    nums_alpha = nums_img.split()[3]
                    del nums_img
                    yellow_nums = Image.new("RGBA", ortho_img.size, (255, 255, 0, 0))
                    yellow_nums.putalpha(nums_alpha)
                    del nums_alpha
                    ortho_img = Image.alpha_composite(ortho_img, yellow_nums)
                    del yellow_nums
                    self.log("✓ Žluté hranice a čísla parcel")
            except Exception as e:
                self.log(f"Chyba překrytí čísel: {e}", "warn")

            # Save final image
            final_img = ortho_img.convert("RGB")
            ortofoto_path = os.path.join(session_dir, "ortofoto_cuzk.jpg")
            final_img.save(ortofoto_path, "JPEG", quality=90)
            ortofoto_url = f"/uploads/{session_id}/ortofoto_cuzk.jpg"
            return ortofoto_path, ortofoto_url

        except Exception as e:
            self.log(f"Chyba stahování ortofota: {e}", "warn")
            return None, None

    # ─── Ortofoto AI Analysis ───────────────────────────────────────────
    async def _analyze_ortofoto(self, ortofoto_path: str, lv_data: LVData, images: list) -> dict | None:
        """Analyze ortofoto with Gemini to detect unregistered buildings."""
        try:
            with open(ortofoto_path, "rb") as f:
                ortofoto_bytes = f.read()

            # Build parcel info for context
            parcel_info = "\n".join([
                f"- Parcela {p.parcel_number}: {p.area_m2} m², {p.land_type}"
                for p in lv_data.parcels
            ])
            building_info = "\n".join([
                f"- {b.part_of} (na pozemku {b.on_parcel})"
                for b in lv_data.buildings
            ]) or "Žádné stavby v LV"

            parts = [
                f"ORTOFOTO pozemků z katastrálního území {lv_data.kat_uzemi_nazev} "
                f"(LV {lv_data.lv_number}):\n\n",
                types.Part.from_bytes(data=ortofoto_bytes, mime_type="image/jpeg"),
                f"\n\nINFORMACE Z LV:\n\nParcely:\n{parcel_info}\n\n"
                f"Zapsané stavby:\n{building_info}\n\n"
                f"Analyzuj ortofoto a hledej stavby, které NEJSOU v LV zapsány.",
            ]

            response_text = await self.client.generate_content(
                system_instruction=ORTOFOTO_ANALYSIS_PROMPT,
                contents=parts,
                response_mime_type="application/json",
                max_output_tokens=2000,
            )

            result = json.loads(response_text)
            detected = result.get("buildings_detected", [])
            self.log(f"Ortofoto analýza: {len(detected)} nezakreslených staveb detekováno")
            return result

        except Exception as e:
            self.log(f"Chyba AI analýzy ortofota: {e}", "warn")
            return None

    # ─── Annotate ortofoto with detected buildings ──────────────────────
    def _annotate_ortofoto(self, ortofoto_path: str, buildings: list, session_id: str) -> str | None:
        """Draw bounding boxes and labels on ortofoto for detected buildings."""
        try:
            img = Image.open(ortofoto_path).convert("RGB")
            draw = ImageDraw.Draw(img)
            w, h = img.size

            # Color mapping by risk level
            RISK_COLORS = {
                "vysoké": (220, 38, 38),    # red
                "střední": (245, 158, 11),   # amber/orange
                "nízké": (34, 197, 94),      # green
            }

            # Try to load a font, fall back to default
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
            except (IOError, OSError):
                font = ImageFont.load_default()
                font_small = font

            for i, b in enumerate(buildings, 1):
                bx = b.get("bbox_x", 0) / 100.0
                by = b.get("bbox_y", 0) / 100.0
                bw = b.get("bbox_w", 10) / 100.0
                bh = b.get("bbox_h", 10) / 100.0

                x1 = int(bx * w)
                y1 = int(by * h)
                x2 = int((bx + bw) * w)
                y2 = int((by + bh) * h)

                # Clamp to image bounds
                x1 = max(0, min(x1, w - 1))
                y1 = max(0, min(y1, h - 1))
                x2 = max(x1 + 1, min(x2, w))
                y2 = max(y1 + 1, min(y2, h))

                risk = b.get("risk_level", "střední")
                color = RISK_COLORS.get(risk, (245, 158, 11))
                label = b.get("label", f"Stavba #{i}")
                area = b.get("estimated_area_m2", "?")

                # Draw rectangle (3px thick)
                for offset in range(3):
                    draw.rectangle(
                        [x1 - offset, y1 - offset, x2 + offset, y2 + offset],
                        outline=color,
                    )

                # Draw label background
                label_text = f"{label} (~{area} m²)"
                bbox = draw.textbbox((0, 0), label_text, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]
                label_y = max(0, y1 - text_h - 6)
                draw.rectangle(
                    [x1, label_y, x1 + text_w + 8, label_y + text_h + 4],
                    fill=color,
                )
                draw.text((x1 + 4, label_y + 2), label_text, fill=(255, 255, 255), font=font)

            # Save annotated image
            session_dir = os.path.join(UPLOAD_DIR, session_id)
            annotated_path = os.path.join(session_dir, "ortofoto_annotated.jpg")
            img.save(annotated_path, "JPEG", quality=90)
            self.log(f"Ortofoto anotováno: {len(buildings)} staveb označeno")
            return annotated_path

        except Exception as e:
            self.log(f"Chyba anotace ortofota: {e}", "warn")
            return None
