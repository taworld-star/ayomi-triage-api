import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
TOKEN = "t" * 40
os.environ["API_TOKEN"] = TOKEN
os.environ.setdefault("TRIAGE_ENGINE", "rules")

LABELS = ["low", "medium", "high", "emergency"]
SOP = [{"id": f"triage-{l}", "version": "draf-1", "text": f"Rubrik prioritas {l}."} for l in LABELS] \
    + [{"id": "incident-workflow", "version": "1", "text": "Alur penanganan laporan insiden Ayomi."}]


def make_input(description, age=30, facts=(), aid="Diawasi pengasuh.", caregiver="low"):
    return {"incident_id": "00000000-0000-4000-8000-000000000000", "input_version": 1,
            "occurred_at": "2026-11-11T09:00:00Z", "age_months": age, "caregiver_urgency": caregiver,
            "description": description, "observed_facts": list(facts), "first_aid_already_done": aid,
            "sop_references": SOP}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app
    with TestClient(app.app) as c:
        yield c


@pytest.fixture
def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def tiny_model_dir(tmp_path):
    """BERT mini acak (bukan model sungguhan) untuk menguji jalur mode model."""
    torch = pytest.importorskip("torch")
    transformers = pytest.importorskip("transformers")
    words = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"] + sorted(set(
        "anak tersedak jatuh kepala terbentur lutut lecet usia bulan fakta pertolongan demam muntah . , : ; ".split()))
    words += list("abcdefghijklmnopqrstuvwxyz0123456789") + [f"##{c}" for c in "abcdefghijklmnopqrstuvwxyz0123456789"]
    vocab = tmp_path / "vocab.txt"
    vocab.write_text("\n".join(words), encoding="utf-8")
    tok_cls = getattr(transformers, "BertTokenizerFast", None) or transformers.BertTokenizer
    tok = tok_cls(vocab_file=str(vocab), do_lower_case=True)
    torch.manual_seed(0)
    config = transformers.BertConfig(vocab_size=len(words), hidden_size=32, num_hidden_layers=2, num_attention_heads=2,
                                     intermediate_size=37, max_position_embeddings=128, num_labels=4,
                                     id2label=dict(enumerate(LABELS)), label2id={l: i for i, l in enumerate(LABELS)})
    model = transformers.BertForSequenceClassification(config).eval()
    out = tmp_path / "model"
    model.save_pretrained(out)
    tok.save_pretrained(out)
    (out / "triage_config.json").write_text(json.dumps({
        "model_version": "tiny-test", "rubric_version": "draf-1", "base_model": "tiny-random-bert", "labels": LABELS,
        "max_len": 64, "thresholds": {"medium": 0.3, "high": 0.3, "emergency": 0.3}, "min_words": 4}))
    return out
