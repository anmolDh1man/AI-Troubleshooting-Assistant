# Production-oriented image for the AI Troubleshooting Assistant (CPU only, non-root).
#   docker build -t ai-troubleshooting-assistant .
#   docker run --rm -p 8501:8501 ai-troubleshooting-assistant
# Settings: pass environment variables (-e LOG_LEVEL=WARNING ...) or mount a secrets file read-only at
# /app/.streamlit/secrets.toml. Never bake secrets into the image (see .dockerignore and SECURITY.md).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/home/app/.cache/huggingface \
    CHROMA_DIR=/home/app/index \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

RUN useradd --create-home --uid 10001 app
WORKDIR /app

# CPU-only PyTorch first (the default Linux wheel bundles CUDA libraries of several GB);
# the torch==2.14.1 pin in requirements.txt is then already satisfied.
COPY requirements.txt .
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.1 \
 && pip install -r requirements.txt

COPY --chown=app:app . .
USER app

# Download the pinned embedding model at build time, so a container starts without reaching Hugging Face.
RUN python -c "from src.config import EMBEDDING_MODEL as m, EMBEDDING_MODEL_REVISION as r; \
from sentence_transformers import SentenceTransformer; SentenceTransformer(m, revision=r)"
ENV HF_HUB_OFFLINE=1

EXPOSE 8501
# Liveness of the Streamlit server. Application checks (KB, model, index) run at startup and in the
# sidebar, and on demand with: docker exec <container> python -m src.health
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "streamlit", "run", "app.py"]
