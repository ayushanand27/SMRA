FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    API_PORT=8010

WORKDIR /app

# System deps for OCR (Tesseract) and PDF rendering (Poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY smra/requirements.txt smra/requirements.txt

# CPU torch first — avoids multi-GB CUDA wheels (needed for HF Spaces free CPU)
RUN python -m pip install --upgrade pip && \
    python -m pip install torch --index-url https://download.pytorch.org/whl/cpu && \
    python -m pip install -r smra/requirements.txt

COPY . .

RUN chmod +x smra/scripts/start_space.sh && \
    useradd --create-home --uid 1000 --shell /bin/bash appuser && \
    chown -R appuser:appuser /app

USER appuser

# Hugging Face Spaces expects the public app on 7860
EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/_stcore/health')" || exit 1

# Dual process: FastAPI (ingestion/rate-limit API) + Streamlit UI
CMD ["bash", "smra/scripts/start_space.sh"]
