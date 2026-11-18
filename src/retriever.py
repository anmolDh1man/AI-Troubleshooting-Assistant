"""Semantic retrieval over the knowledge base using local embeddings + ChromaDB.

Reliability (Phase 4): the index is derived data, rebuilt from data/knowledge_base.json whenever it is
missing, stale (KB or model changed), incomplete (wrong chunk count) or unreadable. An index folder that
cannot be opened is moved aside (never deleted) and a fresh one is built. If the collection disappears
while the app runs, search rebuilds it once and retries; if that fails, IndexUnavailableError is raised so
the assistant can tell "index unavailable" apart from other retrieval failures.
"""

import hashlib
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings
from chromadb.errors import NotFoundError
from sentence_transformers import SentenceTransformer

from src.config import CHROMA_DIR, EMBEDDING_MODEL, EMBEDDING_MODEL_REVISION, TOP_K
from src.kb_loader import KBEntry
from src.observability import get_logger

COLLECTION_NAME = "troubleshooting_kb"
logger = get_logger("retriever")


class IndexUnavailableError(RuntimeError):
    """The vector index is missing and could not be rebuilt."""


def _forget_cached_client(path: str) -> None:
    """ChromaDB caches one client "system" per index path. When opening a corrupt store fails, a broken
    system stays cached and a retry on the same path reuses it, so only that one entry is dropped."""
    from chromadb.api.shared_system_client import SharedSystemClient

    SharedSystemClient._identifier_to_system.pop(path, None)
    SharedSystemClient._identifier_to_refcount.pop(path, None)


@dataclass
class RetrievalResult:
    entry: KBEntry
    score: float        # cosine similarity of the best-matching chunk: 1.0 = same meaning, ~0 = unrelated
    matched_text: str   # the title/symptom/keywords chunk that matched best (shown to the user)


class Retriever:
    """Embeds KB chunks once, stores them in ChromaDB, and finds the closest entries for a query."""

    def __init__(self, entries: list[KBEntry], model_name: str = EMBEDDING_MODEL, persist_dir: Path = CHROMA_DIR,
                 model_revision: str | None = EMBEDDING_MODEL_REVISION):
        self.entries = list(entries)
        self.entries_by_id = {entry.id: entry for entry in entries}
        self.model_name = model_name
        self.model_revision = model_revision
        self.persist_dir = Path(persist_dir)
        self.model = SentenceTransformer(model_name, revision=model_revision)
        self.expected_chunks = sum(len(entry.search_chunks()) for entry in entries)
        self.fingerprint = self._fingerprint(entries)
        self.client = self._open_client()
        self.collection = self._load_or_build_collection(self.client, entries)

    def _open_client(self):
        """Open the persistent index; if the folder is unreadable (e.g. corrupted), move it aside and start fresh."""
        try:
            client = chromadb.PersistentClient(path=str(self.persist_dir), settings=Settings(anonymized_telemetry=False))
            client.list_collections()  # forces the SQLite store to be read
            return client
        except Exception as exc:
            backup = self.persist_dir.with_name(f"{self.persist_dir.name}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}")
            logger.error("vector index unreadable; moving it aside and rebuilding",
                         extra={"fields": {"error_type": type(exc).__name__, "recovery": "moved_aside_and_rebuilt"}})
            shutil.move(str(self.persist_dir), str(backup))
            _forget_cached_client(str(self.persist_dir))
            return chromadb.PersistentClient(path=str(self.persist_dir), settings=Settings(anonymized_telemetry=False))

    def _fingerprint(self, entries: list[KBEntry]) -> str:
        """Hash of the embedded text + model name and revision. If any of them changes, the index is rebuilt."""
        content = self.model_name + (self.model_revision or "") + "".join(
            chunk_id + text for entry in entries for chunk_id, text in entry.search_chunks()
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def is_consistent(self, collection=None) -> bool:
        """The collection was built from this KB and model and holds every chunk."""
        collection = collection or self.collection
        return ((collection.metadata or {}).get("kb_fingerprint") == self.fingerprint
                and collection.count() == self.expected_chunks)

    def _load_or_build_collection(self, client, entries: list[KBEntry]):
        try:
            existing = client.get_collection(COLLECTION_NAME)
        except NotFoundError:
            existing = None  # first run, or the collection was removed
        if existing is not None:
            if self.is_consistent(existing):
                return existing
            logger.warning("vector index stale or incomplete; rebuilding", extra={"fields": {"recovery": "rebuilt"}})
            client.delete_collection(COLLECTION_NAME)

        collection = client.create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine", "kb_fingerprint": self.fingerprint},
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

    def rebuild(self) -> None:
        """Recreate the collection from the KB (used when it disappears while the app is running)."""
        self.collection = self._load_or_build_collection(self.client, self.entries)

    def search(self, query: str, top_k: int = TOP_K) -> list[RetrievalResult]:
        """Return the top_k most similar entries, best first, with similarity scores.

        Each entry is scored by its best-matching chunk (max similarity).
        No threshold is applied here: deciding whether a match is "good enough"
        is the assistant's job, so the scores stay visible for debugging and the UI.
        """
        if not query or not query.strip():
            raise ValueError("Query must not be empty")

        query_embedding = self.model.encode([query.strip()], normalize_embeddings=True).tolist()
        try:
            result = self._query(query_embedding, top_k)
        except NotFoundError:
            # The collection vanished (e.g. the index folder was cleared while the app was running).
            logger.warning("vector collection missing during search; rebuilding once", extra={"fields": {"recovery": "rebuild"}})
            try:
                self.rebuild()
                result = self._query(query_embedding, top_k)
            except Exception as exc:
                raise IndexUnavailableError("The vector index is missing and could not be rebuilt") from exc

        best_per_entry: dict[str, RetrievalResult] = {}
        for metadata, distance, text in zip(result["metadatas"][0], result["distances"][0], result["documents"][0]):
            entry_id = metadata["entry_id"]
            score = round(1 - distance, 4)
            if entry_id not in best_per_entry or score > best_per_entry[entry_id].score:
                best_per_entry[entry_id] = RetrievalResult(self.entries_by_id[entry_id], score, text)

        ranked = sorted(best_per_entry.values(), key=lambda r: r.score, reverse=True)
        return ranked[:top_k]

    def _query(self, query_embedding, top_k: int):
        # Fetch enough chunks that top_k distinct entries are almost always present.
        return self.collection.query(
            query_embeddings=query_embedding,
            n_results=min(self.collection.count(), top_k * 10),
        )
