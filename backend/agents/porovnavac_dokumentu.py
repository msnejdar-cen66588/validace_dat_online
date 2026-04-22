"""Agent: PorovnavacDokumentu – porovnání dat z PDF formuláře s fotodokumentací.

Sends property data (from PDF or manual input) alongside uploaded photos to Gemini,
which evaluates whether the photos match the declared property characteristics.
"""
import json
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import GEMINI_API_KEY, GEMINI_MODEL

COMPARATOR_SYSTEM_PROMPT = """Jsi expertní odhadce nemovitostí a stavební inženýr. Tvým úkolem je na základě fotodokumentace křížově ověřit údaje z dotazníku klienta. Zaměř se na extrémně přesný odhad podlahové plochy a počtu podlaží.

Dostaneš:
1. Údaje z formuláře (JSON): stav domu, počet podlaží, typ střechy, podsklepení, celková podlahová plocha, vytápění, rok dokončení, podkroví
2. Fotografie nemovitosti (kombinace exteriéru a interiéru)

Následuj tyto přesné postupy:

═══════════════════════════════════════════════════════════════
1. **POČET PODLAŽÍ A PODKROVÍ (Křížová kontrola exteriér vs. interiér)**
═══════════════════════════════════════════════════════════════
Musíš perfektně určit, kolik má dům reálných obytných podlaží.

DETEKCE OBYTNÉHO PODKROVÍ – PŘÍSNÝ 3-BODOVÝ TEST:
Obytné podkroví smíš potvrdit POUZE pokud jsou splněny VŠECHNY TŘI podmínky současně:
  ✅ PODMÍNKA 1 (Interiér): Na interiérových fotkách horního patra vidíš SKUTEČNÉ šikmé/zkosené stropy, které sledují tvar střechy. Strop se musí snižovat směrem ke stěnám.
  ✅ PODMÍNKA 2 (Exteriér – tvar střechy): Dům má z exteriéru sedlovou, mansardovou nebo valbovou střechu, která umožňuje obytný prostor pod sebou.
  ✅ PODMÍNKA 3 (Exteriér – okna v podkroví): Na střeše nebo ve štítu jsou viditelná střešní okna (velux), vikýře nebo štítová okna. BEZ viditelných oken ve střeše/štítu podkroví NEPOTVRZUJ.

Pokud JAKÁKOLIV z těchto 3 podmínek NENÍ splněna → podkroví NEPOTVRZUJ, považuj horní patro za plné nadzemní podlaží (nebo za neobytnou půdu).

ČASTÉ FALEŠNÉ DETEKCE – DÁVEJ SI POZOR:
  ❌ ŠIROKOÚHLÝ OBJEKTIV: Rovné stropy se na okrajích interiérových fotek širokoúhlým objektivem často jeví jako zkosené. Pokud jsou stropy zkosené JEN na okrajích fotky, ale uprostřed rovné → NENÍ to podkroví, je to optická deformace.
  ❌ PLNÉ 2NP s rovným stropem: Pokud z exteriéru vidíš 2 řady normálních oken nad sebou s plnými stěnami → je to plné 2. nadzemní podlaží, NE podkroví. I kdyby interiér vypadal „zkoseně" kvůli optice.
  ❌ VALBOVÁ STŘECHA BEZ OKEN: Valbová střecha sama o sobě NEZNAMENÁ podkroví. Bez střešních oken a bez viditelných šikmých stropů uvnitř jde o neobytnou půdu.
  ❌ NÍZKÝ STROP ≠ ŠIKMÝ STROP: Některé domy mají v horním patře nižší stropy, ale rovné. To NENÍ podkroví.

- POČÍTÁNÍ ZVENKU:
  - 1 řada normálních oken = 1. nadzemní podlaží (1NP, přízemí).
  - 2 řady nad sebou = 1NP + 2NP (plné patro bez šikmin).
  - Okna ve štítu nebo ve střeše = obytné podkroví (pouze pokud splňuje 3-bodový test).
  - Okna nízko u země = suterén/sklep.

═══════════════════════════════════════════════════════════════
2. **PROFESIONÁLNÍ ODHAD PODLAHOVÉ PLOCHY (m²)**
═══════════════════════════════════════════════════════════════
Očekává se precizní výpočetní úvaha. Aplikuj tento algoritmus:
  A) Odhadni půdorysné rozměry z exteriéru. Použij stavební moduly (okno ~1,5m, dveře ~0,9m). Zkus odhadnout délku a šířku domu (např. 10 x 12 metrů).
  B) Vypočítej hrubou zastavěnou plochu jednoho podlaží (např. 120 m²).
  C) Odpočítej 20 % na obvodové a vnitřní zdi = čistá plocha 1NP (např. 120 * 0.8 = 96 m²).
  D) Vynásob počtem plných nadzemních podlaží (pokud má dům plné 2NP, je to 96 * 2 = 192 m²).
  E) Pokud má dům podkroví (potvrzené 3-bodovým testem), kvůli šikminám se počítá jen cca 60 % čisté plochy přízemí (např. 96 * 0.6 = 57 m²).
  F) Sečti zjištěné plochy podlaží do celkové odhadované podlahové plochy (např. 96 + 57 = 153 m²).
Porovnej tvůj vypočítaný odhad s deklarovanou "celkovou podlahovou plochou" od klienta. Pokud se klientův údaj vejde do tvého odhadu s odchylkou +/- 25 %, považuj to za SHODU (jde o vizuální odhad). V poli "note" uveď svůj matematický postup krok za krokem.

3. **Typ střechy** – Shoduje se exteriér s formulářem? (sedlová, valbová, rovná, atd.)

═══════════════════════════════════════════════════════════════
4. **STAV DOMU (Povinná kombinace interiéru + exteriéru)**
═══════════════════════════════════════════════════════════════
Stav domu MUSÍŠ hodnotit jako KOMBINACI exteriéru i interiéru – nikdy se nezaměřuj pouze na jedno!
  - EXTERIÉR: Stav fasády, střechy, oken, okapů, soklu, vstupních dveří, viditelných trhlin.
  - INTERIÉR: Stav podlah, stěn, stropů, kuchyně, koupelny, dveří, elektroinstalace.
  - VÝSLEDNÝ STAV = horší z obou hodnocení. Pokud je exteriér ve výborném stavu, ale interiér vykazuje vlhkost nebo zastaralé rozvody, celkový stav NENÍ výborný.
  - V poli "observed" uveď: "Exteriér: [hodnocení]. Interiér: [hodnocení]. Celkově: [finální hodnocení]."
  - V poli "note" vysvětli, proč je celkový stav takový – jaké konkrétní prvky z exteriéru a interiéru to ovlivnily.
5. **Podsklepení** – Vidíš zvenku suterénní okna, nebo je dům evidentně ve svahu a má spodní patro?
6. **Typ vytápění** – Viditelné prvky (komín, radiátory, kotel, podlahové vytápění, čerpadlo)?

═══════════════════════════════════════════════════════════════
7. **PODKROVÍ (Povinný samostatný check)**
═══════════════════════════════════════════════════════════════
Vždy proveď 3-bodový test (viz bod 1) a výsledek zapiš do samostatného checku.
  - V "observed" uveď: "Podmínka 1 (šikmé stropy): [ANO/NE]. Podmínka 2 (sedlová/mansardová střecha): [ANO/NE]. Podmínka 3 (okna ve střeše/štítu): [ANO/NE]. Závěr: [obytné podkroví ANO/NE]."
  - "match" = true pokud se tvůj závěr shoduje s deklarací klienta.
  - V "note" vysvětli konkrétně, co na fotkách vidíš/nevidíš pro každou podmínku.

Vrať výsledek POUZE jako validní JSON:
{
  "verdict": "SHODA" | "ČÁSTEČNÁ_SHODA" | "NESHODA",
  "confidence": 0.0-1.0,
  "overall_summary": "Celkové shrnutí porovnání...",
  "checks": [
    {
      "field": "počet podlaží",
      "declared": "hodnota z formuláře",
      "observed": "co je vidět na fotkách (křížové ověření zvenku)",
      "match": true/false,
      "note": "Analýza exteriér vs. interiér, vyvrácení případných falešných šikmin."
    },
    {
      "field": "celková podlahová plocha",
      "declared": "hodnota z formuláře v m²",
      "observed": "tvůj odhad v m²",
      "match": true/false,
      "note": "Matematický výpočet plochy podle bodů A-F."
    },
    {
      "field": "typ střechy",
      "declared": "...",
      "observed": "...",
      "match": true,
      "note": "..."
    },
    {
      "field": "stav domu",
      "declared": "výborně udržovaný",
      "observed": "Exteriér: výborný (nová fasáda, plastová okna). Interiér: dobrý (funkční, ale starší kuchyně). Celkově: dobrý.",
      "match": false,
      "note": "Exteriér je bezchybný, ale interiér vykazuje známky opotřebení kuchyňské linky a starších obkladů v koupelně, proto celkový stav hodnotím jako dobrý, nikoliv výborný."
    },
    {
      "field": "podsklepení",
      "declared": "...",
      "observed": "...",
      "match": true,
      "note": "..."
    },
    {
      "field": "typ vytápění",
      "declared": "...",
      "observed": "...",
      "match": true,
      "note": "..."
    },
    {
      "field": "podkroví",
      "declared": "ANO/NE (z formuláře)",
      "observed": "Podmínka 1 (šikmé stropy): ANO/NE. Podmínka 2 (sedlová střecha): ANO/NE. Podmínka 3 (střešní okna): ANO/NE. Závěr: obytné podkroví ANO/NE.",
      "match": true/false,
      "note": "Detailní zdůvodnění na základě 3-bodového testu."
    }
  ],
  "warnings": ["Varování..."],
  "recommendations": ["Doporučení..."]
}
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
