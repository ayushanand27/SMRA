import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Prepare environment and imports so this can be run from the repo root or from smra/
script_dir = Path(__file__).resolve().parent
smra_root = script_dir.parent
env_path = smra_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)

sys.path.insert(0, str(smra_root))

try:
    from agents.rag_agent import ingest_pdfs
except Exception:
    from smra.agents.rag_agent import ingest_pdfs

pdf_dir = smra_root / "pdfs"
if not pdf_dir.exists():
    print("No 'pdfs/' directory found at:", pdf_dir)
    sys.exit(1)

print("Beginning PDF ingestion from:", pdf_dir)
try:
    ingest_pdfs(str(pdf_dir))
    print("Ingestion completed successfully.")
except Exception as e:
    print("ERROR during ingestion:", e)
    raise
