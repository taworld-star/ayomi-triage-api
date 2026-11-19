"""Evaluasi mesin triage dengan laporan sintetis dan uji regresi notebook.

    python tools/evaluate.py                     # mesin aturan, lokal
    python tools/evaluate.py --url https://...   # layanan yang sudah di-deploy
                                                 # (token dari env TRIAGE_API_TOKEN)
    python tools/evaluate.py --limit 400 --json hasil.json

Metrik sama dengan Sel 8 notebook. Data sintetis berasal dari bank skenario
yang juga dipakai menyusun aturan, jadi angkanya mengukur kecocokan dengan
rubrik pada kalimat template, BUKAN akurasi pada laporan nyata.
"""
import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from synthetic import LABELS, REGRESSION, generate  # noqa: E402

SOP = [{"id": f"triage-{label}", "version": "draf-1", "text": f"Rubrik prioritas {label}."} for label in LABELS] \
    + [{"id": "incident-workflow", "version": "1", "text": "Alur penanganan laporan insiden Ayomi."}]
TARGET = {"recall_emergency": 0.95, "under_triage": 0.05, "severe_under": 0.0}


def contract_input(row, caregiver="low"):
    return {"incident_id": "00000000-0000-4000-8000-000000000000", "input_version": 1,
            "occurred_at": "2026-11-11T09:00:00Z", "age_months": row.get("age_months"), "caregiver_urgency": caregiver,
            "description": row["description"], "observed_facts": list(row.get("observed_facts", [])),
            "first_aid_already_done": row.get("first_aid_already_done", ""), "sop_references": SOP}


def metrics(y_true, y_pred):
    pairs = [(t, p) for t, p in zip(y_true, y_pred) if p is not None]
    n = len(pairs)
    if not n:
        return {"n": 0}
    em = [(t, p) for t, p in pairs if t == 3]
    hp = [(t, p) for t, p in pairs if t >= 2]
    f1s = []
    for k in range(4):
        tp = sum(1 for t, p in pairs if t == k and p == k)
        fp = sum(1 for t, p in pairs if t != k and p == k)
        fn = sum(1 for t, p in pairs if t == k and p != k)
        f1s.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    r = lambda x: round(x, 4)
    return {"n": n, "abstain": len(y_pred) - n, "macro_f1": r(sum(f1s) / 4), "accuracy": r(sum(t == p for t, p in pairs) / n),
            "recall_emergency": r(sum(p == 3 for _, p in em) / len(em)) if em else None,
            "recall_high_plus": r(sum(p >= 2 for _, p in hp) / len(hp)) if hp else None,
            "under_triage": r(sum(p < t for t, p in pairs) / n),
            "severe_under": r(sum(t == 3 and p <= 1 for t, p in pairs) / n),
            "over_triage": r(sum(p > t for t, p in pairs) / n)}


def local_predict(inp):
    import rules_engine
    result, _ = rules_engine.triage(inp)
    return result


def remote_predictor(url, token):
    import urllib.request

    def predict(inp):
        req = urllib.request.Request(f"{url.rstrip('/')}/triage", data=json.dumps(inp).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=120) as res:
            return json.load(res)["result"]
    return predict


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="URL layanan (tanpa /triage). Kosong = mesin aturan lokal.")
    ap.add_argument("--limit", type=int, default=0, help="Ambil sampel acak sebanyak ini (0 = semua).")
    ap.add_argument("--split", choices=["all", "train", "valid", "test"], default="all")
    ap.add_argument("--json", help="Simpan ringkasan ke file JSON.")
    ap.add_argument("--errors", type=int, default=12, help="Jumlah contoh under-triage yang dicetak.")
    args = ap.parse_args()

    if args.url:
        token = os.environ.get("TRIAGE_API_TOKEN")
        if not token:
            sys.exit("Isi env TRIAGE_API_TOKEN terlebih dahulu.")
        predict = remote_predictor(args.url, token)
    else:
        predict = local_predict

    rows = [r for r in generate() if args.split == "all" or r["split"] == args.split]
    if args.limit:
        rows = random.Random(7).sample(rows, min(args.limit, len(rows)))
    started = time.perf_counter()
    preds, by_cat, wrong = [], defaultdict(lambda: ([], [])), []
    for row in rows:
        out = predict(contract_input(row))
        p = None if out["urgency"] is None else LABELS.index(out["urgency"])
        t = LABELS.index(row["label"])
        preds.append(p)
        by_cat[row["category"]][0].append(t)
        by_cat[row["category"]][1].append(p)
        if p is not None and p < t:
            wrong.append((row, out))
    elapsed = time.perf_counter() - started
    truth = [LABELS.index(r["label"]) for r in rows]
    overall = metrics(truth, preds)

    reg = []
    for age, text, lo, hi in REGRESSION:
        out = predict(contract_input({"description": text, "age_months": age}))
        lvl = None if out["urgency"] is None else LABELS.index(out["urgency"])
        reg.append({"text": text, "got": out["urgency"], "expected": [LABELS[lo], LABELS[hi]],
                    "passed": lvl is not None and lo <= lvl <= hi})

    print(f"Laporan sintetis: {len(rows)} ({args.split}) | label {dict(Counter(r['label'] for r in rows))}")
    print(f"Waktu: {elapsed:.1f} detik ({elapsed / max(len(rows), 1) * 1000:.1f} ms per laporan)")
    print(json.dumps(overall, indent=1))
    print("\nPer kategori (n, macro_f1, under, over):")
    for cat, (t, p) in sorted(by_cat.items()):
        m = metrics(t, p)
        print(f"  {cat:<14} {m['n']:>4}  {m.get('macro_f1')}  {m.get('under_triage')}  {m.get('over_triage')}")
    print(f"\nUji regresi: {sum(r['passed'] for r in reg)}/{len(reg)} lolos")
    for r in reg:
        if not r["passed"]:
            print(f"  GAGAL {r['got']} (harapan {r['expected']}): {r['text']}")
    print(f"\nContoh under-triage ({min(len(wrong), args.errors)} dari {len(wrong)}):")
    for row, out in wrong[:args.errors]:
        print(f"  [{row['label']} -> {out['urgency']}] {row['description']} | fakta: {row['observed_facts']} | {row['first_aid_already_done']}")
    passed = (overall.get("recall_emergency") or 0) >= TARGET["recall_emergency"] \
        and overall["under_triage"] <= TARGET["under_triage"] and overall["severe_under"] <= TARGET["severe_under"] \
        and all(r["passed"] for r in reg)
    print("\nTarget keselamatan (recall_emergency >= 0,95, under <= 5%, severe_under 0, regresi lolos):", "LOLOS" if passed else "BELUM")
    if args.json:
        Path(args.json).write_text(json.dumps({"overall": overall, "regression": reg, "passed": passed,
                                               "categories": {c: metrics(*v) for c, v in by_cat.items()}}, indent=1, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
