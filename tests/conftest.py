"""Shared test setup.

Runs before any test module imports src.config, so every test (including the
Streamlit UI tests) uses a throwaway ChromaDB folder instead of the project's
chroma_db/. python-dotenv does not override variables that are already set.
"""

import atexit
import os
import shutil
import tempfile

_TEST_CHROMA_DIR = tempfile.mkdtemp(prefix="test_chroma_")
os.environ["CHROMA_DIR"] = _TEST_CHROMA_DIR
atexit.register(shutil.rmtree, _TEST_CHROMA_DIR, ignore_errors=True)
