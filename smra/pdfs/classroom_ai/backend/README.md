# ClassroomAI — backend

The FastAPI application lives in the **`app/` package at the repository root** (next to `requirements.txt`). This file documents how it fits together; it is not a separate Python package named `backend`.

FastAPI exposes `/api/v1` JSON and multipart endpoints. The UI (Vite dev server) proxies `/api` to this app (see `frontend/vite.config.ts`).

## Run locally

From the **repository root** (not this folder):

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill OPENAI_API_KEY, Ollama URL, etc.
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

OpenAPI docs: `http://127.0.0.1:8000/docs`.

## High-level flow

1. **Config** (`app/core/config.py`) loads environment (API keys, `CORS_ORIGINS`, Ollama base URL, Stable Diffusion URL, etc.).

2. **Router** (`app/api/v1/router.py`) mounts feature routers under prefix `/api/v1` (see `settings.api_v1_prefix` in config).

3. **LLM abstraction** (`app/services/llm/`): `get_llm_provider()` returns OpenAI or Ollama based on the caller. Vision requests use image+text messages for screenshots.

4. **Explain** is the core lesson generator:
   - Endpoints: `POST /explain/text`, `/explain/text-form`, `/explain/image`, `/explain/images` (`app/api/v1/endpoints/explain.py`).
   - Implementation: `app/services/explanation.py` asks the model for **strict JSON** (markdown explanation, examples, visual briefs, optional `mermaid_diagram`, video prompt, etc.).
   - `_sanitize_mermaid_diagram()` strips fences, finds a valid Mermaid header line, normalizes smart quotes and dashes so the client can render with Mermaid 11.

5. **Downstream features** each have a thin endpoint + service module that calls the same LLM stack (and sometimes image APIs):
   - Quiz → `services/quiz.py`
   - Slides (PPTX) → `services/slides.py`
   - Flashcards → `services/flashcards.py`
   - Infographic → `services/infographic.py` (DALL·E or local SD WebUI)
   - Illustration → `services/illustration_*.py`
   - Audio → `services/tts.py` (OpenAI TTS or edge-tts)
   - Video → `services/video_openai.py` (Sora) or `services/video_opensource.py` (local MP4)

6. **Stack parameter**: Clients send `stack=openai|opensource` (form field or implied). Endpoints map that to the right provider for chat, images, and TTS.

## Request path (typical “full lesson” from the UI)

The React app calls **Explain** first, then (client-side) quiz, slides, flashcards, infographic, and audio in sequence. Each step is a separate HTTP request to the matching `/api/v1/...` route; the backend is stateless aside from job IDs (video/audio file handles, slide deck IDs).

## Diagram / Mermaid notes

Invalid Mermaid from models used to surface as error SVGs in the browser. The frontend now validates with `mermaid.parse()` and rejects SVGs that still contain Mermaid’s error text. The prompt in `explanation.py` instructs ASCII node IDs and quoted labels to reduce syntax errors.
