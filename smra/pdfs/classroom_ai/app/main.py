import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()

app = FastAPI(
    title="ClassroomAI",
    description="AI explanations and visual plans from chapter text or screenshots.",
    version="0.1.0",
)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/")
def root():
    return {
        "service": "ClassroomAI",
        "docs": "/docs",
        "health": "/health",
        "explain": {
            "text": "POST /api/v1/explain/text (JSON; escape newlines as \\n)",
            "text_form": "POST /api/v1/explain/text-form (form: chapter_text, language, topic_hint)",
            "image": "POST /api/v1/explain/image (single file, Swagger-friendly)",
            "images": "POST /api/v1/explain/images (multiple files)",
        },
        "video": {
            "create_job": "POST /api/v1/video/jobs (OpenAI Sora)",
            "status": "GET /api/v1/video/jobs/{id}",
            "file": "GET /api/v1/video/jobs/{id}/file (MP4 when completed)",
        },
        "slides": {
            "generate": "POST /api/v1/slides/generate (JSON → deck + PPTX)",
            "file": "GET /api/v1/slides/{deck_id}/file (.pptx download)",
        },
        "audio": {
            "speech": "POST /api/v1/audio/speech (JSON → MP3 job id)",
            "file": "GET /api/v1/audio/{audio_id}/file (MP3 download)",
        },
        "flashcards": {"generate": "POST /api/v1/flashcards/generate"},
        "infographic": {"generate": "POST /api/v1/infographic/generate"},
        "web_ui": "cd frontend && npm install && npm run dev (proxies /api to this server)",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
