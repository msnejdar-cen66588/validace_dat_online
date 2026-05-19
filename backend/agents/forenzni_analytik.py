"""Agent 2: ForenzniAnalytik – Manipulation Detection (BR-G5).

Detects AI edits, retouching, and metadata inconsistencies:
- Calculates manipulation_score and confidence
- FAIL when score > threshold AND confidence > threshold
- Analyzes local artifacts, metadata mismatches, AI generation
"""
import json
import asyncio
from agents.base import BaseAgent, AgentResult, AgentStatus
from agents.llm_utils import LLMClient, robust_json_parse
from config import (
    GEMINI_API_KEY, GEMINI_MODEL,
    MANIPULATION_SCORE_FAIL, MANIPULATION_SCORE_WARN,
    MANIPULATION_SCORE_THRESHOLD, CONFIDENCE_THRESHOLD,
    GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_CREDENTIALS_JSON, BLOCKED_DOMAINS
)

FORENSIC_SYSTEM_PROMPT = """Jsi forenzní expert na analýzu fotografií nemovitostí. Tvým úkolem je detekovat jakékoliv manipulace, AI úpravy, retuše nebo nesrovnalosti.

ANALYZUJ KAŽDOU FOTOGRAFII NA:
1. **AI Generování**: Je foto generované umělou inteligencí? (podivné textury, nereálné odrazy, anomálie v detailech)
2. **Retuše a Úpravy**: Byly odstraněny nebo přidány objekty? (klonování, healing, content-aware fill)
3. **Lokální Artefakty**: Skoky v kompresi, nekonzistentní šum, blur/sharpen anomálie
4. **Metadata Nesoulad**: Nesoulad mezi vizuálním obsahem a metadaty (osvětlení vs. čas pořízení, GPS vs. zobrazený prostor)
5. **Manipulace Perspektivy**: Zkreslení perspektivy, nereálné úhly, postprodukční korekce
6. **Původ Fotografie**: Jsou fotografie stažené z internetu (např. vodoznaky, specifické kompresní artefakty pro web, loga portálů, zejména sreality.cz)?

PRO KAŽDOU FOTOGRAFII VRAŤ:
- manipulation_score: 0.0-1.0 (0 = žádná manipulace, 1 = jasná manipulace)
- confidence: 0.0-1.0 (jak si jsi jistý svým hodnocením)
- findings: seznam nalezených problémů

VRAŤ JSON:
{
  "photos": [
    {
      "photo_id": "xxx",
      "manipulation_score": 0.15,
      "confidence": 0.85,
      "is_ai_generated": false,
      "is_downloaded_from_internet": false,
      "findings": ["Mírná úprava jasu", "Žádné známky klonování"],
      "risk_level": "low"
    }
  ],
  "overall": {
    "avg_manipulation_score": 0.15,
    "max_manipulation_score": 0.3,
    "avg_confidence": 0.85,
    "flagged_count": 0,
    "summary": "Sada fotek nevykazuje známky významné manipulace."
  }
}

risk_level: "low" (score < 0.3), "medium" (0.3-0.6), "high" (0.6-0.8), "critical" (>0.8)

Odpověz POUZE validním JSON.
"""


class ForenzniAnalytikAgent(BaseAgent):
    """Agent 2: ForenzniAnalytik - detects manipulation and AI edits."""

    def __init__(self, model_name: str = "gemini"):
        super().__init__(
            name="ForenzniAnalytik",
            description="Detekce AI úprav a manipulací (BR-G5)",
            system_prompt=FORENSIC_SYSTEM_PROMPT,
            model_name=model_name
        )
        self.client = LLMClient(model_name=model_name)
        self.vision_client = None
        
        try:
            if GOOGLE_CREDENTIALS_JSON:
                from google.cloud import vision
                from google.oauth2 import service_account
                creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
                credentials = service_account.Credentials.from_service_account_info(creds_dict)
                self.vision_client = vision.ImageAnnotatorClient(credentials=credentials)
                self.log("Google Cloud Vision klient inicializován z JSON řetězce.")
            elif GOOGLE_APPLICATION_CREDENTIALS:
                from google.cloud import vision
                self.vision_client = vision.ImageAnnotatorClient()
                self.log("Google Cloud Vision klient inicializován ze souboru.")
        except ImportError:
            self.log("google-cloud-vision není nainstalováno – web detection přeskočeno.", "warn")
        except Exception as e:
            self.log(f"Nepodařilo se inicializovat Google Cloud Vision: {e}", "warn")

    async def _check_web_detection(self, image_path: str, photo_id: str) -> dict:
        """Checks if the image exists on blocked domains using Google Cloud Vision."""
        if not self.vision_client:
            return {"photo_id": photo_id, "found_on_blocked_domain": False, "details": []}
            
        try:
            from google.cloud import vision
            with open(image_path, "rb") as image_file:
                content = image_file.read()

            image = vision.Image(content=content)
            
            # Run vision API in a separate thread since it's blocking
            response = await asyncio.to_thread(
                self.vision_client.web_detection,
                image=image
            )
            
            web_detection = response.web_detection
            blocked_matches = []
            
            if web_detection.pages_with_matching_images:
                for page in web_detection.pages_with_matching_images:
                    url = page.url.lower()
                    for blocked_domain in BLOCKED_DOMAINS:
                        if blocked_domain in url:
                            blocked_matches.append(url)
                            
            if web_detection.full_matching_images:
                for image_match in web_detection.full_matching_images:
                    url = image_match.url.lower()
                    for blocked_domain in BLOCKED_DOMAINS:
                        if blocked_domain in url:
                            blocked_matches.append(url)
            
            return {
                "photo_id": photo_id, 
                "found_on_blocked_domain": len(blocked_matches) > 0, 
                "details": blocked_matches[:3] # keep only first 3 matches to avoid huge logs
            }
                
        except Exception as e:
            self.log(f"Web detection selhala pro foto {photo_id}: {e}", "error")
            return {"photo_id": photo_id, "found_on_blocked_domain": False, "details": []}

    async def run(self, context: dict) -> AgentResult:
        images = context.get("images", [])
        self.log(f"Analyzing {len(images)} images for manipulation.")

        if not self.client:
            self.log("Gemini API key not configured. Using fallback.", "warn")
            return AgentResult(
                status=AgentStatus.WARN,
                summary="Forenzní analýza nedostupná (chybí API klíč)",
                warnings=["AI analýza nedostupná."],
            )

        try:
            from google.genai import types
            self.log("Sending images for forensic analysis...", "thinking")
            
            # 1. Run Web Detection in parallel for all images if enabled
            web_detection_results = {}
            if self.vision_client:
                self.log("Spouštím Web Detection pro hledání fotografií na internetu...")
                tasks = [self._check_web_detection(img["processed_path"], img["id"]) for img in images]
                results = await asyncio.gather(*tasks)
                for res in results:
                    web_detection_results[res["photo_id"]] = res
            
            # 2. Prepare Gemini prompt
            metadata_info = []
            for img in images:
                meta = img.get("metadata", {})
                metadata_info.append({
                    "photo_id": img["id"],
                    "capture_date": meta.get("capture_date"),
                    "device_model": meta.get("device_model"),
                    "gps": f"{meta.get('gps_latitude')}, {meta.get('gps_longitude')}" if meta.get("gps_latitude") else None,
                })

            parts = [
                f"Analyzuj těchto {len(images)} fotografií na manipulace. Metadata:\n{json.dumps(metadata_info, indent=2, ensure_ascii=False)}\n"
            ]

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
            self.log("ForenzniAnalytik analysis received.", "info")

            # Parse results
            overall = ai_result.get("overall", {})
            photos = ai_result.get("photos", [])
            
            warnings = []
            errors = []
            max_score = overall.get("max_manipulation_score", 0)

            # Check for critical manipulations and Web Detection matches
            for photo in photos:
                photo_id = photo.get("photo_id")
                score = photo.get("manipulation_score", 0)
                confidence = photo.get("confidence", 0)
                
                # Verify web detection result
                web_res = web_detection_results.get(photo_id, {})
                if web_res.get("found_on_blocked_domain"):
                    # Force critical failure if found on blocked domains
                    photo["manipulation_score"] = 1.0
                    photo["confidence"] = 1.0
                    photo["is_downloaded_from_internet"] = True
                    photo["findings"].append(f"FOTOGRAFIE NALEZENA NA ZAKÁZANÝCH DOMÉNÁCH: {', '.join(web_res['details'])}")
                    photo["risk_level"] = "critical"
                    errors.append(f"Photo {photo_id}: Extrémní riziko – fotografie byla stažena z internetu (nalezena shoda na portálech).")
                    max_score = 1.0
                    overall["flagged_count"] = overall.get("flagged_count", 0) + 1
                    continue
                
                # SEMAFOR methodology: >=0.9 = FAIL, 0.3-0.89 = WARN
                if score >= MANIPULATION_SCORE_FAIL:
                    errors.append(
                        f"Photo {photo_id}: manipulation_score={score:.2f} – "
                        f"překročen blokující práh manipulace (≥{MANIPULATION_SCORE_FAIL})"
                    )
                elif score >= MANIPULATION_SCORE_WARN:
                    warnings.append(
                        f"Photo {photo_id}: podezření na manipulaci (score={score:.2f}, práh eskalace ≥{MANIPULATION_SCORE_WARN})"
                    )

            overall["max_manipulation_score"] = max_score
            if errors:
                overall["summary"] = "Nalezena kritická rizika u nahraných fotografií (manipulace nebo stažení z portálů)."

            status = AgentStatus.FAIL if errors else (AgentStatus.WARN if warnings else AgentStatus.SUCCESS)

            self.log(f"ForenzniAnalytik result: {status.value} – flagged: {overall.get('flagged_count', 0)}, max_score: {max_score:.2f}")

            return AgentResult(
                status=status,
                score=max_score,
                summary=overall.get("summary", f"Max manipulation score: {max_score:.2f}"),
                details={
                    "photos": photos,
                    "overall": overall,
                },
                warnings=warnings,
                errors=errors,
            )

        except Exception as e:
            self.log(f"ForenzniAnalytik analysis error: {str(e)}", "error")
            return AgentResult(
                status=AgentStatus.WARN,
                summary=f"Chyba forenzní analýzy: {str(e)}",
                warnings=[f"Analýza selhala: {str(e)}"],
            )

