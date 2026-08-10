#!/usr/bin/env bash
# Hugging Face Spaces entrypoint: FastAPI (ingestion + /health) + Streamlit UI.
# Spaces must expose the UI on port 7860.
set -euo pipefail

PORT="${PORT:-7860}"
API_PORT="${API_PORT:-8010}"

echo "[smra] starting FastAPI on 127.0.0.1:${API_PORT} (ingestion scheduler)"
python -m uvicorn smra.api:app --host 127.0.0.1 --port "${API_PORT}" &
API_PID=$!

cleanup() {
  echo "[smra] shutting down API (pid ${API_PID})"
  kill "${API_PID}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait briefly so /health is up before UI traffic (best-effort).
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${API_PORT}/health', timeout=1)" 2>/dev/null; then
    echo "[smra] API healthy"
    break
  fi
  sleep 1
done

echo "[smra] starting Streamlit on 0.0.0.0:${PORT}"
exec python -m streamlit run smra/app.py \
  --server.port="${PORT}" \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false
