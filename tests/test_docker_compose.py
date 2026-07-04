"""Sanity checks for docker-compose.yml structure."""
from pathlib import Path

COMPOSE_PATH = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_compose_file_exists():
    assert COMPOSE_PATH.is_file()


def test_compose_declares_core_services():
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    for service in ("postgres:", "redis:", "api:"):
        assert service in text
    assert "smra/.env" in text
    assert "DATABASE_URL" in text
    assert "REDIS_URL" in text
