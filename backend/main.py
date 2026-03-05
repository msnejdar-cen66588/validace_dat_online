"""FastAPI main application – AI Validation Pipeline for Rodinné Domy."""
import os
import uuid
import json
from typing import Optional

import fitz

from fastapi import FastAPI, UploadFile, File, Form, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import UPLOAD_DIR, SUPPORTED_EXTENSIONS
from preprocessor import ImagePreprocessor
from orchestrator import PipelineOrchestrator
from pdf_parser import parse_pdf
from lv_parser import parse_lv

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


@app.get("/api/health")
async def health_check():
    return {"status": "ok", "service": "AI Validation Pipeline"}


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
            pdf_bytes = await pdf_file.read()
            parsed = parse_pdf(pdf_bytes)
            if not parsed.is_empty():
                property_data = parsed.to_dict()

            # Save PDF to session dir for reference
            session_dir = os.path.join(UPLOAD_DIR, session_id)
            os.makedirs(session_dir, exist_ok=True)
            pdf_path = os.path.join(session_dir, "formular.pdf")
            with open(pdf_path, "wb") as f:
                f.write(pdf_bytes)

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
            lv_bytes = await lv_pdf_file.read()
            session_dir = os.path.join(UPLOAD_DIR, session_id)
            os.makedirs(session_dir, exist_ok=True)
            lv_pdf_path = os.path.join(session_dir, "lv.pdf")
            with open(lv_pdf_path, "wb") as f:
                f.write(lv_bytes)
            # Parse LV for preview
            try:
                lv_parsed = parse_lv(lv_bytes)
                lv_data_preview = lv_parsed.to_dict()
            except Exception:
                pass

    # Parse selected parcels
    selected_parcels = None
    if selected_parcels_json:
        try:
            selected_parcels = json.loads(selected_parcels_json)
        except json.JSONDecodeError:
            pass

    # === Process image files ===
    valid_files = []
    has_pdf_photos = False
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext in SUPPORTED_EXTENSIONS:
            file_bytes = await f.read()
            valid_files.append((f.filename or "unknown", file_bytes))
        elif ext == ".pdf":
            file_bytes = await f.read()
            try:
                # Otevření PDF přes PyMuPDF z bytestreamu
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                for page_num in range(len(doc)):
                    page = doc.load_page(page_num)
                    image_list = page.get_images(full=True)
                    for img_index, img_info in enumerate(image_list):
                        xref = img_info[0]
                        base_image = doc.extract_image(xref)
                        image_bytes = base_image["image"]
                        image_ext = base_image["ext"]
                        # Pro jistotu povolíme i "jpeg" apod. (ext bez tečky)
                        normalized_ext = f".{image_ext.lower()}".replace(".jpeg", ".jpg")
                        if normalized_ext in SUPPORTED_EXTENSIONS or image_ext.lower() in ("jpeg", "jpg", "png"):
                            img_filename = f"{f.filename}_str{page_num+1}_obr{img_index+1}.{image_ext}"
                            valid_files.append((img_filename, image_bytes))
                            has_pdf_photos = True
            except Exception:
                pass  # Při selhání extrakce přeskočit
        else:
            pass  # Skip unsupported formats silently

    if not valid_files:
        raise HTTPException(status_code=400, detail="No valid image files uploaded.")

    # Preprocess images
    preprocessor = ImagePreprocessor(session_id)
    processed = await preprocessor.process_batch(valid_files)

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
        "files_uploaded": len(valid_files),
        "files_processed": len(processed),
        "images": [img.to_dict() for img in processed],
        "property_data": property_data,
        "lv_data": lv_data_preview,
    }


@app.post("/api/pipeline/start/{session_id}")
async def start_pipeline(
    session_id: str,
    custom_prompts: Optional[dict] = None,
):
    """Start the validation pipeline for a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = sessions[session_id]

    # Create orchestrator
    orchestrator = PipelineOrchestrator(session_id)
    orchestrators[session_id] = orchestrator

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

    # Run pipeline (async)
    result = await orchestrator.run_pipeline(context)

    # Store result
    sessions[session_id]["result"] = result

    return result


@app.get("/api/pipeline/results/{session_id}")
async def get_results(session_id: str):
    """Get pipeline results for a session."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")

    session = sessions[session_id]
    result = session.get("result")
    if not result:
        # Return current state if still running
        orchestrator = orchestrators.get(session_id)
        if orchestrator:
            return orchestrator.get_state()
        raise HTTPException(status_code=404, detail="No results yet.")

    return result


@app.get("/api/pipeline/state/{session_id}")
async def get_pipeline_state(session_id: str):
    """Get current pipeline state (agents status)."""
    orchestrator = orchestrators.get(session_id)
    if not orchestrator:
        raise HTTPException(status_code=404, detail="No active pipeline for this session.")
    return orchestrator.get_state()


@app.post("/api/pipeline/valuation/{session_id}")
async def generate_valuation(session_id: str):
    """Run just the Valuation (Odhadce) agent to get comparative market estimation."""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
        
    session = sessions[session_id]
    context = {
        "session_id": session_id,
        "images": session["images"],
        "property_address": session.get("property_address", ""),
        "property_data": session.get("property_data"),
    }
    
    agent = OdhadceAgent()
    result = await agent.run(context)
    
    # Store result optionally on session if needed
    if "valuation" not in session:
        session["valuation"] = result.to_dict()
        
    return result.to_dict()


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

    orchestrator = orchestrators.get(session_id)
    if orchestrator:
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
        if orchestrator and websocket in orchestrator.active_connections:
            orchestrator.active_connections.remove(websocket)


# Serve uploaded/processed images (panorama, etc.)
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
