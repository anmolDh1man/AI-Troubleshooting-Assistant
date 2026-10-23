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
# Calibrated with scripts/calibrate_retrieval.py (see results/retrieval_calibration.csv):
#   score >= HIGH            -> confident match, answer from the entry
#   LOW <= score < HIGH      -> possible match, show it with a warning and ask for details
#   score < LOW              -> not covered by the knowledge base
HIGH_CONFIDENCE_THRESHOLD = float(os.getenv("HIGH_CONFIDENCE_THRESHOLD", "0.45"))
LOW_CONFIDENCE_THRESHOLD = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.30"))
