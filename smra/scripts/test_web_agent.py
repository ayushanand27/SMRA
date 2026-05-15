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

# Try both import styles
try:
    from agents.web_agent import run_web_agent
except Exception:
    from smra.agents.web_agent import run_web_agent

q = "Latest news about NVIDIA stock"
print(f"Running web agent query: {q}\n")

try:
    r = run_web_agent(q)
except Exception as e:
    print("ERROR while running run_web_agent:")
    raise

print('\nRESULT')
print('ANSWER:', r.get('answer'))
print('SOURCES:', r.get('sources'))
