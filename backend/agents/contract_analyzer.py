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
                    "Jsi expertní OCR systém specializovaný na české právní dokumenty a smlouvy. "
                    "Přepisuješ text z fotografií a skenů s maximální přesností. "
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
        """Classify the type of contract and return type + presets."""
        prompt = f"""Analyzuj následující text smlouvy a urči její typ.

Typy smluv:
- kupni_smlouva (kupní smlouva na nemovitost)
- smlouva_o_uveru (smlouva o úvěru, hypoteční smlouva)
- zastavni_smlouva (zástavní smlouva)
- darovaci_smlouva (darovací smlouva)
- najemni_smlouva (nájemní smlouva)
- smlouva_budouci (smlouva o smlouvě budoucí)
- unknown (pokud nelze určit)

Odpověz POUZE jako JSON:
{{
    "contract_type": "typ_smlouvy",
    "confidence": 0.95,
    "title": "Lidský název smlouvy",
    "summary": "Stručný popis obsahu smlouvy (1-2 věty)",
    "parties": ["Strana 1", "Strana 2"]
}}

TEXT SMLOUVY:
{text[:6000]}
"""
        try:
            response = await self.llm.generate_content(
                system_instruction=(
                    "Jsi právní AI specialista na české bankovní smlouvy. "
                    "Klasifikuješ typ smlouvy a vracíš strukturovaný JSON."
                ),
                contents=[prompt],
                response_mime_type="application/json",
                max_output_tokens=500,
                temperature=0.1,
            )
            result = json.loads(response)
            contract_type = result.get("contract_type", "unknown")

            # Get presets for this type
            preset_config = CONTRACT_PRESETS.get(contract_type, CONTRACT_PRESETS["unknown"])

            return {
                "contract_type": contract_type,
                "confidence": result.get("confidence", 0),
                "title": result.get("title", preset_config["label"]),
                "summary": result.get("summary", ""),
                "parties": result.get("parties", []),
                "icon": preset_config["icon"],
                "label": preset_config["label"],
                "presets": preset_config["presets"],
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
1. Odpověz přesně a stručně na dotaz.
2. Pokud nalezneš relevantní text, cituj PŘESNÝ úryvek textu ze smlouvy.
3. Uveď číslo strany, kde se informace nachází.
4. Pokud informaci nenajdeš, řekni to jasně.

Odpověz jako JSON:
{{
    "answer": "Odpověď na dotaz",
    "found": true,
    "citations": [
        {{
            "text": "Přesný citovaný text ze smlouvy (přesné znění, aby šlo najít ve smlouvě)",
            "page": 1,
            "context": "Okolní kontext citace pro lepší identifikaci"
        }}
    ],
    "highlights": [
        "klíčové slovo nebo fráze k zvýraznění 1",
        "klíčové slovo nebo fráze k zvýraznění 2"
    ]
}}

SMLOUVA:
{pages_ref[:8000]}

DOTAZ UŽIVATELE: {query}
"""
        try:
            response = await self.llm.generate_content(
                system_instruction=(
                    "Jsi právní AI asistent České spořitelny. "
                    "Analyzuješ bankovní smlouvy a odpovídáš na dotazy. "
                    "Vždy cituj přesný text ze smlouvy. "
                    "Odpovídej v češtině."
                ),
                contents=[prompt],
                response_mime_type="application/json",
                max_output_tokens=2048,
                temperature=0.2,
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
                    # Find position of cited text in the page
                    idx = page_text.lower().find(cited_text.lower()[:50])
                    if idx >= 0:
                        # Calculate approximate Y position based on text position ratio
                        total_len = len(page_text)
                        y_ratio = idx / total_len if total_len > 0 else 0
                        highlight_positions.append({
                            "page": page_num,
                            "text": cited_text,
                            "y_ratio": round(y_ratio, 3),
                            "context": citation.get("context", ""),
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
