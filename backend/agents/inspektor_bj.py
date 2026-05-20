"""Agent: InspektorBJ – Defect Detection for Bytová jednotka (apartment).

Visual analysis of technical condition of the apartment and its building:
- Evaluates BOTH the building exterior AND apartment interior
- Assesses common areas (hallways, staircase, elevator)
- Panel vs brick specifics
- Verdict: ANO/NE for online valuation
"""
import json
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import GEMINI_API_KEY, GEMINI_MODEL


INSPECTOR_BJ_SYSTEM_PROMPT = """Jsi specializovaný inspektor bytových jednotek. Tvým úkolem je na základě vizuální analýzy fotografií rozhodnout, zda je byt způsobilý pro automatizované online ocenění. Tvým cílem je identifikovat rizika, která vyžadují zásah odhadce.

KLÍČOVÉ PRAVIDLO – KOMBINACE BUDOVY A BYTU:
Verdikt MUSÍ vycházet z hodnocení OBOU pohledů – budovy (exteriér + společné prostory) i bytu (interiér). Nikdy nehodnoť jen jedno!
- Nejprve posuď budovu (fasáda, střecha, společné prostory, schodiště, výtah).
- Poté posuď byt (podlahy, stěny, stropy, kuchyně, koupelna, okna, rozvody).
- Finální verdikt = horší z obou hodnocení.

Základní princip:
Hledáš byt, který je obyvatelný a funkční. Nevadí, že je vybavení zastaralé (retro), pokud je v dobrém technickém stavu. Jakákoliv probíhající práce nebo poškození konstrukce znamenají stopku.

Rozhodovací kritéria (Kdy zvolit NE):

1. Probíhající rekonstrukce bytu:
   - Chybějící podlahy, odhalené rozvody, vytrhané obklady, chybějící sanitární technika
   - Rozbitá nebo chybějící okna/dveře v bytě

2. Probíhající rekonstrukce budovy:
   - Lešení na fasádě, rozestavěné části domu
   - Nefunkční výtah v domě kde je povinný

3. Stav budovy – fasáda:
   - Závažné poškození fasády (opadaná omítka > 15 % viditelné plochy)
   - Panelové domy: viditelné praskliny v panelových stycích

4. Statické vady budovy:
   - Trhliny v nosném zdivu (diagonální trhliny, praskliny v základech)
   - Vizuální náznak sedání objektu

5. Vlhkost a plísně v bytě:
   - Viditelné mapy od vlhkosti na stěnách/stropech
   - Ložiska plísní v rozích místností
   - Solné výkvěty na zdivu

6. Stav společných prostor:
   - Závažné poškození schodiště, rozpadající se zdi v chodbě
   - Nefunkční osvětlení + silná degradace prostor

Rozhodovací kritéria (Kdy zvolit ANO):
- Byt je starší ale kompletní a funkční (i s retro vybavením)
- Budova je starší ale strukturálně v pořádku
- Běžné opotřebení odpovídající stáří

V důvodu VŽDY uveď hodnocení obou pohledů ve formátu:
"Budova: [hodnocení]. Byt: [hodnocení]. [Celkový závěr]."

Navíc pro každou fotografii, kde vidíš konkrétní vadu, uveď v poli photo_defects její ID a seznam defektních tagů.
Možné defektní tagy: PRASKLINA, VLHKOST, PLISEN, REKONSTRUKCE, POSKOZENA_OMITKA, PORUSENA_STRECHA, VYBYDLENOST
Pokud na fotce žádná vada není, fotku do photo_defects NEZAHRŇUJ.

VRATĚ POUZE VALIDNÍ JSON V TOMTO FORMÁTU:
{
  "verdikt": "ANO" nebo "NE",
  "duvod": "Budova: [hodnocení]. Byt: [hodnocení]. [Celkový závěr v jedné větě].",
  "photo_defects": [
    {"photo_id": "id_fotky", "defects": ["PRASKLINA", "VLHKOST"]}
  ]
}
"""


class InspektorBJAgent(BaseAgent):
    """Agent 4 (BJ): Inspektor - visual defect detection for apartments."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="InspektorBJ",
            description="Rozhodnutí o způsobilosti bytu k online ocenění",
            system_prompt=INSPECTOR_BJ_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        images = context.get("images", [])
        self.log(f"Inspekce bytu: {len(images)} fotografií.")

        if not self.client:
            self.log("Gemini API key not configured.", "warn")
            return AgentResult(
                status=AgentStatus.WARN,
                summary="Inspekce nedostupná (chybí API klíč)",
                score=0,
                warnings=["AI inspekce nedostupná."],
            )

        try:
            from google.genai import types
            self.log("Analyzuji technický stav bytu a budovy...", "thinking")

            parts = [
                f"Proveď technickou inspekci této bytové jednotky. Analyzuj {len(images)} fotografií:\n"
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
                max_output_tokens=3000,
            )

            ai_result = robust_json_parse(response_text)
            self.log("Inspekce bytu dokončena.", "info")

            verdikt = ai_result.get("verdikt", "NE")
            duvod = ai_result.get("duvod", "Neznámý důvod.")
            photo_defects = ai_result.get("photo_defects", [])

            self.log(f"Verdikt: {verdikt}, Důvod: {duvod}")
            if photo_defects:
                self.log(f"Defekty nalezeny na {len(photo_defects)} fotkách.")

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
                    "duvod": duvod,
                    "photo_defects": photo_defects,
                },
                warnings=warnings,
                errors=errors,
            )

        except Exception as e:
            self.log(f"Chyba inspekce bytu: {str(e)}", "error")
            return AgentResult(
                status=AgentStatus.WARN,
                summary=f"Chyba inspekce: {str(e)}",
                score=0,
                warnings=[f"Inspekce selhala: {str(e)}"],
            )
