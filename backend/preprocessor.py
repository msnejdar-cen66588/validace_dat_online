"""Image Pre-processing Module (The Optimizer).

Handles HEIC/Apple + standard Windows formats:
- Compresses photos to max 2MB while preserving EXIF
- Extracts GPS coordinates, capture date, device model
- Converts all inputs to standard JPG for AI analysis
"""
import io
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from PIL import Image, ExifTags
import piexif

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False

from config import MAX_IMAGE_SIZE_BYTES, UPLOAD_DIR, JPEG_QUALITY


@dataclass
class ImageMetadata:
    """Extracted metadata from an image."""
    gps_latitude: Optional[float] = None
    gps_longitude: Optional[float] = None
    capture_date: Optional[str] = None
    device_model: Optional[str] = None
    original_format: Optional[str] = None
    original_size_bytes: int = 0


@dataclass
class ProcessedImage:
    """Result of image pre-processing."""
    id: str = ""
    original_filename: str = ""
    processed_path: str = ""
    metadata: ImageMetadata = field(default_factory=ImageMetadata)
    width: int = 0
    height: int = 0
    size_bytes: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "original_filename": self.original_filename,
            "processed_path": self.processed_path,
            "width": self.width,
            "height": self.height,
            "size_bytes": self.size_bytes,
            "metadata": {
                "gps_latitude": self.metadata.gps_latitude,
                "gps_longitude": self.metadata.gps_longitude,
                "capture_date": self.metadata.capture_date,
                "device_model": self.metadata.device_model,
                "original_format": self.metadata.original_format,
                "original_size_bytes": self.metadata.original_size_bytes,
            },
        }


def _dms_to_decimal(dms_tuple, ref: str) -> Optional[float]:
    """Convert EXIF GPS DMS (degrees, minutes, seconds) to decimal."""
    try:
        degrees = dms_tuple[0][0] / dms_tuple[0][1]
        minutes = dms_tuple[1][0] / dms_tuple[1][1]
        seconds = dms_tuple[2][0] / dms_tuple[2][1]
        decimal = degrees + minutes / 60 + seconds / 3600
        if ref in ("S", "W"):
            decimal = -decimal
        return round(decimal, 6)
    except (TypeError, ZeroDivisionError, IndexError):
        return None


def _extract_metadata(img: Image.Image, original_bytes: bytes) -> ImageMetadata:
    """Extract EXIF metadata from PIL Image.
    
    Uses piexif as primary source, with PIL getexif() as fallback.
    Tries multiple date tags: DateTimeOriginal > DateTimeDigitized > DateTime.
    """
    import logging
    logger = logging.getLogger("preprocessor")
    
    meta = ImageMetadata(
        original_format=img.format or "UNKNOWN",
        original_size_bytes=len(original_bytes),
    )

    # ── Strategy 1: piexif (most reliable for GPS + full EXIF) ──
    exif_dict = None
    try:
        exif_dict = piexif.load(original_bytes)
    except Exception as e:
        logger.debug(f"piexif.load failed: {e}")

    if exif_dict:
        # Device model
        zeroth = exif_dict.get("0th", {})
        if piexif.ImageIFD.Model in zeroth:
            raw = zeroth[piexif.ImageIFD.Model]
            meta.device_model = raw.decode("utf-8", errors="ignore").strip("\x00 ")

        # Capture date — try multiple tags in priority order
        exif_ifd = exif_dict.get("Exif", {})
        date_tags = [
            piexif.ExifIFD.DateTimeOriginal,    # Primary: when photo was taken
            piexif.ExifIFD.DateTimeDigitized,    # Fallback: when digitized
        ]
        for tag in date_tags:
            if tag in exif_ifd:
                raw = exif_ifd[tag]
                date_str = raw.decode("utf-8", errors="ignore").strip("\x00 ")
                if date_str and date_str != "0000:00:00 00:00:00":
                    meta.capture_date = date_str
                    break

        # If still no date, try DateTime from 0th IFD (last resort from piexif)
        if not meta.capture_date and piexif.ImageIFD.DateTime in zeroth:
            raw = zeroth[piexif.ImageIFD.DateTime]
            date_str = raw.decode("utf-8", errors="ignore").strip("\x00 ")
            if date_str and date_str != "0000:00:00 00:00:00":
                meta.capture_date = date_str

        # GPS
        gps_data = exif_dict.get("GPS", {})
        if gps_data:
            lat_dms = gps_data.get(piexif.GPSIFD.GPSLatitude)
            lat_ref = gps_data.get(piexif.GPSIFD.GPSLatitudeRef, b"N")
            lon_dms = gps_data.get(piexif.GPSIFD.GPSLongitude)
            lon_ref = gps_data.get(piexif.GPSIFD.GPSLongitudeRef, b"E")

            if lat_dms and lon_dms:
                if isinstance(lat_ref, bytes):
                    lat_ref = lat_ref.decode()
                if isinstance(lon_ref, bytes):
                    lon_ref = lon_ref.decode()
                meta.gps_latitude = _dms_to_decimal(lat_dms, lat_ref)
                meta.gps_longitude = _dms_to_decimal(lon_dms, lon_ref)

    # ── Strategy 2: PIL getexif() fallback (handles panoramas, edited photos) ──
    if not meta.capture_date or not meta.device_model:
        try:
            pil_exif = img.getexif()
            if pil_exif:
                # Device model fallback
                if not meta.device_model:
                    model_val = pil_exif.get(0x0110)  # Model tag
                    if model_val:
                        meta.device_model = str(model_val).strip("\x00 ")

                # Date fallback — try multiple tags
                if not meta.capture_date:
                    # Try EXIF IFD sub-tags
                    exif_sub = pil_exif.get_ifd(0x8769)  # ExifIFD pointer
                    if exif_sub:
                        for tag_id in [0x9003, 0x9004]:  # DateTimeOriginal, DateTimeDigitized
                            val = exif_sub.get(tag_id)
                            if val and str(val).strip() != "0000:00:00 00:00:00":
                                meta.capture_date = str(val).strip("\x00 ")
                                break

                    # Last resort: DateTime from main IFD
                    if not meta.capture_date:
                        dt_val = pil_exif.get(0x0132)  # DateTime tag
                        if dt_val and str(dt_val).strip() != "0000:00:00 00:00:00":
                            meta.capture_date = str(dt_val).strip("\x00 ")

                # GPS fallback via PIL
                if not meta.gps_latitude or not meta.gps_longitude:
                    gps_ifd = pil_exif.get_ifd(0x8825)  # GPSInfo pointer
                    if gps_ifd:
                        lat = gps_ifd.get(2)   # GPSLatitude
                        lat_r = gps_ifd.get(1)  # GPSLatitudeRef
                        lon = gps_ifd.get(4)   # GPSLongitude
                        lon_r = gps_ifd.get(3)  # GPSLongitudeRef
                        if lat and lon:
                            try:
                                lat_dec = lat[0] + lat[1] / 60 + lat[2] / 3600
                                lon_dec = lon[0] + lon[1] / 60 + lon[2] / 3600
                                if lat_r == "S":
                                    lat_dec = -lat_dec
                                if lon_r == "W":
                                    lon_dec = -lon_dec
                                meta.gps_latitude = round(lat_dec, 6)
                                meta.gps_longitude = round(lon_dec, 6)
                            except (TypeError, IndexError, ZeroDivisionError):
                                pass
        except Exception as e:
            logger.debug(f"PIL getexif fallback failed: {e}")

    if meta.capture_date:
        logger.info(f"EXIF date extracted: {meta.capture_date}")
    else:
        logger.warning(f"No EXIF date found in image (format={meta.original_format})")

    return meta


def _compress_image(img: Image.Image, exif_bytes: bytes, max_bytes: int = MAX_IMAGE_SIZE_BYTES) -> tuple[bytes, int]:
    """Compress image to JPEG under max_bytes, preserving EXIF."""
    quality = JPEG_QUALITY

    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    while quality >= 20:
        buffer = io.BytesIO()
        if exif_bytes:
            img.save(buffer, format="JPEG", quality=quality, exif=exif_bytes)
        else:
            img.save(buffer, format="JPEG", quality=quality)
        data = buffer.getvalue()
        if len(data) <= max_bytes:
            return data, quality
        quality -= 5

    # If still too large, resize
    factor = 0.9
    while factor > 0.3:
        new_size = (int(img.width * factor), int(img.height * factor))
        resized = img.resize(new_size, Image.LANCZOS)
        buffer = io.BytesIO()
        if exif_bytes:
            resized.save(buffer, format="JPEG", quality=60, exif=exif_bytes)
        else:
            resized.save(buffer, format="JPEG", quality=60)
        data = buffer.getvalue()
        if len(data) <= max_bytes:
            return data, 60
        factor -= 0.1

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=20)
    return buffer.getvalue(), 20


class ImagePreprocessor:
    """Handles batch image preprocessing."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.session_dir = os.path.join(UPLOAD_DIR, session_id)
        os.makedirs(self.session_dir, exist_ok=True)

    def _process_file_sync(self, filename: str, file_bytes: bytes) -> ProcessedImage:
        """Synchronous CPU-bound PIL processing."""
        img = Image.open(io.BytesIO(file_bytes))
        metadata = _extract_metadata(img, file_bytes)

        # Extract EXIF bytes for preservation
        exif_bytes = b""
        try:
            exif_dict = piexif.load(file_bytes)
            exif_bytes = piexif.dump(exif_dict)
        except Exception:
            pass

        # ⚡ Immediate downscale to max 2000px – cuts RAM from 36MB to ~7MB per image
        MAX_DIM = 2000
        if img.width > MAX_DIM or img.height > MAX_DIM:
            ratio = min(MAX_DIM / img.width, MAX_DIM / img.height)
            new_size = (int(img.width * ratio), int(img.height * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        # Convert and compress
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        compressed_data, _ = _compress_image(img, exif_bytes)

        # Save processed image
        image_id = str(uuid.uuid4())[:8]
        output_filename = f"{image_id}.jpg"
        output_path = os.path.join(self.session_dir, output_filename)

        with open(output_path, "wb") as f:
            f.write(compressed_data)

        # Read back for dimensions
        processed_img = Image.open(io.BytesIO(compressed_data))

        return ProcessedImage(
            id=image_id,
            original_filename=filename,
            processed_path=output_path,
            metadata=metadata,
            width=processed_img.width,
            height=processed_img.height,
            size_bytes=len(compressed_data),
        )

    async def process_file(self, filename: str, file_bytes: bytes) -> ProcessedImage:
        """Async wrapper around the CPU-bound PIL processing."""
        import asyncio
        return await asyncio.to_thread(self._process_file_sync, filename, file_bytes)

    async def process_batch(self, files: list[tuple[str, bytes]]) -> list[ProcessedImage]:
        """Process multiple image files."""
        results = []
        for filename, file_bytes in files:
            result = await self.process_file(filename, file_bytes)
            results.append(result)
        return results
