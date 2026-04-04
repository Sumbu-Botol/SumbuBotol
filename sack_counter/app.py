"""
Sack Counter — FastAPI Web Application
=======================================
Endpoint:
  GET  /                    → Halaman utama (upload UI)
  POST /detect/image        → Upload gambar, kembalikan gambar teranotasi + hitungan
  POST /detect/video        → Upload video, kembalikan video teranotasi + statistik
  GET  /results/{filename}  → Ambil file hasil (gambar/video)
  GET  /health              → Health check
"""

import os
import uuid
import shutil
import asyncio
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
RESULT_DIR = BASE_DIR / "results"
UPLOAD_DIR.mkdir(exist_ok=True)
RESULT_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Sack Counting Detection",
    description="API untuk mendeteksi dan menghitung karung dari foto/video menggunakan YOLOv8",
    version="1.0.0",
)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

# Lazy-load detector
_detector = None



ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
ALLOWED_VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
MAX_FILE_SIZE_MB = 200


def get_detector():
    global _detector
    if _detector is None:
        from detector import SackDetector
        model_path = os.getenv("SACK_MODEL_PATH", "yolov8n.pt")
        confidence = float(os.getenv("CONFIDENCE_THRESHOLD", "0.40"))
        _detector = SackDetector(model_path=model_path, confidence_threshold=confidence)
    return _detector


def cleanup_file(path: str):
    """Hapus file temporary setelah dikirim ke client."""
    try:
        os.remove(path)
    except OSError:
        pass


def validate_file(file: UploadFile, allowed_exts: set) -> str:
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_exts:
        raise HTTPException(
            status_code=400,
            detail=f"Format tidak didukung: '{ext}'. Gunakan: {', '.join(sorted(allowed_exts))}",
        )
    return ext


async def save_upload(file: UploadFile, ext: str) -> Path:
    filename = f"{uuid.uuid4().hex}{ext}"
    path = UPLOAD_DIR / filename
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        path.unlink()
        raise HTTPException(
            status_code=413,
            detail=f"File terlalu besar ({size_mb:.1f} MB). Maksimum {MAX_FILE_SIZE_MB} MB.",
        )
    return path


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
async def health():
    return {"status": "ok", "service": "sack-counting-detection"}


@app.post("/detect/image")
async def detect_image(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Gambar (JPG/PNG/BMP/WEBP)"),
):
    """
    Upload gambar → deteksi karung → kembalikan JSON + gambar teranotasi.

    Response JSON:
    ```json
    {
      "count": 12,
      "confidence_scores": [0.92, 0.87, ...],
      "bounding_boxes": [[x1,y1,x2,y2], ...],
      "result_url": "/results/abc123.jpg"
    }
    ```
    """
    ext = validate_file(file, ALLOWED_IMAGE_EXT)
    input_path = await save_upload(file, ext)

    result_filename = f"result_{uuid.uuid4().hex}.jpg"
    result_path = RESULT_DIR / result_filename

    try:
        detector = get_detector()
        # Jalankan di thread agar tidak block event loop
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            detector.process_image_file,
            str(input_path),
            str(result_path),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deteksi: {str(e)}")
    finally:
        background_tasks.add_task(cleanup_file, str(input_path))

    return JSONResponse({
        "count": result.count,
        "confidence_scores": result.confidence_scores,
        "bounding_boxes": [list(b) for b in result.bounding_boxes],
        "result_url": f"/results/{result_filename}",
    })


@app.post("/detect/video")
async def detect_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Video (MP4/AVI/MOV/MKV)"),
):
    """
    Upload video → deteksi karung per frame → kembalikan JSON + video teranotasi.

    Response JSON:
    ```json
    {
      "total_frames": 300,
      "avg_count": 8.5,
      "max_count": 12,
      "min_count": 5,
      "result_url": "/results/abc123.mp4"
    }
    ```
    """
    ext = validate_file(file, ALLOWED_VIDEO_EXT)
    input_path = await save_upload(file, ext)

    result_filename = f"result_{uuid.uuid4().hex}.mp4"
    result_path = RESULT_DIR / result_filename

    try:
        detector = get_detector()
        loop = asyncio.get_event_loop()
        stats = await loop.run_in_executor(
            None,
            detector.process_video_file,
            str(input_path),
            str(result_path),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deteksi video: {str(e)}")
    finally:
        background_tasks.add_task(cleanup_file, str(input_path))

    return JSONResponse({
        **stats,
        "result_url": f"/results/{result_filename}",
    })


@app.get("/results/{filename}")
async def get_result(filename: str, background_tasks: BackgroundTasks):
    """Ambil file hasil (gambar/video) lalu hapus dari server setelah diunduh."""
    path = RESULT_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File hasil tidak ditemukan")

    # Tentukan media type
    ext = path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".mp4": "video/mp4",
        ".avi": "video/x-msvideo",
        ".mov": "video/quicktime",
    }
    media_type = media_types.get(ext, "application/octet-stream")

    background_tasks.add_task(cleanup_file, str(path))
    return FileResponse(path, media_type=media_type, filename=filename)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
