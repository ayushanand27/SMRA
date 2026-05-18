import os
from dotenv import load_dotenv
load_dotenv()

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore

embeddings = HuggingFaceEmbeddings(
    model_name="sentence-transformers/all-MiniLM-L6-v2",
    model_kwargs={"device": "cpu"}
)

index_name = os.getenv("PINECONE_INDEX", "smra-index")

# Check what namespace your vectors are actually in (Pinecone SDK v3.x)
from pinecone import Pinecone
pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
idx = pc.Index(index_name)
stats = idx.describe_index_stats()
print("Namespaces in index:", getattr(stats, "namespaces", stats.get("namespaces") if isinstance(stats, dict) else {}))

# Try searching with explicit namespace
namespace = list(stats.namespaces.keys())[0] if stats.namespaces else ""
print(f"Searching in namespace: '{namespace}'")

store = PineconeVectorStore(
    index_name=index_name,
    embedding=embeddings,
    namespace=namespace
)

results = store.similarity_search("revenue", k=3)
print(f"\nFound {len(results)} results")
for i, doc in enumerate(results):
    print(f"\n--- Result {i+1} ---")
    print(f"Source: {doc.metadata.get('source', 'unknown')}")
    print(f"Content: {doc.page_content[:200]}")
