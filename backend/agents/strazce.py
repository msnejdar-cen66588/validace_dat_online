"""Agent 1: Strazce – Completeness Check (BR-G4).

Validates that the photo set meets the mandatory documentation requirements
for RD (rodinný dům) property valuation per SEMAFOR methodology:

1) Aktuální barevné fotografie (min. 9):
   - 6 blokujících kategorií: čelní exteriér, zadní/boční exteriér, vstup do domu,
     hlavní obytná místnost, kuchyň, koupelna
   - Eskalační kategorie (WARN): pozemek/zahrada, technické zázemí, garáž/vedlejší stavby

2) Stáří fotografií — 3 pásma:
   - <90 dní = PASS
   - 90–180 dní = WARN
   - >180 dní = FAIL (chybí datum = FAIL)

3) Kvalita fotografií:
   - Rozlišení min. 1280×720
   - Detekce rozmazání (Laplacian variance)
   - Detekce tmavosti / přesvětlení
   - >30% nekvalitních = FAIL, 10–30% = WARN
"""
import json
import os
import numpy as np
from datetime import datetime
from PIL import Image
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import (
    GEMINI_API_KEY, GEMINI_MODEL,
    PHOTO_AGE_FAIL_DAYS, PHOTO_AGE_WARN_DAYS,
    PHOTO_QUALITY_FAIL_PERCENT, PHOTO_QUALITY_WARN_PERCENT,
    MIN_PHOTO_WIDTH, MIN_PHOTO_HEIGHT,
    MIN_BLUR_SCORE, MIN_BRIGHTNESS, MAX_BRIGHTNESS,
    MIN_TOTAL_PHOTOS,
)

GUARDIAN_SYSTEM_PROMPT = """Jsi expert na validaci fotografické dokumentace nemovitostí typu Rodinný dům (RD) pro účely bankovního ocenění.

POVINNÁ FOTODOKUMENTACE:
1) Aktuální barevné fotografie:
   a) EXTERIÉR — pohled na dům ze všech světových stran (přední, zadní, boční), pokud je to možné.
      Na alespoň jedné fotce musí být viditelné číslo popisné (CP).
   b) VSTUP DO DOMU — fotografie vstupu/vchodu do domu (hlavní vchodové dveře, předsíň, zádveří).
   c) INTERIÉR — fotografie všech místností:
      - kuchyň, obývací pokoj, ložnice, koupelna, WC, chodba, schodiště, sklep, podkroví a další
   d) VEDLEJŠÍ STAVBY — garáž, stodola, dílna, kůlna apod.
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
- VSTUP_DOMU: Vstup do domu (hlavní vchodové dveře, zádveří, předsíň)
- INTERIER_KUCHYN: Kuchyň nebo kuchyňský kout
- INTERIER_OBYVAK: Obývací pokoj
- INTERIER_LOZNICE: Ložnice / dětský pokoj
- INTERIER_KOUPELNA: Koupelna / WC
- INTERIER_CHODBA: Chodba, schodiště, vstupní hala
- INTERIER_SKLEP: Sklep, suterén
- INTERIER_PODKROVI: Podkroví, půdní prostor – klasifikuj jako podkroví POUZE pokud na fotce vidíš skutečně šikmé/zkosené stropy sledující tvar střechy (strop se snižuje ke stěnám). POZOR: širokoúhlý objektiv deformuje okraje fotky a rovné stropy se mohou jevit jako zkosené – to NENÍ podkroví! Nízký rovný strop také NENÍ podkroví.
- INTERIER_OSTATNI: Jiné interiérové prostory (šatna, prádelna, technická místnost, garáž zevnitř)
- TECHNICKE_ZAZEMI: Kotelna, technická místnost, prádelna s technikou (bojler, kotel, čerpadlo)
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
    "has_vstup_domu": true/false,
    "has_vedlejsi_stavba_photo": true/false,
    "vedlejsi_stavba_visible": true/false,
    "has_technicke_zazemi": true/false,
    "has_zahrada_pozemek": true/false,
    "interior_rooms_found": ["kuchyň", "obývák", "ložnice", "koupelna", ...],
    "categories_found": ["EXTERIER_PREDNI", ...]
  }
}

DŮLEŽITÉ:
- "vedlejsi_stavba_visible": true pokud na JAKÉKOLI fotce (i exteriérové) vidíš vedlejší stavbu na pozemku.
- "has_vedlejsi_stavba_photo": true pokud existuje samostatná fotka vedlejší stavby.
- "has_vstup_domu": true pokud existuje fotka zachycující vstup do domu (vchodové dveře, zádveří).
- "interior_rooms_found": seznam typů místností, které jsou zdokumentovány.

Odpověz POUZE validním JSON.
"""


def _assess_photo_quality(image_path: str) -> dict:
    """Assess photo quality: resolution, blur (Laplacian), brightness.

    Returns dict with is_low_quality flag and list of quality issues.
    """
    issues = []
    try:
        img = Image.open(image_path)
        w, h = img.size

        # Resolution check
        if w < MIN_PHOTO_WIDTH and h < MIN_PHOTO_WIDTH:
            # Check both orientations (landscape and portrait)
            if (w < MIN_PHOTO_WIDTH or h < MIN_PHOTO_HEIGHT) and (w < MIN_PHOTO_HEIGHT or h < MIN_PHOTO_WIDTH):
                issues.append(f"Nízké rozlišení ({w}×{h}px, min. {MIN_PHOTO_WIDTH}×{MIN_PHOTO_HEIGHT})")

        # Convert to grayscale numpy for blur/brightness
        gray = np.array(img.convert("L"), dtype=np.float64)

        # Blur detection via Laplacian variance
        # Simple Laplacian kernel convolution
        from scipy.ndimage import laplace
        lap = laplace(gray)
        blur_score = lap.var()
        if blur_score < MIN_BLUR_SCORE:
            issues.append(f"Rozmazaná fotografie (ostrost={blur_score:.0f}, min.={MIN_BLUR_SCORE:.0f})")

        # Brightness check
        avg_brightness = gray.mean()
        if avg_brightness < MIN_BRIGHTNESS:
            issues.append(f"Příliš tmavá fotografie (jas={avg_brightness:.0f}, min.={MIN_BRIGHTNESS})")
        elif avg_brightness > MAX_BRIGHTNESS:
            issues.append(f"Přesvětlená fotografie (jas={avg_brightness:.0f}, max.={MAX_BRIGHTNESS})")

    except Exception as e:
        issues.append(f"Nelze ověřit kvalitu: {e}")

    return {
        "is_low_quality": len(issues) > 0,
        "issues": issues,
    }


class StrazceAgent(BaseAgent):
    """Agent 1: Strazce - validates completeness of the photo set per SEMAFOR methodology."""

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

        if total < MIN_TOTAL_PHOTOS:
            self.log(f"Nedostatečný počet fotek: {total} (min. {MIN_TOTAL_PHOTOS})", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary=f"Nedostatečný počet fotografií: {total} (minimum {MIN_TOTAL_PHOTOS})",
                details={"total_photos": total, "are_photos_current": False},
                errors=[f"Počet fotografií ({total}) je příliš nízký pro kompletní dokumentaci RD (min. {MIN_TOTAL_PHOTOS})."],
            )

        # ── EXIF validation — 3-tier per methodology ──
        exif_warnings = []
        exif_errors = []
        are_photos_current = True
        now = datetime.now()

        for img in images:
            meta = img.get("metadata", {})
            cap_date_str = meta.get("capture_date")
            filename = img.get("original_filename", img.get("id", "Neznámý soubor"))

            if not cap_date_str:
                # Chybí datum = FAIL dle metodiky
                exif_errors.append(f"Fotografie '{filename}' neobsahuje EXIF metadata s datem pořízení.")
                are_photos_current = False
                continue

            try:
                cap_date_str = cap_date_str.strip()
                if " " in cap_date_str:
                    cap_date = datetime.strptime(cap_date_str, "%Y:%m:%d %H:%M:%S")
                else:
                    cap_date = datetime.strptime(cap_date_str, "%Y:%m:%d")

                age_days = (now - cap_date).days

                if age_days > PHOTO_AGE_FAIL_DAYS:
                    exif_errors.append(f"Fotografie '{filename}' je starší než {PHOTO_AGE_FAIL_DAYS} dní ({age_days} dní).")
                    are_photos_current = False
                elif age_days > PHOTO_AGE_WARN_DAYS:
                    exif_warnings.append(f"Fotografie '{filename}' je starší než {PHOTO_AGE_WARN_DAYS} dní ({age_days} dní).")
            except ValueError:
                exif_errors.append(f"Nepodařilo se přečíst datum u fotografie '{filename}' ({cap_date_str}).")
                are_photos_current = False

        if exif_errors:
            self.log(f"Fotodokumentace nevyhovuje EXIF podmínkám — {len(exif_errors)} chyb.", "error")
        if exif_warnings:
            self.log(f"EXIF varování: {len(exif_warnings)} fotek staré 90–180 dní.", "warn")

        # ── Photo quality checks (resolution, blur, brightness) ──
        self.log("Kontroluji kvalitu fotografií (rozlišení, ostrost, jas)...", "thinking")
        quality_issues = []
        low_quality_count = 0
        for img in images:
            qr = _assess_photo_quality(img["processed_path"])
            if qr["is_low_quality"]:
                low_quality_count += 1
                filename = img.get("original_filename", img.get("id", "?"))
                for issue in qr["issues"]:
                    quality_issues.append(f"'{filename}': {issue}")

        quality_percent = (low_quality_count / total * 100) if total > 0 else 0
        quality_errors = []
        quality_warnings = []

        if quality_percent > PHOTO_QUALITY_FAIL_PERCENT:
            quality_errors.append(
                f"{low_quality_count} z {total} fotek ({quality_percent:.0f} %) je nekvalitních "
                f"(rozmazané, tmavé nebo nízké rozlišení). Práh: >{PHOTO_QUALITY_FAIL_PERCENT} %."
            )
            self.log(f"FAIL: {quality_percent:.0f}% nekvalitních fotek", "error")
        elif quality_percent > PHOTO_QUALITY_WARN_PERCENT:
            quality_warnings.append(
                f"{low_quality_count} z {total} fotek ({quality_percent:.0f} %) je nekvalitních. "
                f"Doporučeno nahradit nekvalitní fotografie."
            )
            self.log(f"WARN: {quality_percent:.0f}% nekvalitních fotek", "warn")
        else:
            self.log(f"Kvalita fotek OK ({low_quality_count} nekvalitních z {total}).")

        # ── AI classification ──
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
                max_output_tokens=8000,
            )

            ai_result = robust_json_parse(response_text)
            self.log("AI klasifikace přijata.")

            classifications = ai_result.get("classifications", [])
            summary = ai_result.get("summary", {})

            # Derive categories_found from individual classifications if summary is missing/incomplete
            all_cats_from_classifications = set()
            for cl in classifications:
                for cat in cl.get("categories", []):
                    all_cats_from_classifications.add(cat.upper())

            exterior_count = summary.get("exterior_count", 0)
            interior_count = summary.get("interior_count", 0)
            has_cp = summary.get("has_cislo_popisne", False)
            has_front = summary.get("has_front", False)
            has_rear = summary.get("has_rear", False)
            has_side = summary.get("has_side", False)
            has_vstup = summary.get("has_vstup_domu", False)
            vedlejsi_visible = summary.get("vedlejsi_stavba_visible", False)
            has_vedlejsi_photo = summary.get("has_vedlejsi_stavba_photo", False)
            has_technicke = summary.get("has_technicke_zazemi", False)
            has_zahrada = summary.get("has_zahrada_pozemek", False)
            rooms_found = summary.get("interior_rooms_found", [])
            categories = summary.get("categories_found", [])
            # Merge with categories derived from individual classifications (more reliable)
            categories = list(set(categories) | all_cats_from_classifications)

            self.log(f"Ext: {exterior_count}, Int: {interior_count}, ČP: {has_cp}, "
                     f"Přední/Zadní/Boční: {has_front}/{has_rear}/{has_side}, Vstup: {has_vstup}")
            self.log(f"Místnosti: {', '.join(rooms_found) if rooms_found else 'nezjištěno'}, Kategorie: {', '.join(categories)}")

            # ── Evaluate completeness — methodology-aligned ──
            warnings = []
            errors = []

            # Propagate EXIF errors and warnings
            errors.extend(exif_errors)
            warnings.extend(exif_warnings)

            # Propagate quality errors and warnings
            errors.extend(quality_errors)
            warnings.extend(quality_warnings)

            # === 6 BLOKUJÍCÍCH FOTOGRAFIÍ (FAIL pokud chybí) ===

            # 1. Čelní exteriér
            if not has_front:
                errors.append("BLOKUJÍCÍ: Chybí čelní exteriér (přední pohled na dům, fasáda/vchod).")

            # 2. Zadní/boční exteriér
            if not has_rear and not has_side:
                errors.append("BLOKUJÍCÍ: Chybí zadní NEBO boční pohled na dům.")

            # 3. Vstup do domu
            if not has_vstup:
                errors.append("BLOKUJÍCÍ: Chybí fotografie vstupu do domu (vchodové dveře, zádveří).")

            # Check key rooms — BLOCKING per methodology
            rooms_lower = [r.lower() for r in rooms_found]
            rooms_text = " ".join(rooms_lower)
            # Fallback: also scan categories_found (e.g. INTERIER_KUCHYN) when rooms list is empty/incomplete
            categories_text = " ".join(c.lower() for c in categories)

            # 4. Hlavní obytná místnost (obývák/ložnice)
            if not any(k in rooms_text for k in ["obýv", "obyvak", "living", "pokoj", "ložnic"]) and \
               not any(k in categories_text for k in ["obyvak", "loznice", "interier_obyvak", "interier_loznice"]):
                errors.append("BLOKUJÍCÍ: Chybí fotodokumentace hlavní obytné místnosti (obývací pokoj/ložnice).")

            # 5. Kuchyň
            if not any(k in rooms_text for k in ["kuchyň", "kuchyn", "kitchen"]) and \
               not any(k in categories_text for k in ["kuchyn", "kitchen"]):
                errors.append("BLOKUJÍCÍ: Chybí fotodokumentace kuchyně.")

            # 6. Koupelna
            if not any(k in rooms_text for k in ["koupeln", "bathroom", "wc"]) and \
               not any(k in categories_text for k in ["koupelna", "bathroom", "wc"]):
                errors.append("BLOKUJÍCÍ: Chybí fotodokumentace koupelny.")

            # Exterior count check
            if exterior_count < 2:
                errors.append(
                    f"Nedostatečný počet exteriérových fotek: {exterior_count} "
                    "(požadovány pohledy ze všech stran)"
                )

            # Interior count check
            if interior_count < 3:
                errors.append(
                    f"Nedostatečný počet interiérových fotek: {interior_count}. "
                    "Povinné jsou fotografie všech hlavních místností."
                )

            # ČP — eskalační (WARN)
            if not has_cp:
                warnings.append(
                    "Na žádné fotce nebylo detekováno číslo popisné (ČP). "
                    "Alespoň jedna exteriérová fotka by měla zachycovat ČP."
                )

            # === ESKALAČNÍ KATEGORIE (WARN pokud chybí) ===

            # Pozemek/zahrada
            if not has_zahrada:
                warnings.append("Chybí fotodokumentace pozemku/zahrady.")

            # Technické zázemí (kotelna)
            if not has_technicke:
                warnings.append("Chybí fotodokumentace technického zázemí (kotelna, technická místnost).")

            # Vedlejší stavby — only if they exist
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
                f"ČP={'ANO' if has_cp else 'NE'}, "
                f"Vstup={'ANO' if has_vstup else 'NE'}"
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
                    "has_vstup_domu": has_vstup,
                    "vedlejsi_stavba_visible": vedlejsi_visible,
                    "has_vedlejsi_stavba_photo": has_vedlejsi_photo,
                    "has_technicke_zazemi": has_technicke,
                    "has_zahrada_pozemek": has_zahrada,
                    "interior_rooms_found": rooms_found,
                    "categories_found": categories,
                    "are_photos_current": are_photos_current,
                    "photo_quality": {
                        "low_quality_count": low_quality_count,
                        "low_quality_percent": round(quality_percent, 1),
                        "issues": quality_issues[:10],  # cap at 10 to avoid huge payloads
                    },
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
