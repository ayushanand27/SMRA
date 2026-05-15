from fastapi import APIRouter

from app.api.v1.endpoints import audio, explain, flashcards, illustration, infographic, quiz, slides, video

api_router = APIRouter()
api_router.include_router(explain.router, prefix="/explain", tags=["explain"])
api_router.include_router(video.router, prefix="/video", tags=["video"])
api_router.include_router(illustration.router, prefix="/illustration", tags=["illustration"])

api_router.include_router(quiz.router, prefix="/quiz", tags=["quiz"])
api_router.include_router(slides.router, prefix="/slides", tags=["slides"])
api_router.include_router(audio.router, prefix="/audio", tags=["audio"])
api_router.include_router(flashcards.router, prefix="/flashcards", tags=["flashcards"])
api_router.include_router(infographic.router, prefix="/infographic", tags=["infographic"])
