"""AI Agent for contract analysis — classification, data extraction, and Q&A.

This agent:
1. Classifies the type of contract (kupní, úvěrová, zástavní, etc.)
2. Generates relevant quick presets based on contract type
3. Extracts data for selected presets
4. Answers natural language queries about the contract
5. Returns text positions for highlighting
"""
import json
from typing import Optional
from dataclasses import dataclass, field

from agents.llm_utils import LLMClient


# Predefined presets for each contract type
CONTRACT_PRESETS = {
    "kupni_smlouva": {
        "label": "Kupní smlouva",
        "icon": "🏠",
        "presets": [
            {"id": "kupni_cena", "label": "Kupní cena", "query": "Jaká je celková kupní cena?"},
            {"id": "prodavajici", "label": "Prodávající", "query": "Kdo jsou prodávající? Uveď jména, rodná čísla a adresy."},
            {"id": "kupujici", "label": "Kupující", "query": "Kdo jsou kupující? Uveď jména, rodná čísla a adresy."},
            {"id": "predmet_koupě", "label": "Předmět koupě", "query": "Co je předmětem koupě? Popiš nemovitost."},
            {"id": "parcely", "label": "Parcely", "query": "Jaká parcelní čísla jsou uvedena ve smlouvě?"},
            {"id": "lv_cislo", "label": "List vlastnictví", "query": "Jaké číslo Listu vlastnictví je ve smlouvě uvedeno?"},
            {"id": "katastralní_uzemi", "label": "Katastrální území", "query": "Jaké katastrální území je uvedeno?"},
            {"id": "datum_podpisu", "label": "Datum podpisu", "query": "Jaké je datum podpisu smlouvy?"},
            {"id": "zpusob_uhrady", "label": "Způsob úhrady", "query": "Jaký je způsob úhrady kupní ceny?"},
            {"id": "pravni_vady", "label": "Právní vady / břemena", "query": "Jsou ve smlouvě zmíněny právní vady, věcná břemena nebo zástavní práva?"},
        ],
    },
    "smlouva_o_uveru": {
        "label": "Smlouva o úvěru / hypotéce",
        "icon": "💰",
        "presets": [
            {"id": "vyse_uveru", "label": "Výše úvěru", "query": "Jaká je výše poskytovaného úvěru?"},
            {"id": "urokova_sazba", "label": "Úroková sazba", "query": "Jaká je úroková sazba?"},
            {"id": "splatnost", "label": "Splatnost", "query": "Jaká je doba splatnosti úvěru?"},
            {"id": "rpsn", "label": "RPSN", "query": "Jaké je RPSN (roční procentní sazba nákladů)?"},
            {"id": "zajisteni", "label": "Zajištění", "query": "Čím je úvěr zajištěn?"},
            {"id": "ucel_uveru", "label": "Účel úvěru", "query": "Jaký je účel úvěru?"},
            {"id": "dluznik", "label": "Dlužník", "query": "Kdo je dlužník? Uveď jméno, RČ a adresu."},
            {"id": "veritel", "label": "Věřitel", "query": "Kdo je věřitel (poskytovatel úvěru)?"},
            {"id": "splatky", "label": "Měsíční splátky", "query": "Jaká je výše měsíčních splátek?"},
            {"id": "poplatky", "label": "Poplatky", "query": "Jaké poplatky jsou ve smlouvě uvedeny?"},
        ],
    },
    "zastavni_smlouva": {
        "label": "Zástavní smlouva",
        "icon": "🔒",
        "presets": [
            {"id": "zastavni_pravo", "label": "Zástavní právo", "query": "O jaké zástavní právo se jedná?"},
            {"id": "zastavce", "label": "Zástavce", "query": "Kdo je zástavce? Uveď jméno, RČ a adresu."},
            {"id": "zastavni_veritel", "label": "Zástavní věřitel", "query": "Kdo je zástavní věřitel?"},
            {"id": "zajistena_pohledavka", "label": "Zajištěná pohledávka", "query": "Jaká pohledávka je zástavním právem zajištěna a v jaké výši?"},
            {"id": "predmet_zastavy", "label": "Předmět zástavy", "query": "Co je předmětem zástavy? Uveď parcely, LV, katastrální území."},
            {"id": "poradí", "label": "Pořadí zástavního práva", "query": "V jakém pořadí je zástavní právo?"},
        ],
    },
    "darovaci_smlouva": {
        "label": "Darovací smlouva",
        "icon": "🎁",
        "presets": [
            {"id": "darce", "label": "Dárce", "query": "Kdo je dárce? Uveď jméno, RČ a adresu."},
            {"id": "obdarovany", "label": "Obdarovaný", "query": "Kdo je obdarovaný? Uveď jméno, RČ a adresu."},
            {"id": "predmet_daru", "label": "Předmět daru", "query": "Co je předmětem daru?"},
            {"id": "podminky", "label": "Podmínky", "query": "Jsou ve smlouvě nějaké podmínky nebo výhrady (např. služebnost, věcné břemeno)?"},
            {"id": "parcely", "label": "Parcely", "query": "Jaká parcelní čísla jsou uvedena?"},
        ],
    },
    "najemni_smlouva": {
        "label": "Nájemní smlouva",
        "icon": "🔑",
        "presets": [
            {"id": "pronajimatel", "label": "Pronajímatel", "query": "Kdo je pronajímatel? Uveď jméno/firmu a adresu."},
            {"id": "najemce", "label": "Nájemce", "query": "Kdo je nájemce? Uveď jméno a adresu."},
            {"id": "predmet_najmu", "label": "Předmět nájmu", "query": "Co je předmětem nájmu?"},
            {"id": "vyse_najmu", "label": "Výše nájemného", "query": "Jaká je výše nájemného?"},
            {"id": "doba_najmu", "label": "Doba nájmu", "query": "Na jakou dobu je nájem sjednán?"},
            {"id": "kauce", "label": "Kauce", "query": "Je ve smlouvě uvedena kauce/jistota a v jaké výši?"},
        ],
    },
    "smlouva_budouci": {
        "label": "Smlouva o smlouvě budoucí",
        "icon": "📋",
        "presets": [
            {"id": "budouci_kupujici", "label": "Budoucí kupující", "query": "Kdo je budoucí kupující?"},
            {"id": "budouci_prodavajici", "label": "Budoucí prodávající", "query": "Kdo je budoucí prodávající?"},
            {"id": "budouci_cena", "label": "Budoucí kupní cena", "query": "Jaká je sjednaná budoucí kupní cena?"},
            {"id": "termin_uzavreni", "label": "Termín uzavření", "query": "Do kdy má být budoucí smlouva uzavřena?"},
            {"id": "predmet", "label": "Předmět", "query": "Co je předmětem budoucí smlouvy?"},
            {"id": "smluvni_pokuta", "label": "Smluvní pokuta", "query": "Je ve smlouvě sjednaná smluvní pokuta?"},
        ],
    },
    "unknown": {
        "label": "Neznámý typ smlouvy",
        "icon": "📄",
        "presets": [
            {"id": "smluvni_strany", "label": "Smluvní strany", "query": "Kdo jsou smluvní strany?"},
            {"id": "predmet_smlouvy", "label": "Předmět smlouvy", "query": "Co je předmětem smlouvy?"},
            {"id": "datum_podpisu", "label": "Datum podpisu", "query": "Jaké je datum podpisu?"},
            {"id": "cena", "label": "Cena / částka", "query": "Jsou ve smlouvě uvedeny nějaké finanční částky?"},
            {"id": "podminky", "label": "Podmínky", "query": "Jaké jsou hlavní podmínky smlouvy?"},
        ],
    },
}


class ContractAnalyzerAgent:
    """AI agent for analyzing bank contracts."""

    def __init__(self, model_name: str = "gpt-5.4-mini"):
        self.llm = LLMClient(model_name=model_name)
        self.model_name = model_name

    async def ocr_images(self, images: list[dict]) -> str:
        """Use AI Vision to OCR images of contracts."""
        if not images:
            return ""

        contents = []
        contents.append(
            "DŮLEŽITÉ: Vypiš POUZE text ze smlouvy. NEPŘIDÁVEJ žádný vlastní komentář, úvod ani vysvětlení. "
            "Začni ROVNOU textem smlouvy. Žádné 'Dobře, zde je přepis...' ani nic podobného.\n\n"
            "Přepiš VEŠKERÝ text z těchto obrázků smlouvy. "
            "Zachovej přesně původní formátování, čísla paragrafů, odstavce. "
            "Pokud je text špatně čitelný, přepiš co nejpřesněji. "
            "Upozorni na části, které nelze přečíst značkou [nečitelné]. "
            "Odděl jednotlivé stránky pomocí '--- Strana X ---'."
        )

        # Build vision content
        from google.genai import types as genai_types

        for img_info in images:
            raw_bytes = img_info.get("raw_bytes")
            if raw_bytes:
                # Create an image part for the LLM
                class ImagePart:
                    def __init__(self, data, mime_type):
                        self.data = data
                        self.mime_type = mime_type
                contents.append(ImagePart(raw_bytes, img_info.get("mime_type", "image/jpeg")))

        try:
            text = await self.llm.generate_content(
                system_instruction=(
                    "Jsi OCR systém. Tvůj výstup obsahuje VÝHRADNĚ přepsaný text z obrázků. "
                    "NIKDY nepřidávej vlastní komentáře, úvody, vysvětlení ani shrnutí. "
                    "Začni ROVNOU prvním slovem z dokumentu. "
                    "Zachováváš formátování, čísla paragrafů, odstavce a strukturu dokumentu."
                ),
                contents=contents,
                max_output_tokens=8000,
                temperature=0.1,
            )
            return text or ""
        except Exception as e:
            print(f"[ContractAnalyzer] OCR error: {e}")
            return ""

    async def classify_contract(self, text: str) -> dict:
        """Classify the type of contract and return type + AI-generated presets."""
        prompt = f"""Analyzuj následující text smlouvy. Urči její typ a vygeneruj nejdůležitější předvolby pro vyhledávání.

Typy smluv:
- kupni_smlouva (kupní smlouva na nemovitost)
- smlouva_o_uveru (smlouva o úvěru, hypoteční smlouva)
- zastavni_smlouva (zástavní smlouva)
- darovaci_smlouva (darovací smlouva)
- najemni_smlouva (nájemní smlouva)
- smlouva_budouci (smlouva o smlouvě budoucí)
- unknown (pokud nelze určit)

INSTRUKCE PRO PŘEDVOLBY:
- Vygeneruj 8-12 nejdůležitějších věcí, které by banka/uživatel chtěl z TÉTO KONKRÉTNÍ smlouvy zjistit.
- Seřaď od nejdůležitějších po méně důležité.
- Každá předvolba musí mít unikátní ID, krátký popisek a přesný dotaz.
- Přizpůsob předvolby obsahu smlouvy — pokud smlouva zmiňuje specifické věci (věcná břemena, splátky, pokuty, atd.), přidej pro ně předvolby.
- Popisky musí být krátké (1-3 slova), dotazy konkrétní.

Odpověz POUZE jako JSON:
{{
    "contract_type": "typ_smlouvy",
    "confidence": 0.95,
    "title": "Lidský název smlouvy",
    "summary": "Stručný popis obsahu smlouvy (1-2 věty)",
    "parties": ["Strana 1", "Strana 2"],
    "presets": [
        {{"id": "unikatni_id", "label": "Krátký popisek", "query": "Konkrétní dotaz k vyhledání ve smlouvě"}},
        ...
    ]
}}

TEXT SMLOUVY:
{text[:6000]}
"""
        try:
            response = await self.llm.generate_content(
                system_instruction=(
                    "Jsi právní AI specialista na české bankovní smlouvy. "
                    "Klasifikuješ typ smlouvy a generuješ inteligentní předvolby "
                    "přizpůsobené obsahu konkrétní smlouvy. "
                    "Předvolby musí pokrývat to nejdůležitější, co by banka chtěla vědět."
                ),
                contents=[prompt],
                response_mime_type="application/json",
                max_output_tokens=1500,
                temperature=0.2,
            )
            result = json.loads(response)
            contract_type = result.get("contract_type", "unknown")

            # Get icon and label from static config
            preset_config = CONTRACT_PRESETS.get(contract_type, CONTRACT_PRESETS["unknown"])

            # Use AI-generated presets, fall back to static ones if empty
            ai_presets = result.get("presets", [])
            if not ai_presets or len(ai_presets) < 3:
                ai_presets = preset_config["presets"]

            return {
                "contract_type": contract_type,
                "confidence": result.get("confidence", 0),
                "title": result.get("title", preset_config["label"]),
                "summary": result.get("summary", ""),
                "parties": result.get("parties", []),
                "icon": preset_config["icon"],
                "label": preset_config["label"],
                "presets": ai_presets,
            }
        except Exception as e:
            print(f"[ContractAnalyzer] Classification error: {e}")
            fallback = CONTRACT_PRESETS["unknown"]
            return {
                "contract_type": "unknown",
                "confidence": 0,
                "title": "Smlouva",
                "summary": "Typ smlouvy nebyl rozpoznán.",
                "parties": [],
                "icon": fallback["icon"],
                "label": fallback["label"],
                "presets": fallback["presets"],
            }

    async def query_contract(self, text: str, query: str, pages_text: list[str]) -> dict:
        """Answer a query about the contract and return the answer + text position info."""
        # Build page reference
        pages_ref = ""
        for i, pt in enumerate(pages_text):
            pages_ref += f"\n\n=== STRANA {i+1} ===\n{pt}"

        prompt = f"""Odpověz na dotaz uživatele ohledně této smlouvy.

PRAVIDLA:
1. Prohledej CELOU smlouvu od začátku do konce.
2. Odpověz přesně a stručně na dotaz. Uveď konkrétní čísla, částky, data, jména.
3. Cituj PŘESNÝ úryvek textu ze smlouvy — DOSLOVA, znak po znaku, jak je napsán v dokumentu. Necituj parafrázovaně.
4. Citace musí být dostatečně dlouhá (alespoň 30 znaků), aby šla jednoznačně najít v textu smlouvy.
5. Uveď číslo strany, kde se informace nachází.
6. Pokud informaci opravdu nenajdeš po prohledání celé smlouvy, řekni to jasně.
7. V highlights uveď PŘESNÉ fráze z textu smlouvy, které se mají zvýraznit (doslovné citace, ne parafrázované).

Odpověz jako JSON:
{{
    "answer": "Odpověď na dotaz s konkrétními údaji",
    "found": true,
    "citations": [
        {{
            "text": "PŘESNÝ doslovný úryvek ze smlouvy (min 30 znaků, max 200 znaků)",
            "page": 1
        }}
    ],
    "highlights": [
        "přesná fráze ze smlouvy k zvýraznění 1",
        "přesná fráze ze smlouvy k zvýraznění 2"
    ]
}}

SMLOUVA:
{pages_ref[:12000]}

DOTAZ UŽIVATELE: {query}
"""
        try:
            response = await self.llm.generate_content(
                system_instruction=(
                    "Jsi právní AI asistent České spořitelny specializovaný na analýzu bankovních smluv. "
                    "Vždy prohledáš CELÝ dokument a najdeš požadovanou informaci. "
                    "Cituješ DOSLOVA text ze smlouvy — přesné znění včetně čísel, částek a interpunkce. "
                    "NIKDY neparafrázuj citace. Citace musí jít najít v originálním textu smlouvy. "
                    "Odpovídej v češtině."
                ),
                contents=[prompt],
                response_mime_type="application/json",
                max_output_tokens=2048,
                temperature=0.1,
            )
            result = json.loads(response)

            # Find text positions for highlighting
            highlights = result.get("highlights", [])
            citations = result.get("citations", [])

            # Try to find exact positions of highlighted text in the document
            highlight_positions = []
            for citation in citations:
                cited_text = citation.get("text", "")
                page_num = citation.get("page", 1) - 1  # Convert to 0-indexed

                if page_num < len(pages_text) and cited_text:
                    page_text = pages_text[page_num]
                    
                    # Multi-strategy search: try progressively shorter substrings
                    found_idx = -1
                    search_text = cited_text.strip()
                    
                    # Strategy 1: Full text match
                    found_idx = page_text.lower().find(search_text.lower())
                    
                    # Strategy 2: Try first 80 chars
                    if found_idx < 0 and len(search_text) > 80:
                        found_idx = page_text.lower().find(search_text[:80].lower())
                    
                    # Strategy 3: Try first 40 chars
                    if found_idx < 0 and len(search_text) > 40:
                        found_idx = page_text.lower().find(search_text[:40].lower())
                    
                    # Strategy 4: Try key numbers/amounts from the citation
                    if found_idx < 0:
                        import re
                        numbers = re.findall(r'[\d.,]+\s*(?:Kč|CZK|EUR|%)', search_text)
                        for num in numbers:
                            idx = page_text.find(num)
                            if idx >= 0:
                                found_idx = idx
                                break
                    
                    # Strategy 5: Try significant words (3+ chars)
                    if found_idx < 0:
                        words = [w for w in search_text.split() if len(w) >= 5]
                        for word in words[:3]:
                            idx = page_text.lower().find(word.lower())
                            if idx >= 0:
                                found_idx = idx
                                break
                    
                    if found_idx >= 0:
                        # Calculate Y position based on LINE number for accurate visual mapping
                        lines_before = page_text[:found_idx].count('\n')
                        total_lines = max(page_text.count('\n'), 1)
                        y_ratio = lines_before / total_lines if total_lines > 0 else 0
                        # Clamp to reasonable range (5% - 95%)
                        y_ratio = max(0.05, min(0.95, y_ratio))
                        
                        highlight_positions.append({
                            "page": page_num,
                            "text": cited_text,
                            "y_ratio": round(y_ratio, 3),
                        })

            return {
                "answer": result.get("answer", "Nepodařilo se najít odpověď."),
                "found": result.get("found", False),
                "citations": citations,
                "highlights": highlights,
                "highlight_positions": highlight_positions,
            }
        except Exception as e:
            print(f"[ContractAnalyzer] Query error: {e}")
            return {
                "answer": f"Chyba při zpracování dotazu: {str(e)}",
                "found": False,
                "citations": [],
                "highlights": [],
                "highlight_positions": [],
            }

    async def extract_preset(self, text: str, preset_query: str, pages_text: list[str]) -> dict:
        """Extract data for a specific preset query — uses the same query mechanism."""
        return await self.query_contract(text, preset_query, pages_text)

    async def extract_all(self, text: str, pages_text: list[str], contract_type: str, presets: list[dict]) -> dict:
        """Extract ALL key data from the contract with verification and validation.
        
        Two-phase approach:
        1. AI extracts all data
        2. Post-processing verifies citations, validates formats, recalculates confidence
        """
        import re
        
        # Build FULL page reference (no truncation)
        pages_ref = ""
        for i, pt in enumerate(pages_text):
            pages_ref += f"\n\n=== STRANA {i+1} ===\n{pt}"

        # Build preset list for the prompt
        preset_list = "\n".join([f"- {p['label']}: {p['query']}" for p in presets])

        prompt = f"""Extrahuj VŠECHNY klíčové údaje z této smlouvy do strukturované tabulky.

TYP SMLOUVY: {contract_type}

POŽADOVANÉ ÚDAJE (extrahuj minimálně tyto, ale přidej i další důležité):
{preset_list}

KRITICKÁ PRAVIDLA:
1. Prohledej CELOU smlouvu od začátku do konce — KAŽDOU stranu.
2. Pro každý údaj uveď PŘESNOU hodnotu — konkrétní číslo, jméno, datum, adresu.
3. Citace MUSÍ být DOSLOVNÝ kopie textu ze smlouvy (min 20 znaků) — ne parafráze.
4. U částek uveď PŘESNÝ formát jak je ve smlouvě (včetně Kč, haléřů, slovního vyjádření).
5. U jmen uveď CELÉ jméno včetně titulů pokud jsou uvedeny.
6. U rodných čísel uveď ve formátu jak je ve smlouvě.
7. U dat uveď přesný formát ze smlouvy.
8. Pokud údaj nenajdeš, nastav found na false a confidence na 0.
9. Přidej i další důležité údaje, které ve smlouvě najdeš ale nejsou v seznamu výše.
10. Hledej i IMPLICITNÍ informace (např. pokud je uvedena cena bez DPH a DPH, spočítej celkovou).

FORMÁT ODPOVĚDI (JSON):
{{
    "fields": [
        {{
            "id": "unikatni_id",
            "label": "Název údaje",
            "value": "Extrahovaná hodnota",
            "page": 1,
            "found": true,
            "confidence": 0.95,
            "citation": "DOSLOVNÝ úryvek ze smlouvy (min 20, max 200 znaků)",
            "data_type": "typ_dat"
        }}
    ],
    "summary": "Stručné shrnutí smlouvy (2-3 věty)",
    "red_flags": [
        {{
            "severity": "high",
            "title": "Název problému",
            "description": "Popis nalezeného problému",
            "page": 1
        }}
    ]
}}

MOŽNÉ data_type: "amount" (částka), "person" (jméno), "date" (datum), "id_number" (RČ/IČO), "address" (adresa), "parcel" (parcela/LV), "text" (jiné)

SMLOUVA:
{pages_ref}
"""
        try:
            response = await self.llm.generate_content(
                system_instruction=(
                    "Jsi právní AI analytik České spořitelny. "
                    "Extrahuj VŠECHNA klíčová data ze smlouvy do strukturované tabulky. "
                    "Buď ABSOLUTNĚ důkladný — nenech žádný důležitý údaj. "
                    "Citace MUSÍ být doslovné kopie textu — ne parafráze. "
                    "U částek VŽDY uveď přesné číslo. "
                    "Identifikuj potenciální problémy (red flags): nesrovnalosti, "
                    "chybějící podpisy, neobvyklé klauzule, vysoké pokuty, chybějící data."
                ),
                contents=[prompt],
                response_mime_type="application/json",
                max_output_tokens=6000,
                temperature=0.05,
            )
            result = json.loads(response)
            
            # ═══ PHASE 2: Post-processing verification ═══
            fields = result.get("fields", [])
            red_flags = result.get("red_flags", [])
            
            verified_fields = []
            for field in fields:
                citation = field.get("citation", "")
                page_num = field.get("page", 1) - 1
                data_type = field.get("data_type", "text")
                original_confidence = field.get("confidence", 0.5)
                
                # ─── Citation Verification ───
                citation_verified = False
                if page_num < len(pages_text) and citation:
                    page_text = pages_text[page_num]
                    found_idx = self._find_text_position(page_text, citation)
                    
                    if found_idx >= 0:
                        citation_verified = True
                        # Calculate Y position for highlights
                        lines_before = page_text[:found_idx].count('\n')
                        total_lines = max(page_text.count('\n'), 1)
                        y_ratio = max(0.05, min(0.95, lines_before / total_lines))
                        field["y_ratio"] = round(y_ratio, 3)
                    else:
                        # Try other pages (AI might have wrong page number)
                        for alt_page, alt_text in enumerate(pages_text):
                            if alt_page == page_num:
                                continue
                            alt_idx = self._find_text_position(alt_text, citation)
                            if alt_idx >= 0:
                                citation_verified = True
                                field["page"] = alt_page + 1  # Fix page number
                                lines_before = alt_text[:alt_idx].count('\n')
                                total_lines = max(alt_text.count('\n'), 1)
                                y_ratio = max(0.05, min(0.95, lines_before / total_lines))
                                field["y_ratio"] = round(y_ratio, 3)
                                break
                
                # ─── Recalculate confidence based on verification ───
                if field.get("found", False):
                    if citation_verified:
                        # Boost confidence if citation was verified in text
                        field["confidence"] = min(1.0, original_confidence + 0.05)
                        field["verified"] = True
                    else:
                        # Lower confidence if citation not found
                        field["confidence"] = max(0.3, original_confidence - 0.25)
                        field["verified"] = False
                
                # ─── Data Type Validation ───
                value = field.get("value", "")
                
                if data_type == "id_number" and value:
                    # Validate Czech RČ format (YYMMDD/XXXX or YYMMDDXXXX)
                    rc_clean = re.sub(r'[/\s]', '', value)
                    if re.match(r'^\d{9,10}$', rc_clean):
                        field["format_valid"] = True
                    else:
                        field["format_valid"] = False
                        if field.get("found"):
                            red_flags.append({
                                "severity": "medium",
                                "title": f"Neplatný formát RČ/IČO: {value}",
                                "description": f"Hodnota '{value}' nemá platný formát rodného čísla nebo IČO.",
                                "page": field.get("page", 1),
                            })
                
                elif data_type == "amount" and value:
                    # Extract and normalize amount
                    amount_match = re.search(r'[\d\s.,]+', value.replace('\xa0', ' '))
                    if amount_match:
                        amount_str = amount_match.group().replace(' ', '').replace('.', '').replace(',', '.')
                        try:
                            parsed_amount = float(amount_str)
                            field["parsed_amount"] = parsed_amount
                            field["format_valid"] = True
                        except ValueError:
                            field["format_valid"] = False
                
                elif data_type == "date" and value:
                    # Check basic date format
                    if re.search(r'\d{1,2}\.\s*\d{1,2}\.\s*\d{4}', value):
                        field["format_valid"] = True
                    else:
                        field["format_valid"] = False
                
                verified_fields.append(field)
            
            # ─── Cross-field consistency checks ───
            # Check if party names appear consistently
            person_fields = [f for f in verified_fields if f.get("data_type") == "person" and f.get("found")]
            amount_fields = [f for f in verified_fields if f.get("data_type") == "amount" and f.get("found")]
            
            # Check for suspiciously low-confidence found fields
            low_conf_count = sum(1 for f in verified_fields if f.get("found") and f.get("confidence", 0) < 0.5)
            if low_conf_count > 3:
                red_flags.append({
                    "severity": "medium",
                    "title": f"Nízká jistota u {low_conf_count} údajů",
                    "description": "Více extrahovaných údajů má nízkou jistotu. Doporučujeme manuální kontrolu.",
                    "page": None,
                })
            
            # Check if any found fields have unverified citations
            unverified = [f for f in verified_fields if f.get("found") and not f.get("verified", False)]
            if unverified:
                red_flags.append({
                    "severity": "low",
                    "title": f"{len(unverified)} citací nebylo ověřeno v textu",
                    "description": "Některé citace nebyly nalezeny v přesném znění v textu smlouvy. AI mohla parafrázovat.",
                    "page": None,
                })
            
            return {
                "fields": verified_fields,
                "summary": result.get("summary", ""),
                "red_flags": red_flags,
                "stats": {
                    "total": len(verified_fields),
                    "found": sum(1 for f in verified_fields if f.get("found")),
                    "verified": sum(1 for f in verified_fields if f.get("verified")),
                    "high_confidence": sum(1 for f in verified_fields if f.get("confidence", 0) >= 0.9),
                },
            }
        except Exception as e:
            print(f"[ContractAnalyzer] Extract all error: {e}")
            return {
                "fields": [],
                "summary": f"Chyba při extrakci: {str(e)}",
                "red_flags": [],
                "stats": {"total": 0, "found": 0, "verified": 0, "high_confidence": 0},
            }

    async def compare_contracts(self, text_a: str, text_b: str, 
                                 name_a: str, name_b: str) -> dict:
        """Compare two contracts and return structured differences."""
        prompt = f"""Porovnej tyto dva dokumenty a najdi VŠECHNY rozdíly.

DOKUMENT A: {name_a}
{text_a[:7000]}

===

DOKUMENT B: {name_b}
{text_b[:7000]}

PRAVIDLA:
1. Porovnej oba dokumenty systematicky — smluvní strany, částky, data, podmínky, parcely, atd.
2. Identifikuj co se ZMĚNILO, co PŘIBYLO a co CHYBÍ.
3. U každého rozdílu cituj přesný text z obou dokumentů.
4. Vyhodnoť závažnost rozdílu (low/medium/high/critical).

Odpověz jako JSON:
{{
    "summary": "Stručné shrnutí porovnání (2-3 věty)",
    "are_same_type": true,
    "type_a": "Typ dokumentu A",
    "type_b": "Typ dokumentu B",
    "differences": [
        {{
            "category": "Kategorie (cena/strany/podmínky/data/parcely/jiné)",
            "title": "Název rozdílu",
            "severity": "high",
            "text_a": "Text z dokumentu A",
            "text_b": "Text z dokumentu B (nebo null pokud chybí)",
            "description": "Popis změny"
        }}
    ],
    "added_in_b": [
        {{
            "title": "Co přibylo v dokumentu B",
            "text": "Citace z dokumentu B",
            "severity": "medium"
        }}
    ],
    "missing_in_b": [
        {{
            "title": "Co chybí v dokumentu B",
            "text": "Citace z dokumentu A",
            "severity": "medium"
        }}
    ]
}}
"""
        try:
            response = await self.llm.generate_content(
                system_instruction=(
                    "Jsi právní AI analytik specializovaný na porovnávání bankovních smluv. "
                    "Systematicky porovnáváš dva dokumenty a identifikuješ VŠECHNY rozdíly. "
                    "Buď důkladný — i malý rozdíl v čísle nebo datu může být zásadní. "
                    "Odpovídej v češtině."
                ),
                contents=[prompt],
                response_mime_type="application/json",
                max_output_tokens=4000,
                temperature=0.1,
            )
            return json.loads(response)
        except Exception as e:
            print(f"[ContractAnalyzer] Compare error: {e}")
            return {
                "summary": f"Chyba při porovnávání: {str(e)}",
                "differences": [],
                "added_in_b": [],
                "missing_in_b": [],
            }

    @staticmethod
    def _find_text_position(page_text: str, citation: str) -> int:
        """Multi-strategy text search for finding citation position."""
        import re
        search = citation.strip()
        
        # Strategy 1: Full match
        idx = page_text.lower().find(search.lower())
        if idx >= 0:
            return idx
        
        # Strategy 2: First 80 chars
        if len(search) > 80:
            idx = page_text.lower().find(search[:80].lower())
            if idx >= 0:
                return idx
        
        # Strategy 3: First 40 chars
        if len(search) > 40:
            idx = page_text.lower().find(search[:40].lower())
            if idx >= 0:
                return idx
        
        # Strategy 4: Numbers/amounts
        numbers = re.findall(r'[\d.,]+\s*(?:Kč|CZK|EUR|%)', search)
        for num in numbers:
            idx = page_text.find(num)
            if idx >= 0:
                return idx
        
        # Strategy 5: Significant words
        words = [w for w in search.split() if len(w) >= 5]
        for word in words[:3]:
            idx = page_text.lower().find(word.lower())
            if idx >= 0:
                return idx
        
        return -1
