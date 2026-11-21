"""API Incident Urgency Triage untuk Ayomi.

POST /triage  input kontrak AI v1 `incident_triage` -> {result, meta}
GET  /health  status dan mesin yang aktif

Dua mesin dengan keluaran kontrak yang sama:
- "model": IndoBERT hasil fine-tune notebook docs/06-fitur-ai/notebooks/incident-triage-indobert.ipynb,
  dimuat dari repo model Hugging Face (MODEL_REPO) atau folder lokal (MODEL_DIR).
  Fungsi triage-nya adalah triage_core.py, salinan persis Sel 5 notebook.
- "rules": aturan rubrik draf-1 (rules_engine.py), dipakai selama model belum
  lulus kriteria di panduan.

TRIAGE_ENGINE=auto memilih model bila MODEL_REPO/MODEL_DIR diisi, selain itu
aturan. Bila model diminta tetapi gagal dimuat, layanan berhenti saat start
(tidak diam-diam pindah ke aturan).

Laporan tidak disimpan dan tidak ditulis ke log.
"""
import hmac
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import rules_engine

log = logging.getLogger("ayomi-triage")
MAX_BODY = 64 * 1024
LABELS = rules_engine.LABELS


def _env_int(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


class RulesEngine:
    name = "rules"

    def __init__(self):
        self.model_version = rules_engine.ENGINE_VERSION
        self.rubric_version = rules_engine.RUBRIC_VERSION
        self.base_model = None

    def run(self, inp):
        result, info = rules_engine.triage(inp)
        return result, None, info


class ModelEngine:
    name = "model"

    def __init__(self, path):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        import triage_core
        torch.set_num_threads(_env_int("TORCH_THREADS", 2))
        cfg_path = os.path.join(path, "triage_config.json")
        if not os.path.exists(cfg_path):
            raise RuntimeError("triage_config.json tidak ada di folder model. Jalankan ulang Sel 14-15 notebook "
                               "(versi yang menyimpan konfigurasi triage ke triage_config.json).")
        with open(cfg_path, encoding="utf-8") as fh:
            self.cfg = json.load(fh)
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSequenceClassification.from_pretrained(path).eval()
        self.core = triage_core
        self.model_version = self.cfg["model_version"]
        self.rubric_version = self.cfg["rubric_version"]
        self.base_model = self.cfg.get("base_model")

    @classmethod
    def load(cls):
        local = os.environ.get("MODEL_DIR", "").strip()
        if not local:
            from huggingface_hub import snapshot_download
            local = snapshot_download(os.environ["MODEL_REPO"].strip(), token=os.environ.get("HF_READ_TOKEN") or None)
        return cls(local)

    def run(self, inp):
        result, probs = self.core.triage(self.model, self.tok, self.cfg, inp)
        probabilities = None if probs is None else {l: round(float(p), 4) for l, p in zip(LABELS, probs)}
        return result, probabilities, {}


def load_engine():
    mode = os.environ.get("TRIAGE_ENGINE", "auto").strip().lower()
    if mode == "auto":
        mode = "model" if (os.environ.get("MODEL_REPO", "").strip() or os.environ.get("MODEL_DIR", "").strip()) else "rules"
    if mode == "rules":
        return RulesEngine()
    if mode == "model":
        return ModelEngine.load()
    raise RuntimeError(f"TRIAGE_ENGINE tidak dikenal: {mode} (pilih auto, rules, atau model)")


Short = Annotated[str, Field(max_length=500)]


class SopRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=40)
    text: str = Field(max_length=4000)


class TriageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: str = Field(min_length=1, max_length=64)
    input_version: int = Field(ge=1)
    occurred_at: str = Field(min_length=1, max_length=40)
    age_months: int | None = Field(default=None, ge=0, le=240)
    caregiver_urgency: Literal["low", "medium", "high", "emergency"]
    description: str = Field(min_length=1, max_length=4000)
    observed_facts: list[Short] = Field(default_factory=list, max_length=100)
    first_aid_already_done: str = Field(default="", max_length=2000)
    sop_references: list[SopRef] = Field(default_factory=list, max_length=100)


@asynccontextmanager
async def lifespan(app):
    token = os.environ.get("API_TOKEN", "")
    if len(token) < 32:
        raise RuntimeError("API_TOKEN wajib diisi, minimal 32 karakter.")
    app.state.token = f"Bearer {token}".encode()
    app.state.engine = load_engine()
    app.state.slots = threading.BoundedSemaphore(_env_int("TRIAGE_CONCURRENCY", 1))
    # Pemanasan: muat bobot dan tokenizer ke memori sebelum permintaan pertama.
    app.state.engine.run({"incident_id": "warmup", "input_version": 1, "occurred_at": "2026-01-01T00:00:00Z",
                          "age_months": 30, "caregiver_urgency": "low", "description": "Anak jatuh di halaman dan lututnya lecet.",
                          "observed_facts": [], "first_aid_already_done": "Dibersihkan.", "sop_references": []})
    log.warning("triage siap: mesin=%s versi=%s rubrik=%s", app.state.engine.name, app.state.engine.model_version,
                app.state.engine.rubric_version)
    yield


app = FastAPI(title="Ayomi Incident Triage", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


UNAUTHORIZED = {"code": "unauthorized", "error": "Token API tidak valid."}


def token_valid(header):
    return hmac.compare_digest((header or "").encode("utf-8", "replace"), app.state.token)


@app.middleware("http")
async def guard(request: Request, call_next):
    # Token diperiksa sebelum isi permintaan dibaca atau divalidasi, jadi permintaan
    # tanpa token selalu mendapat 401 dan tidak pernah melihat pesan validasi.
    if request.url.path == "/triage" and not token_valid(request.headers.get("authorization")):
        return JSONResponse(status_code=401, content={"detail": UNAUTHORIZED})
    length = request.headers.get("content-length")
    if length and (not length.isdigit() or int(length) > MAX_BODY):
        return JSONResponse(status_code=413, content={"detail": {"code": "input_too_large", "error": "Input maksimal 64 KB."}})
    return await call_next(request)


def authorize(header):
    if not token_valid(header):
        raise HTTPException(status_code=401, detail=UNAUTHORIZED)


@app.get("/health")
def health():
    engine = app.state.engine
    return {"status": "ok", "engine": engine.name, "model_version": engine.model_version,
            "rubric_version": engine.rubric_version}


@app.post("/triage")
def triage_endpoint(body: TriageInput, authorization: str | None = Header(default=None)):
    authorize(authorization)
    if not app.state.slots.acquire(timeout=float(os.environ.get("TRIAGE_QUEUE_TIMEOUT", "30"))):
        raise HTTPException(status_code=503, detail={"code": "busy", "error": "Layanan sedang sibuk. Coba lagi."})
    try:
        started = time.perf_counter()
        inp = body.model_dump()
        engine = app.state.engine
        result, probabilities, info = engine.run(inp)
    finally:
        app.state.slots.release()
    return {"result": result,
            "meta": {"incident_id": inp["incident_id"], "input_version": inp["input_version"],
                     "engine": engine.name, "model_version": engine.model_version,
                     "rubric_version": engine.rubric_version, "base_model": engine.base_model,
                     "probabilities": probabilities, "matched_rules": info.get("matched_rules"),
                     "latency_ms": round((time.perf_counter() - started) * 1000)}}
