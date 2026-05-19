"""
Samostatný agent pro ověření podlahové plochy z dokumentů.

Specializovaný agent pro bankovní použití – extrahuje podlahovou plochu
z nahraných dokumentů (kupní smlouvy, prohlášení vlastníka, vyúčtování služeb atd.),
ověřuje aritmetiku rozpisu místností a vypočítá započitatelnou plochu dle metodiky.

Dvou-fázový přístup:
  Fáze 1: OCR / extrakce textu z obrázků dokumentu
  Fáze 2: Strukturovaná analýza extrahovaného textu

Autor: AI Pipeline pro ČS
"""

import os
import json
import traceback
from typing import Optional

from agents.llm_utils import LLMClient, robust_json_parse


# ──────────────────────────────────────────────────────────────
#  FÁZE 1 – Extrakce surového textu z dokumentu
# ──────────────────────────────────────────────────────────────

PHASE1_OCR_PROMPT = """Jsi OCR specialista. Tvým JEDINÝM úkolem je přečíst a přepsat veškerý text z poskytnutého dokumentu (obrázku/PDF).

PRAVIDLA:
1. Přepiš KOMPLETNĚ a DOSLOVNĚ veškerý text, který v dokumentu vidíš.
2. Zachovej strukturu: nadpisy, odstavce, odrážky, tabulky.
3. Čísla přepisuj PŘESNĚ tak, jak jsou v dokumentu (včetně desetinných čárek/teček).
4. U tabulek a seznamů zachovej zarovnání pomocí tabulátorů nebo mezer.
5. Pokud je dokument vícestránkový, označ začátek každé stránky jako "=== STRÁNKA X ===".
6. NEPŘIDÁVEJ žádné vlastní komentáře ani interpretace – pouze přepiš text.
7. Pokud text není čitelný, napiš [NEČITELNÉ] na příslušné místo.

Výstup: čistý přepis textu dokumentu."""


# ──────────────────────────────────────────────────────────────
#  FÁZE 2 – Strukturovaná analýza extrahovaného textu
# ──────────────────────────────────────────────────────────────

PHASE2_ANALYSIS_PROMPT = """Jsi expert na analýzu dokumentů pro ověření podlahové plochy bytové jednotky dle bankovní metodiky.

Dostáváš PŘEPIS TEXTU z dokumentu (kupní smlouva, prohlášení vlastníka, vyúčtování služeb atd.).
Tvým úkolem je z tohoto textu EXTRAHOVAT informace o podlahové ploše.

═══════════════════════════════════════════════════
AKCEPTOVATELNÉ TYPY DOKUMENTŮ:
═══════════════════════════════════════════════════
1. Nabývací titul (kupní smlouva, smlouva o převodu)
2. Prohlášení vlastníka
3. Vyúčtování služeb
4. Evidenční list SVJ/BD
5. Odhad nemovitosti (znalecký posudek)

Neakceptovatelné: fotky, vlastní poznámky, inzeráty.

═══════════════════════════════════════════════════
POSTUP:
═══════════════════════════════════════════════════

KROK 1 – Identifikuj typ dokumentu.

KROK 2 – Najdi CELKOVOU PLOCHU bytu.
Hledej fráze jako:
- "celková plocha předmětné jednotky"
- "podlahová plocha"
- "plocha bytu"
- "plocha jednotky"
- "výměra"
- číslo následované "m2" nebo "m²"

KROK 3 – Najdi ROZPIS MÍSTNOSTÍ (skladbu), pokud existuje.
Hledej fráze jako:
- "skladba předmětné jednotky"
- "skladba bytu"
- seznam místností s plochami (kuchyně, pokoj, předsíň, koupelna, chodba, komora...)

KROK 4 – OVĚŘ ARITMETIKU (povinně, pokud existuje rozpis):
a) Sečti plochy VŠECH místností z rozpisu krok po kroku.
b) Porovnej tvůj součet s celkovou plochou uvedenou v dokumentu.
c) Pokud se liší, zapiš přesný rozdíl a možné příčiny.

KROK 5 – VYPOČÍTEJ ZAPOČITATELNOU PLOCHU:
- Hlavní plocha bytu: koeficient 1.0
- Balkón, lodžie, terasa, sklep, komora: koeficient 0.5
- Garáž: koeficient 0.0 (nezapočítává se)
- Zahrada: koeficient 0.0 (nezapočítává se)

PRAVIDLO: Vedlejší plocha × 0.5 nesmí překročit 20 % hlavní plochy.
Vzorec: Započitatelná = Hlavní + MIN(Vedlejší × 0.5, Hlavní × 0.20)

═══════════════════════════════════════════════════
VÝSTUP – POUZE validní JSON (žádný markdown):
═══════════════════════════════════════════════════
{
  "document_type": "kupní smlouva",
  "is_acceptable": true,
  "extracted_floor_area_m2": 84.80,
  "room_breakdown": [
    {"name": "Kuchyně", "area_m2": 7.10},
    {"name": "Pokoj 1", "area_m2": 20.88}
  ],
  "room_sum_m2": 89.50,
  "verification_result": "NESOULAD: Součet místností 89.50 m2 vs. celková plocha 84.80 m2. Rozdíl 4.70 m2.",
  "area_components": {
    "byt_m2": 84.80,
    "balkon_m2": 0,
    "terasa_m2": 0,
    "sklep_m2": 0,
    "garaz_m2": 0,
    "zahrada_m2": 0
  },
  "zapocitatalna_plocha_m2": 84.80,
  "zapocitatalna_vypocet": "Byt: 84.80 m2. Vedlejší: 0. Celkem: 84.80 m2.",
  "confidence": 0.95,
  "notes": "Kupní smlouva, plocha nalezena v čl. I bod 1.2.3."
}

DŮLEŽITÉ:
- extracted_floor_area_m2 MUSÍ být číslo, pokud jsi v textu našel jakoukoli zmínku o ploše.
- Pokud text zmiňuje plochu v m2, VŽDY ji extrahuj – nenechávej null.
- room_breakdown je prázdný seznam [], pokud rozpis místností neexistuje.
- confidence je číslo od 0.0 do 1.0 (např. 0.95).
"""


class FloorAreaDocumentAgent:
    """
    Samostatný agent pro extrakci a ověření podlahové plochy z dokumentů.
    
    Dvou-fázový přístup pro maximální spolehlivost:
      1. OCR fáze – přepis textu z obrázků/PDF
      2. Analytická fáze – strukturovaná extrakce dat z přepisaného textu
    
    Fallback: Pokud dvou-fázový přístup selže, zkusí přímou analýzu obrázků.
    """

    def __init__(self, model_name: str = "gemini", logger=None):
        self.client = LLMClient(model_name=model_name)
        self.logger = logger  # Callback: (message, level) -> None
        self._logs = []

    def log(self, message: str, level: str = "info"):
        """Log a message."""
        self._logs.append({"message": message, "level": level})
        if self.logger:
            self.logger(message, level)
        print(f"[FloorAreaAgent][{level}] {message}")

    async def analyze(
        self,
        doc_paths: list[str],
        declared_area: str = "neznámo",
    ) -> Optional[dict]:
        """
        Hlavní metoda – analyzuje dokumenty a vrátí strukturovaný výsledek.
        
        Args:
            doc_paths: Cesty k souborům dokumentu (PDF/obrázky)
            declared_area: Deklarovaná plocha z formuláře klienta
            
        Returns:
            dict s klíči: document_type, is_acceptable, extracted_floor_area_m2,
            room_breakdown, verification_result, area_components,
            zapocitatalna_plocha_m2, zapocitatalna_vypocet, confidence, notes
            
            Nebo None při fatální chybě.
        """
        # Validate inputs
        valid_paths = [p for p in doc_paths if os.path.exists(p)]
        if not valid_paths:
            self.log("Žádné platné soubory pro analýzu.", "warn")
            return None

        # No file limit for local execution
        if len(valid_paths) > 20:
            self.log(f"Omezuji počet souborů z {len(valid_paths)} na 20.", "warn")
            valid_paths = valid_paths[:20]

        self.log(
            f"Analyzuji {len(valid_paths)} soubor(ů) dokumentu. "
            f"Deklarovaná plocha: {declared_area}"
        )

        # ── FÁZE 1: OCR – extrakce textu ──
        ocr_text = await self._phase1_ocr(valid_paths)

        if ocr_text and len(ocr_text.strip()) > 50:
            self.log(f"OCR fáze úspěšná, extrahováno {len(ocr_text)} znaků textu.")

            # ── FÁZE 2: Analýza textu ──
            result = await self._phase2_analyze(ocr_text, declared_area)
            
            if result and result.get("extracted_floor_area_m2") is not None:
                self.log(
                    f"Analýza úspěšná: {result.get('extracted_floor_area_m2')} m², "
                    f"typ: {result.get('document_type')}"
                )
                return result
            else:
                self.log(
                    "Fáze 2 neextrahovala plochu. Zkouším fallback přímou analýzou obrázků.",
                    "warn"
                )
        else:
            self.log(
                f"OCR extrahoval příliš málo textu ({len(ocr_text) if ocr_text else 0} znaků). "
                "Zkouším fallback přímou analýzou obrázků.",
                "warn"
            )

        # ── FALLBACK: Přímá analýza obrázků ──
        result = await self._fallback_direct_analysis(valid_paths, declared_area)
        
        if result and result.get("extracted_floor_area_m2") is not None:
            self.log(
                f"Fallback úspěšný: {result.get('extracted_floor_area_m2')} m², "
                f"typ: {result.get('document_type')}"
            )
            return result

        self.log("Ani fallback nedokázal extrahovat plochu z dokumentu.", "warn")
        return result or {
            "document_type": "neznámý",
            "is_acceptable": False,
            "extracted_floor_area_m2": None,
            "room_breakdown": [],
            "room_sum_m2": None,
            "verification_result": None,
            "area_components": {},
            "zapocitatalna_plocha_m2": None,
            "zapocitatalna_vypocet": None,
            "confidence": 0.0,
            "notes": "Nepodařilo se extrahovat plochu z dokumentu.",
        }

    # ──────────────────────────────────────────────────────────
    #  FÁZE 1: OCR
    # ──────────────────────────────────────────────────────────

    async def _phase1_ocr(self, doc_paths: list[str]) -> Optional[str]:
        """Extrahuje text z obrázků/PDF dokumentu."""
        try:
            from google.genai import types

            mime_map = {
                "pdf": "application/pdf",
                "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp",
                "heic": "image/heic", "heif": "image/heif",
                "tiff": "image/tiff", "tif": "image/tiff",
                "bmp": "image/bmp",
            }

            parts = ["Přepiš veškerý text z následujícího dokumentu:\n\n"]

            total_bytes = 0
            for i, doc_path in enumerate(doc_paths):
                with open(doc_path, "rb") as f:
                    doc_bytes = f.read()
                total_bytes += len(doc_bytes)

                ext = doc_path.lower().rsplit(".", 1)[-1] if "." in doc_path else ""
                mime_type = mime_map.get(ext, "image/jpeg")

                parts.append(
                    types.Part.from_bytes(data=doc_bytes, mime_type=mime_type)
                )
                if len(doc_paths) > 1:
                    parts.append(f"\n=== STRÁNKA {i + 1}/{len(doc_paths)} ===\n")

                del doc_bytes


            self.log(f"OCR: Čtu {len(doc_paths)} stránek ({total_bytes} bytes)...")

            response_text = await self.client.generate_content(
                system_instruction=PHASE1_OCR_PROMPT,
                contents=parts,
                response_mime_type="text/plain",
                max_output_tokens=16000,
                temperature=0.1,  # Low temperature for accurate OCR
            )

            del parts

            if response_text:
                # Log first 500 chars for debugging
                preview = response_text[:500].replace("\n", " ")
                self.log(f"OCR výsledek (ukázka): {preview}...")

            return response_text

        except Exception as e:
            self.log(f"OCR fáze selhala: {e}", "error")
            self.log(traceback.format_exc(), "error")
            return None

    # ──────────────────────────────────────────────────────────
    #  FÁZE 2: Strukturovaná analýza textu
    # ──────────────────────────────────────────────────────────

    async def _phase2_analyze(
        self, ocr_text: str, declared_area: str
    ) -> Optional[dict]:
        """Analyzuje OCR text a extrahuje strukturovaná data o ploše."""
        REQUIRED_KEYS = [
            "document_type", "is_acceptable", "extracted_floor_area_m2",
            "zapocitatalna_plocha_m2", "area_components",
        ]

        for attempt, tokens in enumerate([8000, 12000], start=1):
            try:
                prompt = (
                    f"Deklarovaná plocha bytu z formuláře klienta: {declared_area}\n\n"
                    f"PŘEPIS DOKUMENTU:\n"
                    f"{'='*60}\n"
                    f"{ocr_text}\n"
                    f"{'='*60}\n\n"
                    f"Analyzuj výše uvedený text a extrahuj informace o podlahové ploše. "
                    f"Vrať POUZE validní JSON dle instrukcí v systémovém promptu. "
                    f"DŮLEŽITÉ: JSON musí obsahovat VŠECHNA pole včetně "
                    f"zapocitatalna_plocha_m2, zapocitatalna_vypocet, area_components a notes."
                )

                self.log(f"Fáze 2 pokus {attempt}: max_output_tokens={tokens}")

                response_text = await self.client.generate_content(
                    system_instruction=PHASE2_ANALYSIS_PROMPT,
                    contents=[prompt],
                    response_mime_type="application/json",
                    max_output_tokens=tokens,
                    temperature=0.2,
                )

                if not response_text:
                    self.log("Fáze 2: AI vrátila prázdnou odpověď.", "warn")
                    continue

                # Debug log
                self.log(f"Fáze 2 raw odpověď ({len(response_text)} znaků, ukázka): {response_text[:500]}")

                result = robust_json_parse(response_text)

                if not result:
                    self.log("Fáze 2: JSON parsing selhal.", "warn")
                    continue

                self.log(f"Fáze 2 parsováno: keys={list(result.keys())}")

                # Check for truncation – are required keys present?
                missing_keys = [k for k in REQUIRED_KEYS if k not in result]
                if missing_keys and attempt < 2:
                    self.log(
                        f"Fáze 2: Odpověď oříznutá, chybí klíče: {missing_keys}. "
                        f"Zkouším znovu s vyšším limitem tokenů.",
                        "warn"
                    )
                    continue

                return result

            except Exception as e:
                self.log(f"Fáze 2 pokus {attempt} selhala: {e}", "error")
                self.log(traceback.format_exc(), "error")

        return None

    # ──────────────────────────────────────────────────────────
    #  FALLBACK: Přímá analýza obrázků (bez OCR)
    # ──────────────────────────────────────────────────────────

    async def _fallback_direct_analysis(
        self, doc_paths: list[str], declared_area: str
    ) -> Optional[dict]:
        """Přímá analýza obrázků – fallback pokud OCR + analýza selže."""
        try:
            from google.genai import types

            mime_map = {
                "pdf": "application/pdf",
                "jpg": "image/jpeg", "jpeg": "image/jpeg",
                "png": "image/png", "webp": "image/webp",
                "heic": "image/heic", "heif": "image/heif",
                "tiff": "image/tiff", "tif": "image/tiff",
                "bmp": "image/bmp",
            }

            parts = [
                f"ÚKOL: Analyzuj tento dokument a najdi PODLAHOVOU PLOCHU bytu.\n"
                f"Deklarovaná plocha z formuláře: {declared_area}\n"
                f"Dokument má {len(doc_paths)} stránek.\n"
                f"HLEDEJ: 'celková plocha', 'podlahová plocha', 'plocha jednotky', "
                f"'skladba', 'm2', 'm²', seznamy místností.\n"
                f"Vrať JSON dle instrukcí.\n\n"
            ]

            for i, doc_path in enumerate(doc_paths):
                with open(doc_path, "rb") as f:
                    doc_bytes = f.read()

                ext = doc_path.lower().rsplit(".", 1)[-1] if "." in doc_path else ""
                mime_type = mime_map.get(ext, "image/jpeg")

                parts.append(
                    types.Part.from_bytes(data=doc_bytes, mime_type=mime_type)
                )
                parts.append(f"(Stránka {i + 1}/{len(doc_paths)})")

                del doc_bytes


            parts.append(
                "\nAnalyzuj VŠECHNY stránky. Najdi celkovou plochu a rozpis místností. "
                "Vrať JSON. extracted_floor_area_m2 NESMÍ být null pokud vidíš jakoukoli plochu v m2!"
            )

            self.log("Fallback: Přímá analýza obrázků...")

            response_text = await self.client.generate_content(
                system_instruction=PHASE2_ANALYSIS_PROMPT,
                contents=parts,
                response_mime_type="application/json",
                max_output_tokens=8000,
                temperature=0.2,
            )

            del parts

            if not response_text:
                self.log("Fallback: AI vrátila prázdnou odpověď.", "warn")
                return None

            self.log(f"Fallback raw odpověď (prvních 800 znaků): {response_text[:800]}")

            result = robust_json_parse(response_text)
            if result:
                self.log(f"Fallback parsováno: keys={list(result.keys())}")
            return result

        except Exception as e:
            self.log(f"Fallback selhal: {e}", "error")
            self.log(traceback.format_exc(), "error")
            return None
