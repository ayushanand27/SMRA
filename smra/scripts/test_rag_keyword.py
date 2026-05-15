"""
Test RAG queries using keyword-based similarity (NO embeddings required).
This bypasses the HuggingFace hang and tests the rest of the pipeline.
"""
import os
import sys
import re
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

from utils.llm import call_llm

# Load local pickle store directly
import pickle
local_store_path = smra_root / "data" / "rag_local_store.pkl"

if not local_store_path.exists():
    print("❌ Local store not found at:", local_store_path)
    sys.exit(1)

with open(local_store_path, "rb") as f:
    store = pickle.load(f)

texts = store.get("texts", [])
metadatas = store.get("metadatas", [])

print("=" * 70)
print("RAG AGENT TEST (Keyword-Based Search - No Embeddings)")
print("=" * 70)
print(f"Loaded {len(texts)} text chunks from local store\n")

RAG_SYSTEM = """You are a financial analyst. Answer using ONLY the context provided.
If context is insufficient, say exactly: "I couldn't find that in the available filings."
Always cite which document/section you found the answer in."""


def keyword_search(query: str, k: int = 4):
    """Simple keyword-based similarity (no embeddings required)."""
    query_words = set(re.findall(r'\w+', query.lower()))
    scored = []
    
    for i, text in enumerate(texts):
        text_words = set(re.findall(r'\w+', text.lower()))
        if not text:
            continue
        
        # Count matching keywords (even one match counts)
        matching = len(query_words & text_words)
        # Prefer longer matches and texts that have query keywords
        score = matching if matching > 0 else (1.0 / (1.0 + len(text) / 1000))
        scored.append((score, i))
    
    # Always return top k results, even if score is low
    scored.sort(reverse=True)
    return [(texts[i], metadatas[i]) for _, i in scored[:k]]


test_queries = [
    "What was Apple's total net sales?",
    "What is NVIDIA's revenue?",
    "Tell me about financial results",
]

for q in test_queries:
    print(f"\n[QUERY] {q}")
    print("-" * 70)
    try:
        # Get relevant chunks using keyword search
        results = keyword_search(q, k=4)
        
        if not results:
            print("[NO MATCH] No relevant content found")
            continue
        
        context = "\n\n---\n\n".join(
            [
                f"[{(m or {}).get('source', 'Unknown')} p{(m or {}).get('page', '?')}]\n{t}"
                for t, m in results
            ]
        )
        
        # Debug: show context length
        print(f"[DEBUG] Context length: {len(context)} chars, {len(context.split())} words")
        print(f"[DEBUG] Context preview: {context[:200]}...")
        
        # Use LLM to synthesize answer
        answer = call_llm(RAG_SYSTEM, f"Context:\n{context}\n\nQuestion: {q}")
        
        # Truncate for readability
        display_answer = (answer[:300] + "...") if len(answer) > 300 else answer
        print(f"[ANSWER]\n{display_answer}")
        
        sources = sorted({(m or {}).get("source", "Unknown") for _, m in results})
        print(f"\n[SOURCES] {', '.join(sources)}")
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()

print("\n" + "=" * 70)
print("END OF TEST")
print("=" * 70)
