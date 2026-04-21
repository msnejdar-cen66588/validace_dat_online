"""Agent 1: Strazce – Completeness Check (BR-G4).

Validates that the photo set meets the mandatory documentation requirements
for RD (rodinný dům) property valuation:

1) Aktuální barevné fotografie:
   - Exteriér domu s číslem popisným, pohled ze všech světových stran (pokud možné)
   - Interiér všech místností (kuchyň, pokoje, koupelna, chodba a další)
   - Vedlejší stavby (garáž, stodola apod.) — POUZE pokud existují

2) Dokumentace půdorysů (nepovinné, bonus pokud je k dispozici)
"""
import json
from datetime import datetime
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import GEMINI_API_KEY, GEMINI_MODEL

GUARDIAN_SYSTEM_PROMPT = """Jsi expert na validaci fotografické dokumentace nemovitostí typu Rodinný dům (RD) pro účely bankovního ocenění.

POVINNÁ FOTODOKUMENTACE:
1) Aktuální barevné fotografie:
   a) EXTERIÉR — pohled na dům ze všech světových stran (přední, zadní, boční), pokud je to možné.
      Na alespoň jedné fotce musí být viditelné číslo popisné (CP).
   b) INTERIÉR — fotografie všech místností:
      - kuchyň, obývací pokoj, ložnice, koupelna, WC, chodba, schodiště, sklep, podkroví a další
   c) VEDLEJŠÍ STAVBY — garáž, stodola, dílna, kůlna apod.
      Vedlejší stavby se fotí POUZE pokud na pozemku existují.
      Pokud na žádné fotce ani z exteriéru nevidíš vedlejší stavby, nepovažuj to za chybu.

   POZNÁMKA: Půdorysy/projektová dokumentace NEJSOU povinné. Pokud jsou přiloženy, klasifikuj je jako PUDORYS, ale jejich absence není chyba.

2) Dokumentace půdorysů — projektová dokumentace, studie, půdorysy s rozměry
   (nemusí být fotografie, může to být PDF s technickými výkresy)

KATEGORIE PRO KLASIFIKACI:
- EXTERIER_PREDNI: Přední pohled na dům (fasáda, vchod), ideálně s číslem popisným
- EXTERIER_ZADNI: Zadní pohled na dům (ze zahrady/dvora)
- EXTERIER_BOCNI: Boční pohled na dům
- EXTERIER_DETAIL: Detail exteriéru (střecha, okna, fasáda zblízka, sokl)
- EXTERIER_CISLO_POPISNE: Fotografie s viditelným číslem popisným na domě
- INTERIER_KUCHYN: Kuchyň nebo kuchyňský kout
- INTERIER_OBYVAK: Obývací pokoj
- INTERIER_LOZNICE: Ložnice / dětský pokoj
- INTERIER_KOUPELNA: Koupelna / WC
- INTERIER_CHODBA: Chodba, schodiště, vstupní hala
- INTERIER_SKLEP: Sklep, suterén
- INTERIER_PODKROVI: Podkroví, půdní prostor
- INTERIER_OSTATNI: Jiné interiérové prostory (šatna, prádelna, technická místnost, garáž zevnitř)
- VEDLEJSI_STAVBA: Vedlejší stavba — garáž, stodola, dílna, kůlna, zahradní domek
- OKOLI: Zahrada, příjezdová cesta, okolí domu, pohled na pozemek
- PUDORYS: Půdorys, technický výkres, projektová dokumentace

PRAVIDLA:
1. Jedna fotografie MŮŽE patřit do více kategorií (např. kuchyň s jídelním koutem = INTERIER_KUCHYN + INTERIER_OBYVAK).
2. Pro každou fotku vrať seznam kategorií, do kterých spadá.
3. V popisu uveď stručně co vidíš na fotce.
4. Pokud na exteriérové fotce vidíš číslo popisné, přidej kategorii EXTERIER_CISLO_POPISNE.
5. Pokud na fotce vidíš vedlejší stavbu (i na pozadí exteriéru), přidej VEDLEJSI_STAVBA.

Vrať JSON:
{
  "classifications": [
    {"photo_id": "xxx", "categories": ["EXTERIER_PREDNI", "EXTERIER_CISLO_POPISNE"], "description": "Přední pohled na RD s viditelným ČP 425"}
  ],
  "summary": {
    "total_photos": N,
    "exterior_count": N,
    "interior_count": N,
    "has_cislo_popisne": true/false,
    "has_front": true/false,
    "has_rear": true/false,
    "has_side": true/false,
    "has_vedlejsi_stavba_photo": true/false,
    "vedlejsi_stavba_visible": true/false,
    "interior_rooms_found": ["kuchyň", "obývák", "ložnice", "koupelna", ...],
    "categories_found": ["EXTERIER_PREDNI", ...]
  }
}

DŮLEŽITÉ:
- "vedlejsi_stavba_visible": true pokud na JAKÉKOLI fotce (i exteriérové) vidíš vedlejší stavbu na pozemku.
- "has_vedlejsi_stavba_photo": true pokud existuje samostatná fotka vedlejší stavby.
- "interior_rooms_found": seznam typů místností, které jsou zdokumentovány (nemusí být česky, stačí klíčová slova).

Odpověz POUZE validním JSON.
"""


class StrazceAgent(BaseAgent):
    """Agent 1: Strazce - validates completeness of the photo set."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="Strazce",
            description="Ověření úplnosti fotografické dokumentace (BR-G4)",
            system_prompt=GUARDIAN_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        images = context.get("images", [])
        total = len(images)

        self.log(f"Kontrola úplnosti: {total} fotografií.")

        if total < 5:
            self.log(f"Nedostatečný počet fotek: {total}", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary=f"Nedostatečný počet fotografií: {total} (minimum ~9)",
                details={"total_photos": total},
                errors=[f"Počet fotografií ({total}) je příliš nízký pro kompletní dokumentaci RD."],
            )

        # ── EXIF validation (must be < 3 months old, must exist) ──
        exif_errors = []
        now = datetime.now()
        for img in images:
            meta = img.get("metadata", {})
            cap_date_str = meta.get("capture_date")
            filename = img.get("original_filename", img.get("id", "Neznámý soubor"))
            
            if not cap_date_str:
                exif_errors.append(f"Fotografie '{filename}' neobsahuje EXIF metadata s datem pořízení.")
                continue
                
            try:
                cap_date_str = cap_date_str.strip()
                if " " in cap_date_str:
                    cap_date = datetime.strptime(cap_date_str, "%Y:%m:%d %H:%M:%S")
                else:
                    cap_date = datetime.strptime(cap_date_str, "%Y:%m:%d")
                
                age_days = (now - cap_date).days
                if age_days > 90:
                    exif_errors.append(f"Fotografie '{filename}' je starší než 3 měsíce ({age_days} dní).")
            except ValueError:
                exif_errors.append(f"Nepodařilo se přečíst datum u fotografie '{filename}' ({cap_date_str}).")

        if exif_errors:
            self.log(f"Fotodokumentace nevyhovuje EXIF podmínkám, zapisuji upozornění.", "warn")

        self.log("Klasifikuji fotografie pomocí AI...", "thinking")

        if not self.client:
            self.log("Gemini API key nenakonfigurován. Používám fallback.", "warn")
            return self._fallback_result(total)

        try:
            from google.genai import types
            parts = [f"Klasifikuj těchto {total} fotografií rodinného domu:\n"]

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
            self.log("AI klasifikace přijata.")

            classifications = ai_result.get("classifications", [])
            summary = ai_result.get("summary", {})

            exterior_count = summary.get("exterior_count", 0)
            interior_count = summary.get("interior_count", 0)
            has_cp = summary.get("has_cislo_popisne", False)
            has_front = summary.get("has_front", False)
            has_rear = summary.get("has_rear", False)
            has_side = summary.get("has_side", False)
            vedlejsi_visible = summary.get("vedlejsi_stavba_visible", False)
            has_vedlejsi_photo = summary.get("has_vedlejsi_stavba_photo", False)
            rooms_found = summary.get("interior_rooms_found", [])
            categories = summary.get("categories_found", [])

            self.log(f"Ext: {exterior_count}, Int: {interior_count}, ČP: {has_cp}, "
                     f"Přední/Zadní/Boční: {has_front}/{has_rear}/{has_side}")
            self.log(f"Místnosti: {', '.join(rooms_found) if rooms_found else 'nezjištěno'}")

            # ── Evaluate completeness ──
            warnings = []
            errors = []
            
            if exif_errors:
                warnings.extend(exif_errors)

            # Exterior checks
            if exterior_count < 2:
                errors.append(
                    f"Nedostatečný počet exteriérových fotek: {exterior_count} "
                    "(požadovány pohledy ze všech stran)"
                )

            if not has_cp:
                warnings.append(
                    "Na žádné fotce nebylo detekováno číslo popisné (ČP). "
                    "Alespoň jedna exteriérová fotka by měla zachycovat ČP."
                )

            if not has_front:
                errors.append("Chybí přední pohled na dům (fasáda/vchod).")

            if not has_rear and not has_side:
                warnings.append(
                    "Chybí zadní nebo boční pohled na dům. "
                    "Doporučeno doplnit pohledy ze všech dostupných stran."
                )

            # Interior checks — medium severity, not strict for large houses
            if interior_count < 3:
                errors.append(
                    f"Nedostatečný počet interiérových fotek: {interior_count}. "
                    "Povinné jsou fotografie všech hlavních místností."
                )
            else:
                # Check key rooms
                rooms_lower = [r.lower() for r in rooms_found]
                rooms_text = " ".join(rooms_lower)

                missing_rooms = []
                if not any(k in rooms_text for k in ["kuchyň", "kuchyn", "kitchen"]):
                    missing_rooms.append("kuchyň")
                if not any(k in rooms_text for k in ["koupeln", "bathroom", "wc"]):
                    missing_rooms.append("koupelna")
                if not any(k in rooms_text for k in ["obýv", "obyvak", "living", "pokoj"]):
                    missing_rooms.append("obývací pokoj")

                if missing_rooms:
                    warnings.append(
                        f"Riziko střední: Chybí fotodokumentace místností: "
                        f"{', '.join(missing_rooms)}. "
                        f"U RD s větším počtem místností nemusí být všechny zdokumentovány."
                    )

            # Secondary buildings — only if they exist
            if vedlejsi_visible and not has_vedlejsi_photo:
                warnings.append(
                    "Na exteriérových fotkách je viditelná vedlejší stavba, "
                    "ale chybí její samostatná fotodokumentace."
                )

            # Determine status
            if errors:
                status = AgentStatus.FAIL
            elif warnings:
                status = AgentStatus.WARN
            else:
                status = AgentStatus.SUCCESS

            # Build exterior sides summary
            sides = []
            if has_front:
                sides.append("přední")
            if has_rear:
                sides.append("zadní")
            if has_side:
                sides.append("boční")
            sides_text = ", ".join(sides) if sides else "žádný"

            summary_text = (
                f"Sada {total} fotek: "
                f"Ext={exterior_count} ({sides_text}), "
                f"Int={interior_count} ({len(rooms_found)} typů místností), "
                f"ČP={'ANO' if has_cp else 'NE'}"
            )
            if vedlejsi_visible:
                summary_text += f", Vedlejší stavba={'zdokumentována' if has_vedlejsi_photo else 'nezdokumentována'}"

            self.log(f"Výsledek: {status.value}")

            # Build image metadata map for frontend (GPS, date, device)
            image_metadata = {}
            for img in images:
                img_id = img.get("id", "")
                meta = img.get("metadata", {})
                image_metadata[img_id] = {
                    "original_filename": img.get("original_filename", ""),
                    "gps_latitude": meta.get("gps_latitude"),
                    "gps_longitude": meta.get("gps_longitude"),
                    "capture_date": meta.get("capture_date"),
                    "device_model": meta.get("device_model"),
                }

            return AgentResult(
                status=status,
                summary=summary_text,
                details={
                    "classifications": classifications,
                    "total_photos": total,
                    "exterior_count": exterior_count,
                    "interior_count": interior_count,
                    "has_cislo_popisne": has_cp,
                    "exterior_sides": {"front": has_front, "rear": has_rear, "side": has_side},
                    "vedlejsi_stavba_visible": vedlejsi_visible,
                    "has_vedlejsi_stavba_photo": has_vedlejsi_photo,
                    "interior_rooms_found": rooms_found,
                    "categories_found": categories,
                    "image_metadata": image_metadata,
                },
                warnings=warnings,
                errors=errors,
            )

        except Exception as e:
            self.log(f"Chyba AI klasifikace: {str(e)}", "error")
            return self._fallback_result(total)

    def _fallback_result(self, total: int) -> AgentResult:
        """Fallback when AI is unavailable."""
        return AgentResult(
            status=AgentStatus.WARN,
            summary=f"Počet fotek: {total} (AI klasifikace nedostupná)",
            details={"total_photos": total, "ai_available": False},
            warnings=["AI klasifikace nedostupná – nelze ověřit úplnost dokumentace."],
        )
