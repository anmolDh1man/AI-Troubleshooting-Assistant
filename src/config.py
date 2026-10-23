"""Central configuration, read from environment variables (.env) with safe defaults."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

KB_PATH = PROJECT_ROOT / "data" / "knowledge_base.json"
CHROMA_DIR = PROJECT_ROOT / "chroma_db"

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
GENERATOR = os.getenv("GENERATOR", "template")
TOP_K = int(os.getenv("TOP_K", "3"))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.40"))
