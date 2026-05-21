"""Agent: StrategBJ – Final aggregation for Bytová jednotka pipeline.

Aggregates results from all BJ agents and produces the traffic-light decision:
 • ONLINE   (green)  – all checks pass, proceed automatically
 • SUPERVISED (yellow) – some warnings, needs human review
 • RETURN   (red)     – critical issues, return to client
"""
import json
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import GEMINI_API_KEY, GEMINI_MODEL

STRATEG_BJ_SYSTEM_PROMPT = """Jsi hlavní rozhodčí agentní pipeline pro validaci ocenění BYTOVÝCH JEDNOTEK.

Dostáváš výsledky všech ostatních agentů:
1. StrazceBJ – úplnost fotodokumentace bytu
2. ForenzniAnalytik – ověření autenticity fotek
3. Historik – efektivní stáří budovy
4. InspektorBJ – technický stav bytu a budovy
5. PorovnavacDokumentuBJ – porovnání formuláře s fotkami + ověření dokumentu podlahové plochy
6. KatastralniAnalytik – analýza LV a ortofota
7. GeoValidator – GPS validace a panoramatické porovnání

Na základě VŠECH výsledků zvol finální SEMAFOR:

🟢 **ONLINE** – Vše v pořádku, byt lze ocenit online.
   Podmínky:
   - Fotodokumentace je kompletní (min 4 fotky bytu)
   - Fotky jsou autentické
   - Byt je způsobilý k online ocenění (verdikt Inspektora = ANO)
   - Data z formuláře odpovídají fotodokumentaci
   - Dokument podlahové plochy je akceptovatelný a plocha odpovídá
   - Žádné vysoké riziko z LV

🟡 **SUPERVISED** – Byt nelze ocenit plně online automaticky, vyžaduje dohled nebo manuální ocenění odhadcem.
   Sem spadají všechny případy, kdy je dokumentace sice v pořádku, ale nemovitost sama o sobě nesplňuje parametry.
   Příklady (FAIL z odborných agentů):
   - Byt nezpůsobilý k ocenění (verdikt Inspektora = NE, např. rozestavěno, špatný stav)
   - Podezření na manipulaci fotek (ForenzniAnalytik = FAIL)
   - Vysoké riziko z LV (zástavy, zákazy zcizení)
   - GPS nesoulad
   - Drobné neshody v porovnání formuláře

🔴 **RETURN** – Vrátit klientovi k doplnění (Chybí podklady).
   Tento stav použij POUZE pokud by byt pravděpodobně šel ocenit online, ale klient nedoložil všechny nutné podklady!
   Příklady:
   - Nedostatečná, neaktuální nebo zcela nevyhovující fotodokumentace (StrazceBJ = FAIL)
   - GDPR problém (detekovány rozpoznatelné obličeje na fotkách)
   - Nevyhovující, chybějící nebo zcela rozporuplný doklad o podlahové ploše (PorovnavacDokumentuBJ = FAIL)

SPECIFIKA PRO BYTOVÉ JEDNOTKY:
- Podlahová plocha je KLÍČOVÝ údaj – věnuj zvláštní pozornost porovnání plochy z formuláře, dokumentu a vizuálního odhadu
- Stav budovy (exteriér, společné prostory) je důležitý SPOLEČNĚ se stavem bytu
- U BJ se NEŘEŠÍ: vedlejší stavby, pozemky, zastavěná plocha, podsklepení

VÝSTUP (POUZE JSON):
{
  "semaphore": "ONLINE" | "SUPERVISED" | "RETURN",
  "semaphore_color": "green" | "yellow" | "red",
  "headline": "Stručný nadpis rozhodnutí (max 10 slov)",
  "reasoning": "Podrobné zdůvodnění rozhodnutí – uveď klíčové faktory z jednotlivých agentů.",
  "key_findings": [
    {"agent": "StrazceBJ", "result": "OK/WARN/FAIL", "note": "Stručný popis"},
    {"agent": "ForenzniAnalytik", "result": "...", "note": "..."},
    ...
  ],
  "warnings": ["Seznam varování pro odhadce"],
  "recommendations": ["Doporučení pro další postup"]
}
"""


class StrategBJAgent(BaseAgent):
    """Final aggregation agent for BJ pipeline."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="StrategBJ",
            description="Finální rozhodnutí o ocenění bytové jednotky",
            system_prompt=STRATEG_BJ_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        agent_results = context.get("agent_results", {})
        property_data = context.get("property_data")

        self.log(f"Agregace {len(agent_results)} agentů pro bytovou jednotku...", "thinking")

        # ── Collect agent summaries (trimmed — no full details to avoid payload bloat) ──
        agent_summaries = {}
        for name, result in agent_results.items():
            if hasattr(result, 'status'):
                # Extract only key fields from details to keep the payload manageable
                trimmed_details = {}
                if hasattr(result, 'details') and isinstance(result.details, dict):
                    for key in ("verdict", "confidence", "semaphore", "semaphore_color",
                                "effective_age", "category", "overall_summary",
                                "suitability_verdict", "total_photos", "are_photos_current",
                                "missing_categories", "visual_score"):
                        if key in result.details:
                            trimmed_details[key] = result.details[key]

                agent_summaries[name] = {
                    "status": result.status.value,
                    "summary": result.summary,
                    "warnings": result.warnings[:5] if result.warnings else [],
                    "errors": result.errors[:3] if result.errors else [],
                    "key_details": trimmed_details,
                }
            elif isinstance(result, dict):
                agent_summaries[name] = {
                    "status": result.get("status", "unknown"),
                    "summary": result.get("summary", ""),
                    "warnings": (result.get("warnings") or [])[:5],
                    "errors": (result.get("errors") or [])[:3],
                }

        if not self.client:
            self.log("API key not configured, using rule-based fallback.", "warn")
            return self._rule_based_decision(agent_summaries, property_data)

        try:
            # Build context for Strateg — safe serialization
            def _safe_default(obj):
                try:
                    return str(obj)
                except Exception:
                    return "<non-serializable>"

            context_text = json.dumps(
                {
                    "agent_results": agent_summaries,
                    "property_data": property_data,
                },
                ensure_ascii=False,
                indent=2,
                default=_safe_default,
            )

            # Truncate if excessively large (>30k chars) to avoid LLM token limits
            if len(context_text) > 30000:
                context_text = context_text[:30000] + "\n... (zkráceno)"
                self.log("Kontext zkrácen na 30k znaků", "warn")

            response_text = await self.client.generate_content(
                system_instruction=self.system_prompt,
                contents=(
                    f"Rozhodni o finálním semaforu pro tuto bytovou jednotku.\n\n"
                    f"VÝSLEDKY AGENTŮ:\n{context_text}"
                ),
                response_mime_type="application/json",
                max_output_tokens=4000,
            )

            ai_result = robust_json_parse(response_text)
            semaphore = ai_result.get("semaphore", "SUPERVISED")
            semaphore_color = ai_result.get("semaphore_color", "yellow")
            headline = ai_result.get("headline", "Výsledek kontroly bytové jednotky")
            reasoning = ai_result.get("reasoning", "")
            key_findings = ai_result.get("key_findings", [])
            warnings = ai_result.get("warnings", [])
            recommendations = ai_result.get("recommendations", [])

            self.log(f"Semafor: {semaphore} ({semaphore_color})")
            self.log(f"Headline: {headline}")

            # Map semaphore to agent status
            if semaphore == "ONLINE":
                status = AgentStatus.SUCCESS
            elif semaphore == "RETURN":
                status = AgentStatus.FAIL
            else:
                status = AgentStatus.WARN

            return AgentResult(
                status=status,
                summary=headline,
                category=semaphore,
                details={
                    "semaphore": semaphore,
                    "semaphore_color": semaphore_color,
                    "headline": headline,
                    "reasoning": reasoning,
                    "key_findings": key_findings,
                    "agent_summaries": agent_summaries,
                },
                warnings=warnings,
            )

        except Exception as e:
            self.log(f"Chyba Stratéga: {str(e)}", "error")
            return self._rule_based_decision(agent_summaries, property_data)

    def _rule_based_decision(self, agent_summaries: dict, property_data: dict | None) -> AgentResult:
        """Simple rule-based fallback when AI is unavailable."""
        fails = sum(1 for a in agent_summaries.values()
                    if (a.get("status") if isinstance(a, dict) else "") == "fail")
        warns_for_supervised = sum(1 for name, a in agent_summaries.items()
                    if (a.get("status") if isinstance(a, dict) else "") == "warn"
                    and name not in ("StrazceBJ", "Strazce"))

        failing_agents = [name for name, a in agent_summaries.items()
                          if (a.get("status") if isinstance(a, dict) else "") == "fail"]

        agents_blocking_online = {"InspektorBJ", "ForenzniAnalytik", "GeoValidator", "Historik", "KatastralniAnalytik"}
        agents_missing_docs = {"StrazceBJ", "GDPRValidator", "PorovnavacDokumentuBJ"}

        is_ineligible_for_online = any(a in failing_agents for a in agents_blocking_online)
        is_missing_docs = any(a in failing_agents for a in agents_missing_docs)

        if is_ineligible_for_online:
            semaphore, color, status = "SUPERVISED", "yellow", AgentStatus.WARN
            reasoning = "Rule-based: Nemovitost vyžaduje dohled (nelze plně online)."
        elif is_missing_docs:
            semaphore, color, status = "RETURN", "red", AgentStatus.FAIL
            reasoning = "Rule-based: Chybí/nevyhovuje fotodokumentace nebo dokument plochy."
        elif warns_for_supervised >= 1:
            semaphore, color, status = "SUPERVISED", "yellow", AgentStatus.WARN
            reasoning = f"Rule-based: 0 fails, {warns_for_supervised} warnings."
        else:
            semaphore, color, status = "ONLINE", "green", AgentStatus.SUCCESS
            reasoning = "Rule-based: Vše v pořádku."

        return AgentResult(
            status=status,
            summary=f"Semafor: {semaphore} (rule-based fallback)",
            category=semaphore,
            details={
                "semaphore": semaphore,
                "semaphore_color": color,
                "headline": f"BJ kontrola – {semaphore}",
                "reasoning": reasoning,
                "key_findings": [],
                "agent_summaries": agent_summaries,
            },
            warnings=["Strateg BJ: AI analýza nedostupná, použit rule-based fallback."],
        )
