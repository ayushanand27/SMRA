"""Shared pytest fixtures for SMRA test isolation."""
import pytest


@pytest.fixture(autouse=True)
def _reset_module_caches():
    """Clear process-wide cache singletons before/after every test."""
    from smra.cache.semantic_cache import reset_semantic_cache
    from smra.cache.ttl_cache import reset_query_cache

    reset_semantic_cache()
    reset_query_cache()
    yield
    reset_semantic_cache()
    reset_query_cache()
