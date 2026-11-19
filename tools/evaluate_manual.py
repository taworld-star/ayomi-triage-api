"""Evaluasi mesin aturan pada data/test_manual.csv (204 laporan fiktif tulisan LLM).

    python tools/evaluate_manual.py                 # metrik bagian uji (136) dan semua (204)
    python tools/evaluate_manual.py --errors calib  # kesalahan bagian kalibrasi (68)

Pembagian sama dengan notebook Colab (Sel 7): train_test_split(test_size=2/3,
stratify=label, random_state=42), menghasilkan 68 laporan kalibrasi dan 136 uji.

ATURAN JUJUR: aturan hanya boleh disetel dengan melihat kesalahan bagian
kalibrasi. Kesalahan bagian uji (--errors test) dibuka setelah pengukuran,
dan pola yang terlihat di sana tidak dipakai untuk menyetel aturan; kalau
dipakai, angka uji berikutnya tidak lagi bisa dipercaya dan butuh data uji baru.

Butuh pandas dan scikit-learn (requirements-dev.txt).
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import rules_engine  # noqa: E402
from evaluate import contract_input, metrics  # noqa: E402

LABELS = rules_engine.LABELS


def load(path):
    df = pd.read_csv(path, dtype=str).fillna("")
    df["observed_facts"] = df.observed_facts.apply(lambda s: [x.strip() for x in s.split("|") if x.strip()])
    df["age_months"] = [int(a) if a.strip() else None for a in df.age_months]
    df["y"] = df.label.map(LABELS.index)
    calib, test = train_test_split(df, test_size=2 / 3, stratify=df.label, random_state=42)
    return df, calib, test


def predict(part):
    preds, rules = [], []
    for row in part.to_dict("records"):
        out, info = rules_engine.triage(contract_input(row, caregiver=row["caregiver_urgency"] or "low"))
        preds.append(LABELS.index(out["urgency"]) if out["urgency"] else 0)
        rules.append(info["matched_rules"])
    return np.array(preds), rules


def report(name, part):
    pred, _ = predict(part)
    y = part.y.values
    reporter = part.caregiver_urgency.map(LABELS.index).values
    print(f"\n== {name} ({len(part)} laporan)")
    for label, p in (("aturan", pred), ("pelapor saja", reporter), ("max(pelapor, aturan)", np.maximum(reporter, pred))):
        m = metrics(list(y), list(p))
        print(f"{label:<22} macro_f1 {m['macro_f1']:.3f} | recall_em {m['recall_emergency']:.3f} "
              f"| recall_high+ {m['recall_high_plus']:.3f} | under {m['under_triage']:.3f} "
              f"| severe {m['severe_under']:.3f} | over {m['over_triage']:.3f}")


def errors(part):
    pred, rules = predict(part)
    for row, p, r in zip(part.to_dict("records"), pred, rules):
        if LABELS[p] != row["label"]:
            print(f"[{row['label']} -> {LABELS[p]}] {row['description']} | {row['observed_facts']} | aturan: {r[:4]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(ROOT / "data" / "test_manual.csv"))
    ap.add_argument("--errors", choices=["none", "calib", "test"], default="none")
    args = ap.parse_args()
    df, calib, test = load(args.csv)
    print(f"Mesin {rules_engine.ENGINE_VERSION}, rubrik {rules_engine.RUBRIC_VERSION}")
    report("uji (sama dengan notebook)", test)
    report("semua (termasuk kalibrasi)", df)
    if args.errors != "none":
        print(f"\n== kesalahan bagian {args.errors}")
        errors(calib if args.errors == "calib" else test)


if __name__ == "__main__":
    main()
