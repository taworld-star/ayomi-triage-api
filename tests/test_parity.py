"""triage_core.py dan bank skenario harus sama persis dengan notebook di repo aplikasi.

Lokasi notebook: env AYOMI_NOTEBOOK, atau ../ayomi-project-cut-meutia/docs/incident-triage-indobert.ipynb.
Dilewati bila notebook tidak ada (misalnya saat build Docker).
"""
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOK = Path(os.environ.get("AYOMI_NOTEBOOK",
                               ROOT.parent / "ayomi-project-cut-meutia" / "docs" / "incident-triage-indobert.ipynb"))


def cells():
    if not NOTEBOOK.exists():
        pytest.skip(f"notebook tidak ditemukan: {NOTEBOOK}")
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    return ["".join(c["source"]) if isinstance(c["source"], list) else c["source"] for c in nb["cells"]]


def test_core_matches_notebook():
    core = next(c for c in cells() if c.startswith("TRIAGE_CORE = r'''"))
    body = re.search(r"TRIAGE_CORE = r'''\n(.*?)'''", core, re.S).group(1)
    assert body in (ROOT / "triage_core.py").read_text(encoding="utf-8")


def test_scenarios_match_notebook():
    cell = next(c for c in cells() if c.startswith("def sc("))
    text = (ROOT / "tools" / "synthetic.py").read_text(encoding="utf-8")
    block = text.split("# --- notebook Sel 6: awal salinan\n")[1].split("# --- notebook Sel 6: akhir salinan")[0]
    assert block in cell


def test_notebook_saves_triage_config_separately():
    """config.json milik model tidak boleh ditimpa konfigurasi triage."""
    source = "\n".join(cells())
    assert 'MODEL_DIR / "triage_config.json"' in source
    assert '(MODEL_DIR / "config.json").write_text' not in source
