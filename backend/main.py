"""FastAPI main application – AI Validation Pipeline for Rodinné Domy."""
import os
import uuid
import json
import gc
from typing import Optional

import io
import base64
from urllib.parse import unquote
from pypdf import PdfReader
import httpx

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect, HTTPException, Body, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import UPLOAD_DIR, SUPPORTED_EXTENSIONS
from preprocessor import ImagePreprocessor
from orchestrator import PipelineOrchestrator
from pdf_parser import parse_pdf
from lv_parser import parse_lv
from agents.odhadce import OdhadceAgent
from report_generator import ReportGenerator
from batch_processor import (
    BatchSession, group_files_by_subfolder, prepare_batch_cases, run_batch,
)
from contract_ocr import process_contract_pdf, process_contract_images
from agents.contract_analyzer import ContractAnalyzerAgent

app = FastAPI(
    title="AI Validation Pipeline – Rodinné Domy",
    description="Orchestrace autonomních AI agentů pro validaci nemovitostí",
    version="1.0.0",
)

# CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory session store
sessions: dict[str, dict] = {}
orchestrators: dict[str, PipelineOrchestrator] = {}
pipeline_results: dict[str, dict] = {}
global_websockets: dict[str, list[WebSocket]] = {}

# Batch session store
batch_sessions: dict[str, BatchSession] = {}
batch_websockets: dict[str, list[WebSocket]] = {}

# Contract analysis session store
contract_sessions: dict[str, dict] = {}


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "AI Validation Pipeline"}


@app.get("/api/debug-config")
async def debug_config():
    """Check which API keys are configured (without exposing them)."""
    from config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL, GEMINI_API_KEY
    return {
        "openai_key_set": bool(OPENAI_API_KEY and len(OPENAI_API_KEY) > 10),
        "openai_key_prefix": OPENAI_API_KEY[:8] + "..." if OPENAI_API_KEY else "EMPTY",
        "openai_base_url": OPENAI_BASE_URL,
        "openai_model": OPENAI_MODEL,
        "gemini_key_set": bool(GEMINI_API_KEY and len(GEMINI_API_KEY) > 5),
    }


@app.get("/api/proxy-image")
async def proxy_image(url: str):
    """Proxy image from sreality CDN to avoid CORS restrictions in browser."""
    from fastapi.responses import Response
    decoded = unquote(url)
    # Only allow sreality CDN to prevent abuse
    if "sdn.cz" not in decoded:
        raise HTTPException(status_code=400, detail="Nepodporovaný zdroj obrázku.")
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.sreality.cz/",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(decoded, headers=headers)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(content=resp.content, media_type=content_type,
                            headers={"Cache-Control": "public, max-age=3600"})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Nelze načíst obrázek: {e}")


@app.post("/api/parse-pdf")
async def parse_pdf_endpoint(pdf_file: UploadFile = File(...)):
    """Parse a PDF form and return extracted property data instantly."""
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Soubor musí být ve formátu PDF.")

    pdf_bytes = await pdf_file.read()
    try:
        parsed = parse_pdf(pdf_bytes)
        return {"property_data": parsed.to_dict() if not parsed.is_empty() else None}
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Nepodařilo se zpracovat PDF: {str(e)}")


@app.post("/api/parse-lv")
async def parse_lv_endpoint(lv_file: UploadFile = File(...)):
    """Parse a List Vlastnictví PDF and return extracted data instantly."""
    if not lv_file.filename or not lv_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Soubor musí být ve formátu PDF.")

    lv_bytes = await lv_file.read()
    try:
        parsed = parse_lv(lv_bytes)
        return {"lv_data": parsed.to_dict() if not parsed.is_empty() else None}
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Nepodařilo se zpracovat LV: {str(e)}")


@app.post("/api/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    year_built: Optional[int] = Form(None),
    year_reconstructed: Optional[int] = Form(None),
    property_address: Optional[str] = Form(None),
    pdf_file: Optional[UploadFile] = File(None),
    lv_pdf_file: Optional[UploadFile] = File(None),
    property_data_json: Optional[str] = Form(None),
    selected_parcels_json: Optional[str] = Form(None),
):
    """Upload and preprocess images, optionally with PDF forms and LV."""
    session_id = str(uuid.uuid4())[:8]

    # === Handle PDF file ===
    property_data = None

    if pdf_file and pdf_file.filename:
        ext = os.path.splitext(pdf_file.filename)[1].lower()
        if ext == ".pdf":
            import asyncio
            pdf_bytes = await pdf_file.read()
            parsed = await asyncio.to_thread(parse_pdf, pdf_bytes)
            if not parsed.is_empty():
                property_data = parsed.to_dict()

            # Save PDF to session dir for reference
            session_dir = os.path.join(UPLOAD_DIR, session_id)
            os.makedirs(session_dir, exist_ok=True)
            pdf_path = os.path.join(session_dir, "formular.pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)
            del pdf_bytes
            gc.collect()

    # === Handle manual property data (JSON string from frontend) ===
    if not property_data and property_data_json:
        try:
            property_data = json.loads(property_data_json)
        except json.JSONDecodeError:
            pass

    # === Handle LV PDF ===
    lv_pdf_path = None
    lv_data_preview = None
    if lv_pdf_file and lv_pdf_file.filename:
        ext = os.path.splitext(lv_pdf_file.filename)[1].lower()
        if ext == ".pdf":
            import asyncio
            lv_bytes = await lv_pdf_file.read()
            session_dir = os.path.join(UPLOAD_DIR, session_id)
            os.makedirs(session_dir, exist_ok=True)
            lv_pdf_path = os.path.join(session_dir, "lv.pdf")
            with open(lv_pdf_path, "wb") as f:
                f.write(lv_bytes)
            # Parse LV for preview
            try:
                lv_parsed = await asyncio.to_thread(parse_lv, lv_bytes)
                lv_data_preview = lv_parsed.to_dict()
            except Exception:
                pass
            del lv_bytes
            gc.collect()

    # Parse selected parcels
    selected_parcels = None
    if selected_parcels_json:
        try:
            selected_parcels = json.loads(selected_parcels_json)
        except json.JSONDecodeError:
            pass

    # Calculate total area of selected parcels if we have LV data
    if selected_parcels and lv_data_preview and "parcels" in lv_data_preview:
        if property_data is None:
            property_data = {}
        total_area = sum(
            p.get("area_m2", 0) for p in lv_data_preview["parcels"] 
            if p.get("parcel_number") in selected_parcels
        )
        if total_area > 0:
            property_data["plocha_pozemku"] = str(total_area)

    # Preprocessor initialization
    preprocessor = ImagePreprocessor(session_id)
    processed = []

    # === Process image files incrementally to save memory ===
    has_pdf_photos = False
    
    import asyncio
    
    tasks = []
    
    # Funkce projede dávku a ošetří přeplnění RAM na free serveru (v jednu chvíli se zpracují kompresí max 3 bitmapy)
    async def flush_tasks():
        if tasks:
            processed_results = await asyncio.gather(*tasks)
            processed.extend(processed_results)
            tasks.clear()
            gc.collect()  # Free PIL memory after each batch

    async def _process_file_to_thread(filename, fbytes):
        res = await preprocessor.process_file(filename, fbytes)
        return res

    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            file_bytes = await f.read()
            # Skip files > 15MB to prevent OOM on free tier
            if len(file_bytes) > 15_000_000:
                continue
            tasks.append(_process_file_to_thread(f.filename or "unknown", file_bytes))
            if len(tasks) >= 3:  # batch of 3 OK with downscaling (7MB/img vs 36MB)
                await flush_tasks()
        elif ext == ".pdf":
            file_bytes = await f.read()
            try:
                reader = PdfReader(io.BytesIO(file_bytes))
                pdf_img_count = 0
                for page_num, page in enumerate(reader.pages):
                    for img_index, image_file_object in enumerate(page.images):
                        if pdf_img_count >= 4:  # max 4 images from PDF
                            break
                        image_bytes = image_file_object.data
                        image_name = image_file_object.name
                        image_ext = image_name.split('.')[-1] if '.' in image_name else "jpg"
                        
                        normalized_ext = f".{image_ext.lower()}".replace(".jpeg", ".jpg")
                        if normalized_ext in SUPPORTED_EXTENSIONS or image_ext.lower() in ("jpeg", "jpg", "png", "webp"):
                            img_filename = f"{f.filename}_str{page_num+1}_obr{img_index+1}.{image_ext}"
                            has_pdf_photos = True
                            tasks.append(_process_file_to_thread(img_filename, image_bytes))
                            pdf_img_count += 1
                            if len(tasks) >= 2:
                                await flush_tasks()
                    if pdf_img_count >= 4:
                        break
                del reader, file_bytes
                gc.collect()
            except Exception as e:
                print(f"Error extracting photos from PDF: {e}")
                pass
        else:
            pass

    # Zbylé soubory mimo troj-dávkování
    await flush_tasks()

    if not processed:
        raise HTTPException(status_code=400, detail="No valid image files uploaded.")

    # Use address from PDF data if not explicitly provided
    effective_address = property_address
    if not effective_address and property_data:
        effective_address = property_data.get("adresa", "")

    # Use year from PDF data if not explicitly provided
    effective_year_built = year_built
    if not effective_year_built and property_data:
        try:
            effective_year_built = int(property_data.get("stavba_dokoncena", "") or "0") or None
        except (ValueError, TypeError):
            pass

    # Store session data
    sessions[session_id] = {
        "session_id": session_id,
        "images": [img.to_dict() for img in processed],
        "year_built": effective_year_built,
        "year_reconstructed": year_reconstructed,
        "property_address": effective_address,
        "property_data": property_data,
        "processed_paths": [img.processed_path for img in processed],
        "lv_pdf_path": lv_pdf_path,
        "selected_parcels": selected_parcels,
        "has_pdf_photos": has_pdf_photos,
    }

    return {
        "session_id": session_id,
        "files_uploaded": len(processed),
        "files_processed": len(processed),
        "images": [img.to_dict() for img in processed],
        "property_data": property_data,
        "lv_data": lv_data_preview,
    }


@app.post("/api/pipeline/start/{session_id}")
async def start_pipeline(
    session_id: str,
    background_tasks: BackgroundTasks,
    custom_prompts: Optional[dict] = None,
    model: str = "gemini"
):
    """Starts the validation pipeline in the background."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = sessions[session_id]
    session["model"] = model  # Store model for valuation endpoint

    # Create orchestrator
    orchestrator = PipelineOrchestrator(session_id, model_name=model)
    orchestrators[session_id] = orchestrator

    # Attach any websockets that connected before orchestrator creation
    if session_id in global_websockets:
        for ws in global_websockets[session_id]:
            if ws not in orchestrator.active_connections:
                orchestrator.active_connections.append(ws)

    # Build context
    context = {
        "session_id": session_id,
        "images": session["images"],
        "year_built": session.get("year_built"),
        "year_reconstructed": session.get("year_reconstructed"),
        "property_address": session.get("property_address", ""),
        "property_data": session.get("property_data"),
        "lv_pdf_path": session.get("lv_pdf_path"),
        "selected_parcels": session.get("selected_parcels"),
        "has_pdf_photos": session.get("has_pdf_photos", False),
        "custom_prompts": custom_prompts or {},
    }

    async def run_and_store():
        try:
            # Run pipeline (async)
            result = await orchestrator.run_pipeline(context)

            # Attach property data
            result["property_data"] = session.get("property_data")
            result["property_address"] = session.get("property_address")

            # Store result
            sessions[session_id]["result"] = result
        except Exception as e:
            print(f"Pipeline error for session {session_id}: {e}")

    # Dispatch to background
    background_tasks.add_task(run_and_store)

    return {
        "status": "started",
        "message": "Pipeline runs in the background. Use WebSocket for updates.",
        "pipeline_id": orchestrator.pipeline_id,
        "session_id": session_id,
    }


@app.get("/api/pipeline/results/{session_id}")
async def get_results(session_id: str):
    """Get pipeline results for a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = sessions[session_id]
    result = session.get("result")
    
    if not result:
        # Pipeline still running or not started yet
        orchestrator = orchestrators.get(session_id)
        return {
            "completed": False,
            "is_running": orchestrator.is_running if orchestrator else False,
        }

    return {"completed": True, **result}


@app.get("/api/pipeline/state/{session_id}")
async def get_pipeline_state(session_id: str):
    """Get current pipeline state (agents status)."""
    orchestrator = orchestrators.get(session_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="No active pipeline for this session.")
        
    state = orchestrator.get_state()
    if session_id in sessions:
        state["property_data"] = sessions[session_id].get("property_data")
        state["property_address"] = sessions[session_id].get("property_address")
    return state


@app.post("/api/pipeline/valuation/{session_id}")
async def generate_valuation(
    session_id: str, 
    payload: dict = Body(None),
    model: str = None
):
    """Run just the Valuation (Odhadce) agent to get comparative market estimation."""
    session = sessions.get(session_id, {})
    
    # Use the model from query param, or fall back to the session's model, or default to gpt-5.4-mini
    effective_model = model or session.get("model") or "gpt-5.4-mini"
    
    # Use provided overrides if any
    custom_address = payload.get("adresa") if payload else None
    custom_area = payload.get("plocha") if payload else None
    custom_land = payload.get("pozemek") if payload else None
    custom_condition = payload.get("stav") if payload else None

    # We provide this override mapping in context
    context = {
        "session_id": session_id,
        "images": session.get("images", []),
        "property_address": session.get("property_address", ""),
        "property_data": session.get("property_data"),
        "valuation_overrides": {
            "adresa": custom_address,
            "plocha": custom_area,
            "pozemek": custom_land,
            "stav": custom_condition
        }
    }
    
    agent = OdhadceAgent(model_name=effective_model)
    result = await agent.run(context)
    
    # Store result optionally on session if needed
    if session_id in sessions and "valuation" not in session:
        session["valuation"] = result.to_dict()
        
    return result.to_dict()


@app.get("/api/pipeline/report/{session_id}")
async def get_pipeline_report(session_id: str):
    """Generate and return a PDF report for the session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    
    session = sessions[session_id]
    result = session.get("result")
    
    if not result:
        raise HTTPException(status_code=400, detail="Pipeline results not available yet.")
    
    try:
        from fastapi.responses import Response
        generator = ReportGenerator()
        pdf_bytes = generator.generate_valuation_report(session, result)
        
        # Determine filename based on address
        address = session.get("property_address") or "odhad_nemovitosti"
        # Sanitize filename (remove special chars, spaces to underscores)
        import re
        safe_name = re.sub(r'[^\w\s-]', '', address).strip().replace(' ', '_')
        if not safe_name:
            safe_name = "report"
            
        filename = f"{safe_name}.pdf"
        
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )
    except Exception as e:
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Chyba při generování PDF: {str(e)}")


@app.post("/api/agent/prompt/{session_id}/{agent_name}")
async def update_agent_prompt(session_id: str, agent_name: str, prompt: dict):
    """Update an agent's system prompt."""
    orchestrator = orchestrators.get(session_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="No active pipeline.")

    agent = orchestrator.agents.get(agent_name)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found.")

    agent.system_prompt = prompt.get("system_prompt", agent.system_prompt)
    return {"status": "ok", "agent": agent_name, "prompt_length": len(agent.system_prompt)}


@app.websocket("/ws/pipeline/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket for real-time pipeline updates."""
    await websocket.accept()

    if session_id not in global_websockets:
        global_websockets[session_id] = []
    global_websockets[session_id].append(websocket)

    orchestrator = orchestrators.get(session_id)
    if orchestrator and websocket not in orchestrator.active_connections:
        orchestrator.active_connections.append(websocket)

    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            msg = json.loads(data)

            # Handle client messages (e.g., prompt updates)
            if msg.get("type") == "update_prompt":
                agent_name = msg.get("agent")
                new_prompt = msg.get("prompt")
                if orchestrator and agent_name in orchestrator.agents:
                    orchestrator.agents[agent_name].system_prompt = new_prompt
                    await websocket.send_json({
                        "type": "prompt_updated",
                        "agent": agent_name,
                    })

    except WebSocketDisconnect:
        if session_id in global_websockets and websocket in global_websockets[session_id]:
            global_websockets[session_id].remove(websocket)
        if orchestrator and websocket in orchestrator.active_connections:
            orchestrator.active_connections.remove(websocket)


# ── Batch Processing Endpoints ────────────────────────────────────────────


@app.post("/api/batch/upload")
async def batch_upload(
    files: list[UploadFile] = File(...),
    model: str = Form("gpt-5.4-mini"),
):
    """Upload a folder (webkitdirectory) for batch processing.
    Files arrive with their relative paths preserved via webkitdirectory.
    """
    batch_id = str(uuid.uuid4())[:8]

    # Read all files into memory, keyed by their webkitRelativePath
    file_bytes_map: dict[str, bytes] = {}
    for f in files:
        if not f.filename:
            continue
        fbytes = await f.read()
        file_bytes_map[f.filename] = fbytes

    if not file_bytes_map:
        raise HTTPException(status_code=400, detail="Žádné soubory nebyly nahrány.")

    # Group by subfolder
    raw_cases = group_files_by_subfolder(list(file_bytes_map.keys()), file_bytes_map)

    if not raw_cases:
        raise HTTPException(status_code=400, detail="Nebyly nalezeny žádné podsložky s podklady.")

    # Prepare cases (compress images, parse PDFs)
    prepared_cases = await prepare_batch_cases(raw_cases, batch_id)

    if not prepared_cases:
        raise HTTPException(status_code=400, detail="Žádný případ neobsahoval platné soubory.")

    # Create batch session
    batch = BatchSession(batch_id, model=model)
    batch.cases = prepared_cases

    # Also store each case session in the global sessions dict
    # so that /api/pipeline/results/{session_id} works for individual cases
    for case in prepared_cases:
        sessions[case["session_id"]] = {
            "session_id": case["session_id"],
            "images": case["images"],
            "year_built": case.get("year_built"),
            "property_address": case.get("property_address", ""),
            "property_data": case.get("property_data"),
            "lv_pdf_path": case.get("lv_pdf_path"),
            "selected_parcels": case.get("selected_parcels"),
            "has_pdf_photos": case.get("has_pdf_photos", False),
        }

    batch_sessions[batch_id] = batch

    # Free uploaded bytes
    del file_bytes_map
    gc.collect()

    return {
        "batch_id": batch_id,
        "total_cases": len(prepared_cases),
        "cases": [
            {
                "case_id": c["case_id"],
                "rev_id": c["rev_id"],
                "session_id": c["session_id"],
                "address": c.get("address", ""),
                "file_counts": c.get("file_counts", {}),
            }
            for c in prepared_cases
        ],
    }


@app.post("/api/batch/start/{batch_id}")
async def start_batch_pipeline(
    batch_id: str,
    background_tasks: BackgroundTasks,
):
    """Start sequential processing of all cases in a batch."""
    batch = batch_sessions.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")

    if batch.status == "processing":
        raise HTTPException(status_code=400, detail="Batch is already processing.")

    # Attach any websockets that connected before start
    if batch_id in batch_websockets:
        for ws in batch_websockets[batch_id]:
            if ws not in batch.active_connections:
                batch.active_connections.append(ws)

    async def _run():
        try:
            await run_batch(batch)
            # Store results in individual sessions too
            for case in batch.cases:
                sid = case["session_id"]
                cid = case["case_id"]
                if sid in sessions and cid in batch.case_results:
                    sessions[sid]["result"] = batch.case_results[cid]
        except Exception as e:
            print(f"[Batch] Fatal error: {e}")
            batch.status = "error"

    background_tasks.add_task(_run)

    return {
        "status": "started",
        "batch_id": batch_id,
        "total_cases": len(batch.cases),
    }


@app.get("/api/batch/status/{batch_id}")
async def get_batch_status(batch_id: str):
    """Get current batch processing status with per-case results."""
    batch = batch_sessions.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return batch.to_status_dict()


@app.get("/api/batch/case-result/{batch_id}/{case_id}")
async def get_batch_case_result(batch_id: str, case_id: str):
    """Get the full pipeline result for a specific case in a batch."""
    batch = batch_sessions.get(batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found.")
    result = batch.case_results.get(case_id)
    if not result:
        raise HTTPException(status_code=404, detail="Case result not available yet.")
    return {"completed": True, **result}


@app.websocket("/ws/batch/{batch_id}")
async def batch_websocket_endpoint(websocket: WebSocket, batch_id: str):
    """WebSocket for real-time batch processing updates."""
    await websocket.accept()

    if batch_id not in batch_websockets:
        batch_websockets[batch_id] = []
    batch_websockets[batch_id].append(websocket)

    batch = batch_sessions.get(batch_id)
    if batch and websocket not in batch.active_connections:
        batch.active_connections.append(websocket)

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if batch_id in batch_websockets and websocket in batch_websockets[batch_id]:
            batch_websockets[batch_id].remove(websocket)
        if batch and websocket in batch.active_connections:
            batch.active_connections.remove(websocket)


# ── Contract Analysis Endpoints ───────────────────────────────────────────


@app.post("/api/contract/upload")
async def upload_contract(
    files: list[UploadFile] = File(...),
    model: str = Form("gpt-5.4-mini"),
):
    """Upload a contract document (PDF or images) for AI analysis."""
    session_id = str(uuid.uuid4())[:8]
    
    pdf_files = []
    image_files = []
    
    for f in files:
        if not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        fbytes = await f.read()
        
        if ext == ".pdf":
            pdf_files.append((f.filename, fbytes))
        elif ext in SUPPORTED_EXTENSIONS:
            image_files.append((f.filename, fbytes))
    
    if not pdf_files and not image_files:
        raise HTTPException(status_code=400, detail="Nahrajte alespoň jeden soubor (PDF nebo obrázek).")
    
    # Process document
    if pdf_files:
        # Use first PDF
        filename, pdf_bytes = pdf_files[0]
        doc = await process_contract_pdf(pdf_bytes, session_id, filename)
    else:
        doc = await process_contract_images(image_files, session_id)
    
    # If document has images but no text, run AI OCR
    agent = ContractAnalyzerAgent(model_name=model)
    
    if doc.raw_images and not doc.full_text.strip():
        ocr_text = await agent.ocr_images(doc.raw_images)
        doc.full_text = ocr_text
        # Split text by page markers
        if "--- Strana" in ocr_text:
            import re
            page_texts = re.split(r'--- Strana \d+ ---', ocr_text)
            page_texts = [pt.strip() for pt in page_texts if pt.strip()]
            for i, pt in enumerate(page_texts):
                if i < len(doc.pages):
                    doc.pages[i].full_text = pt
        elif doc.pages:
            doc.pages[0].full_text = ocr_text
    
    # Classify contract type
    classification = await agent.classify_contract(doc.full_text)
    doc.doc_type = classification["contract_type"]
    
    # Save page images for serving
    session_dir = os.path.join(UPLOAD_DIR, f"contract_{session_id}")
    os.makedirs(session_dir, exist_ok=True)
    
    # Save PDF for rendering or save images
    page_image_urls = []
    if pdf_files:
        pdf_path = os.path.join(session_dir, "document.pdf")
        with open(pdf_path, "wb") as f:
            f.write(pdf_files[0][1])
        # We'll serve PDF directly
    
    for i, page in enumerate(doc.pages):
        if page.image_data:
            img_path = os.path.join(session_dir, f"page_{i}.jpg")
            with open(img_path, "wb") as f:
                f.write(page.image_data)
            page_image_urls.append(f"/uploads/contract_{session_id}/page_{i}.jpg")
    
    # Store session
    contract_sessions[session_id] = {
        "session_id": session_id,
        "document": doc,
        "classification": classification,
        "model": model,
        "has_pdf": bool(pdf_files),
        "pdf_filename": pdf_files[0][0] if pdf_files else None,
        "page_image_urls": page_image_urls,
    }
    
    # Clean raw_images to free memory (keep text)
    doc.raw_images = []
    for page in doc.pages:
        page.image_data = None
    gc.collect()
    
    return {
        "session_id": session_id,
        "filename": doc.filename,
        "total_pages": doc.total_pages,
        "full_text": doc.full_text,
        "pages": [p.to_dict() for p in doc.pages],
        "classification": classification,
        "has_pdf": bool(pdf_files),
        "page_image_urls": page_image_urls,
    }


@app.post("/api/contract/query/{session_id}")
async def query_contract(
    session_id: str,
    payload: dict = Body(...),
):
    """Query the contract with a natural language question or preset."""
    cs = contract_sessions.get(session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Contract session not found.")
    
    query = payload.get("query", "")
    if not query:
        raise HTTPException(status_code=400, detail="Dotaz nesmí být prázdný.")
    
    doc = cs["document"]
    model = payload.get("model", cs.get("model", "gpt-5.4-mini"))
    
    agent = ContractAnalyzerAgent(model_name=model)
    pages_text = [p.full_text for p in doc.pages]
    
    result = await agent.query_contract(doc.full_text, query, pages_text)
    
    return result


@app.post("/api/contract/extract-all/{session_id}")
async def extract_all_contract_data(
    session_id: str,
    payload: dict = Body(...),
):
    """Extract ALL key data from the contract in one shot."""
    cs = contract_sessions.get(session_id)
    if not cs:
        raise HTTPException(status_code=404, detail="Contract session not found.")
    
    doc = cs["document"]
    model = payload.get("model", cs.get("model", "gpt-5.4-mini"))
    classification = cs["classification"]
    
    agent = ContractAnalyzerAgent(model_name=model)
    pages_text = [p.full_text for p in doc.pages]
    
    result = await agent.extract_all(
        doc.full_text, 
        pages_text, 
        classification.get("contract_type", "unknown"),
        classification.get("presets", []),
    )
    
    return result


@app.post("/api/contract/compare")
async def compare_contracts_endpoint(
    payload: dict = Body(...),
):
    """Compare two contract sessions."""
    session_a = payload.get("session_a")
    session_b = payload.get("session_b")
    model = payload.get("model", "gpt-5.4-mini")
    
    if not session_a or not session_b:
        raise HTTPException(status_code=400, detail="Vyžadovány dva session IDs.")
    
    cs_a = contract_sessions.get(session_a)
    cs_b = contract_sessions.get(session_b)
    
    if not cs_a:
        raise HTTPException(status_code=404, detail=f"Session A ({session_a}) nenalezena.")
    if not cs_b:
        raise HTTPException(status_code=404, detail=f"Session B ({session_b}) nenalezena.")
    
    agent = ContractAnalyzerAgent(model_name=model)
    result = await agent.compare_contracts(
        cs_a["document"].full_text,
        cs_b["document"].full_text,
        cs_a["document"].filename,
        cs_b["document"].filename,
    )
    
    return result


@app.get("/api/contract/page-image/{session_id}/{page_num}")
async def get_contract_page_image(session_id: str, page_num: int):
    """Get page image for a contract session."""
    from fastapi.responses import FileResponse
    
    img_path = os.path.join(UPLOAD_DIR, f"contract_{session_id}", f"page_{page_num}.jpg")
    if os.path.exists(img_path):
        return FileResponse(img_path, media_type="image/jpeg")
    raise HTTPException(status_code=404, detail="Page image not found.")


@app.get("/api/contract/pdf/{session_id}")
async def get_contract_pdf(session_id: str):
    """Get the original PDF for a contract session."""
    from fastapi.responses import FileResponse
    
    pdf_path = os.path.join(UPLOAD_DIR, f"contract_{session_id}", "document.pdf")
    if os.path.exists(pdf_path):
        return FileResponse(pdf_path, media_type="application/pdf")
    raise HTTPException(status_code=404, detail="PDF not found.")


# Serve uploaded/processed images (panorama, etc.)
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
