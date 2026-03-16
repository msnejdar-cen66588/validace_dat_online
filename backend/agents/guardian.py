"""Agent 1: Guardian – Completeness Check (BR-G4).

Validates that the photo set meets minimum requirements for RD (family house):
- Min 9 photos total
- Min 2 exterior photos
- Min 3 interior photos
- Must detect rear/side exterior (blocking requirement)
- Allows 1 photo for multiple categories
"""
import json
from google import genai
from google.genai import types

from agents.base import BaseAgent, AgentResult, AgentStatus
from config import (
    GEMINI_API_KEY, GEMINI_MODEL,
    MIN_TOTAL_PHOTOS, MIN_EXTERIOR_PHOTOS, MIN_INTERIOR_PHOTOS,
)

GUARDIAN_SYSTEM_PROMPT = """Jsi expert na validaci fotografické dokumentace pro účely bankovního online ocenění rodinného domu (RD).

Tvůj úkol je:
1. Klasifikovat každou fotografii do kategorií.
2. Ověřit ÚPLNOST sady (dostatečný počet, kategorie, zadní/boční pohled).
3. Posoudit AKTUÁLNOST fotografií – jsou to skutečné aktuální fotografie dané nemovitosti?

KATEGORIE:
- EXTERIER_PREDNI: Přední pohled na dům (fasáda, vchod)
- EXTERIER_ZADNI: Zadní pohled na dům (zahrada, terasa)
- EXTERIER_BOCNI: Boční pohled na dům
- EXTERIER_DETAIL: Detail exteriéru (střecha, okna, fasáda zblízka)
- INTERIER_KUCHYN: Kuchyň
- INTERIER_OBYVAK: Obývací pokoj
- INTERIER_LOZNICE: Ložnice
- INTERIER_KOUPELNA: Koupelna
- INTERIER_OSTATNI: Jiné interiérové prostory (chodba, schodiště, sklep, garáž)
- OKOLÍ: Zahrada, příjezdová cesta, okolí domu

PRAVIDLA:
1. Jedna fotografie MŮŽE patřit do více kategorií.
2. Vrať JSON ve formátu:
{
  "classifications": [
    {"photo_id": "xxx", "categories": ["EXTERIER_PREDNI"], "description": "Přední pohled na RD..."},
    ...
  ],
  "summary": {
    "total_photos": N,
    "exterior_count": N,
    "interior_count": N,
    "has_rear_or_side_exterior": true/false,
    "categories_found": ["EXTERIER_PREDNI", ...],
    "are_photos_current": true/false,
    "actuality_note": "<pokud jsou podezřelé, stručně vysvětli proč; jinak 'Fotografie vypadají aktuálně.'>"
  }
}

AKTUÁLNOST – nastav are_photos_current = false pokud:
- Fotografie vypadají jako AI-generované (příliš dokonalé, nepřirozené)
- Jsou evidentně staré (rozlišení 640×480, analogové artefakty)
- Jsou to záběry z jiné nemovitosti nebo katalogové fotografie
- Více než polovina fotek neodpovídá žádné standardní kategorii RD
Pokud fotografie nebudí podezření, nastav are_photos_current = true.

Odpověz POUZE validním JSON.
"""


class GuardianAgent(BaseAgent):
    """Agent 1: Guardian - validates completeness of the photo set."""

    def __init__(self):
        super().__init__(
            name="Guardian",
            description="Ověření úplnosti fotografické sady (BR-G4)",
            system_prompt=GUARDIAN_SYSTEM_PROMPT,
        )
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

    async def run(self, context: dict) -> AgentResult:
        images = context.get("images", [])
        total = len(images)

        self.log(f"Received {total} images for completeness check.")

        # Basic count check
        if total < MIN_TOTAL_PHOTOS:
            self.log(f"FAIL: Only {total} photos, minimum is {MIN_TOTAL_PHOTOS}.", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary=f"Nedostatečný počet fotografií: {total}/{MIN_TOTAL_PHOTOS}",
                details={"total_photos": total, "required": MIN_TOTAL_PHOTOS},
                errors=[f"Počet fotografií ({total}) je menší než minimum ({MIN_TOTAL_PHOTOS})."],
            )

        # Use AI to classify photos
        self.log("Klasifikuji fotografie pomocí AI...", "thinking")

        if not self.client:
            self.log("Gemini API key not configured. Using fallback logic.", "warn")
            return self._fallback_result(total)

        try:
            # Build content parts with images
            parts = [f"Klasifikuj těchto {total} fotografií rodinného domu:\n"]

            for img in images:
                with open(img["processed_path"], "rb") as f:
                    image_bytes = f.read()
                parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                parts.append(f"Photo ID: {img['id']}")

            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=parts,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    response_mime_type="application/json",
                    max_output_tokens=2000,
                ),
            )

            result_text = response.text
            self.log("AI classification received.", "info")
            ai_result = json.loads(result_text)

            # Parse AI response
            classifications = ai_result.get("classifications", [])
            summary = ai_result.get("summary", {})
            exterior_count = summary.get("exterior_count", 0)
            interior_count = summary.get("interior_count", 0)
            has_rear_side = summary.get("has_rear_or_side_exterior", False)
            are_photos_current = summary.get("are_photos_current", True)
            actuality_note = summary.get("actuality_note", "")

            self.log(f"Exterior: {exterior_count}, Interior: {interior_count}, Rear/Side: {has_rear_side}, Aktuální: {are_photos_current}")

            # Validate requirements
            warnings = []
            errors = []

            if exterior_count < MIN_EXTERIOR_PHOTOS:
                errors.append(f"Nedostatečný počet exteriérových fotek: {exterior_count}/{MIN_EXTERIOR_PHOTOS}")
            if interior_count < MIN_INTERIOR_PHOTOS:
                errors.append(f"Nedostatečný počet interiérových fotek: {interior_count}/{MIN_INTERIOR_PHOTOS}")
            if not has_rear_side:
                errors.append("BLOKUJÍCÍ: Chybí exteriér zadní nebo boční pohled.")
            if not are_photos_current:
                errors.append(f"BLOKUJÍCÍ: Fotodokumentace nevypadá aktuálně. {actuality_note}")

            if errors:
                status = AgentStatus.FAIL
            elif warnings:
                status = AgentStatus.WARN
            else:
                status = AgentStatus.SUCCESS

            self.log(f"Guardian result: {status.value}")

            return AgentResult(
                status=status,
                summary=f"Sada {total} fotek: Ext={exterior_count}, Int={interior_count}, Zadní/Boční={'ANO' if has_rear_side else 'NE'}, Aktuální={'ANO' if are_photos_current else 'NE'}",
                details={
                    "classifications": classifications,
                    "total_photos": total,
                    "exterior_count": exterior_count,
                    "interior_count": interior_count,
                    "has_rear_or_side_exterior": has_rear_side,
                    "are_photos_current": are_photos_current,
                    "actuality_note": actuality_note,
                    "categories_found": summary.get("categories_found", []),
                },
                warnings=warnings,
                errors=errors,
            )

        except Exception as e:
            self.log(f"AI classification error: {str(e)}", "error")
            return self._fallback_result(total)

    def _fallback_result(self, total: int) -> AgentResult:
        """Fallback when AI is unavailable."""
        return AgentResult(
            status=AgentStatus.WARN,
            summary=f"Počet fotek: {total} (AI klasifikace nedostupná)",
            details={"total_photos": total, "ai_available": False},
            warnings=["AI klasifikace nedostupná – nelze ověřit kategorie."],
        )
