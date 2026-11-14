import asyncio
import io
import uuid
from pathlib import Path

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError

UPLOAD_DIR = Path(__file__).parent.parent.parent / "static" / "uploads"
ALLOWED_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
ALLOWED_DOCUMENT_TYPES = ALLOWED_TYPES | {"application/pdf"}
MAX_SIZE = 12 * 1024 * 1024  # input limit before compression
MAX_DOCUMENT_SIZE = 8 * 1024 * 1024
DEFAULT_QUALITY = 82
DOCUMENT_QUALITY = 75
TARGET_BYTES = 450 * 1024
DOCUMENT_TARGET_BYTES = 300 * 1024


def ensure_upload_dir():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _validate(file: UploadFile, allowed: set[str] | None = None, max_size: int = MAX_SIZE):
    allowed = allowed or ALLOWED_TYPES
    if file.content_type not in allowed:
        raise ValueError(
            f"Tipo no permitido: {file.content_type}. Usa JPEG, PNG, WebP o PDF."
        )
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size > max_size:
        raise ValueError(f"Archivo demasiado grande. Máximo {max_size // (1024 * 1024)} MB.")


def _compress(
    content: bytes,
    size: int,
    quality: int,
    target_bytes: int = TARGET_BYTES,
) -> bytes:
    """Resize within a square, strip metadata and encode as WebP."""
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.load()
            image = ImageOps.exif_transpose(source)

            # Flatten transparency onto white so the WebP always renders well.
            if image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            ):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.split()[-1])
                image = background
            else:
                image = image.convert("RGB")

            # Keep the whole image visible: scale it down to fit inside the
            # square without cropping. Small images are left untouched.
            image.thumbnail((size, size), Image.Resampling.LANCZOS)

            # Real phone photos compress very well, but noisy images may still
            # exceed the target. Step the quality down instead of storing
            # several hundred kilobytes per dish.
            encoded = b""
            for attempt_quality in (quality, max(quality - 10, 68), max(quality - 20, 60)):
                output = io.BytesIO()
                image.save(
                    output,
                    format="WEBP",
                    quality=attempt_quality,
                    method=6,
                    optimize=True,
                )
                encoded = output.getvalue()
                if len(encoded) <= target_bytes:
                    break
            return encoded
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("El archivo no es una imagen válida") from exc


async def save_upload(
    file: UploadFile,
    size: int = 800,
    quality: int = DEFAULT_QUALITY,
) -> str:
    """Optimize and store an image, returning its public URL.

    Images are scaled to fit inside ``size x size`` without cropping, converted
    to WebP and stripped of EXIF metadata. A 4 MB phone photo usually ends up
    between 80 and 300 KB.
    """
    _validate(file)
    content = await file.read()
    if not content:
        raise ValueError("El archivo está vacío")

    ensure_upload_dir()
    processed = await asyncio.to_thread(_compress, content, size, quality)

    filename = f"{uuid.uuid4().hex}.webp"
    destination = UPLOAD_DIR / filename
    destination.write_bytes(processed)
    return f"/static/uploads/{filename}"


async def save_document(file: UploadFile) -> str:
    """Store a receipt or payment proof, accepting images or PDF.

    Images are resized to a readable size and converted to WebP with a smaller
    target size. PDFs are stored as-is after validating the file signature.
    """
    _validate(file, ALLOWED_DOCUMENT_TYPES, MAX_DOCUMENT_SIZE)
    content = await file.read()
    if not content:
        raise ValueError("El archivo está vacío")

    ensure_upload_dir()
    is_pdf = file.content_type == "application/pdf" or content.startswith(b"%PDF")
    if is_pdf:
        if not content.startswith(b"%PDF"):
            raise ValueError("El archivo no es un PDF válido")
        filename = f"{uuid.uuid4().hex}.pdf"
        destination = UPLOAD_DIR / filename
        destination.write_bytes(content)
        return f"/static/uploads/{filename}"

    processed = await asyncio.to_thread(
        _compress,
        content,
        1400,
        DOCUMENT_QUALITY,
        DOCUMENT_TARGET_BYTES,
    )
    filename = f"{uuid.uuid4().hex}.webp"
    destination = UPLOAD_DIR / filename
    destination.write_bytes(processed)
    return f"/static/uploads/{filename}"


def delete_upload(url: str | None) -> None:
    """Remove a previously stored local upload (best effort)."""
    if not url or not url.startswith("/static/uploads/"):
        return
    filename = Path(url).name
    if not filename or filename in (".", ".."):
        return
    path = UPLOAD_DIR / filename
    try:
        path.unlink()
    except FileNotFoundError:
        pass
