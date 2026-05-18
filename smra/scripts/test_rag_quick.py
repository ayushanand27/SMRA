from pathlib import Path
import sys
from dotenv import load_dotenv

# Load smra/.env explicitly
smra_root = Path(__file__).resolve().parents[1]
load_dotenv(smra_root / ".env")
sys.path.insert(0, str(smra_root))

from agents.rag_agent import run_rag_agent

for q in [
    "What was Apple total net sales?",
    "What was NVIDIA revenue in 2024?",
]:
    print("\n=== QUERY ===")
    print(q)
    r = run_rag_agent(q)
    print("ANSWER:", r.get("answer", "no answer"))
    print("SOURCES:", r.get("meta", {}).get("sources", []))
    print("SCORES:", r.get("meta", {}).get("scores", []))
