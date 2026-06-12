from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import uuid

from fastapi import HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError


AVATAR_MAX_UPLOAD_BYTES = 4 * 1024 * 1024
AVATAR_SIZE = 640
AVATAR_DIR = Path(__file__).resolve().parents[1] / "uploads" / "driver_avatars"
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}


def _ensure_avatar_dir() -> None:
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)


async def process_driver_avatar(file: UploadFile) -> dict:
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(status_code=400, detail="Poza trebuie să fie JPG, PNG sau WEBP")

    raw = await file.read()
    if len(raw) > AVATAR_MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Poza depășește limita de 4 MB")

    try:
        with Image.open(BytesIO(raw)) as image:
            image = image.convert("RGB")
            image.thumbnail((AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (AVATAR_SIZE, AVATAR_SIZE), (245, 245, 245))
            left = (AVATAR_SIZE - image.width) // 2
            top = (AVATAR_SIZE - image.height) // 2
            canvas.paste(image, (left, top))
            buffer = BytesIO()
            canvas.save(buffer, format="WEBP", quality=82, method=6)
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="Fișierul nu este o imagine validă") from exc

    _ensure_avatar_dir()
    avatar_id = str(uuid.uuid4())
    filename = f"{avatar_id}.webp"
    path = AVATAR_DIR / filename
    data = buffer.getvalue()
    path.write_bytes(data)
    return {
        "avatar_id": avatar_id,
        "file_path": str(path),
        "content_type": "image/webp",
        "size": len(data),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
