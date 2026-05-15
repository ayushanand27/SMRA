import os
import sys
from pathlib import Path
from dotenv import load_dotenv

script_dir = Path(__file__).resolve().parent
smra_root = script_dir.parent
env_path = smra_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)

sys.path.insert(0, str(smra_root))

try:
    from router import classify_intent
except Exception:
    from smra.router import classify_intent

queries = [
    "Show me NVDA 20 day moving average",
    "Latest news about Tesla",
    "What was Apple revenue in annual report",
]

for q in queries:
    print(q, "->", classify_intent(q))
