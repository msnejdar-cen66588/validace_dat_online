"""Agent 4: Inspektor – Defect Detection & Scoring.

Visual analysis of technical condition:
- Scoring 0-30 (Element age, Maintenance, Defects)
- Critical overrides: structural cracks, collapsed roof, structural damage → immediate FAIL/Cat. 5
- Severity classification: Minor, Medium, Severe, Critical
"""
import json
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient
from config import GEMINI_API_KEY, GEMINI_MODEL
from google.genai import types


INSPECTOR_SYSTEM_PROMPT = """Jsi specializovaný inspektor nemovitostí. Tvým úkolem je na základě vizuální analýzy fotografií rozhodnout, zda je rodinný dům (RD) způsobilý pro automatizované online ocenění. Tvým cílem je identifikovat rizika, která vyžadují zásah odhadce nebo statika.

Základní princip:
Hledáš dům, který je obyvatelný a funkční. Nevadí, že je vybavení zastaralé (retro), pokud je v dobrém technickém stavu. Jakákoliv probíhající práce nebo poškození konstrukce znamenají stopku.

Rozhodovací kritéria (Kdy zvolit NE):

1. Probíhající rekonstrukce:
- Interiér: Chybějící podlahy, odhalené cihly, vytrhané rozvody, chybějící sanitární technika (WC, vany), lešení v interiéru.
- Exteriér: Rozestavěné části, lešení, chybějící okna nebo dveře.

2. Stav fasády:
- Pokud chybí finální vrstva nebo je omítka opadaná na více než 15 % viditelné plochy.
- Základní šedá jádrová omítka je akceptovatelná, pokud je celistvá a plní ochrannou funkci.

3. Statické vady (Kritické):
- Jakékoliv trhliny a praskliny v nosném zdivu (zejména diagonální trhliny nad okny/dveřmi nebo praskliny v základech).
- Vizuální náznak "sedání" objektu.

4. Vlhkost a plísně:
- Viditelné mapy od vlhkosti na stěnách či stropech.
- Solné výkvěty (bílý povlak) na zdivu.
- Ložiska plísní v rozích místností.
- Odfouknutá a vlhkem degradovaná omítka u soklu budovy.

5. Celková neobyvatelnost:
- Zásadní poškození střechy, vybitá okna, stav "vybydlenosti".

Rozhodovací kritéria (Kdy zvolit ANO):
- Dům je starý, esteticky zastaralý (např. 80. léta), ale vše je kompletní a funkční.
- Dům je čistý, suchý a bez prasklin.
- Zahrada je neudržovaná, ale dům jako takový je stavebně v pořádku.

Odpovídej maximálně ve dvou větách v důvodu.

VRAŤ POUZE VALIDNÍ JSON V TOMTO FORMÁTU:
{
  "verdikt": "ANO" nebo "NE",
  "duvod": "Stručný a věcný popis v češtině. Pokud je verdikt NE, konkrétně uveď, co na fotografii vidíš."
}
"""

class InspektorAgent(BaseAgent):
    """Agent 4: Inspektor - visual defect detection (ANO/NE pro online ocenění)."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="Inspektor",
            description="Rozhodnutí o způsobilosti k online ocenění",
            system_prompt=INSPECTOR_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        images = context.get("images", [])
        self.log(f"Inspecting {len(images)} images for technical condition.")

        if not self.client:
            self.log("Gemini API key not configured.", "warn")
            return AgentResult(
                status=AgentStatus.WARN,
                summary="Inspekce nedostupná (chybí API klíč)",
                score=0,
                warnings=["AI inspekce nedostupná."],
            )

        try:
            self.log("Sending images for technical inspection...", "thinking")

            parts = [
                f"Proveď technickou inspekci tohoto rodinného domu. Analyzuj {len(images)} fotografií:\n"
            ]

            for img in images:
                with open(img["processed_path"], "rb") as f:
                    image_bytes = f.read()
                parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                parts.append(f"Photo ID: {img['id']}")

            response_text = await self.client.generate_content(
                system_instruction=self.system_prompt,
                contents=parts,
                response_mime_type="application/json",
                max_output_tokens=1000,
            )

            ai_result = json.loads(response_text)
            self.log("Inspection analysis received.", "info")

            verdikt = ai_result.get("verdikt", "NE")
            duvod = ai_result.get("duvod", "Neznámý důvod.")

            self.log(f"Verdikt: {verdikt}, Důvod: {duvod}")

            warnings = []
            errors = []

            if verdikt.upper() == "NE":
                status = AgentStatus.FAIL
                errors.append(f"Nezpůsobilé pro online ocenění: {duvod}")
            else:
                status = AgentStatus.SUCCESS

            return AgentResult(
                status=status,
                summary=f"Způsobilé k online ocenění: {verdikt}",
                details={
                    "verdikt": verdikt,
                    "duvod": duvod
                },
                warnings=warnings,
                errors=errors,
            )

        except Exception as e:
            self.log(f"Inspection error: {str(e)}", "error")
            return AgentResult(
                status=AgentStatus.WARN,
                summary=f"Chyba inspekce: {str(e)}",
                score=0,
                warnings=[f"Inspekce selhala: {str(e)}"],
            )
