"""Agent 5: Strateg – Aggregation Logic & Routing (SEMAFOR methodology).

Final decision-maker per SEMAFOR rules:
- 🟢 ONLINE: 0 FAIL, 0 WARN (or only INFO-level)
- 🟡 SUPERVISED: 0 FAIL, 1+ WARN
- 🔴 VRÁTIT KLIENTOVI: ANY FAIL from ANY agent
"""
import json
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import (
    GEMINI_API_KEY, GEMINI_MODEL
)


REPORT_PROMPT = """Jsi senior analytik nemovitostí. Na základě výsledků automatické validace napiš stručný, čitelný report.

Piš česky, profesionálně ale srozumitelně – jako by to psal zkušený kolega pro svého nadřízeného.
Nepoužívej technický žargon. Nepiš o „agentech\" – piš o kontrolách a zjištěních.

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
Nepiš \"Agent zjistil\" ale \"Bylo ověřeno\" nebo \"Kontrola ukázala\" apod.

Vrať POUZE text reportu, bez markdownu ani JSON.
"""


class StrategAgent(BaseAgent):
    """Agent 5: Strateg - final aggregation and routing decision per SEMAFOR methodology."""

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
        gdpr = agent_results.get("GDPRValidator")

        self.log("Agregace výsledků všech kontrol...")

        # Count warnings and fails
        total_warns = 0
        # Warnings that actually trigger SUPERVISED (Strazce WARN = photo age 90-180 days → only informational)
        total_warns_for_supervised = 0
        has_fail = False
        failing_agents = []
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
            # Strazce WARNs (photo age 90-180 days) are informational only – do NOT trigger SUPERVISED
            if name not in ("Strazce", "StrazceBJ"):
                total_warns_for_supervised += len(result.warnings)
            all_warnings.extend(result.warnings)
            all_errors.extend(result.errors)
            if result.status == AgentStatus.FAIL:
                has_fail = True
                failing_agents.append(name)
                self.log(f"FAIL: {name} – {result.summary}", "error")
            elif result.warnings:
                self.log(f"WARN: {name} – {len(result.warnings)} varování", "warn")
            else:
                self.log(f"OK: {name}")

        # Effective age
        effective_age = None
        if historian and historian.details.get("effective_age") is not None:
            effective_age = historian.details["effective_age"]

        # Final category from Historik
        final_category = None
        if historian and historian.category is not None:
            final_category = historian.category

        # Critical override from Inspektor
        inspektor_fail = inspector and inspector.status == AgentStatus.FAIL
        if inspektor_fail:
            final_category = 5

        # ── SEMAFOR decision tree — per methodology ────────────────────────────
        #
        # 🟡 SUPERVISED (Nevyhovuje online):
        #     - Inspektor FAIL (nemovitost nevhodná pro online ocenění)
        #     - ForenzníAnalytik FAIL (manipulace fotek)
        #     - GeoValidator FAIL (GPS >1000m)
        #     - KatastralniAnalytik FAIL
        #     - PorovnavacDokumentu FAIL (rozpor formulář vs realita u RD)
        #     - 0 FAIL, ale 1+ WARN
        #
        # 🔴 VRÁTIT KLIENTOVI (Chybí podklady):
        #     - Pouze pokud by šlo online, ale chybí dokumentace!
        #     - Strážce FAIL (neúplná/neaktuální fotodokumentace)
        #     - GDPR FAIL (obličeje na fotkách)
        #
        # 🟢 ONLINE: 0 FAIL, 0 WARN
        #

        # Agenti, jejichž selhání znamená, že nemovitost prostě NEMŮŽE jít online (-> SUPERVISED)
        agents_blocking_online = {"Inspektor", "ForenzniAnalytik", "GeoValidator", "Historik", "KatastralniAnalytik", "PorovnavacDokumentu"}
        
        # Agenti, jejichž selhání znamená chybnou/chybějící dokumentaci (-> VRÁTIT KLIENTOVI)
        agents_missing_docs = {"Strazce", "GDPRValidator"}

        is_ineligible_for_online = any(a in failing_agents for a in agents_blocking_online)
        is_missing_docs = any(a in failing_agents for a in agents_missing_docs)

        if is_ineligible_for_online:
            semaphore = "SUPERVISED"
            semaphore_color = "orange"
            fail_reasons = []
            for name in failing_agents:
                if name in agents_blocking_online:
                    summary = agent_summaries.get(name, {}).get("summary", "")
                    fail_reasons.append(f"{name}: {summary}")
            semaphore_reason = f"Nemovitost vyžaduje dohled pracovníka (nesplňuje kritéria pro online): {' | '.join(fail_reasons)}"

        elif is_missing_docs:
            semaphore = "VRÁTIT KLIENTOVI"
            semaphore_color = "red"
            fail_reasons = []
            for name in failing_agents:
                if name in agents_missing_docs:
                    summary = agent_summaries.get(name, {}).get("summary", "")
                    if name == "Strazce":
                        fail_reasons.append(f"Fotodokumentace je neúplná nebo nevyhovující: {summary}")
                    elif name == "GDPRValidator":
                        fail_reasons.append(f"GDPR problém (osoby na fotkách): {summary}")
            semaphore_reason = " | ".join(fail_reasons)

        elif total_warns_for_supervised >= 1:
            semaphore = "SUPERVISED"
            semaphore_color = "orange"
            semaphore_reason = (
                f"Online ocenění je možné, ale výsledky vyžadují manuální přezkoumání "
                f"supervizorem ({total_warns_for_supervised} varování)."
            )
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
                "failing_agents": failing_agents,
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

            # Response is plain text report (not JSON)
            report = response_text.strip() if response_text else self._fallback_report(agent_summaries, semaphore, category)
            self.log("Strateg report vygenerován.", "info")
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
