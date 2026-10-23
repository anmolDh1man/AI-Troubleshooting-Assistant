"""Semantic retrieval over the knowledge base using local embeddings + ChromaDB."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from src.config import CHROMA_DIR, EMBEDDING_MODEL, TOP_K
from src.kb_loader import KBEntry

COLLECTION_NAME = "troubleshooting_kb"


@dataclass
class RetrievalResult:
    entry: KBEntry
    score: float        # cosine similarity of the best-matching chunk: 1.0 = same meaning, ~0 = unrelated
    matched_text: str   # the title/symptom/keywords chunk that matched best (shown to the user)


class Retriever:
    """Embeds KB chunks once, stores them in ChromaDB, and finds the closest entries for a query."""

    def __init__(self, entries: list[KBEntry], model_name: str = EMBEDDING_MODEL, persist_dir: Path = CHROMA_DIR):
        self.entries_by_id = {entry.id: entry for entry in entries}
        self.model_name = model_name
        self.model = SentenceTransformer(model_name)
        client = chromadb.PersistentClient(path=str(persist_dir), settings=Settings(anonymized_telemetry=False))
        self.collection = self._load_or_build_collection(client, entries)

    def _fingerprint(self, entries: list[KBEntry]) -> str:
        """Hash of the embedded text + model name. If the KB or model changes, the index is rebuilt."""
        content = self.model_name + "".join(
            chunk_id + text for entry in entries for chunk_id, text in entry.search_chunks()
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def _load_or_build_collection(self, client, entries: list[KBEntry]):
        fingerprint = self._fingerprint(entries)
        try:
            existing = client.get_collection(COLLECTION_NAME)
            if (existing.metadata or {}).get("kb_fingerprint") == fingerprint:
                return existing
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass  # collection does not exist yet

        collection = client.create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine", "kb_fingerprint": fingerprint},
        )
        chunks = [(entry.id, chunk_id, text) for entry in entries for chunk_id, text in entry.search_chunks()]
        embeddings = self.model.encode([text for _, _, text in chunks], normalize_embeddings=True)
        collection.add(
            ids=[chunk_id for _, chunk_id, _ in chunks],
            documents=[text for _, _, text in chunks],
            embeddings=embeddings.tolist(),
            metadatas=[{"entry_id": entry_id} for entry_id, _, _ in chunks],
        )
        return collection

    def search(self, query: str, top_k: int = TOP_K) -> list[RetrievalResult]:
        """Return the top_k most similar entries, best first, with similarity scores.

        Each entry is scored by its best-matching chunk (max similarity).
        No threshold is applied here: deciding whether a match is "good enough"
        is the assistant's job, so the scores stay visible for debugging and the UI.
        """
        if not query or not query.strip():
            raise ValueError("Query must not be empty")

        query_embedding = self.model.encode([query.strip()], normalize_embeddings=True).tolist()
        # Fetch enough chunks that top_k distinct entries are almost always present.
        result = self.collection.query(
            query_embeddings=query_embedding,
            n_results=min(self.collection.count(), top_k * 10),
        )

        best_per_entry: dict[str, RetrievalResult] = {}
        for metadata, distance, text in zip(result["metadatas"][0], result["distances"][0], result["documents"][0]):
            entry_id = metadata["entry_id"]
            score = round(1 - distance, 4)
            if entry_id not in best_per_entry or score > best_per_entry[entry_id].score:
                best_per_entry[entry_id] = RetrievalResult(self.entries_by_id[entry_id], score, text)

        ranked = sorted(best_per_entry.values(), key=lambda r: r.score, reverse=True)
        return ranked[:top_k]
