"""Legacy import shim: expose call_llm as utils.llm.call_llm by delegating
to `smra.utils.llm`.
"""
try:
    # If running from the repo root where smra is a package
    from smra.utils.llm import call_llm
except Exception as _e:
    # Last resort: fail with a clear message when imported but smra not on path
    def call_llm(*args, **kwargs):
        raise RuntimeError(
            "call_llm shim couldn't locate smra.utils.llm; ensure the repository root is on PYTHONPATH or import smra.utils.llm directly"
        ) from _e

__all__ = ["call_llm"]
