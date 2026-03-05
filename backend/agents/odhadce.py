"""Agent 8: Odhadce (Tržní ocenění) – Porovnávací metoda.

- Vytváří tržní odhad (NHZP) pomocí porovnávací metody.
- Simuluje nalezení 3 nejvhodnějších realistických srovnávacích nemovitostí.
- Poskytuje koeficienty podobnosti pro manuální donastavení.
"""
import json

from google import genai
from google.genai import types

from agents.base import BaseAgent, AgentResult, AgentStatus
from config import GEMINI_API_KEY, GEMINI_MODEL


VALUATION_PROMPT = """Jsi expertní odhadce nemovitostí (soudní znalec / profesionální makléř) se specializací na trh s rodinnými domy v České republice.

TVŮJ ÚKOL:
Na základě dodaných parametrů konkrétního rodinného domu (velikost, stav, adresa/lokalita) vypracuj odhad jeho obvyklé tržní ceny (NHZP) pomocí POROVNÁVACÍ METODY.
Jelikož nemáš živý přístup k aktuálním nabídkám Srealit, **vytvoříš ze svých obsáhlých znalostí realitního trhu (rok 2024-2026) 3 vysoce realistické a reprezentativní "jako by aktuální" nabídky podobných domů** ve stejné nebo velmi podobné lokalitě.

METODIKA:
1. Odhadni základní/výchozí tržní cenu za analyzovaný dům (v CZK).
2. Vygeneruj 3 konkrétní vzorky (nabídky rodinných domů) pro srovnání.
   - Snaž se, aby vzorky měly podobnou podlahovou plochu a stav.
   - Musí být v blízkém či srovnatelném okolí (stejné město/okres/kraj s ohledem na atraktivitu).
   - U každého vzorku urči "koeficient_podobnosti" (float kolem 1.00, kde 1.00 = naprosto stejné, 1.05 = vzorek je o 5% lepší, 0.90 = vzorek je o 10% horší atd.) - koeficienty nesmí být u všech stejné.
   - Vymysli pro vzorky realistické adresy (ulice, obec), rozlohy a krátké popisy stavu.

Vrať POUZE striktně formátovaný JSON podle této struktury, nic jiného:
{
  "zakladni_odhad_czk": 8500000,
  "duvod_odhadu": "Krátké shrnutí, proč jsi zvolil tuto cenovou hladinu (lokalita, stav).",
  "vzorky": [
    {
      "id": 1,
      "adresa": "Krátká 12, Boskovice",
      "velikost_domu_m2": 150,
      "velikost_pozemku_m2": 600,
      "stav": "Po řečné rekonstrukci",
      "cena_czk": 8800000,
      "koeficient_podobnosti": 1.05,
      "oduvodneni_koeficientu": "Vzorek je mírně větší a má lepší izolaci, proto je cenově výš."
    },
    ...
  ]
}
"""


class OdhadceAgent(BaseAgent):
    """Agent 8: Odhadce – určuje NHZP porovnávací metodou."""

    def __init__(self):
        super().__init__(
            name="Odhadce",
            description="Určuje tržní tržní hodnotu nemovitosti (NHZP) porovnávací metodou (3 nejlepší vzorky ze simulovaného trhu).",
            system_prompt=VALUATION_PROMPT,
        )
        self.client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

    async def run(self, context: dict) -> AgentResult:
        self.log("Zahajuji odhad obvyklé tržní ceny (NHZP)...", "info")

        if not self.client:
            self.log("Chybí Gemini API klíč.", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary="Odhadce nedostupný (chybí API).",
                errors=["Gemini API klíč nenalezen."]
            )

        # Gather property details from context
        prop_data = context.get("property_data") or {}
        address = context.get("property_address") or prop_data.get("adresa") or "Neznámá adresa (ČR)"
        floor_area = prop_data.get("celkova_podlahova_plocha") or "Neznámá"
        condition = prop_data.get("stav_rodinneho_domu") or "Neznámý stav"
        roof = prop_data.get("typ_strechy") or "Neznámá střecha"
        heating = prop_data.get("typ_vytapeni") or "Neznámé vytápění"

        prompt_text = (
            f"Parametry analyzované nemovitosti:\n"
            f"- Adresa: {address}\n"
            f"- Podlahová plocha: {floor_area}\n"
            f"- Stav: {condition}\n"
            f"- Střecha: {roof}\n"
            f"- Vytápění: {heating}\n\n"
            f"Nyní prosím vypracuj odhad a 3 vzorky podle instrukcí."
        )

        try:
            self.log("Generuji odhad a porovnávací vzorky...", "thinking")
            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    response_mime_type="application/json",
                    max_output_tokens=1500,
                ),
            )

            result_json = json.loads(response.text)
            zakladni_odhad = result_json.get("zakladni_odhad_czk", 0)
            
            # Format to millions for summary
            odhad_m = zakladni_odhad / 1_000_000

            self.log(f"Úspěšně vygenerován odhad: {odhad_m:.1f} mil. Kč a 3 srovnávací vzorky.", "info")

            return AgentResult(
                status=AgentStatus.SUCCESS,
                summary=f"Odhadní cena: {odhad_m:.2f} mil. Kč. Vygenerovány 3 vzorky.",
                details={
                    "odhad_czk": zakladni_odhad,
                    "duvod": result_json.get("duvod_odhadu", ""),
                    "vzorky": result_json.get("vzorky", []),
                    "analyzed_params": {
                        "address": address,
                        "area": floor_area,
                        "condition": condition
                    }
                }
            )

        except Exception as e:
            self.log(f"Chyba při tvorbě odhadu: {e}", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary="Odhad se nepodařilo dokončit kvůli systémové chybě.",
                errors=[str(e)]
            )
