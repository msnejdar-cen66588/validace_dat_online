"""Agent: StrazceBJ – Completeness Check for Bytová jednotka (apartment).

Validates that the photo set meets the mandatory documentation requirements
for BJ (bytová jednotka) property valuation:

1) Aktuální barevné fotografie (minimálně 4, max. stáří 1 měsíc):
   - Exteriér domu s číslem popisným
   - Vchod do bytové/nebytové jednotky
   - Interiér všech místností (kuchyň, pokoje, koupelna, chodba a další)

2) Dokumenty plochy – handled separately (not by this agent)
"""
import json
from datetime import datetime
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import GEMINI_API_KEY, GEMINI_MODEL, BJ_MIN_TOTAL_PHOTOS, BJ_MAX_PHOTO_AGE_DAYS

GUARDIAN_BJ_SYSTEM_PROMPT = """Jsi expert na validaci fotografické dokumentace nemovitostí typu Bytová jednotka (BJ) pro účely bankovního ocenění.

POVINNÁ FOTODOKUMENTACE PRO BYTOVOU JEDNOTKU:
1) Aktuální barevné fotografie (minimálně 4, max. stáří 1 měsíc):
   a) EXTERIÉR BUDOVY — pohled na celou bytovou budovu, ideálně s viditelným číslem popisným (ČP).
   b) VSTUP DO JEDNOTKY — společné prostory domu (chodba, schodiště, výtah) a/nebo vstupní dveře do bytu.
   c) INTERIÉR — fotografie VŠECH místností bytu:
      - kuchyň/kuchyňský kout, obývací pokoj, ložnice, koupelna, WC, chodba, a další
   
   POZNÁMKA: U bytu se NEFOTÍ vedlejší stavby, zahrady ani okolí (na rozdíl od RD).
   Půdorysy nejsou povinné, ale pokud jsou přiloženy, klasifikuj je jako PUDORYS.

KATEGORIE PRO KLASIFIKACI:
- EXTERIER_BUDOVA: Celkový pohled na bytový dům (fasáda, vchod do domu), ideálně s ČP
- EXTERIER_CISLO_POPISNE: Fotografie s viditelným číslem popisným na budově
- VSTUP_JEDNOTKY: Společné prostory (chodba, schodiště, výtah), vstupní dveře bytu
- INTERIER_KUCHYN: Kuchyň nebo kuchyňský kout
- INTERIER_POKOJ: Obývací pokoj, ložnice, dětský pokoj, pracovna
- INTERIER_KOUPELNA: Koupelna / WC
- INTERIER_CHODBA: Chodba bytu, předsíň, vstupní hala bytu
- INTERIER_OSTATNI: Jiné interiérové prostory (šatna, prádelna, komora, sklep bytu)
- BALKON_TERASA: Balkon, terasa, lodžie
- PUDORYS: Půdorys, technický výkres

PRAVIDLA:
1. Jedna fotografie MŮŽE patřit do více kategorií.
2. Pro každou fotku vrať seznam kategorií.
3. V popisu uveď stručně co vidíš.
4. Pokud na exteriérové fotce vidíš číslo popisné, přidej EXTERIER_CISLO_POPISNE.

Vrať JSON:
{
  "classifications": [
    {"photo_id": "xxx", "categories": ["EXTERIER_BUDOVA", "EXTERIER_CISLO_POPISNE"], "description": "Panelový dům s viditelným ČP 1649"}
  ],
  "summary": {
    "total_photos": N,
    "exterior_count": N,
    "interior_count": N,
    "has_cislo_popisne": true/false,
    "has_exterior": true/false,
    "has_vstup_jednotky": true/false,
    "has_balkon_terasa": true/false,
    "interior_rooms_found": ["kuchyň", "pokoj", "koupelna", ...],
    "categories_found": ["EXTERIER_BUDOVA", ...]
  }
}

Odpověz POUZE validním JSON.
"""


class StrazceBJAgent(BaseAgent):
    """Agent 1 (BJ): Strazce - validates completeness of the photo set for apartments."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="StrazceBJ",
            description="Ověření úplnosti fotografické dokumentace bytu",
            system_prompt=GUARDIAN_BJ_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        images = context.get("images", [])
        total = len(images)

        self.log(f"Kontrola úplnosti BJ: {total} fotografií.")

        if total < BJ_MIN_TOTAL_PHOTOS:
            self.log(f"Nedostatečný počet fotek: {total}", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary=f"Nedostatečný počet fotografií: {total} (minimum {BJ_MIN_TOTAL_PHOTOS})",
                details={"total_photos": total},
                errors=[f"Počet fotografií ({total}) je příliš nízký pro kompletní dokumentaci bytu."],
            )

        # ── EXIF validation (must be < 1 month old for BJ) ──
        exif_errors = []
        now = datetime.now()
        for img in images:
            meta = img.get("metadata", {})
            cap_date_str = meta.get("capture_date")
            filename = img.get("original_filename", img.get("id", "Neznámý soubor"))

            if not cap_date_str:
                exif_errors.append(f"Fotografie '{filename}' neobsahuje EXIF metadata s datem pořízení.")
                continue

            try:
                cap_date_str = cap_date_str.strip()
                if " " in cap_date_str:
                    cap_date = datetime.strptime(cap_date_str, "%Y:%m:%d %H:%M:%S")
                else:
                    cap_date = datetime.strptime(cap_date_str, "%Y:%m:%d")

                age_days = (now - cap_date).days
                if age_days > BJ_MAX_PHOTO_AGE_DAYS:
                    exif_errors.append(f"Fotografie '{filename}' je starší než 1 měsíc ({age_days} dní).")
            except ValueError:
                exif_errors.append(f"Nepodařilo se přečíst datum u fotografie '{filename}' ({cap_date_str}).")

        if exif_errors:
            self.log(f"Fotodokumentace nevyhovuje EXIF podmínkám (max 1 měsíc).", "warn")

        self.log("Klasifikuji fotografie bytové jednotky pomocí AI...", "thinking")

        if not self.client:
            self.log("Gemini API key nenakonfigurován. Používám fallback.", "warn")
            return self._fallback_result(total)

        try:
            from google.genai import types
            parts = [f"Klasifikuj těchto {total} fotografií bytové jednotky:\n"]

            for img in images:
                with open(img["processed_path"], "rb") as f:
                    image_bytes = f.read()
                parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                parts.append(f"Photo ID: {img['id']}")

            response_text = await self.client.generate_content(
                system_instruction=self.system_prompt,
                contents=parts,
                response_mime_type="application/json",
                max_output_tokens=8000,
            )

            ai_result = robust_json_parse(response_text)
            self.log("AI klasifikace přijata.")

            classifications = ai_result.get("classifications", [])
            summary = ai_result.get("summary", {})

            exterior_count = summary.get("exterior_count", 0)
            interior_count = summary.get("interior_count", 0)
            has_cp = summary.get("has_cislo_popisne", False)
            has_exterior = summary.get("has_exterior", False)
            has_vstup = summary.get("has_vstup_jednotky", False)
            has_balkon = summary.get("has_balkon_terasa", False)
            rooms_found = summary.get("interior_rooms_found", [])
            categories = summary.get("categories_found", [])

            self.log(f"Ext: {exterior_count}, Int: {interior_count}, ČP: {has_cp}, "
                     f"Vstup: {has_vstup}, Balkón: {has_balkon}")
            self.log(f"Místnosti: {', '.join(rooms_found) if rooms_found else 'nezjištěno'}")

            # ── Evaluate completeness ──
            warnings = []
            errors = []

            if exif_errors:
                warnings.extend(exif_errors)

            # Exterior check
            if not has_exterior:
                errors.append("Chybí exteriérová fotografie bytového domu.")

            if not has_cp:
                warnings.append(
                    "Na žádné fotce nebylo detekováno číslo popisné (ČP). "
                    "Alespoň jedna exteriérová fotka by měla zachycovat ČP."
                )

            # Entry/common areas check
            if not has_vstup:
                warnings.append(
                    "Chybí fotografie vstupu do bytové jednotky "
                    "(společné prostory, chodba domu, vstupní dveře bytu)."
                )

            # Interior checks
            if interior_count < 2:
                errors.append(
                    f"Nedostatečný počet interiérových fotek bytu: {interior_count}. "
                    "Povinné jsou fotografie všech místností."
                )
            else:
                rooms_lower = [r.lower() for r in rooms_found]
                rooms_text = " ".join(rooms_lower)

                missing_rooms = []
                if not any(k in rooms_text for k in ["kuchyň", "kuchyn", "kitchen", "kuchyňsk"]):
                    missing_rooms.append("kuchyň")
                if not any(k in rooms_text for k in ["koupeln", "bathroom", "wc"]):
                    missing_rooms.append("koupelna")
                if not any(k in rooms_text for k in ["pokoj", "obýv", "obyvak", "living", "ložnic"]):
                    missing_rooms.append("obývací pokoj/ložnice")

                if missing_rooms:
                    warnings.append(
                        f"Chybí fotodokumentace místností: {', '.join(missing_rooms)}."
                    )

            # Determine status
            if errors:
                status = AgentStatus.FAIL
            elif warnings:
                status = AgentStatus.WARN
            else:
                status = AgentStatus.SUCCESS

            summary_text = (
                f"Sada {total} fotek bytu: "
                f"Ext={exterior_count}, Int={interior_count}, "
                f"ČP={'ANO' if has_cp else 'NE'}, "
                f"Vstup={'ANO' if has_vstup else 'NE'}"
            )
            if has_balkon:
                summary_text += ", Balkón/terasa=ANO"

            self.log(f"Výsledek: {status.value}")

            # Build image metadata map for frontend
            image_metadata = {}
            for img in images:
                img_id = img.get("id", "")
                meta = img.get("metadata", {})
                image_metadata[img_id] = {
                    "original_filename": img.get("original_filename", ""),
                    "gps_latitude": meta.get("gps_latitude"),
                    "gps_longitude": meta.get("gps_longitude"),
                    "capture_date": meta.get("capture_date"),
                    "device_model": meta.get("device_model"),
                }

            return AgentResult(
                status=status,
                summary=summary_text,
                details={
                    "classifications": classifications,
                    "total_photos": total,
                    "exterior_count": exterior_count,
                    "interior_count": interior_count,
                    "has_cislo_popisne": has_cp,
                    "has_exterior": has_exterior,
                    "has_vstup_jednotky": has_vstup,
                    "has_balkon_terasa": has_balkon,
                    "interior_rooms_found": rooms_found,
                    "categories_found": categories,
                    "image_metadata": image_metadata,
                },
                warnings=warnings,
                errors=errors,
            )

        except Exception as e:
            self.log(f"Chyba AI klasifikace: {str(e)}", "error")
            return self._fallback_result(total)

    def _fallback_result(self, total: int) -> AgentResult:
        """Fallback when AI is unavailable."""
        return AgentResult(
            status=AgentStatus.WARN,
            summary=f"Počet fotek: {total} (AI klasifikace nedostupná)",
            details={"total_photos": total, "ai_available": False},
            warnings=["AI klasifikace nedostupná – nelze ověřit úplnost dokumentace."],
        )
