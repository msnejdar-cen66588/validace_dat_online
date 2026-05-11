"""Agent: PorovnavacDokumentuBJ – porovnání dat z PDF formuláře s fotodokumentací + ověření podlahové plochy.

BJ variant: compares apartment-specific data from PDF with photos.
Additionally validates floor area document (nabývací titul, prohlášení vlastníka, etc.).
"""
import json
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import GEMINI_API_KEY, GEMINI_MODEL

COMPARATOR_BJ_SYSTEM_PROMPT = """Jsi expertní odhadce nemovitostí specializovaný na bytové jednotky. Tvým úkolem je na základě fotodokumentace křížově ověřit údaje z dotazníku klienta pro bytovou jednotku.

Dostaneš:
1. Údaje z formuláře (JSON): informace o budově (konstrukce, stav, podlaží) + informace o bytu (typ, plocha, stav, vytápění)
2. Fotografie nemovitosti (exteriér budovy, vstup do jednotky, interiér bytu)

Následuj tyto přesné postupy:

═══════════════════════════════════════════════════════════════
1. **TYP JEDNOTKY A POČET MÍSTNOSTÍ**
═══════════════════════════════════════════════════════════════
Ověř, zda deklarovaný typ jednotky (1+1, 2+kk, 3+1, ...) odpovídá počtu viditelných místností na fotkách.
- "1+1" = 1 pokoj + oddělená kuchyň
- "1+kk" = 1 pokoj s kuchyňským koutem
- "2+kk" = 2 pokoje + kuchyňský kout
- "3+1" = 3 pokoje + oddělená kuchyň
- Pokud počet místností na fotkách nesedí, zapiš neshodu.

═══════════════════════════════════════════════════════════════
2. **PLOCHA BYTU (m²) – Vizuální odhad**
═══════════════════════════════════════════════════════════════
Na základě interiérových fotek odhadni celkovou podlahovou plochu bytu:
- Odhadni rozměry každé viditelné místnosti (délka × šířka).
- Použij měřítko: dveře ~0,9m, okno ~1,5m, kuchyňská linka ~2,5-3m.
- Sečti plochy všech odhadnutých místností.
- Porovnej s deklarovanou plochou. Odchylka +/- 25 % = SHODA.

═══════════════════════════════════════════════════════════════
3. **STAV BYTU (Povinná kombinace)**
═══════════════════════════════════════════════════════════════
Stav bytu MUSÍŠ hodnotit z interiérových fotek:
- Stav podlah, stěn, stropů, kuchyně, koupelny, dveří, oken.
- Porovnej s deklarovaným stavem bytu z formuláře.
- V poli "observed" uveď: "Interiér: [hodnocení]. Celkově: [finální hodnocení]."

═══════════════════════════════════════════════════════════════
4. **KONSTRUKCE BUDOVY**
═══════════════════════════════════════════════════════════════
Z exteriérových fotek urči, zda je budova panelová, cihlová, nebo jiná.
Porovnej s deklarací v formuláři.

═══════════════════════════════════════════════════════════════
5. **PODLAŽÍ**
═══════════════════════════════════════════════════════════════
Pokud jsou k dispozici fotky z oken nebo balkonů, zkontroluj zda výhled odpovídá deklarovanému podlaží.
Pokud nelze ověřit, uveď "Nelze ověřit z fotek."

6. **VÝTAH** – Je viditelný na fotkách ze společných prostor?
7. **BALKÓN/TERASA** – Odpovídá deklaraci? Jsou viditelné na fotkách?
8. **TYP VYTÁPĚNÍ** – Viditelné radiátory, podlahové topení, konvektory?

Vrať výsledek POUZE jako validní JSON:
{
  "verdict": "SHODA" | "ČÁSTEČNÁ_SHODA" | "NESHODA",
  "confidence": 0.0-1.0,
  "overall_summary": "Celkové shrnutí porovnání...",
  "checks": [
    {
      "field": "typ jednotky",
      "declared": "1+1",
      "observed": "Na fotkách vidím 1 pokoj + oddělenou kuchyň = 1+1",
      "match": true,
      "note": "Počet místností odpovídá deklarovanému typu."
    },
    {
      "field": "plocha bytu",
      "declared": "33 m²",
      "observed": "Odhad ~30 m²",
      "match": true,
      "note": "Kuchyň ~6 m², pokoj ~16 m², koupelna ~4 m², chodba ~4 m². Celkem ~30 m². Odchylka 9 % = SHODA."
    },
    {
      "field": "stav bytu",
      "declared": "Dobře udržovaný",
      "observed": "Interiér: dobrý stav, funkční vybavení.",
      "match": true,
      "note": "Stav odpovídá deklaraci."
    },
    {
      "field": "konstrukce budovy",
      "declared": "Panelový",
      "observed": "Panelový dům",
      "match": true,
      "note": "..."
    },
    {
      "field": "podlaží",
      "declared": "2",
      "observed": "Nelze ověřit z fotek.",
      "match": true,
      "note": "..."
    },
    {
      "field": "výtah",
      "declared": "ano",
      "observed": "...",
      "match": true,
      "note": "..."
    },
    {
      "field": "balkón/terasa",
      "declared": "0 m²",
      "observed": "...",
      "match": true,
      "note": "..."
    },
    {
      "field": "typ vytápění",
      "declared": "dálkové",
      "observed": "...",
      "match": true,
      "note": "..."
    }
  ],
  "warnings": ["Varování..."],
  "recommendations": ["Doporučení..."]
}
"""

FLOOR_AREA_DOC_PROMPT = """Jsi expert na analýzu dokumentů pro ověření podlahové plochy bytové jednotky dle metodiky bank.

Dostáváš dokument (PDF nebo obrázky), který by měl věrohodně potvrzovat podlahovou plochu jednotky.
POZOR: Dokument může být rozdělen do VÍCE SOUBORŮ (např. kupní smlouva naskenovaná po stránkách do
samostatných PDF nebo fotek). Vždy analyzuj VŠECHNY poskytnuté soubory jako JEDEN celistvý dokument.

═══════════════════════════════════════════════════════════════
AKCEPTOVATELNÉ TYPY DOKUMENTŮ:
═══════════════════════════════════════════════════════════════
1. Nabývací titul k nemovitosti (kupní smlouva, smlouva o převodu, smlouva o smlouvě budoucí)
2. Prohlášení vlastníka
3. Vyúčtování služeb
4. Evidenční list SVJ/BD
5. Odhad nemovitosti (znalecký posudek)

NEAKCEPTOVATELNÉ: fotky, vlastní poznámky, inzeráty, katastrovní mapy bez plochy.

═══════════════════════════════════════════════════════════════
TVŮJ ÚKOL:
═══════════════════════════════════════════════════════════════
1. Identifikuj TYP DOKUMENTU – je to jeden z akceptovatelných typů?
2. EXTRAHUJ VŠECHNY údaje o plochách, které dokument obsahuje:
   - Podlahová plocha bytu (hlavní obytná plocha)
   - Plocha balkónu / lodžie
   - Plocha terasy
   - Plocha sklepa / komory / skladu
   - Plocha garáže / garážového stání
   - Plocha zahrady / předzahrádky
   Hledej klíčová slova: "podlahová plocha", "výměra", "plocha bytu", "plocha jednotky", "m²", "celková plocha"
3. VYPOČÍTEJ ZAPOČITATELNOU PLOCHU dle metodiky:
   - Plocha bytu: koeficient 1.0 (100 %)
   - Balkón / lodžie: koeficient 0.2 (20 %)
   - Terasa: koeficient 0.1 (10 %)
   - Sklep / komora: koeficient 0.1 (10 %)
   - Garáž: koeficient 0.8 (80 %) – pouze pokud je součástí jednotky
   - Zahrada: koeficient 0.0 (nezapočítává se)
   Započitatelná plocha = byt×1.0 + balkón×0.2 + terasa×0.1 + sklep×0.1 + garáž×0.8
4. Posuď VĚROHODNOST – je to formální dokument s právní vahou?

═══════════════════════════════════════════════════════════════
VÝSTUP – vrať POUZE validní JSON:
═══════════════════════════════════════════════════════════════
{
  "document_type": "kupní smlouva" | "prohlášení vlastníka" | "vyúčtování služeb" | "evidenční list" | "odhad nemovitosti" | "neznámý" | "neakceptovatelný",
  "is_acceptable": true/false,
  "extracted_floor_area_m2": 55.0,
  "area_components": {
    "byt_m2": 55.0,
    "balkon_m2": 4.5,
    "terasa_m2": 0,
    "sklep_m2": 3.2,
    "garaz_m2": 0,
    "zahrada_m2": 0
  },
  "zapocitatalna_plocha_m2": 56.22,
  "zapocitatalna_vypocet": "55.0×1.0 + 4.5×0.2 + 0×0.1 + 3.2×0.1 + 0×0.8 = 56.22 m²",
  "confidence": 0.0-1.0,
  "notes": "Podrobný popis: jaký dokument to je, co v něm stojí, odkud jsi plochu vzal."
}

Pokud plochu nenajdeš, nastav extracted_floor_area_m2 a zapocitatalna_plocha_m2 na null.
"""


class PorovnavacDokumentuBJAgent(BaseAgent):
    """Compares declared apartment data (from PDF/manual input) with photo evidence.
    Also validates floor area documentation."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="PorovnavacDokumentuBJ",
            description="Porovnání údajů z formuláře bytu s fotodokumentací + ověření podlahové plochy",
            system_prompt=COMPARATOR_BJ_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        property_data = context.get("property_data")
        images = context.get("images", [])
        floor_area_doc_paths = context.get("floor_area_doc_paths", [])

        # Skip if no property data provided
        if not property_data:
            self.log("Žádná data z formuláře – přeskakuji porovnání.", "info")
            return AgentResult(
                status=AgentStatus.SUCCESS,
                summary="Přeskočeno – nebyla poskytnuta data z formuláře.",
                details={"skipped": True, "reason": "no_property_data"},
            )

        self.log(f"Porovnávám data bytu z formuláře s {len(images)} fotografiemi...", "thinking")

        if not self.client:
            self.log("Gemini API key not configured.", "warn")
            return AgentResult(
                status=AgentStatus.WARN,
                summary="Porovnání není dostupné – chybí API klíč.",
                details={"skipped": True, "reason": "no_api_key"},
                warnings=["Gemini API klíč není nakonfigurován."],
            )

        if not images:
            self.log("Žádné fotografie pro porovnání.", "warn")
            return AgentResult(
                status=AgentStatus.WARN,
                summary="Porovnání není možné – žádné fotografie.",
                details={"skipped": True, "reason": "no_images"},
                warnings=["Nebyla poskytnuta žádná fotodokumentace."],
            )

        try:
            from google.genai import types

            # ── Build photo classification map from StrazceBJ results ──
            classification_map: dict[str, list[str]] = {}
            description_map: dict[str, str] = {}
            agent_results = context.get("agent_results", {})
            strazce_result = agent_results.get("StrazceBJ")
            if strazce_result and hasattr(strazce_result, 'details') and strazce_result.details:
                classifications = strazce_result.details.get("classifications", [])
                for clf in classifications:
                    photo_id = clf.get("photo_id", "")
                    categories = clf.get("categories", [])
                    description = clf.get("description", "")
                    classification_map[photo_id] = categories
                    description_map[photo_id] = description

            # ── Prioritize photos: exterior first, then interior ──
            exterior_images = []
            interior_images = []
            other_images = []

            for img in images:
                img_id = img.get("id", "")
                cats = classification_map.get(img_id, [])
                cats_text = " ".join(cats).upper()
                if "EXTERIER" in cats_text or "VSTUP" in cats_text:
                    exterior_images.append(img)
                elif "INTERIER" in cats_text:
                    interior_images.append(img)
                else:
                    other_images.append(img)

            prioritized = exterior_images + interior_images + other_images
            photos_to_send = prioritized[:10]

            self.log(f"Odesílám {len(photos_to_send)} fotek pro porovnání")

            # Build prompt
            property_json = json.dumps(property_data, ensure_ascii=False, indent=2)
            parts = [
                f"Údaje z formuláře ocenění bytové jednotky:\n```json\n{property_json}\n```\n\n"
                f"Porovnej tyto údaje s následujícími {len(photos_to_send)} fotografiemi:\n"
            ]

            for img in photos_to_send:
                try:
                    with open(img["processed_path"], "rb") as f:
                        image_bytes = f.read()
                    parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

                    img_id = img.get("id", "?")
                    cats = classification_map.get(img_id, [])
                    desc = description_map.get(img_id, "")
                    label_parts = [f"Photo ID: {img_id}"]
                    if cats:
                        label_parts.append(f"Typ: {', '.join(cats)}")
                    if desc:
                        label_parts.append(f"Popis: {desc}")
                    parts.append(" | ".join(label_parts))
                except Exception as e:
                    self.log(f"Error reading image {img.get('id', '?')}: {e}", "warn")

            response_text = await self.client.generate_content(
                system_instruction=self.system_prompt,
                contents=parts,
                response_mime_type="application/json",
                max_output_tokens=8000,
            )

            self.log("AI porovnání bytu dokončeno.", "info")
            ai_result = robust_json_parse(response_text)

            verdict = ai_result.get("verdict", "UNKNOWN")
            confidence = ai_result.get("confidence", 0.0)
            checks = ai_result.get("checks", [])
            ai_warnings = ai_result.get("warnings", [])
            recommendations = ai_result.get("recommendations", [])
            overall_summary = ai_result.get("overall_summary", "")

             # ── Floor area document validation ──
            # All uploaded files are treated as ONE document (e.g. a contract split into multiple PDFs/photos)
            floor_area_results = []
            if floor_area_doc_paths and len(floor_area_doc_paths) > 0:
                self.log(
                    f"Ověřuji podklad podlahové plochy ({len(floor_area_doc_paths)} soubor(ů) = 1 dokument)...",
                    "thinking",
                )
                for dp in floor_area_doc_paths:
                    self.log(f"  Soubor: {dp}")

                # Single AI call with ALL files as one document
                floor_area_result = await self._validate_floor_area_doc(
                    floor_area_doc_paths, property_data
                )

                if floor_area_result:
                    floor_area_results.append(floor_area_result)
                    declared_area = property_data.get("plocha_bytu", "neznámo")
                    extracted = floor_area_result.get("extracted_floor_area_m2")
                    zapocit = floor_area_result.get("zapocitatalna_plocha_m2")
                    components = floor_area_result.get("area_components", {})
                    vypocet = floor_area_result.get("zapocitatalna_vypocet", "")
                    doc_type = floor_area_result.get("document_type", "neznámý")
                    is_acceptable = floor_area_result.get("is_acceptable", False)
                    doc_label = "dokument podlahové plochy"

                    if not is_acceptable:
                        checks.append({
                            "field": doc_label,
                            "declared": declared_area,
                            "observed": f"Typ dokumentu: {doc_type} – neakceptovatelný",
                            "match": False,
                            "note": floor_area_result.get("notes", ""),
                        })
                        ai_warnings.append(
                            f"Nahraný dokument ({doc_type}) není akceptovatelný podklad."
                        )
                    elif extracted is not None:
                        try:
                            declared_num = float(
                                str(declared_area).replace("m²", "").replace("m2", "").replace(",", ".").strip()
                            )
                            diff_pct = abs(extracted - declared_num) / declared_num * 100 if declared_num > 0 else 999
                            area_match = diff_pct <= 10

                            # Build rich observed text
                            observed_parts = [f"{extracted} m² (z {doc_type})"]
                            if zapocit is not None:
                                observed_parts.append(f"Započitatelná plocha: {zapocit} m²")
                            observed_text = " | ".join(observed_parts)

                            # Build detailed note with component breakdown
                            note_parts = [
                                f"Plocha z dokumentu: {extracted} m², deklarovaná: {declared_num} m². "
                                f"Odchylka: {diff_pct:.0f} %."
                            ]
                            if vypocet:
                                note_parts.append(f"Výpočet: {vypocet}")
                            if components:
                                comp_strs = []
                                if components.get("byt_m2"):
                                    comp_strs.append(f"byt: {components['byt_m2']} m²")
                                if components.get("balkon_m2"):
                                    comp_strs.append(f"balkón: {components['balkon_m2']} m²")
                                if components.get("terasa_m2"):
                                    comp_strs.append(f"terasa: {components['terasa_m2']} m²")
                                if components.get("sklep_m2"):
                                    comp_strs.append(f"sklep: {components['sklep_m2']} m²")
                                if components.get("garaz_m2"):
                                    comp_strs.append(f"garáž: {components['garaz_m2']} m²")
                                if comp_strs:
                                    note_parts.append("Složky: " + ", ".join(comp_strs))

                            checks.append({
                                "field": doc_label,
                                "declared": declared_area,
                                "observed": observed_text,
                                "match": area_match,
                                "note": " ".join(note_parts),
                            })
                            if not area_match:
                                ai_warnings.append(
                                    f"Plocha z dokumentu ({extracted} m²) se neshoduje "
                                    f"s deklarovanou ({declared_num} m²) – odchylka {diff_pct:.0f} %."
                                )
                        except (ValueError, TypeError):
                            checks.append({
                                "field": doc_label,
                                "declared": declared_area,
                                "observed": f"{extracted} m² (z {doc_type})" + (f" | Započitatelná: {zapocit} m²" if zapocit else ""),
                                "match": True,
                                "note": "Nelze numericky porovnat s deklarovanou plochou.",
                            })

                        # Also add a dedicated "započitatelná plocha" check if available
                        if zapocit is not None:
                            checks.append({
                                "field": "započitatelná plocha",
                                "declared": declared_area,
                                "observed": f"{zapocit} m²",
                                "match": True,
                                "note": vypocet or f"Započitatelná plocha dle metodiky: {zapocit} m²",
                            })
                    else:
                        checks.append({
                            "field": doc_label,
                            "declared": declared_area,
                            "observed": f"Typ: {doc_type} – plocha nebyla nalezena v dokumentu",
                            "match": False,
                            "note": floor_area_result.get("notes", ""),
                        })
                        ai_warnings.append(
                            "V nahraném dokumentu se nepodařilo najít podlahovou plochu."
                        )
                else:
                    self.log("Dokument podlahové plochy nebylo možné zpracovat.", "warn")
                    ai_warnings.append("Dokument podlahové plochy se nepodařilo zpracovat.")
            else:
                # No floor area docs uploaded
                ai_warnings.append(
                    "Nebyl nahrán dokument potvrzující podlahovou plochu jednotky."
                )

            # Count matches/mismatches
            matches = sum(1 for c in checks if c.get("match", False))
            mismatches = len(checks) - matches

            # Override verdict based on checks
            if checks:
                if mismatches == 0:
                    verdict = "SHODA"
                elif matches == 0:
                    verdict = "NESHODA"
                else:
                    verdict = "ČÁSTEČNÁ_SHODA"

            if verdict == "SHODA":
                status = AgentStatus.SUCCESS
            elif verdict == "ČÁSTEČNÁ_SHODA":
                status = AgentStatus.WARN
            else:
                status = AgentStatus.FAIL

            self.log(f"Výsledek: {verdict} (confidence: {confidence})")

            return AgentResult(
                status=status,
                summary=f"{verdict}: {matches} shod, {mismatches} neshod (spolehlivost {confidence:.0%})",
                details={
                    "verdict": verdict,
                    "confidence": confidence,
                    "overall_summary": overall_summary,
                    "checks": checks,
                    "recommendations": recommendations,
                    "property_data": property_data,
                    "floor_area_results": floor_area_results,
                },
                warnings=ai_warnings,
            )

        except Exception as e:
            self.log(f"Chyba při porovnání: {str(e)}", "error")
            return AgentResult(
                status=AgentStatus.WARN,
                summary=f"Porovnání selhalo: {str(e)}",
                details={"error": str(e)},
                warnings=[f"Porovnání dokumentů nebylo možné provést: {str(e)}"],
            )

    async def _validate_floor_area_doc(
        self, doc_paths: list[str], property_data: dict
    ) -> dict | None:
        """Validate floor area document(s) using AI.

        All provided files are treated as parts of a single document
        (e.g. a purchase contract split into multiple PDFs or photos).
        They are sent together in one AI call so the model sees the
        complete document context.
        """
        try:
            import os
            from google.genai import types

            # Read all files and build parts
            file_parts = []
            total_bytes = 0
            for doc_path in doc_paths:
                if not os.path.exists(doc_path):
                    self.log(f"Soubor neexistuje: {doc_path}", "warn")
                    continue

                with open(doc_path, "rb") as f:
                    doc_bytes = f.read()

                total_bytes += len(doc_bytes)

                # Determine mime type
                ext = doc_path.lower().rsplit(".", 1)[-1] if "." in doc_path else ""
                mime_map = {
                    "pdf": "application/pdf",
                    "jpg": "image/jpeg",
                    "jpeg": "image/jpeg",
                    "png": "image/png",
                    "webp": "image/webp",
                    "heic": "image/heic",
                    "heif": "image/heif",
                    "tiff": "image/tiff",
                    "tif": "image/tiff",
                    "bmp": "image/bmp",
                }
                mime_type = mime_map.get(ext, "image/jpeg")

                file_parts.append({
                    "bytes": doc_bytes,
                    "mime_type": mime_type,
                    "filename": os.path.basename(doc_path),
                })

            if not file_parts:
                self.log("Žádné platné soubory pro ověření plochy.", "warn")
                return None

            self.log(
                f"Čtu {len(file_parts)} soubor(ů) podlahové plochy "
                f"(celkem {total_bytes} bytes) jako 1 dokument"
            )

            declared_area = property_data.get("plocha_bytu", "neznámo")

            # Build prompt with ALL files as one document
            file_count_note = ""
            if len(file_parts) > 1:
                file_count_note = (
                    f"\n\nDOKUMENT JE ROZDĚLEN DO {len(file_parts)} SOUBORŮ. "
                    "Všechny soubory tvoří dohromady JEDEN dokument (např. kupní smlouva "
                    "naskenovaná po stránkách). Analyzuj je jako celek.\n"
                )

            parts = [
                f"Analyzuj tento dokument, který by měl potvrzovat podlahovou plochu bytové jednotky.\n"
                f"Deklarovaná plocha bytu z formuláře: {declared_area}\n"
                f"{file_count_note}\n"
                f"Extrahuj VŠECHNY zmíněné plochy (byt, balkón, terasa, sklep, garáž) "
                f"a VYPOČÍTEJ započitatelnou plochu dle metodiky.\n\n",
            ]

            for i, fp in enumerate(file_parts):
                parts.append(
                    types.Part.from_bytes(data=fp["bytes"], mime_type=fp["mime_type"])
                )
                if len(file_parts) > 1:
                    parts.append(f"(Soubor {i + 1}/{len(file_parts)}: {fp['filename']})")

            parts.append(
                "\n\nUrči typ dokumentu, extrahuj plochy, vypočítej započitatelnou plochu a posuď věrohodnost."
            )

            response_text = await self.client.generate_content(
                system_instruction=FLOOR_AREA_DOC_PROMPT,
                contents=parts,
                response_mime_type="application/json",
                max_output_tokens=3000,
            )

            result = robust_json_parse(response_text)
            zapocit = result.get("zapocitatalna_plocha_m2")
            components = result.get("area_components", {})
            self.log(
                f"Dokument plochy: typ={result.get('document_type')}, "
                f"plocha bytu={result.get('extracted_floor_area_m2')} m², "
                f"započitatelná={zapocit} m², "
                f"komponenty={components}, "
                f"akceptovatelný={result.get('is_acceptable')}"
            )
            return result

        except Exception as e:
            self.log(f"Chyba ověření dokumentu plochy: {e}", "warn")
            import traceback
            self.log(f"Traceback: {traceback.format_exc()}", "warn")
            return None
