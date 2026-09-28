import logging
import urllib.request
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routers import upload, auth, query, documents

app = FastAPI(title="Multi-Tenant RAG API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(upload.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(query.router, prefix="/api")
app.include_router(documents.router, prefix="/api")


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.on_event("startup")
def download_reranker_model():
    model_dir = Path("/app/models/reranker")
    model_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "model.onnx": "https://huggingface.co/onnx-community/bge-reranker-base-ONNX/resolve/main/onnx/model_quantized.onnx",
        "tokenizer.json": "https://huggingface.co/onnx-community/bge-reranker-base-ONNX/resolve/main/tokenizer.json",
        "config.json": "https://huggingface.co/onnx-community/bge-reranker-base-ONNX/resolve/main/config.json",
    }

    for filename, url in files.items():
        path = model_dir / filename
        if path.exists() and path.stat().st_size > 0:
            continue
        logging.info("Downloading %s ...", filename)
        try:
            urllib.request.urlretrieve(url, path)
            logging.info("Downloaded %s (%s bytes)", filename, path.stat().st_size)
        except Exception as exc:
            logging.warning("Failed to download %s: %s", filename, exc)

