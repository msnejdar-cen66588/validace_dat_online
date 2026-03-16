"""Agent 5: Strateg – Aggregation Logic & Routing.

Final decision-maker:
- Tracks precedence: BR-G4 (completeness) has highest priority
- Warning counting: 0 = ONLINE, 1-2 = SUPERVISED, 3+ or any FAIL = RETURN TO CLIENT
- Compares AI result vs user input using 2D matrix
- Generates human-readable report via Gemini
"""
import json
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient
from config import (
    GEMINI_API_KEY, GEMINI_MODEL
)


REPORT_PROMPT = """Jsi senior analytik nemovitostí. Na základě výsledků automatické validace napiš stručný, čitelný report.

Piš česky, profesionálně ale srozumitelně – jako by to psal zkušený kolega pro svého nadřízeného.
Nepoužívej technický žargon. Nepiš o „agentech" – piš o kontrolách a zjištěních.

STRUKTURA REPORTU:
1. **Shrnutí** (2-3 věty – celkový verdikt, nejdůležitější zjištění)
2. **Fotodokumentace** (kompletnost, kvalita dodaných fotek)
3. **Stav nemovitosti** (technický stav, nalezené vady)
4. **Věk a kategorizace** (efektivní věk, přiřazená kategorie)
5. **Ověření autentičnosti** (manipulace fotek, GPS ověření lokace)
6. **Porovnání dokumentů** (shoda/neshoda dat z formuláře s fotodokumentací – pokud byla data z PDF k dispozici, popiš jak se dokumentace shoduje s realitou na fotkách)
7. **Doporučení** (co doporučuješ jako další krok)

Piš stručně – každá sekce max 2-3 věty.
Pokud jsou problémy, jasně je pojmenuj. Pokud je vše v pořádku, řekni jasně „bez nálezu".
Nepiš "Agent zjistil" ale "Bylo ověřeno" nebo "Kontrola ukázala" apod.

Vrať POUZE text reportu, bez markdownu ani JSON.
"""


class StrategAgent(BaseAgent):
    """Agent 5: Strateg - final aggregation and routing decision."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="Strateg",
            description="Agregační logika a finální rozhodnutí (Semafor)",
            system_prompt=REPORT_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        agent_results = context.get("agent_results", {})

        guardian = agent_results.get("Strazce")
        forensic = agent_results.get("ForenzniAnalytik")
        historian = agent_results.get("Historik")
        inspector = agent_results.get("Inspektor")
        geovalidator = agent_results.get("GeoValidator")

        self.log("Agregace výsledků všech kontrol...")

        # Count warnings and fails
        total_warns = 0
        has_fail = False
        all_warnings = []
        all_errors = []
        agent_summaries = {}

        for name, result in agent_results.items():
            if result is None or name == "Strateg":
                continue
            agent_summaries[name] = {
                "status": result.status.value,
                "summary": result.summary,
                "warnings": result.warnings,
                "errors": result.errors,
                "details": result.details,
                "score": result.score,
                "category": result.category,
            }
            total_warns += len(result.warnings)
            all_warnings.extend(result.warnings)
            all_errors.extend(result.errors)
            if result.status == AgentStatus.FAIL:
                has_fail = True
                self.log(f"FAIL: {name} – {result.summary}", "error")
            elif result.warnings:
                self.log(f"WARN: {name} – {len(result.warnings)} varování", "warn")
            else:
                self.log(f"OK: {name}")

        # Priority check: Strazce FAIL is blocking
        guardian_fail = guardian and guardian.status == AgentStatus.FAIL
        if guardian_fail:
            self.log("BLOKUJÍCÍ: Neúplná nebo neaktuální fotodokumentace", "error")

        # Check photo actuality separately
        photos_not_current = (
            guardian_fail and
            guardian.details and
            not guardian.details.get("are_photos_current", True)
        )

        effective_age = None
        if historian and historian.details.get("effective_age") is not None:
            effective_age = historian.details["effective_age"]

        # Determine final category
        final_category = None
        if historian and historian.category is not None:
            final_category = historian.category

        # Critical override from Inspektor
        inspektor_fail = inspector and inspector.status == AgentStatus.FAIL
        if inspektor_fail:
            final_category = 5
            has_fail = True
            self.log(f"Kritický nález inspektora: {inspector.summary}", "error")

        # ── Semaphore decision tree ────────────────────────────────────────────
        # Priority: photo completeness/actuality > property condition > general warnings
        if guardian_fail and photos_not_current:
            semaphore = "VRÁTIT KLIENTOVI"
            semaphore_color = "red"
            semaphore_reason = "Fotodokumentace není aktuální nebo se zdá být archivní. Vyžádejte od klienta aktuální fotografie nemovitosti."
        elif guardian_fail:
            semaphore = "VRÁTIT KLIENTOVI"
            semaphore_color = "red"
            semaphore_reason = "Fotodokumentace je neúplná. Chybí povinné záběry (zadní/boční pohled nebo dostatečný počet interiérových fotek)."
        elif inspektor_fail:
            semaphore = "VRÁTIT KLIENTOVI"
            semaphore_color = "red"
            semaphore_reason = f"Nemovitost není způsobilá pro online ocenění kvůli technickému stavu. {inspector.details.get('duvod', '') if inspector and inspector.details else ''}"
        elif has_fail or total_warns >= 3:
            semaphore = "VRÁTIT KLIENTOVI"
            semaphore_color = "red"
            semaphore_reason = "Bylo zjištěno příliš mnoho nesrovnalostí. Případ vyžaduje fyzickou prohlídku odhadce."
        elif total_warns >= 1:
            semaphore = "SUPERVISED"
            semaphore_color = "orange"
            semaphore_reason = "Online ocenění je možné, ale výsledky vyžadují manuální přezkoumání supervizorem."
        else:
            semaphore = "ONLINE"
            semaphore_color = "green"
            semaphore_reason = "Nemovitost splňuje všechna kritéria pro plně automatizované online ocenění."

        self.log(f"Verdikt: {semaphore} | Kategorie: {final_category} | Důvod: {semaphore_reason[:80]}")

        # Generate human-readable report via Gemini
        human_report = await self._generate_report(
            agent_summaries, semaphore, final_category,
            effective_age, total_warns, has_fail,
        )

        # Build status
        status = AgentStatus.FAIL if semaphore == "VRÁTIT KLIENTOVI" else (
            AgentStatus.WARN if semaphore == "SUPERVISED" else AgentStatus.SUCCESS
        )

        return AgentResult(
            status=status,
            category=final_category,
            summary=human_report,
            details={
                "semaphore": semaphore,
                "semaphore_color": semaphore_color,
                "semaphore_reason": semaphore_reason,
                "final_category": final_category,
                "total_warnings": total_warns,
                "has_fail": has_fail,
                "human_report": human_report,
                "agent_summaries": agent_summaries,
            },
            warnings=all_warnings,
            errors=all_errors,
        )

    async def _generate_report(
        self,
        agent_summaries: dict,
        semaphore: str,
        category: int | None,
        effective_age: int | None,
        total_warns: int,
        has_fail: bool,
    ) -> str:
        """Generate a human-readable report using Gemini."""
        if not self.client:
            return self._fallback_report(agent_summaries, semaphore, category)

        try:
            self.log("Generuji závěrečný report...", "thinking")

            data_context = json.dumps({
                "verdikt": semaphore,
                "kategorie": category,
                "efektivni_vek": effective_age,
                "pocet_varovani": total_warns,
                "ma_fail": has_fail,
                "vysledky_kontrol": {
                    name: {
                        "stav": s.get("status"),
                        "shrnuti": s.get("summary"),
                        "varovani": s.get("warnings", []),
                        "chyby": s.get("errors", []),
                    }
                    for name, s in agent_summaries.items()
                },
            }, ensure_ascii=False, indent=2)

            response_text = await self.client.generate_content(
                system_instruction=self.system_prompt,
                contents=f"Napiš stručný report na základě těchto dat:\n\n{data_context}",
                max_output_tokens=1500,
            )

            report = response_text.strip()
            self.log("Report vygenerován.")
            return report

        except Exception as e:
            self.log(f"Chyba generování reportu: {e}", "warn")
            return self._fallback_report(agent_summaries, semaphore, category)

    def _fallback_report(self, summaries: dict, semaphore: str, category: int | None) -> str:
        """Fallback report when AI is unavailable."""
        lines = [f"Verdikt: {semaphore}"]
        if category:
            lines.append(f"Přiřazená kategorie: {category}")
        lines.append("")
        for name, s in summaries.items():
            lines.append(f"{name}: {s.get('summary', '–')}")
        return "\n".join(lines)
