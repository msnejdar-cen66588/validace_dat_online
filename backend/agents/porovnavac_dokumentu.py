"""Agent: PorovnavacDokumentu – porovnání dat z PDF formuláře s fotodokumentací.

Sends property data (from PDF or manual input) alongside uploaded photos to Gemini,
which evaluates whether the photos match the declared property characteristics.
"""
import json
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import GEMINI_API_KEY, GEMINI_MODEL

COMPARATOR_SYSTEM_PROMPT = """Jsi expert na validaci nemovitostí. Tvým úkolem je porovnat údaje z formuláře
ocenění rodinného domu s přiloženou fotodokumentací.

Dostaneš:
1. Údaje z formuláře (JSON): stav domu, počet podlaží, typ střechy, podsklepení, celková podlahová plocha, vytápění, rok dokončení
2. Fotografie nemovitosti

Na základě fotografií ověř, zda odpovídají údajům z formuláře. Konkrétně hodnoť KAŽDÝ z těchto bodů:

═══════════════════════════════════════════════════════════════
1. **POČET PODLAŽÍ** — NEJDŮLEŽITĚJŠÍ KONTROLA (častá chyba!)
═══════════════════════════════════════════════════════════════

Toto je NEJČASTĚJŠÍ chyba v dokumentaci. Pečlivě spočítej podlaží z fotografií:

PRAVIDLA PRO POČÍTÁNÍ PODLAŽÍ:
- **1NP (přízemí)** = vždy se počítá
- **2NP (patro)** = plné nadzemní podlaží se svislými stěnami v celé výšce
- **Podkroví (obytné)** = prostor pod střechou se střešními okny, vikýři nebo obytně upravený
  → Obytné podkroví se POČÍTÁ jako podlaží a mělo by být v deklaraci uvedeno
  → Záleží na formuláři: může být uvedeno jako „1+podkroví" nebo „2 podlaží"
- **Půda (neobytná)** = prostor pod střechou BEZ oken, BEZ vikýřů, neupravený
  → Neobytná půda se NEPOČÍTÁ jako podlaží
- **Suterén/sklep** = podzemní podlaží
  → Může i nemusí být počítáno podle formuláře, ale musí být konzistentní s „podsklepení"

ČASTÉ CHYBY, KTERÉ MUSÍŠ ODHALIT:
- Deklarováno „2 podlaží" ale na fotce je vidět jen přízemí + podkroví → ve skutečnosti 1NP + podkroví
- Deklarováno „1 podlaží" ale na fotce je vidět přízemí + celé patro → ve skutečnosti 2NP
- Podkroví s vikýři/střešními okny ale neuvedeno v podlažích
- Suterén viditelný (suterénní okna, anglické dvorky) ale neuveden

JAK POZNAT POČET PODLAŽÍ Z FOTEK:
- Počítej ŘADY OKEN nad sebou na exteriérových fotkách
- 1 řada oken = přízemí (1NP)
- 2 řady oken = přízemí + patro (2NP)
- Okna ve střeše (střešní okna, vikýře) = podkroví
- Okna pod úrovní terénu = suterén
- Na interiérových fotkách: šikmé stropy/stěny = podkroví

PODKROVÍ — PODROBNÁ ANALÝZA:
- Pokud vidíš VIKÝŘE (výstupky ze střechy s okny) → obytné podkroví
- Pokud vidíš STŘEŠNÍ OKNA (Velux apod.) → obytné podkroví
- Pokud na interiérových fotkách vidíš šikmé stropy s nábytkem → obytné podkroví
- Pokud střecha nemá žádná okna a je strmá → pravděpodobně neobytná půda
- Sedlová/mansardová střecha s okny → téměř jistě podkroví

2. **Celková podlahová plocha** – Odhadni přibližnou podlahovou plochu z fotografií.
   Zohledni viditelný půdorys domu (šířka × hloubka), počet podlaží, a porovnej s deklarovanou hodnotou.
   Pokud je rozdíl větší než 20 %, označ jako neshodu. Uveď jak jsi odhad provedl.

3. **Typ střechy** – Shoduje se typ střechy na fotkách (sedlová, valbová, plochá, mansardová, pultová) s deklarovaným?

4. **Stav domu** – Odpovídá vizuální stav domu (fasáda, okna, celkový dojem) deklarovanému stavu?

5. **Podsklepení** – Jsou na fotkách viditelné známky sklepa (suterénní okna, anglické dvorky, schody dolů)?
   Porovnej s deklarací. Konzistentní s počtem podlaží (pokud vidíš suterén, musí být uveden).

6. **Typ vytápění** – Jsou na fotkách viditelné prvky vytápění (komín, plynový kotel, tepelné čerpadlo, radiátory, podlahové vytápění, solární panely, krb)?

7. **Celkový dojem** – Celkové zhodnocení souladu formuláře a fotek.

Vrať výsledek jako JSON:
{
  "verdict": "SHODA" | "ČÁSTEČNÁ_SHODA" | "NESHODA",
  "confidence": 0.0-1.0,
  "overall_summary": "Celkové shrnutí porovnání...",
  "checks": [
    {
      "field": "počet podlaží",
      "declared": "hodnota z formuláře",
      "observed": "co je vidět na fotkách (např. '1NP + obytné podkroví')",
      "match": true/false,
      "note": "Detailní analýza: kolik řad oken, vikýře, střešní okna, šikmé stropy..."
    },
    {
      "field": "celková podlahová plocha",
      "declared": "hodnota z formuláře v m²",
      "observed": "odhadovaná plocha z fotek v m² (postup odhadu)",
      "match": true/false,
      "note": "Jak jsi k odhadu dospěl, proč se shoduje/neshoduje..."
    },
    ...
  ],
  "warnings": ["Případná varování..."],
  "recommendations": ["Doporučení..."]
}

Odpověz POUZE validním JSON. Buď objektivní a EXTRA pečlivý v hodnocení počtu podlaží a podkroví.
Vždy zahrň kontrolu podlahové plochy a počtu podlaží jako PRVNÍ dva body v checks.
"""


class PorovnavacDokumentuAgent(BaseAgent):
    """Compares declared property data (from PDF/manual input) with photo evidence."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="PorovnavacDokumentu",
            description="Porovnání údajů z formuláře s fotodokumentací",
            system_prompt=COMPARATOR_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        property_data = context.get("property_data")
        images = context.get("images", [])

        # Skip if no property data provided
        if not property_data:
            self.log("Žádná data z formuláře – přeskakuji porovnání.", "info")
            return AgentResult(
                status=AgentStatus.SUCCESS,
                summary="Přeskočeno – nebyla poskytnuta data z formuláře.",
                details={"skipped": True, "reason": "no_property_data"},
            )

        self.log(f"Porovnávám data z formuláře s {len(images)} fotografiemi...", "thinking")

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
            # Build prompt with property data
            property_json = json.dumps(property_data, ensure_ascii=False, indent=2)
            parts = [
                f"Údaje z formuláře ocenění rodinného domu:\n```json\n{property_json}\n```\n\n"
                f"Porovnej tyto údaje s následujícími {len(images)} fotografiemi nemovitosti:\n"
            ]

            # Attach photos (max 10 to stay within limits)
            photos_to_send = images[:10]
            for img in photos_to_send:
                try:
                    with open(img["processed_path"], "rb") as f:
                        image_bytes = f.read()
                    parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                    parts.append(f"Photo ID: {img['id']}")
                except Exception as e:
                    self.log(f"Error reading image {img.get('id', '?')}: {e}", "warn")

            response_text = await self.client.generate_content(
                system_instruction=self.system_prompt,
                contents=parts,
                response_mime_type="application/json",
                max_output_tokens=3000,
            )

            self.log("AI porovnání dokončeno.", "info")
            ai_result = robust_json_parse(response_text)

            verdict = ai_result.get("verdict", "UNKNOWN")
            confidence = ai_result.get("confidence", 0.0)
            checks = ai_result.get("checks", [])
            ai_warnings = ai_result.get("warnings", [])
            recommendations = ai_result.get("recommendations", [])
            overall_summary = ai_result.get("overall_summary", "")

            # Count matches/mismatches from actual check data
            matches = sum(1 for c in checks if c.get("match", False))
            mismatches = len(checks) - matches

            # Override AI verdict with actual check results to prevent inconsistency
            # (AI sometimes says ČÁSTEČNÁ_SHODA while all checks show match=True)
            if checks:
                if mismatches == 0:
                    verdict = "SHODA"
                elif matches == 0:
                    verdict = "NESHODA"
                else:
                    verdict = "ČÁSTEČNÁ_SHODA"

            # Determine status based on (corrected) verdict
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
