"""OCR module for contract document processing.

Supports:
- PDF with selectable text (direct extraction via pdfplumber)
- PDF with scanned images (OCR via Google Cloud Vision)
- Photos/scans of contracts (JPEG, PNG, HEIC, etc.)
- Multi-page documents (multiple images = one contract)
"""
import os
import io
import base64
import json
from typing import Optional
from dataclasses import dataclass, field

import pdfplumber
from PIL import Image


@dataclass
class TextBlock:
    """A block of text with its position in the document."""
    text: str
    page: int  # 0-indexed page number
    x: float  # Normalized x position (0-1)
    y: float  # Normalized y position (0-1)
    width: float  # Normalized width (0-1)
    height: float  # Normalized height (0-1)
    confidence: float = 1.0

    def to_dict(self):
        return {
            "text": self.text,
            "page": self.page,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
            "confidence": round(self.confidence, 3),
        }


@dataclass
class DocumentPage:
    """A single page of the document."""
    page_number: int  # 0-indexed
    full_text: str
    blocks: list[TextBlock] = field(default_factory=list)
    image_data: Optional[bytes] = None  # Raw image bytes for rendering
    image_mime: str = "image/jpeg"
    width: int = 0
    height: int = 0

    def to_dict(self):
        return {
            "page_number": self.page_number,
            "full_text": self.full_text,
            "blocks": [b.to_dict() for b in self.blocks],
            "has_image": self.image_data is not None,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class ContractDocument:
    """Full processed contract document."""
    session_id: str
    filename: str
    doc_type: str = "unknown"  # Will be classified by AI
    total_pages: int = 0
    pages: list[DocumentPage] = field(default_factory=list)
    full_text: str = ""  # All pages concatenated
    raw_images: list[dict] = field(default_factory=list)  # For AI Vision processing

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "filename": self.filename,
            "doc_type": self.doc_type,
            "total_pages": self.total_pages,
            "pages": [p.to_dict() for p in self.pages],
            "full_text": self.full_text,
        }


def _extract_pdf_text(pdf_bytes: bytes) -> ContractDocument:
    """Extract text from PDF with selectable text using pdfplumber."""
    doc = ContractDocument(session_id="", filename="")
    pages = []
    all_text_parts = []

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        doc.total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ""
            blocks = []

            # Extract words with positions
            words = page.extract_words(keep_blank_chars=True) or []
            pw = float(page.width) if page.width else 1.0
            ph = float(page.height) if page.height else 1.0

            # Group words into lines for better block representation
            current_line = []
            current_top = None
            line_tolerance = 3  # pixels

            for w in words:
                wtop = float(w.get("top", 0))
                if current_top is None or abs(wtop - current_top) > line_tolerance:
                    if current_line:
                        line_text = " ".join(cw["text"] for cw in current_line)
                        x0 = min(float(cw.get("x0", 0)) for cw in current_line)
                        top = min(float(cw.get("top", 0)) for cw in current_line)
                        x1 = max(float(cw.get("x1", 0)) for cw in current_line)
                        bottom = max(float(cw.get("bottom", 0)) for cw in current_line)
                        blocks.append(TextBlock(
                            text=line_text,
                            page=i,
                            x=x0 / pw,
                            y=top / ph,
                            width=(x1 - x0) / pw,
                            height=(bottom - top) / ph,
                        ))
                    current_line = [w]
                    current_top = wtop
                else:
                    current_line.append(w)

            # Last line
            if current_line:
                line_text = " ".join(cw["text"] for cw in current_line)
                x0 = min(float(cw.get("x0", 0)) for cw in current_line)
                top = min(float(cw.get("top", 0)) for cw in current_line)
                x1 = max(float(cw.get("x1", 0)) for cw in current_line)
                bottom = max(float(cw.get("bottom", 0)) for cw in current_line)
                blocks.append(TextBlock(
                    text=line_text,
                    page=i,
                    x=x0 / pw,
                    y=top / ph,
                    width=(x1 - x0) / pw,
                    height=(bottom - top) / ph,
                ))

            dp = DocumentPage(
                page_number=i,
                full_text=page_text,
                blocks=blocks,
                width=int(pw),
                height=int(ph),
            )
            pages.append(dp)
            all_text_parts.append(page_text)

    doc.pages = pages
    doc.full_text = "\n\n--- Strana {} ---\n\n".join(
        "{}".format("") for _ in range(len(pages))
    )
    # Build full text with page markers
    text_sections = []
    for i, p in enumerate(pages):
        text_sections.append(f"--- Strana {i+1} ---\n{p.full_text}")
    doc.full_text = "\n\n".join(text_sections)

    return doc


def _image_to_base64(image_bytes: bytes, mime_type: str = "image/jpeg") -> str:
    """Convert image bytes to base64 string."""
    return base64.b64encode(image_bytes).decode("utf-8")


def _preprocess_image(image_bytes: bytes) -> bytes:
    """Preprocess an image for better OCR results.
    
    Attempts: resize if too large, convert to grayscale for contrast,
    adjust brightness/contrast for poor-quality photos.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))

        # Convert RGBA/P to RGB
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        # Resize if too large (keep OCR quality but reduce memory)
        max_dim = 4000
        if max(img.size) > max_dim:
            ratio = max_dim / max(img.size)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        # Save as JPEG
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        return buf.getvalue()
    except Exception:
        return image_bytes


async def process_contract_pdf(pdf_bytes: bytes, session_id: str, filename: str) -> ContractDocument:
    """Process a PDF contract — extract text, or OCR if scanned."""
    doc = _extract_pdf_text(pdf_bytes)
    doc.session_id = session_id
    doc.filename = filename

    # Check if we got meaningful text
    has_text = len(doc.full_text.replace("-", "").replace(" ", "").replace("\n", "")) > 50

    if has_text:
        return doc

    # If no text, this is likely a scanned PDF — extract images for AI processing
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(pdf_bytes))
    images_for_ai = []

    for page_num, page in enumerate(reader.pages):
        for img_obj in page.images:
            img_bytes = _preprocess_image(img_obj.data)
            b64 = _image_to_base64(img_bytes)
            images_for_ai.append({
                "page": page_num,
                "data": b64,
                "mime_type": "image/jpeg",
                "raw_bytes": img_bytes,
            })

    doc.raw_images = images_for_ai
    # Text will be filled by AI Vision OCR in the analyzer agent
    return doc


async def process_contract_images(
    image_files: list[tuple[str, bytes]],
    session_id: str,
) -> ContractDocument:
    """Process multiple images as pages of a single contract."""
    doc = ContractDocument(session_id=session_id, filename="multi-image")
    doc.total_pages = len(image_files)
    images_for_ai = []

    for i, (filename, img_bytes) in enumerate(image_files):
        processed = _preprocess_image(img_bytes)
        b64 = _image_to_base64(processed)

        # Get image dimensions
        try:
            img = Image.open(io.BytesIO(processed))
            w, h = img.size
        except Exception:
            w, h = 0, 0

        dp = DocumentPage(
            page_number=i,
            full_text="",  # Will be filled by AI OCR
            image_data=processed,
            image_mime="image/jpeg",
            width=w,
            height=h,
        )
        doc.pages.append(dp)

        images_for_ai.append({
            "page": i,
            "data": b64,
            "mime_type": "image/jpeg",
            "raw_bytes": processed,
        })

    doc.raw_images = images_for_ai
    doc.filename = image_files[0][0] if image_files else "unknown"
    return doc
