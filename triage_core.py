# Inti triage IndoBERT: SALINAN PERSIS TRIAGE_CORE dari Sel 5 notebook
# docs/incident-triage-indobert.ipynb (repo aplikasi Ayomi). Jangan diubah di sini;
# ubah di notebook lalu salin ulang. tests/test_parity.py memeriksa kesamaannya.
import re
import numpy as np
import torch

LABELS = ["low", "medium", "high", "emergency"]
LABEL_ID = {"low": "rendah", "medium": "sedang", "high": "tinggi", "emergency": "darurat"}
_CONDITION = re.compile(r"(sekarang|saat ini|skrg|kondisi|tenang|bermain lagi|main lagi|tidur|napas|bernapas|sadar|menangis|nangis|lemas|ceria|aktif)", re.I)
_EMPTY_AID = re.compile(r"\s*(-|belum( ada)?( tindakan)?( dicatat)?|tidak ada)?\.?\s*", re.I)

def build_text(age_months, description, observed_facts, first_aid):
    parts = []
    if age_months is not None:
        parts.append(f"Usia {int(age_months)} bulan.")
    parts.append((description or "").strip())
    facts = [f.strip() for f in observed_facts or [] if f and f.strip()]
    if facts:
        parts.append("Fakta: " + "; ".join(facts) + ".")
    if first_aid and first_aid.strip():
        parts.append("Pertolongan: " + first_aid.strip())
    return " ".join(p for p in parts if p)

@torch.no_grad()
def predict_proba(model, tok, texts, max_len, batch_size=32):
    device = next(model.parameters()).device
    out = []
    for i in range(0, len(texts), batch_size):
        enc = tok(list(texts[i:i + batch_size]), truncation=True, max_length=max_len, padding=True, return_tensors="pt").to(device)
        out.append(torch.softmax(model(**enc).logits.float(), dim=-1).cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, len(LABELS)))

def decide(probs, th):
    cum = probs[:, ::-1].cumsum(axis=1)[:, ::-1]          # cum[:, k] = P(level >= k)
    pred = np.zeros(len(probs), dtype=int)
    pred[cum[:, 1] >= th["medium"]] = 1
    pred[cum[:, 2] >= th["high"]] = 2
    pred[cum[:, 3] >= th["emergency"]] = 3
    return pred

def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text or "") if len(s.strip()) >= 3]

def _text_of(inp, description=None, facts=None, aid=None):
    return build_text(inp.get("age_months"),
                      inp["description"] if description is None else description,
                      inp["observed_facts"] if facts is None else facts,
                      inp["first_aid_already_done"] if aid is None else aid)

def find_evidence(model, tok, cfg, inp, level, top_k=2):
    sources = [("d", None, inp["description"])]
    sources += [("f", i, f) for i, f in enumerate(inp["observed_facts"])]
    sources += [("a", None, inp["first_aid_already_done"])]
    cands = [(kind, i, s) for kind, i, text in sources for s in _sentences(text)][:25]
    if not cands:
        return []
    def without(kind, i, sentence):
        if kind == "d":
            return _text_of(inp, description=inp["description"].replace(sentence, "", 1))
        if kind == "f":
            facts = list(inp["observed_facts"]); facts[i] = facts[i].replace(sentence, "", 1)
            return _text_of(inp, facts=facts)
        return _text_of(inp, aid=inp["first_aid_already_done"].replace(sentence, "", 1))
    probs = predict_proba(model, tok, [_text_of(inp)] + [without(*c) for c in cands], cfg["max_len"])
    cum = probs[:, level:].sum(axis=1)
    drops = cum[0] - cum[1:]
    order = [int(j) for j in np.argsort(-drops) if drops[j] >= 0.05][:top_k]
    if not order:
        alone = predict_proba(model, tok, [build_text(inp.get("age_months"), c[2], [], "") for c in cands], cfg["max_len"])
        order = [int(np.argmax(alone[:, level:].sum(axis=1)))]
    return [cands[j][2] for j in order]

def missing_information(inp):
    missing = []
    if not _CONDITION.search(_text_of(inp)):
        missing.append("Kondisi anak saat ini")
    if _EMPTY_AID.fullmatch(inp.get("first_aid_already_done") or ""):
        missing.append("Pertolongan pertama yang sudah dilakukan")
    return missing

def triage(model, tok, cfg, inp):
    refs_by_id = {s["id"]: f'{s["id"]}@{s["version"]}' for s in inp.get("sop_references", [])}
    missing = missing_information(inp)
    words = len(re.findall(r"\w+", " ".join([inp["description"], *inp["observed_facts"]])))
    if words < cfg["min_words"]:
        refs = [refs_by_id[k] for k in ("incident-workflow",) if k in refs_by_id]
        return {"urgency": None,
                "reason": "Uraian laporan terlalu singkat untuk dinilai; urgensi dari pelapor tetap dipakai.",
                "evidence_quotes": [], "sop_refs": refs,
                "missing_information": missing or ["Uraian kejadian yang lebih lengkap"],
                "operational_actions": ["request_more_information"] + (["follow_approved_sop"] if refs else []),
                "needs_human_review": True}, None
    probs = predict_proba(model, tok, [_text_of(inp)], cfg["max_len"])
    level = int(decide(probs, cfg["thresholds"])[0])
    urgency = LABELS[level]
    quotes = find_evidence(model, tok, cfg, inp, level) if level > 0 else []
    refs = [refs_by_id[k] for k in (f"triage-{urgency}", "incident-workflow") if k in refs_by_id]
    caregiver = inp.get("caregiver_urgency")
    raises = caregiver in LABELS and level > LABELS.index(caregiver)
    actions = (["notify_manager"] if level >= 2 or raises else []) \
        + (["request_more_information"] if missing and level >= 1 else []) + (["follow_approved_sop"] if refs else [])
    if quotes:
        reason = f'Usulan prioritas {LABEL_ID[urgency]} berdasarkan bagian laporan: "{quotes[0]}".'
    elif level == 0:
        reason = "Usulan prioritas rendah: tidak ditemukan tanda yang memerlukan prioritas lebih tinggi menurut rubrik."
    else:
        reason = f"Usulan prioritas {LABEL_ID[urgency]} berdasarkan pola laporan secara keseluruhan."
    return {"urgency": urgency, "reason": reason, "evidence_quotes": quotes, "sop_refs": refs,
            "missing_information": missing, "operational_actions": actions, "needs_human_review": True}, probs[0]
