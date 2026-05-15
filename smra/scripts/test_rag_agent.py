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
    from agents.rag_agent import run_rag_agent
except Exception:
    from smra.agents.rag_agent import run_rag_agent

q = "What was NVIDIA revenue in 2024?"
print(f"Running RAG agent query: {q}\n")

try:
    r = run_rag_agent(q)
except Exception as e:
    print("ERROR while running run_rag_agent:")
    raise

print('\nRESULT')
print('ANSWER:', r.get('answer'))
print('SOURCES:', r.get('sources'))
