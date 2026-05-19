"""Agent: GDPRValidator – Detekce osob a obličejů na fotografiích.

GDPR-compliant face/person detection using Gemini Vision:
- Scans all photos for visible faces and identifiable persons
- FAIL: face detected with confidence >80%
- WARN: uncertain detection 60–80%
- PASS: no faces detected

This agent must run BEFORE any other processing to ensure compliance.
"""
import json
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import (
    GEMINI_API_KEY, GEMINI_MODEL,
    GDPR_FACE_FAIL_CONFIDENCE, GDPR_FACE_WARN_CONFIDENCE,
)

GDPR_SYSTEM_PROMPT = """Jsi expert na GDPR compliance a detekci osob na fotografiích nemovitostí.

TVŮJ ÚKOL:
Analyzuj každou fotografii a zjisti, zda se na ní nachází rozpoznatelné osoby nebo obličeje.

Pro účely bankovního ocenění nemovitostí je ZAKÁZÁNO zpracovávat fotografie, na kterých jsou
rozpoznatelné osoby (GDPR – nařízení o ochraně osobních údajů).

ANALYZUJ:
1. **Přímé obličeje** — osoba se dívá do kamery nebo je obličej jasně viditelný
2. **Boční profily** — obličej viditelný z boku
3. **Osoby na pozadí** — osoby v pozadí fotky (i malé, vzdálené)
4. **Odrazy** — obličeje viditelné v zrcadlech, oknech, lesklých površích
5. **Fotografie/portréty na stěnách** — rodinné fotky na stěnách nejsou problém (jsou součást interiéru)

VRAŤ JSON:
{
  "photos": [
    {
      "photo_id": "xxx",
      "has_person": true/false,
      "confidence": 0.0-1.0,
      "description": "Popis nálezu – kde je osoba viditelná",
      "person_type": "direct_face" | "side_profile" | "background" | "reflection" | "none"
    }
  ],
  "overall": {
    "total_with_persons": 0,
    "max_confidence": 0.0,
    "summary": "Celkové shrnutí"
  }
}

DŮLEŽITÉ:
- Rodinné fotografie na stěnách (rámečky, portréty) IGNORUJ – to je součást interiéru.
- Pokud je osoba ve velké vzdálenosti a není rozpoznatelná → confidence < 0.6
- Pokud je obličej jasně viditelný → confidence > 0.8

Odpověz POUZE validním JSON.
"""


class GDPRValidatorAgent(BaseAgent):
    """GDPR Validator - detects persons and faces on property photos."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="GDPRValidator",
            description="GDPR detekce osob a obličejů na fotografiích",
            system_prompt=GDPR_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        images = context.get("images", [])
        self.log(f"GDPR kontrola: {len(images)} fotografií.")

        if not images:
            return AgentResult(
                status=AgentStatus.SUCCESS,
                summary="Žádné fotografie ke kontrole.",
                details={"total_with_persons": 0},
            )

        if not self.client:
            self.log("API klíč nenakonfigurován. Přeskakuji GDPR kontrolu.", "warn")
            return AgentResult(
                status=AgentStatus.WARN,
                summary="GDPR kontrola přeskočena (chybí API klíč)",
                warnings=["GDPR detekce nedostupná – nelze ověřit přítomnost osob."],
            )

        try:
            from google.genai import types
            self.log("Odesílám fotografie na GDPR detekci...", "thinking")

            parts = [f"Zkontroluj těchto {len(images)} fotografií na přítomnost osob/obličejů:\n"]

            for img in images:
                with open(img["processed_path"], "rb") as f:
                    image_bytes = f.read()
                parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                parts.append(f"Photo ID: {img['id']}")

            response_text = await self.client.generate_content(
                system_instruction=self.system_prompt,
                contents=parts,
                response_mime_type="application/json",
                max_output_tokens=4000,
            )

            ai_result = robust_json_parse(response_text)
            self.log("GDPR analýza přijata.")

            photos = ai_result.get("photos", [])
            overall = ai_result.get("overall", {})

            warnings = []
            errors = []
            flagged_photos = []

            for photo in photos:
                photo_id = photo.get("photo_id", "?")
                has_person = photo.get("has_person", False)
                confidence = photo.get("confidence", 0.0)
                description = photo.get("description", "")
                person_type = photo.get("person_type", "none")

                if not has_person:
                    continue

                if confidence >= GDPR_FACE_FAIL_CONFIDENCE:
                    errors.append(
                        f"GDPR FAIL: Fotografie '{photo_id}' obsahuje rozpoznatelnou osobu "
                        f"(jistota {confidence:.0%}): {description}"
                    )
                    flagged_photos.append(photo_id)
                elif confidence >= GDPR_FACE_WARN_CONFIDENCE:
                    warnings.append(
                        f"GDPR WARN: Fotografie '{photo_id}' – možná osoba "
                        f"(jistota {confidence:.0%}): {description}"
                    )
                    flagged_photos.append(photo_id)

            total_with_persons = overall.get("total_with_persons", len(flagged_photos))
            max_confidence = overall.get("max_confidence", 0.0)

            # Determine status
            if errors:
                status = AgentStatus.FAIL
                summary = (
                    f"GDPR: Nalezeny rozpoznatelné osoby na {len(errors)} fotografiích. "
                    f"Fotografie musí být anonymizovány nebo nahrazeny."
                )
            elif warnings:
                status = AgentStatus.WARN
                summary = (
                    f"GDPR: Možná přítomnost osob na {len(warnings)} fotografiích. "
                    f"Doporučena manuální kontrola."
                )
            else:
                status = AgentStatus.SUCCESS
                summary = "GDPR: Žádné rozpoznatelné osoby nebyly detekovány."

            self.log(f"GDPR výsledek: {status.value} – {total_with_persons} fotek s osobami")

            return AgentResult(
                status=status,
                summary=summary,
                details={
                    "photos": photos,
                    "overall": overall,
                    "flagged_photos": flagged_photos,
                    "total_with_persons": total_with_persons,
                    "max_confidence": max_confidence,
                },
                warnings=warnings,
                errors=errors,
            )

        except Exception as e:
            self.log(f"Chyba GDPR detekce: {str(e)}", "error")
            return AgentResult(
                status=AgentStatus.WARN,
                summary=f"GDPR detekce selhala: {str(e)}",
                warnings=[f"GDPR analýza selhala: {str(e)}"],
            )
