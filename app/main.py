"""FastAPI entry point for RemoveBG."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .processor import InvalidImage, parse_hex_color, prepare_image, remove_background
from .storage import Archive, safe_client_filename


APP_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = APP_ROOT / "static"
DATA_ROOT = Path(os.getenv("REMOVEBG_DATA_DIR", "/data"))
MAX_UPLOAD_BYTES = int(os.getenv("REMOVEBG_MAX_UPLOAD_MB", "15")) * 1024 * 1024
MAX_PIXELS = int(os.getenv("REMOVEBG_MAX_PIXELS", "12000000"))
MAX_CONCURRENCY = max(1, int(os.getenv("REMOVEBG_MAX_CONCURRENCY", "1")))
RATE_LIMIT = max(1, int(os.getenv("REMOVEBG_RATE_LIMIT", "20")))
RATE_WINDOW_SECONDS = max(60, int(os.getenv("REMOVEBG_RATE_WINDOW_SECONDS", "600")))
ALLOWED_HOSTS = [
    host.strip()
    for host in os.getenv(
        "REMOVEBG_ALLOWED_HOSTS", "removebg.ananaba.be,localhost,127.0.0.1,removebg"
    ).split(",")
    if host.strip()
]

archive = Archive(
    DATA_ROOT,
    retention_days=int(os.getenv("REMOVEBG_RETENTION_DAYS", "90")),
    save_originals=os.getenv("REMOVEBG_SAVE_ORIGINALS", "true").lower() in {"1", "true", "yes"},
)
processing_slots = asyncio.Semaphore(MAX_CONCURRENCY)


class RateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        async with self.lock:
            bucket = self.hits[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                return False
            bucket.append(now)

            if len(self.hits) > 10_000:
                empty_keys = [name for name, values in self.hits.items() if not values or values[-1] < cutoff]
                for name in empty_keys[:2_000]:
                    self.hits.pop(name, None)
            return True


rate_limiter = RateLimiter(RATE_LIMIT, RATE_WINDOW_SECONDS)

app = FastAPI(
    title="RemoveBG",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)
app.mount("/assets", StaticFiles(directory=STATIC_ROOT), name="assets")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self' https://dashboard.ananaba.be; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": str(exc.detail)})


@app.get("/", include_in_schema=False)
async def home() -> FileResponse:
    return FileResponse(STATIC_ROOT / "index.html")


@app.get("/healthz", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def read_upload_limited(upload: UploadFile) -> bytes:
    data = bytearray()
    while chunk := await upload.read(1024 * 1024):
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Le fichier dépasse la limite de {MAX_UPLOAD_BYTES // (1024 * 1024)} Mo.",
            )
    return bytes(data)


def client_ip(request: Request) -> str:
    cloudflare_ip = request.headers.get("CF-Connecting-IP", "").strip()
    if cloudflare_ip:
        return cloudflare_ip[:64]
    return (request.client.host if request.client else "unknown")[:64]


@app.post("/api/remove-background", include_in_schema=False)
async def process(
    request: Request,
    image: UploadFile = File(...),
    tolerance: int = Form(30),
    background_color: str = Form(""),
    remove_enclosed: bool = Form(True),
) -> Response:
    if not await rate_limiter.allow(client_ip(request)):
        raise HTTPException(
            status_code=429,
            detail="Trop de traitements. Réessaie dans quelques minutes.",
        )

    if image.content_type not in {"image/png", "image/jpeg", "image/webp"}:
        raise HTTPException(status_code=415, detail="Formats acceptés : PNG, JPEG et WebP.")
    if not 0 <= tolerance <= 255:
        raise HTTPException(status_code=422, detail="La tolérance doit être comprise entre 0 et 255.")

    raw = await read_upload_limited(image)
    await image.close()
    if not raw:
        raise HTTPException(status_code=400, detail="Le fichier est vide.")

    try:
        prepared = await asyncio.to_thread(prepare_image, raw, MAX_PIXELS)
        selected_color = parse_hex_color(background_color)
    except (InvalidImage, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    started = time.perf_counter()
    async with processing_slots:
        try:
            result_png, detected_color, removed_pixels = await asyncio.to_thread(
                remove_background,
                prepared.image,
                tolerance,
                selected_color,
                remove_enclosed,
            )
        except (MemoryError, OSError):
            raise HTTPException(
                status_code=503,
                detail="Le serveur n’a pas assez de mémoire pour traiter cette image.",
            ) from None

    elapsed_ms = round((time.perf_counter() - started) * 1000)
    job_id = uuid.uuid4().hex
    cleaned_name = safe_client_filename(image.filename)
    metadata = {
        "client_filename": cleaned_name,
        "detected_format": prepared.detected_format,
        "width": prepared.width,
        "height": prepared.height,
        "input_bytes": len(raw),
        "sanitized_bytes": len(prepared.sanitized_png),
        "result_bytes": len(result_png),
        "tolerance": tolerance,
        "background_rgb": list(detected_color),
        "background_mode": "manual" if selected_color else "automatic",
        "remove_enclosed": remove_enclosed,
        "removed_pixels": removed_pixels,
        "processing_ms": elapsed_ms,
    }

    try:
        await asyncio.to_thread(
            archive.store,
            job_id=job_id,
            original_png=prepared.sanitized_png,
            result_png=result_png,
            metadata=metadata,
        )
    except OSError:
        raise HTTPException(
            status_code=507,
            detail="Le traitement a réussi, mais l’archive locale ne peut pas être écrite.",
        ) from None

    return Response(
        content=result_png,
        media_type="image/png",
        headers={
            "Content-Disposition": 'attachment; filename="removebg-result.png"',
            "X-Job-ID": job_id,
            "X-Processing-Time-Ms": str(elapsed_ms),
            "X-Background-Color": ",".join(str(value) for value in detected_color),
        },
    )
