from pathlib import Path
import os
import sys
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore

smra_root = Path(__file__).resolve().parents[1]
load_dotenv(smra_root / ".env")
sys.path.insert(0, str(smra_root))

embeddings = HuggingFaceEmbeddings(
    model_name='sentence-transformers/all-MiniLM-L6-v2',
    model_kwargs={'device': 'cpu'},
)
store = PineconeVectorStore(
    index_name=os.getenv('PINECONE_INDEX', 'smra-index'),
    embedding=embeddings,
)

query = 'Apple total net sales revenue'
docs = store.similarity_search(query, k=2)
print(f'Query: {query}')
print(f'Returned {len(docs)} chunks')
for i, d in enumerate(docs):
    print(f'--- Chunk {i + 1} ---')
    print(d.page_content[:400])
    print()
