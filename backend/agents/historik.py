"""Agent 3: Historik – Age Calculation (BR-G6).

Calculates effective age and assigns primary category:
- Formula: 2026 - year_of_reconstruction (priority), else 2026 - year_of_construction
- Reconstruction takes precedence
- Assigns primary category 1-5 based on effective age
"""
from agents.base import BaseAgent, AgentResult, AgentStatus
from config import REFERENCE_YEAR


HISTORIAN_SYSTEM_PROMPT = """Jsi expert na hodnocení stáří nemovitostí. Tvým úkolem je:

1. Vypočítat EFEKTIVNÍ VĚK nemovitosti podle vzorce:
   - Pokud existuje rok rekonstrukce: efektivní_věk = {ref_year} - rok_rekonstrukce
   - Pokud ne: efektivní_věk = {ref_year} - rok_výstavby
   - Rekonstrukce má VŽDY přednost.

2. Přiřadit PRIMÁRNÍ KATEGORII (1-5) dle efektivního věku:
   - Kat. 1: 0-5 let (novostavba / čerstvá rekonstrukce)
   - Kat. 2: 6-15 let (moderní)
   - Kat. 3: 16-30 let (starší, ale udržovaný)
   - Kat. 4: 31-50 let (starší, vyžaduje pozornost)
   - Kat. 5: 50+ let (starý, potenciální rizika)
""".format(ref_year=REFERENCE_YEAR)


class HistorikAgent(BaseAgent):
    """Agent 3: Historik - calculates effective age and category."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="Historik",
            description="Výpočet efektivního věku a kategorie (BR-G6)",
            system_prompt=HISTORIAN_SYSTEM_PROMPT,
            model_name=model_name
        )

    async def run(self, context: dict) -> AgentResult:
        year_built = context.get("year_built")
        year_reconstructed = context.get("year_reconstructed")

        self.log(f"Input: rok výstavby={year_built}, rok rekonstrukce={year_reconstructed}")

        if not year_built and not year_reconstructed:
            self.log("Missing both year_built and year_reconstructed.", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary="Chybí rok výstavby i rekonstrukce.",
                errors=["Nelze vypočítat efektivní věk bez roku výstavby nebo rekonstrukce."],
            )

        # Calculate effective age
        if year_reconstructed and year_reconstructed > 0:
            effective_age = REFERENCE_YEAR - year_reconstructed
            age_source = "rekonstrukce"
            self.log(f"Using reconstruction year: {year_reconstructed}")
        else:
            effective_age = REFERENCE_YEAR - year_built
            age_source = "výstavba"
            self.log(f"Using construction year: {year_built}")

        # Ensure non-negative
        effective_age = max(0, effective_age)

        self.log(f"Effective age: {effective_age} let (zdroj: {age_source})")

        # Assign category
        if effective_age <= 5:
            category = 1
            cat_desc = "Novostavba / čerstvá rekonstrukce"
        elif effective_age <= 15:
            category = 2
            cat_desc = "Moderní"
        elif effective_age <= 30:
            category = 3
            cat_desc = "Starší, udržovaný"
        elif effective_age <= 50:
            category = 4
            cat_desc = "Starší, vyžaduje pozornost"
        else:
            category = 5
            cat_desc = "Starý, potenciální rizika"

        self.log(f"Category: {category} – {cat_desc}")

        warnings = []
        if effective_age > 50:
            warnings.append(f"Nemovitost je velmi stará ({effective_age} let). Doporučena důkladná inspekce.")

        return AgentResult(
            status=AgentStatus.SUCCESS,
            category=category,
            summary=f"Efektivní věk: {effective_age} let ({age_source}) → Kategorie {category} ({cat_desc})",
            details={
                "effective_age": effective_age,
                "age_source": age_source,
                "year_built": year_built,
                "year_reconstructed": year_reconstructed,
                "reference_year": REFERENCE_YEAR,
                "category": category,
                "category_description": cat_desc,
            },
            warnings=warnings,
        )
