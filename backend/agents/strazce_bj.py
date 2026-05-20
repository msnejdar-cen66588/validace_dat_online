"""Agent: StrazceBJ – Completeness Check for Bytová jednotka (apartment).

Validates that the photo set meets the mandatory documentation requirements
for BJ (bytová jednotka) property valuation per SEMAFOR methodology:

1) Aktuální barevné fotografie (minimálně 4):
   - Blokující kategorie (FAIL): exteriér budovy, kuchyň, koupelna, hlavní pokoj
   - Eskalační kategorie (WARN): vstup do jednotky, balkón/terasa

2) Stáří fotografií — 3 pásma:
   - <90 dní = PASS
   - 90–180 dní = WARN
   - >180 dní = FAIL (chybí datum = FAIL)

3) Kvalita fotografií:
   - Rozlišení min. 1280×720
   - Detekce rozmazání, tmavosti
   - >30% nekvalitních = FAIL, 10–30% = WARN
"""
import json
import numpy as np
from datetime import datetime
from PIL import Image
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import (
    GEMINI_API_KEY, GEMINI_MODEL, BJ_MIN_TOTAL_PHOTOS,
    PHOTO_AGE_FAIL_DAYS, PHOTO_AGE_WARN_DAYS,
    PHOTO_QUALITY_FAIL_PERCENT, PHOTO_QUALITY_WARN_PERCENT,
    MIN_PHOTO_WIDTH, MIN_PHOTO_HEIGHT,
    MIN_BLUR_SCORE, MIN_BRIGHTNESS, MAX_BRIGHTNESS,
)

GUARDIAN_BJ_SYSTEM_PROMPT = """Jsi expert na validaci fotografické dokumentace nemovitostí typu Bytová jednotka (BJ) pro účely bankovního ocenění.

POVINNÁ FOTODOKUMENTACE PRO BYTOVOU JEDNOTKU:
1) Aktuální barevné fotografie (minimálně 4):
   a) EXTERIÉR BUDOVY — pohled na celou bytovou budovu, ideálně s viditelným číslem popisným (ČP).
   b) VSTUP DO JEDNOTKY — společné prostory domu (chodba, schodiště, výtah) a/nebo vstupní dveře do bytu.
   c) INTERIÉR — fotografie VŠECH místností bytu:
      - kuchyň/kuchyňský kout, obývací pokoj, ložnice, koupelna, WC, chodba, a další
   
   POZNÁMKA: U bytu se NEFOTÍ vedlejší stavby, zahrady ani okolí (na rozdíl od RD).
   Půdorysy nejsou povinné, ale pokud jsou přiloženy, klasifikuj je jako PUDORYS.

KATEGORIE PRO KLASIFIKACI:
- EXTERIER_BUDOVA: Celkový pohled na bytový dům (fasáda, vchod do domu), ideálně s ČP
- EXTERIER_CISLO_POPISNE: Fotografie s viditelným číslem popisným na budově
- VSTUP_JEDNOTKY: Společné prostory (chodba, schodiště, výtah), vstupní dveře bytu
- INTERIER_KUCHYN: Kuchyň nebo kuchyňský kout
- INTERIER_POKOJ: Obývací pokoj, ložnice, dětský pokoj, pracovna
- INTERIER_KOUPELNA: Koupelna / WC
- INTERIER_CHODBA: Chodba bytu, předsíň, vstupní hala bytu
- INTERIER_OSTATNI: Jiné interiérové prostory (šatna, prádelna, komora, sklep bytu)
- BALKON_TERASA: Balkon, terasa, lodžie
- PUDORYS: Půdorys, technický výkres

PRAVIDLA:
1. Jedna fotografie MŮŽE patřit do více kategorií.
2. Pro každou fotku vrať seznam kategorií.
3. V popisu uveď stručně co vidíš.
4. Pokud na exteriérové fotce vidíš číslo popisné, přidej EXTERIER_CISLO_POPISNE.

Vrať JSON:
{
  "classifications": [
    {"photo_id": "xxx", "categories": ["EXTERIER_BUDOVA", "EXTERIER_CISLO_POPISNE"], "description": "Panelový dům s viditelným ČP 1649"}
  ],
  "summary": {
    "total_photos": N,
    "exterior_count": N,
    "interior_count": N,
    "has_cislo_popisne": true/false,
    "has_exterior": true/false,
    "has_vstup_jednotky": true/false,
    "has_balkon_terasa": true/false,
    "interior_rooms_found": ["kuchyň", "pokoj", "koupelna", ...],
    "categories_found": ["EXTERIER_BUDOVA", ...]
  }
}

Odpověz POUZE validním JSON.
"""


def _assess_photo_quality_bj(image_path: str) -> dict:
    """Assess photo quality for BJ: resolution, blur (Laplacian), brightness."""
    issues = []
    try:
        img = Image.open(image_path)
        w, h = img.size

        # Resolution check
        if w < MIN_PHOTO_WIDTH and h < MIN_PHOTO_WIDTH:
            if (w < MIN_PHOTO_WIDTH or h < MIN_PHOTO_HEIGHT) and (w < MIN_PHOTO_HEIGHT or h < MIN_PHOTO_WIDTH):
                issues.append(f"Nízké rozlišení ({w}×{h}px, min. {MIN_PHOTO_WIDTH}×{MIN_PHOTO_HEIGHT})")

        # Convert to grayscale numpy for blur/brightness
        gray = np.array(img.convert("L"), dtype=np.float64)

        # Blur detection
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


class StrazceBJAgent(BaseAgent):
    """Agent 1 (BJ): Strazce - validates completeness of the photo set per SEMAFOR methodology."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="StrazceBJ",
            description="Ověření úplnosti fotografické dokumentace bytu",
            system_prompt=GUARDIAN_BJ_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)

    async def run(self, context: dict) -> AgentResult:
        images = context.get("images", [])
        total = len(images)

        self.log(f"Kontrola úplnosti BJ: {total} fotografií.")

        if total < BJ_MIN_TOTAL_PHOTOS:
            self.log(f"Nedostatečný počet fotek: {total}", "error")
            return AgentResult(
                status=AgentStatus.FAIL,
                summary=f"Nedostatečný počet fotografií: {total} (minimum {BJ_MIN_TOTAL_PHOTOS})",
                details={"total_photos": total, "are_photos_current": False},
                errors=[f"Počet fotografií ({total}) je příliš nízký pro kompletní dokumentaci bytu."],
            )

        # ── EXIF validation — 3-tier per SEMAFOR methodology ──
        exif_warnings = []
        exif_errors = []
        are_photos_current = True
        now = datetime.now()

        for img in images:
            meta = img.get("metadata", {})
            cap_date_str = meta.get("capture_date")
            filename = img.get("original_filename", img.get("id", "Neznámý soubor"))

            if not cap_date_str:
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
            self.log(f"EXIF chyby: {len(exif_errors)} fotek.", "error")
        if exif_warnings:
            self.log(f"EXIF varování: {len(exif_warnings)} fotek staré 90–180 dní.", "warn")

        # ── Photo quality checks ──
        self.log("Kontroluji kvalitu fotografií...", "thinking")
        quality_issues = []
        low_quality_count = 0
        for img in images:
            qr = _assess_photo_quality_bj(img["processed_path"])
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
                f"{low_quality_count} z {total} fotek ({quality_percent:.0f} %) je nekvalitních."
            )
        elif quality_percent > PHOTO_QUALITY_WARN_PERCENT:
            quality_warnings.append(
                f"{low_quality_count} z {total} fotek ({quality_percent:.0f} %) je nekvalitních."
            )

        # ── AI classification ──
        self.log("Klasifikuji fotografie bytové jednotky pomocí AI...", "thinking")

        if not self.client:
            self.log("Gemini API key nenakonfigurován. Používám fallback.", "warn")
            return self._fallback_result(total)

        try:
            from google.genai import types
            parts = [f"Klasifikuj těchto {total} fotografií bytové jednotky:\n"]

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

            # Derive categories from individual classifications (more reliable than summary)
            all_cats_from_classifications = set()
            for cl in classifications:
                for cat in cl.get("categories", []):
                    all_cats_from_classifications.add(cat.upper())

            exterior_count = summary.get("exterior_count", 0)
            interior_count = summary.get("interior_count", 0)
            has_cp = summary.get("has_cislo_popisne", False)
            has_exterior = summary.get("has_exterior", False)
            has_vstup = summary.get("has_vstup_jednotky", False)
            has_balkon = summary.get("has_balkon_terasa", False)
            rooms_found = summary.get("interior_rooms_found", [])
            categories = summary.get("categories_found", [])
            # Merge with categories from individual classifications
            categories = list(set(categories) | all_cats_from_classifications)

            self.log(f"Ext: {exterior_count}, Int: {interior_count}, ČP: {has_cp}, "
                     f"Vstup: {has_vstup}, Balkón: {has_balkon}")
            self.log(f"Místnosti: {', '.join(rooms_found) if rooms_found else 'nezjištěno'}, Kategorie: {', '.join(categories)}")

            # ── Evaluate completeness — SEMAFOR methodology ──
            warnings = []
            errors = []

            # Propagate EXIF errors and warnings
            errors.extend(exif_errors)
            warnings.extend(exif_warnings)

            # Propagate quality errors and warnings
            errors.extend(quality_errors)
            warnings.extend(quality_warnings)

            # === BLOKUJÍCÍ KATEGORIE BJ (FAIL pokud chybí) ===

            # 1. Exteriér budovy
            if not has_exterior:
                errors.append("BLOKUJÍCÍ: Chybí exteriérová fotografie bytového domu.")

            # Check key rooms — BLOCKING per methodology
            rooms_lower = [r.lower() for r in rooms_found]
            rooms_text = " ".join(rooms_lower)
            categories_text = " ".join(c.lower() for c in categories)

            # 2. Hlavní pokoj (obývák/ložnice)
            if not any(k in rooms_text for k in ["pokoj", "obýv", "obyvak", "living", "ložnic"]) and \
               not any(k in categories_text for k in ["pokoj", "obyvak", "loznice", "interier_pokoj"]):
                errors.append("BLOKUJÍCÍ: Chybí fotodokumentace hlavního pokoje (obývací pokoj/ložnice).")

            # 3. Kuchyň
            if not any(k in rooms_text for k in ["kuchyň", "kuchyn", "kitchen", "kuchyňsk"]) and \
               not any(k in categories_text for k in ["kuchyn", "kitchen"]):
                errors.append("BLOKUJÍCÍ: Chybí fotodokumentace kuchyně.")

            # 4. Koupelna
            if not any(k in rooms_text for k in ["koupeln", "bathroom", "wc"]) and \
               not any(k in categories_text for k in ["koupelna", "bathroom", "wc"]):
                errors.append("BLOKUJÍCÍ: Chybí fotodokumentace koupelny.")

            # Interior count check
            if interior_count < 2:
                errors.append(
                    f"Nedostatečný počet interiérových fotek bytu: {interior_count}. "
                    "Povinné jsou fotografie všech místností."
                )

            # === ESKALAČNÍ KATEGORIE BJ (WARN pokud chybí) ===

            # ČP
            if not has_cp:
                warnings.append(
                    "Na žádné fotce nebylo detekováno číslo popisné (ČP). "
                    "Alespoň jedna exteriérová fotka by měla zachycovat ČP."
                )

            # Vstup do jednotky
            if not has_vstup:
                warnings.append(
                    "Chybí fotografie vstupu do bytové jednotky "
                    "(společné prostory, chodba domu, vstupní dveře bytu)."
                )

            # Determine status
            if errors:
                status = AgentStatus.FAIL
            elif warnings:
                status = AgentStatus.WARN
            else:
                status = AgentStatus.SUCCESS

            summary_text = (
                f"Sada {total} fotek bytu: "
                f"Ext={exterior_count}, Int={interior_count}, "
                f"ČP={'ANO' if has_cp else 'NE'}, "
                f"Vstup={'ANO' if has_vstup else 'NE'}"
            )
            if has_balkon:
                summary_text += ", Balkón/terasa=ANO"

            self.log(f"Výsledek: {status.value}")

            # Build image metadata map for frontend
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
                    "has_exterior": has_exterior,
                    "has_vstup_jednotky": has_vstup,
                    "has_balkon_terasa": has_balkon,
                    "interior_rooms_found": rooms_found,
                    "categories_found": categories,
                    "are_photos_current": are_photos_current,
                    "photo_quality": {
                        "low_quality_count": low_quality_count,
                        "low_quality_percent": round(quality_percent, 1),
                        "issues": quality_issues[:10],
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
