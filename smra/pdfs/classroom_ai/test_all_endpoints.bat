@echo off
setlocal enabledelayedexpansion

echo === 1: GET / ===
curl -s -i http://127.0.0.1:8000/
echo.

echo === 2: GET /api/v1/debug/openai-test ===
curl -s -i http://127.0.0.1:8000/api/v1/debug/openai-test
echo.

echo === 3: POST /api/v1/explain/text ===
curl -s -i -X POST http://127.0.0.1:8000/api/v1/explain/text -H "Content-Type: application/json" -d "{\"chapter_text\":\"Photosynthesis is the process by which plants convert light energy into chemical energy used to produce sugars and oxygen. This short passage is for endpoint testing purposes.\",\"output_language\":\"english\"}"
echo.

echo === 4: POST /api/v1/illustration ===
curl -s -i -X POST http://127.0.0.1:8000/api/v1/illustration -H "Content-Type: application/json" -d "{\"prompt\":\"leaf cell diagram\",\"topic_hint\":\"Photosynthesis\",\"visual_kind\":\"diagram\",\"style\":\"diagramPro\"}"
echo.

echo === 5: POST /api/v1/flashcards/generate ===
curl -s -i -X POST http://127.0.0.1:8000/api/v1/flashcards/generate -H "Content-Type: application/json" -d "{\"topic\":\"Photosynthesis\",\"card_count\":4}"
echo.

echo === 6: POST /api/v1/quiz/generate ===
curl -s -i -X POST http://127.0.0.1:8000/api/v1/quiz/generate -H "Content-Type: application/json" -d "{\"topic\":\"Photosynthesis\",\"question_count\":3}"
echo.

echo === 7: POST /api/v1/slides/generate ===
curl -s -i -X POST http://127.0.0.1:8000/api/v1/slides/generate -H "Content-Type: application/json" -d "{\"topic\":\"Photosynthesis\",\"slide_count\":3}"
echo.

echo === 8: POST /api/v1/infographic/generate ===
curl -s -i -X POST http://127.0.0.1:8000/api/v1/infographic/generate -H "Content-Type: application/json" -d "{\"topic\":\"Photosynthesis\"}"
echo.

echo === 9: POST /api/v1/audio/speech ===
curl -s -i -X POST http://127.0.0.1:8000/api/v1/audio/speech -H "Content-Type: application/json" -d "{\"context_text\":\"Photosynthesis converts light energy into chemical energy; plants capture sunlight to make sugars and release oxygen. This sentence ensures the minimum length for TTS testing.\",\"openai_voice\":\"nova\"}"
echo.

echo === 10: POST /api/v1/video/jobs ===
curl -s -i -X POST http://127.0.0.1:8000/api/v1/video/jobs -H "Content-Type: application/json" -d "{\"prompt\":\"Short explainer: Photosynthesis overview for testing.\",\"stack\":\"openai\",\"seconds\":\"4\"}"
echo.

echo All done.
endlocal
