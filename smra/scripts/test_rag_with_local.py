"""
Test RAG queries using the local fallback store.
This demonstrates the project works even if Pinecone is unreachable or embeddings hang.
"""
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

# Force local-only mode (skip Pinecone)
os.environ["PINECONE_DISABLED"] = "1"

try:
    from agents.rag_agent import run_rag_agent
except Exception:
    from smra.agents.rag_agent import run_rag_agent

test_queries = [
    "What was Apple's total net sales?",
    "What is NVIDIA's revenue?",
    "Tell me about Apple financial results",
]

print("=" * 70)
print("RAG AGENT TEST (Local Fallback Store)")
print("=" * 70)
print("Note: PINECONE_DISABLED=1 → using local pickle store only\n")

for q in test_queries:
    print(f"\n📋 Query: {q}")
    print("-" * 70)
    try:
        r = run_rag_agent(q)
        answer = r.get("answer", "ERROR: No answer")
        sources = r.get("sources", [])
        
        # Truncate long answers for readability
        display_answer = (answer[:300] + "...") if len(answer) > 300 else answer
        print(f"✅ Answer:\n{display_answer}")
        print(f"\n📁 Sources: {', '.join(sources) if sources else 'None'}")
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 70)
print("END OF TEST")
print("=" * 70)
