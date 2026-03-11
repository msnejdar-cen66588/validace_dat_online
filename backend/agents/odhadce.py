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


VALUATION_PROMPT = """Jsi expertní AI agent pro online oceňování rezidenčních nemovitostí (rodinných domů) porovnávací metodou podle standardů bankovních institucí v ČR.
Striktně dodržuj profesionální terminologii certifikovaného bankovního odhadce (např. obvyklá cena, oceňovaná nemovitost, srovnávací vzorek, index odlišnosti, redukce pramene ceny).

TVŮJ ÚKOL:
Na základě dodaných parametrů konkrétního rodinného domu (velikost, stav, adresa/lokalita) vypracuj odhad jeho obvyklé tržní ceny (NHZP) pomocí POROVNÁVACÍ METODY s využitím 8 koeficientů (K1 až K8).
Vytvoříš ze svých obsáhlých znalostí realitního trhu v ČR a na základě vyhledávání na internetu 3 vysoce realistické aktuální nabídky podobných domů ve stejné nebo velmi podobné lokalitě.

METODIKA a KROK 1:
1. Vyhledej na internetu (sreality.cz, bezrealitky.cz, idnes reality atd.) 3 konkrétní reálné vzorky (aktuální ceníkové nabídky rodinných domů) pro srovnání.
   - U každého vzorku MUSÍŠ doplnit pole "zdroj_url", které bude odkazovat na konkrétní inzerát nebo zdroj na internetu.
   - U každého vzorku doplň "obrazek_url" tak, že se pokusíš získat odkaz na náhledovou fotografii inzerátu z vyhledávání. Pokud nelze skutečnou fotku z inzerátu získat, vlož "https://loremflickr.com/600/400/house,exterior?lock={id}".
   - Jednotková cena (Kč/m2) oceňované nemovitosti nesmí být nikdy vyšší než cena inzerovaná u totožného objektu.

KROK 2: APLIKACE KOREKČNÍCH KOEFICIENTŮ (K1 až K8)
U každého vzorku stanovíš 8 koeficientů. Pokud jsou vlastnosti totožné s naším domem, K = 1.00. Pokud se srovnávací vzorek jeví LEPŠÍ než náš dům, použij K < 1.00. Pokud se vzorek jeví HORŠÍ, použij K > 1.00. (Koeficienty zapisuj ve formátu např. 0.85, 1.05 - NIKDY jako celá čísla 85 nebo procenta).
- K1 (Redukce pramene ceny): 0.70 až 1.00 (typicky 0.85 pro inzerci).
- K2 (Velikost objektu): Poměr velikosti (zde dej 1.00, velikost zohledníme přes metry čtvereční na frontendu).
- K3 (Poloha): 0.90 až 1.10. Zohledňuje okolí a dostupnost.
- K4 (Provedení a vybavení): 0.80 až 1.20. Materiály a konstrukce.
- K5 (Celkový stav): 0.22 až 1.50. Opotřebení, stáří, investice.
- K6 (Vliv pozemku): Cizí pozemek = 0.85, vlastní do 1.5x zastavěné plochy = 1.00, větší pozemky prémie dle poměru (1.05 až 1.20).
- K7 (Úvaha zpracovatele): 0.80 až 1.20. Přístup, břemena, rizika (většinou 1.00).
- K8 (Energetická náročnost): 0.80 až 1.20. Horší energetická třída vzorku = K > 1.00.

Vrať POUZE striktně formátovaný JSON podle této struktury, nic jiného:
{
  "zakladni_odhad_czk": 8500000,
  "duvod_odhadu": "Profesionální odůvodnění zjištěné obvyklé ceny, stručná analýza trhu v dané lokalitě a komentář zpracovatele k výběru srovnávacích vzorků.",
  "vzorky": [
    {
      "id": 1,
      "adresa": "Ulička 12, Město",
      "velikost_domu_m2": 150,
      "velikost_pozemku_m2": 600,
      "stav": "Po řečné rekonstrukci",
      "cena_czk": 8800000,
      "zdroj_url": "https://www.sreality.cz/detail/prodej/dum/rodinny/...",
      "obrazek_url": "https://d18-a.sdn.cz/d_18/c_img_....jpeg",
      "koeficienty": {
        "k1": 0.85, "k2": 1.00, "k3": 1.05, "k4": 1.00, "k5": 0.90, "k6": 1.00, "k7": 1.00, "k8": 1.00
      },
      "oduvodneni_koeficientu": "Profesionální zdůvodnění odlišností: Vzorek 1 je po nedávné rekonstrukci (k5=0.90) a má objektivně lepší polohu (k3=1.05)."
    }
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

        # Overrides from frontend if user edited the inputs manually
        overrides = context.get("valuation_overrides") or {}
        address = overrides.get("adresa") or address
        floor_area = overrides.get("plocha") or floor_area
        condition = overrides.get("stav") or condition
        land_area = overrides.get("pozemek") or prop_data.get("plocha_pozemku") or "Neznámá"

        prompt_text = (
            f"Parametry analyzované nemovitosti:\n"
            f"- Adresa: {address}\n"
            f"- Podlahová/Užitná plocha: {floor_area}\n"
            f"- Plocha pozemku: {land_area}\n"
            f"- Stav: {condition}\n"
            f"- Střecha: {roof}\n"
            f"- Vytápění: {heating}\n\n"
            f"Nyní prosím vypracuj odhad a 3 vzorky podle instrukcí."
        )

        try:
            self.log("Generuji odhad a porovnávací vzorky...", "thinking")
            # We must remove response_mime_type="application/json" because Gemini 
            # currently does not support controlled generation (JSON mode) coupled with the Search tool.
            prompt_text += "\n\nDŮLEŽITÉ: Tvá odpověď musí být POUZE validní čistý JSON objekt bez jakéhokoliv dalšího textu nebo Markdown formátování (žádné ```json ... ```)."
            
            response = await self.client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt_text,
                config=types.GenerateContentConfig(
                    system_instruction=self.system_prompt,
                    max_output_tokens=1500,
                    tools=[{"google_search": {}}],
                ),
            )

            # In case LLM still wraps in markdown
            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
            raw_text = raw_text.strip()

            result_json = json.loads(raw_text)
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
            import traceback
            tb = traceback.format_exc()
            print(f"Exception from gemini: {tb}")
            self.log(f"Chyba při tvorbě odhadu:\n{tb}", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary="Odhad se nepodařilo dokončit kvůli systémové chybě.",
                errors=[str(e)]
            )
