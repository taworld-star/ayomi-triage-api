import os

import pytest
from fastapi.testclient import TestClient

from conftest import LABELS, make_input

CONTRACT_KEYS = {"urgency", "reason", "evidence_quotes", "sop_refs", "missing_information", "operational_actions",
                 "needs_human_review"}


def sources(inp):
    return [inp["description"], *inp["observed_facts"], inp["first_aid_already_done"]]


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["engine"] == "rules" and body["rubric_version"] == "draf-1"


def test_docs_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_requires_token(client):
    inp = make_input("[ANAK] jatuh di halaman dan lututnya lecet.")
    assert client.post("/triage", json=inp).status_code == 401
    assert client.post("/triage", json=inp, headers={"Authorization": "Bearer salah"}).status_code == 401


def test_rejects_unknown_field_and_large_body(client, auth):
    inp = make_input("[ANAK] jatuh di halaman dan lututnya lecet.")
    assert client.post("/triage", json={**inp, "diagnosis": "x"}, headers=auth).status_code == 422
    assert client.post("/triage", json={**inp, "description": "a" * 70_000}, headers=auth).status_code == 413


def test_emergency_result_follows_contract(client, auth):
    inp = make_input("[ANAK] tersedak anggur, wajahnya membiru dan tidak bisa menangis.",
                     facts=["bibir kebiruan"], aid="Pengasuh melakukan tepukan punggung.", caregiver="medium")
    res = client.post("/triage", json=inp, headers=auth)
    assert res.status_code == 200
    body = res.json()
    result, meta = body["result"], body["meta"]
    assert set(result) == CONTRACT_KEYS
    assert result["urgency"] == "emergency"
    assert result["evidence_quotes"] and all(any(q in s for s in sources(inp)) for q in result["evidence_quotes"])
    assert result["sop_refs"] == ["triage-emergency@draf-1", "incident-workflow@1"]
    assert result["operational_actions"][0] == "notify_manager"
    assert meta["engine"] == "rules" and meta["probabilities"] is None and "choking_airway" in meta["matched_rules"]


def test_short_report_abstains(client, auth):
    body = client.post("/triage", json=make_input("Jatuh."), headers=auth).json()
    assert body["result"]["urgency"] is None and body["result"]["missing_information"]


def test_token_required_at_startup(monkeypatch):
    import app
    monkeypatch.setenv("API_TOKEN", "pendek")
    with pytest.raises(RuntimeError):
        with TestClient(app.app):
            pass


def test_model_engine(monkeypatch, tiny_model_dir, auth):
    """Jalur mode model dengan BERT mini acak: memuat triage_config.json dan memakai triage_core."""
    import app
    monkeypatch.setenv("TRIAGE_ENGINE", "auto")
    monkeypatch.setenv("MODEL_DIR", str(tiny_model_dir))
    with TestClient(app.app) as c:
        health = c.get("/health").json()
        assert health["engine"] == "model" and health["model_version"] == "tiny-test"
        inp = make_input("[ANAK] jatuh dan kepala terbentur lantai. Ada benjol kecil.", facts=["lutut lecet"])
        body = c.post("/triage", json=inp, headers=auth).json()
    assert set(body["result"]) == CONTRACT_KEYS
    assert body["result"]["urgency"] in LABELS
    assert set(body["meta"]["probabilities"]) == set(LABELS)
    assert all(any(q in s for s in sources(inp)) for q in body["result"]["evidence_quotes"])


def test_model_without_triage_config_fails_loudly(monkeypatch, tiny_model_dir):
    import app
    (tiny_model_dir / "triage_config.json").unlink()
    monkeypatch.setenv("TRIAGE_ENGINE", "model")
    monkeypatch.setenv("MODEL_DIR", str(tiny_model_dir))
    with pytest.raises(RuntimeError, match="triage_config.json"):
        with TestClient(app.app):
            pass
    assert os.environ["TRIAGE_ENGINE"] == "model"
