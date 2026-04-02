"""Batch Processor – handles upload, classification & sequential processing of multiple valuation cases."""
import asyncio
import gc
import io
import os
import time
import uuid
from typing import Optional

from fastapi import WebSocket
from pypdf import PdfReader

from config import UPLOAD_DIR, SUPPORTED_EXTENSIONS
from preprocessor import ImagePreprocessor
from orchestrator import PipelineOrchestrator
from pdf_parser import parse_pdf
from lv_parser import parse_lv


# ── Filename-based PDF classification ──────────────────────────────────────

def classify_pdf(filename: str) -> str:
    """Classify a PDF by its filename convention.
    Returns 'formular' for client data form, 'lv' for List Vlastnictví, or 'unknown'.
    """
    name_lower = filename.lower()
    if name_lower.startswith("udajeprooceneni"):
        return "formular"
    if name_lower.startswith("list vlastnictv"):
        return "lv"
    # Fallback heuristics
    if "lv" in name_lower and "vlastnictv" in name_lower:
        return "lv"
    if "oceneni" in name_lower or "udaje" in name_lower:
        return "formular"
    return "unknown"


# ── Subfolder grouping from webkitdirectory upload ─────────────────────────

def group_files_by_subfolder(filenames: list[str], file_bytes_map: dict[str, bytes]) -> dict[str, dict]:
    """Group uploaded files by their immediate subfolder.

    webkitdirectory sends relative paths like: 'batch/01/photo.jpg', 'batch/02/lv.pdf'
    We extract the first-level subfolder under the root as the case ID.

    Returns: { subfolder_name: { 'images': [...], 'pdfs': [...] } }
    """
    cases: dict[str, dict] = {}

    for filepath, fbytes in file_bytes_map.items():
        # Normalize path separators
        parts = filepath.replace("\\", "/").split("/")

        # Skip hidden files / __MACOSX
        if any(p.startswith(".") or p.startswith("__") for p in parts):
            continue

        # Determine subfolder name and filename
        if len(parts) >= 3:
            # e.g. "root_folder/01/file.jpg" → subfolder = "01", filename = "file.jpg"
            subfolder = parts[-2]
            filename = parts[-1]
        elif len(parts) == 2:
            # e.g. "01/file.jpg" → subfolder = "01", filename = "file.jpg"
            subfolder = parts[0]
            filename = parts[1]
        else:
            # Single file at root level, skip
            continue

        if not filename or filename.startswith("."):
            continue

        if subfolder not in cases:
            cases[subfolder] = {"images": [], "pdfs": [], "rev_id": subfolder}

        ext = os.path.splitext(filename)[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            cases[subfolder]["images"].append((filename, fbytes))
        elif ext == ".pdf":
            pdf_type = classify_pdf(filename)
            cases[subfolder]["pdfs"].append({
                "filename": filename,
                "bytes": fbytes,
                "type": pdf_type,
            })

    return cases


# ── Batch session management ──────────────────────────────────────────────

class BatchSession:
    """Represents a batch of valuation cases."""

    def __init__(self, batch_id: str, model: str = "gpt-5.4-mini"):
        self.batch_id = batch_id
        self.model = model
        self.status = "pending"  # pending | processing | completed | error
        self.cases: list[dict] = []
        self.case_results: dict[str, dict] = {}
        self.current_case_index = -1
        self.start_time: Optional[float] = None
        self.first_case_time: Optional[float] = None
        self.total_time: Optional[float] = None
        self.active_connections: list[WebSocket] = []
        # Raw file data for lazy processing
        self.raw_cases: dict[str, dict] = {}

    async def broadcast(self, message: dict):
        """Broadcast a message to all connected WebSocket clients."""
        for ws in self.active_connections:
            try:
                await ws.send_json(message)
            except Exception:
                pass

    def estimated_remaining_seconds(self) -> Optional[float]:
        """Estimate remaining time based on first case duration."""
        if self.first_case_time is None or self.current_case_index < 0:
            return None
        remaining = len(self.cases) - (self.current_case_index + 1)
        if remaining <= 0:
            return 0.0
        return round(self.first_case_time * remaining, 1)

    def to_status_dict(self) -> dict:
        """Return batch status for API response."""
        completed_count = len(self.case_results)
        total = len(self.cases)
        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "model": self.model,
            "total_cases": total,
            "completed_cases": completed_count,
            "current_case_index": self.current_case_index,
            "estimated_remaining": self.estimated_remaining_seconds(),
            "total_time": self.total_time,
            "cases": [
                {
                    "case_id": c["case_id"],
                    "rev_id": c["rev_id"],
                    "status": c.get("status", "pending"),
                    "address": c.get("address", ""),
                    "semaphore": self.case_results.get(c["case_id"], {}).get("semaphore"),
                    "semaphore_color": self.case_results.get(c["case_id"], {}).get("semaphore_color"),
                    "total_time": self.case_results.get(c["case_id"], {}).get("total_time"),
                }
                for c in self.cases
            ],
        }


async def prepare_single_case(
    rev_id: str,
    case_data: dict,
    batch_id: str,
) -> dict:
    """Process uploaded files for a single case: compress images, parse PDFs.
    This is called lazily, one case at a time, right before running agents on it.

    Memory-safe: mirrors the single-upload flow from /api/upload:
    - Images processed in batches of 3 with gc.collect() between batches
    - Files > 15MB skipped to prevent OOM on Render free tier (512MB)
    - PDF readers deleted immediately after use
    - PDF bytes freed after parsing
    """
    case_id = f"{batch_id}_{rev_id}"
    session_id = str(uuid.uuid4())[:8]

    # Create session directory
    session_dir = os.path.join(UPLOAD_DIR, session_id)
    os.makedirs(session_dir, exist_ok=True)

    # ── Process images (batched, memory-safe) ──
    preprocessor = ImagePreprocessor(session_id)
    processed_images: list = []
    has_pdf_photos = False
    tasks: list = []

    async def flush_tasks():
        """Process pending image tasks in a batch, then free PIL memory."""
        if tasks:
            results = await asyncio.gather(*tasks)
            processed_images.extend(results)
            tasks.clear()
            gc.collect()

    for filename, fbytes in case_data.get("images", []):
        # Skip files > 15MB to prevent OOM on free tier
        if len(fbytes) > 15_000_000:
            continue
        tasks.append(preprocessor.process_file(filename, fbytes))
        if len(tasks) >= 3:  # batch of 3 – same as single upload (7MB/img after downscale)
            await flush_tasks()

    # Flush remaining images
    await flush_tasks()

    # Free raw image bytes immediately – they're compressed & saved to disk now
    case_data["images"] = []
    gc.collect()

    # ── Process PDFs embedded photos (batched, max 4 images per PDF) ──
    for pdf_info in case_data.get("pdfs", []):
        if pdf_info["type"] == "unknown":
            try:
                reader = PdfReader(io.BytesIO(pdf_info["bytes"]))
                img_count = 0
                for page_num, page in enumerate(reader.pages):
                    for img_idx, img_obj in enumerate(page.images):
                        if img_count >= 4:
                            break
                        image_ext = img_obj.name.split(".")[-1] if "." in img_obj.name else "jpg"
                        img_filename = f"{pdf_info['filename']}_p{page_num+1}_i{img_idx+1}.{image_ext}"
                        has_pdf_photos = True
                        tasks.append(preprocessor.process_file(img_filename, img_obj.data))
                        img_count += 1
                        if len(tasks) >= 2:
                            await flush_tasks()
                    if img_count >= 4:
                        break
                del reader
                gc.collect()
            except Exception:
                pass
            # Free the PDF bytes for unknown type after extracting images
            pdf_info["bytes"] = b""
            gc.collect()

    # Flush remaining PDF image tasks
    await flush_tasks()

    # ── Parse formulář PDF ──
    property_data = None
    for pdf_info in case_data.get("pdfs", []):
        if pdf_info["type"] == "formular":
            try:
                parsed = await asyncio.to_thread(parse_pdf, pdf_info["bytes"])
                if not parsed.is_empty():
                    property_data = parsed.to_dict()
            except Exception as e:
                print(f"[Batch] Error parsing form PDF in {rev_id}: {e}")
            # Free bytes after parsing
            pdf_info["bytes"] = b""
            gc.collect()
            break

    # ── Parse LV PDF ──
    lv_pdf_path = None
    selected_parcels = None
    for pdf_info in case_data.get("pdfs", []):
        if pdf_info["type"] == "lv":
            try:
                lv_path = os.path.join(session_dir, "lv.pdf")
                with open(lv_path, "wb") as f:
                    f.write(pdf_info["bytes"])
                lv_pdf_path = lv_path

                lv_parsed = await asyncio.to_thread(parse_lv, pdf_info["bytes"])
                lv_data = lv_parsed.to_dict()
                # All parcels auto-selected
                if lv_data and "parcels" in lv_data:
                    selected_parcels = [p["parcel_number"] for p in lv_data["parcels"]]

                    # Calculate total land area
                    if property_data is None:
                        property_data = {}
                    total_area = sum(p.get("area_m2", 0) for p in lv_data["parcels"])
                    if total_area > 0:
                        property_data["plocha_pozemku"] = str(total_area)
            except Exception as e:
                print(f"[Batch] Error parsing LV in {rev_id}: {e}")
            # Free bytes after parsing (saved to disk already)
            pdf_info["bytes"] = b""
            gc.collect()
            break

    # Extract address & year from property data
    property_address = ""
    year_built = None
    if property_data:
        property_address = property_data.get("adresa", "") or ""
        try:
            year_built = int(property_data.get("stavba_dokoncena", "") or "0") or None
        except (ValueError, TypeError):
            pass

    case = {
        "case_id": case_id,
        "session_id": session_id,
        "rev_id": rev_id,
        "status": "pending",
        "images": [img.to_dict() for img in processed_images],
        "property_data": property_data,
        "property_address": property_address,
        "address": property_address,
        "year_built": year_built,
        "lv_pdf_path": lv_pdf_path,
        "selected_parcels": selected_parcels,
        "has_pdf_photos": has_pdf_photos,
        "file_counts": {
            "images": len(processed_images),
            "pdfs": len(case_data.get("pdfs", [])),
        },
    }

    # Free processed PIL objects
    del processed_images
    gc.collect()
    return case


async def process_batch_case(
    batch: BatchSession,
    case: dict,
    case_index: int,
) -> dict:
    """Process a single case within a batch. Returns the pipeline result dict."""
    case_id = case["case_id"]
    session_id = case["session_id"]
    rev_id = case["rev_id"]

    case["status"] = "processing"
    batch.current_case_index = case_index

    await batch.broadcast({
        "type": "batch_case_start",
        "batch_id": batch.batch_id,
        "case_id": case_id,
        "rev_id": rev_id,
        "index": case_index,
        "timestamp": time.time(),
    })

    # Create orchestrator for this case
    orchestrator = PipelineOrchestrator(session_id, model_name=batch.model)

    # Attach batch WS connections to orchestrator so agent-level events are forwarded too
    orchestrator.active_connections = list(batch.active_connections)

    context = {
        "session_id": session_id,
        "images": case["images"],
        "year_built": case.get("year_built"),
        "year_reconstructed": None,
        "property_address": case.get("property_address", ""),
        "property_data": case.get("property_data"),
        "lv_pdf_path": case.get("lv_pdf_path"),
        "selected_parcels": case.get("selected_parcels"),
        "has_pdf_photos": case.get("has_pdf_photos", False),
        "custom_prompts": {},
    }

    case_start = time.time()
    try:
        result = await orchestrator.run_pipeline(context)
        result["property_data"] = case.get("property_data")
        result["property_address"] = case.get("property_address")
        result["rev_id"] = rev_id
    except Exception as e:
        result = {
            "session_id": session_id,
            "rev_id": rev_id,
            "semaphore": "ERROR",
            "semaphore_color": "gray",
            "total_time": round(time.time() - case_start, 2),
            "agents": {},
            "error": str(e),
        }

    case_time = round(time.time() - case_start, 2)
    result["total_time"] = case_time
    case["status"] = "completed"

    # Track first case time for estimates
    if batch.first_case_time is None:
        batch.first_case_time = case_time

    batch.case_results[case_id] = result

    await batch.broadcast({
        "type": "batch_case_complete",
        "batch_id": batch.batch_id,
        "case_id": case_id,
        "rev_id": rev_id,
        "index": case_index,
        "semaphore": result.get("semaphore", "UNKNOWN"),
        "semaphore_color": result.get("semaphore_color", "gray"),
        "address": case.get("address", ""),
        "total_time": case_time,
        "estimated_remaining": batch.estimated_remaining_seconds(),
        "timestamp": time.time(),
    })

    gc.collect()
    return result


async def run_batch(batch: BatchSession, sessions_store: dict, selected_case_ids: list[str] | None = None):
    """Run all cases in a batch sequentially.
    
    Each case is prepared (images compressed, PDFs parsed) and then
    immediately processed by agents before moving to the next case.
    This gives the user results for each case as fast as possible.
    
    If selected_case_ids is provided, only those cases are processed;
    the rest are skipped and their raw data freed.
    """
    batch.status = "processing"
    batch.start_time = time.time()

    # Build the ordered list of rev_ids from raw_cases
    all_rev_ids = sorted(batch.raw_cases.keys())

    # Filter to selected cases if specified
    if selected_case_ids:
        selected_rev_ids = []
        for rev_id in all_rev_ids:
            case_id = f"{batch.batch_id}_{rev_id}"
            if case_id in selected_case_ids:
                selected_rev_ids.append(rev_id)
            else:
                # Free raw data for unselected cases
                if rev_id in batch.raw_cases:
                    del batch.raw_cases[rev_id]
        ordered_rev_ids = selected_rev_ids
    else:
        ordered_rev_ids = all_rev_ids

    total_cases = len(ordered_rev_ids)

    # Initialize placeholder cases in the batch for status tracking
    batch.cases = [
        {
            "case_id": f"{batch.batch_id}_{rev_id}",
            "rev_id": rev_id,
            "status": "pending",
            "address": "",
            "session_id": "",
            "file_counts": {
                "images": len([f for f in batch.raw_cases[rev_id].get("images", [])]),
                "pdfs": len([f for f in batch.raw_cases[rev_id].get("pdfs", [])]),
            },
        }
        for rev_id in ordered_rev_ids
    ]

    await batch.broadcast({
        "type": "batch_start",
        "batch_id": batch.batch_id,
        "total_cases": total_cases,
        "case_ids": [c["case_id"] for c in batch.cases],
        "rev_ids": ordered_rev_ids,
        "timestamp": time.time(),
    })

    for i, rev_id in enumerate(ordered_rev_ids):
        case_data = batch.raw_cases[rev_id]

        # ── Phase 1: Prepare this case (compress images, parse PDFs) ──
        batch.cases[i]["status"] = "preparing"
        batch.current_case_index = i

        await batch.broadcast({
            "type": "batch_case_preparing",
            "batch_id": batch.batch_id,
            "case_id": batch.cases[i]["case_id"],
            "rev_id": rev_id,
            "index": i,
            "timestamp": time.time(),
        })

        prepared_case = await prepare_single_case(rev_id, case_data, batch.batch_id)

        # Update the placeholder with prepared data
        batch.cases[i].update(prepared_case)

        # Store session data in the global sessions store
        sessions_store[prepared_case["session_id"]] = {
            "session_id": prepared_case["session_id"],
            "images": prepared_case["images"],
            "year_built": prepared_case.get("year_built"),
            "property_address": prepared_case.get("property_address", ""),
            "property_data": prepared_case.get("property_data"),
            "lv_pdf_path": prepared_case.get("lv_pdf_path"),
            "selected_parcels": prepared_case.get("selected_parcels"),
            "has_pdf_photos": prepared_case.get("has_pdf_photos", False),
        }

        # Free raw bytes for this case to save memory
        del batch.raw_cases[rev_id]
        gc.collect()

        # ── Phase 2: Run agents on this case ──
        await process_batch_case(batch, batch.cases[i], i)

        # Store full result in the sessions store (for detail API)
        sid = batch.cases[i]["session_id"]
        cid = batch.cases[i]["case_id"]
        if sid in sessions_store and cid in batch.case_results:
            sessions_store[sid]["result"] = batch.case_results[cid]

        # ── Memory cleanup after case completion ──
        # Free heavy image data from the case dict (no longer needed)
        batch.cases[i]["images"] = []
        batch.cases[i].pop("property_data", None)
        batch.cases[i].pop("lv_pdf_path", None)
        batch.cases[i].pop("selected_parcels", None)

        # Slim down case_results to only keep summary fields
        # Full result lives in sessions_store for the detail API
        if cid in batch.case_results:
            full_result = batch.case_results[cid]
            batch.case_results[cid] = {
                "semaphore": full_result.get("semaphore"),
                "semaphore_color": full_result.get("semaphore_color"),
                "total_time": full_result.get("total_time"),
                "rev_id": full_result.get("rev_id"),
                "session_id": full_result.get("session_id"),
            }
            del full_result

        gc.collect()

        # Small delay between cases to let GC settle & avoid rate limits
        if i < total_cases - 1:
            await asyncio.sleep(2)

    batch.status = "completed"
    batch.total_time = round(time.time() - batch.start_time, 2)

    # Summary stats
    semaphore_counts = {"GREEN": 0, "YELLOW": 0, "RED": 0, "ERROR": 0, "UNKNOWN": 0}
    for result in batch.case_results.values():
        s = result.get("semaphore", "UNKNOWN").upper()
        if s in semaphore_counts:
            semaphore_counts[s] += 1
        else:
            semaphore_counts["UNKNOWN"] += 1

    await batch.broadcast({
        "type": "batch_complete",
        "batch_id": batch.batch_id,
        "total_time": batch.total_time,
        "total_cases": total_cases,
        "semaphore_summary": semaphore_counts,
        "timestamp": time.time(),
    })


# Legacy function kept for compatibility but no longer used in the batch flow
async def prepare_batch_cases(
    raw_cases: dict[str, dict],
    batch_id: str,
) -> list[dict]:
    """Process uploaded files for each case: compress images, parse PDFs, return case dicts.
    
    NOTE: This function is no longer used in the batch flow.
    Cases are now prepared lazily one at a time in run_batch().
    """
    prepared = []
    for rev_id, case_data in sorted(raw_cases.items()):
        case = await prepare_single_case(rev_id, case_data, batch_id)
        prepared.append(case)
    return prepared
