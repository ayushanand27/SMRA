import os
import re
from dotenv import load_dotenv
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore

load_dotenv()
embeddings = HuggingFaceEmbeddings(model_name='sentence-transformers/all-MiniLM-L6-v2', model_kwargs={'device':'cpu'})
store = PineconeVectorStore(index_name=os.getenv('PINECONE_INDEX','smra-index'), embedding=embeddings)
docs = store.similarity_search('Apple net sales revenue total', k=4)

print('Numbers found in chunks:')
for i, d in enumerate(docs):
    numbers = re.findall(r'\$[\d,]+|\d{2,3},\d{3}|\d{4,}', d.page_content)
    print(f'Chunk {i+1}: {numbers[:10]}')
    print(f'  Text preview: {d.page_content[:200]}')
    print()
