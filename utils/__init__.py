"""Compatibility shim package to allow legacy imports like `from utils.llm import call_llm`.

This package forwards to `smra.utils` so both `from utils...` and `from smra.utils...` work.
"""

from . import llm  # re-export
