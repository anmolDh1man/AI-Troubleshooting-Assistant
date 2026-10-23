"""Verify that the Phase 0 environment works: packages, embedding model, and ChromaDB."""

import sys
from importlib.metadata import version

print(f"Python: {sys.version.split()[0]}  ({sys.executable})")

for pkg in ["streamlit", "chromadb", "sentence-transformers", "torch", "python-dotenv", "pytest"]:
    print(f"  {pkg:<22} {version(pkg)}")

# 1. Embedding model (downloads ~90 MB on the first run)
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
texts = [
    "Payment API is returning HTTP 500 errors",
    "Checkout service throws internal server error",
    "Printer is out of paper",
]
embeddings = model.encode(texts, normalize_embeddings=True)
print(f"\nEmbedding shape: {embeddings.shape}  (expected: (3, 384))")

# 2. ChromaDB in-memory collection using our own embeddings
import chromadb

client = chromadb.Client()
collection = client.create_collection(name="setup_check", metadata={"hnsw:space": "cosine"})
collection.add(ids=["a", "b", "c"], documents=texts, embeddings=embeddings.tolist())

query = model.encode(["payment api 500 error"], normalize_embeddings=True).tolist()
result = collection.query(query_embeddings=query, n_results=3)

print("\nQuery: 'payment api 500 error'")
for doc_id, dist, doc in zip(result["ids"][0], result["distances"][0], result["documents"][0]):
    print(f"  {doc_id}  similarity={1 - dist:.3f}  {doc}")

print("\nSetup check passed.")
