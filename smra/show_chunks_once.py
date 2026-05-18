import os
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore

load_dotenv()
embeddings = HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2', model_kwargs={'device':'cpu'})
store = PineconeVectorStore(index_name=os.getenv('PINECONE_INDEX','smra-index'), embedding=embeddings)
docs = store.similarity_search('Apple total net sales revenue', k=2)
for i, d in enumerate(docs):
    print(f'=== CHUNK {i+1} ===')
    print(d.page_content[:600])
    print()
