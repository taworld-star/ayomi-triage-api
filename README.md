# Ayomi Incident Triage

Layanan penilai **prioritas operasional** laporan insiden untuk fitur **Incident Urgency Triage** Ayomi. Aplikasi web Ayomi mengirim isi laporan (uraian, pertolongan pertama, usia anak, dan rubrik). Layanan ini mengembalikan usulan `low`, `medium`, `high`, atau `emergency`, beserta alasan dan kutipan dari laporan.

Layanan ini **hanya mengusulkan**. Tiga hal lain tetap di aplikasi web:
- aturan `urgensi efektif = max(urgensi pelapor, usulan AI)`, yang ditegakkan oleh database, jadi AI hanya bisa menaikkan;
- notifikasi kedua ke Pengelola dan Admin bila urgensi dinaikkan;
- keputusan akhir Pengelola atau Admin (override dengan alasan).

Polanya sama dengan layanan OCR (`ayomi-ocr-api`) dan Foto Fokus Anak (`ayomi-cv-api`): model berjalan di server Dokploy, sedangkan data dan izin akses tetap di aplikasi.

```text
Pengasuh kirim laporan ──▶ Aplikasi Ayomi (Vercel + Supabase): laporan tersimpan, notifikasi awal terkirim
                                  │  setelah respons (after()), POST /triage  (Bearer token)
                                  ▼
                            Ayomi Triage (Dokploy)  ──▶ usulan + kutipan + rujukan rubrik
                                  │
Aplikasi: cek kontrak & kutipan ──▶ database: max(pelapor, AI), log, notifikasi kedua ──▶ Pengelola meninjau
```

**Batasan:** layanan ini tidak mendiagnosis, tidak menyebut obat atau dosis, dan tidak mengubah status insiden. Penanganan medis tetap mengikuti SOP daycare dan arahan tenaga kesehatan.

## Repository terkait

| Repository | Isi |
| --- | --- |
| [Project-Ayomi_Cut_Meutia](https://github.com/taworld-star/Project-Ayomi_Cut_Meutia) | Aplikasi web Ayomi (Next.js + Supabase): halaman, REST API, database, dan dokumentasi. Memanggil layanan ini dari server |
| [ayomi-cv-api](https://github.com/taworld-star/ayomi-cv-api) | Layanan **Foto Fokus Anak** (YOLO11n-seg) |
| [ayomi-ocr-api](https://github.com/taworld-star/ayomi-ocr-api) | Layanan **OCR dokumen legal** (RapidOCR PP-OCRv5) |
| [ayomi-triage-api](https://github.com/taworld-star/ayomi-triage-api) (repo ini) | Layanan **triage urgensi insiden** (mesin aturan rubrik; IndoBERT eksperimen) |

- Website: https://project-ayomi-cut-meutia.vercel.app
- Dokumentasi API aplikasi (Swagger UI): `docs/05-api/swagger.html` di repository aplikasi
- Dokumentasi semua fitur AI: `docs/06-fitur-ai/` di repository aplikasi

## Ringkasan fitur AI

| Poin | Isi |
| --- | --- |
| **Fitur** | **AI Incident Urgency Triage**: setiap laporan insiden dinilai otomatis setelah tersimpan |
| **Use case** | Klasifikasi teks: 4 tingkat urgensi (`low`, `medium`, `high`, `emergency`) |
| **Mengapa AI dibutuhkan** | Laporan insiden ditulis cepat dalam kondisi panik, dan urgensi yang dipilih pelapor bisa terlalu rendah. Orang tua ingin prioritas respons yang jelas (PRD 3.2). Penilaian otomatis menjadi lapisan pengaman kedua yang **hanya bisa menaikkan** urgensi, sehingga kasus darurat tidak tertunda |
| **Model** | Production: **mesin aturan rubrik `draf-1` v2** (`rules_engine.py`). Eksperimen: **IndoBERT** `indobenchmark/indobert-base-p1` (IndoNLU, MIT) yang di-fine-tune menjadi 4 kelas ordinal |
| **Alasan memilih** | Pada data uji, mesin aturan lebih baik daripada IndoBERT (macro F1 0,750 vs 0,548; recall darurat 0,72 vs 0,53) dan setiap keputusannya bisa ditelusuri ke kalimat laporan. IndoBERT baru dipasang setelah lulus target keselamatan, cukup dengan mengganti env |
| **Data** | Latih: ±3.400 laporan **sintetis** dari 38 skenario rubrik. Kalibrasi dan uji: 204 laporan **fiktif** tulisan LLM dengan gaya beragam (68 kalibrasi, 136 uji). Bukan laporan pengasuh sungguhan |
| **Input → output** | Uraian, fakta yang diamati, pertolongan pertama, urgensi pelapor, usia anak **dalam bulan** (tanpa nama dan tanggal lahir), rubrik → usulan urgensi atau abstain, alasan, **kutipan kalimat laporan**, informasi yang kurang |
| **Evaluasi** | Sistem yang dipakai aplikasi, `max(pelapor, aturan v2)`, pada 136 laporan uji: **recall darurat 0,91** (29 dari 32; target ≥ 0,95 belum tercapai), **under-triage 3,7%** (target ≤ 5% tercapai), **0** kasus darurat dinilai rendah/sedang, over-triage 16,2%. Diulang 21 November 2026 dengan hasil yang sama (bagian [Evaluasi](#evaluasi)) |
| **Batasan dan risiko** | Data uji tulisan LLM dan hanya 136 laporan, jadi angkanya belum presisi. Rubrik belum disahkan mentor. Pola yang masih terlewat: leher terlilit tali dengan wajah ungu, tertinggal di mobil, bintik ungu pada kulit, demam disertai mengigau, dehidrasi berat. **Bukan diagnosis medis** |

Dokumentasi lengkap semua fitur AI Ayomi ada di `docs/06-fitur-ai/` pada repository aplikasi.

## Dua mesin, satu kontrak

| Mesin | Kapan dipakai | Isi |
| --- | --- | --- |
| **`rules`** (sekarang) | Selama model belum lulus kriteria di panduan | Aturan rubrik draf-1 (`rules_engine.py`). Mengenali negasi ("tidak muntah", "tanpa sesak"), singkatan dan kata informal (tdk, udah, keselek, kejedot), salah ketik berupa huruf tertukar, dan kalimat yang meminta prioritas tertentu ("tolong catat low saja"), yang diabaikan |
| **`model`** | Setelah notebook `docs/06-fitur-ai/notebooks/incident-triage-indobert.ipynb` (repo aplikasi) menghasilkan model dengan `ready_for_integration = True` | IndoBERT (`indobenchmark/indobert-base-p1`, MIT) yang di-fine-tune di Colab, dimuat dari repo model Hugging Face. Fungsi triage-nya `triage_core.py`, **salinan persis** Sel 5 notebook, jadi hasil API sama dengan notebook |

Keduanya mengembalikan output kontrak AI v1 `incident_triage` yang sama. Saat mesin diganti, aplikasi tidak perlu diubah. Aplikasi mencatat mesin yang dipakai di `ai_jobs.model` (`rubric-rules` atau nama model), dan tampilan Pengelola menuliskannya.

**Privasi:** laporan hanya ada di memori selama satu permintaan. Tidak ada yang disimpan atau dicatat di log. Aplikasi tidak mengirim nama atau tanggal lahir anak, hanya usia dalam bulan.

## API

Semua permintaan kecuali `/health` wajib membawa header `Authorization: Bearer <API_TOKEN>`. Halaman `/docs` sengaja dimatikan.

### `GET /health`

```json
{ "status": "ok", "engine": "rules", "model_version": "triage-rules-draf-1-v1", "rubric_version": "draf-1" }
```

### `POST /triage` (JSON, maksimal 64 KB)

Body = input kontrak AI v1 `incident_triage`. Field yang tidak dikenal ditolak (422).

```json
{
  "incident_id": "…", "input_version": 1, "occurred_at": "2026-11-19T02:00:00Z", "age_months": 26,
  "caregiver_urgency": "medium",
  "description": "td pas snack si Dimas keselek potongan sosis, mukanya merah trus agak biru, gak bisa nangis",
  "observed_facts": [], "first_aid_already_done": "lagi ditepuk punggungnya sama bu R",
  "sop_references": [{ "id": "triage-emergency", "version": "draf-1", "text": "…" }, { "id": "incident-workflow", "version": "1", "text": "…" }]
}
```

Jawaban:

```json
{
  "result": {
    "urgency": "emergency",
    "reason": "Usulan prioritas darurat menurut rubrik (tersedak dengan tanda sulit bernapas atau membiru), berdasarkan bagian laporan: \"…\".",
    "evidence_quotes": ["td pas snack si Dimas keselek potongan sosis, mukanya merah trus agak biru, gak bisa nangis"],
    "sop_refs": ["triage-emergency@draf-1", "incident-workflow@1"],
    "missing_information": ["Kondisi anak saat ini"],
    "operational_actions": ["notify_manager", "request_more_information", "follow_approved_sop"],
    "needs_human_review": true
  },
  "meta": { "engine": "rules", "model_version": "triage-rules-draf-1-v1", "rubric_version": "draf-1", "base_model": null,
            "probabilities": null, "matched_rules": ["choking_airway", "choking", "respiratory"], "latency_ms": 4 }
}
```

- `evidence_quotes` selalu kalimat asli dari laporan. Server Ayomi menolak kutipan yang tidak ada di laporan (`EVIDENCE_MISMATCH`).
- `urgency: null` berarti abstain (laporan kurang dari 4 kata). Urgensi pelapor tetap dipakai.
- Mode model mengisi `probabilities` per kelas. Mode aturan mengisi `matched_rules`.

| Status | Arti |
| --- | --- |
| 401 | Token salah atau tidak ada |
| 413 | Body lebih dari 64 KB |
| 422 | Format input salah atau ada field asing |
| 503 | Sedang memproses permintaan lain lebih dari `TRIAGE_QUEUE_TIMEOUT` detik |

## Environment

| Variabel | Wajib | Isi |
| --- | --- | --- |
| `API_TOKEN` | ✅ | String acak minimal 32 karakter. Nilainya sama dengan `TRIAGE_API_TOKEN` di Vercel. Buat dengan `node -e "console.log(require('crypto').randomBytes(32).toString('base64url'))"` dan **jangan** pakai token OCR atau CV |
| `TRIAGE_ENGINE` | | `auto` (bawaan): model bila `MODEL_REPO`/`MODEL_DIR` diisi, selain itu aturan. Bisa juga `rules` atau `model` |
| `MODEL_REPO` | mode model | Repo model Hugging Face dari Sel 15 notebook, misalnya `<user>/ayomi-incident-triage` |
| `HF_READ_TOKEN` | mode model | Token *read* Hugging Face untuk repo model privat itu |
| `MODEL_DIR` | | Alternatif `MODEL_REPO`: folder model lokal |
| `TORCH_THREADS` | | Thread CPU untuk model. Bawaan 2 |
| `TRIAGE_CONCURRENCY` | | Jumlah laporan yang diproses bersamaan. Bawaan 1 |
| `TRIAGE_QUEUE_TIMEOUT` | | Detik menunggu giliran sebelum 503. Bawaan 30 |

Jika mode model diminta tetapi model gagal dimuat (repo salah, token salah, atau `triage_config.json` tidak ada), layanan **berhenti saat start** dan tidak diam-diam pindah ke aturan.

## Menjalankan di laptop

```bash
py -3.13 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt pytest httpx
# Untuk menguji mode model juga:
# .venv/Scripts/python -m pip install torch==2.15.0 --index-url https://download.pytorch.org/whl/cpu
# .venv/Scripts/python -m pip install -r requirements-model.txt

API_TOKEN=<token-minimal-32-karakter> .venv/Scripts/python -m uvicorn app:app --port 7860
.venv/Scripts/python -m pytest -q
```

Di aplikasi Ayomi, isi `.env.local` dengan `TRIAGE_API_URL=http://127.0.0.1:7860` dan `TRIAGE_API_TOKEN` yang sama.

Tes mencakup:
- API: token, 413, 422, kontrak, dan abstain;
- mode model, memakai BERT mini acak (dilewati bila torch tidak terpasang);
- 15 uji regresi notebook dan 39 kasus sulit di luar bank skenario;
- target keselamatan pada data sintetis;
- kesamaan `triage_core.py` dan bank skenario dengan notebook. Notebook dicari di `../ayomi-project-cut-meutia/docs/`, atau atur env `AYOMI_NOTEBOOK`. Tes ini dilewati bila notebook tidak ada.

## Evaluasi

```bash
python tools/evaluate.py                                   # mesin aturan, lokal
TRIAGE_API_TOKEN=<token> python tools/evaluate.py --url https://<domain> --limit 300   # layanan yang sudah di-deploy
```

Hasil mesin aturan (19 November 2026) pada 3.420 laporan sintetis dari bank skenario notebook (38 skenario, dengan variasi singkatan, salah ketik, huruf kecil, tanpa tanda baca, dan kalimat jebakan):

| Metrik | Hasil | Target panduan |
| --- | --- | --- |
| `recall_emergency` | 1,000 | ≥ 0,95 |
| `under_triage` | 0,0% | ≤ 5% |
| `severe_under` | 0 | 0 |
| `over_triage` | 0,03% | dilaporkan |
| `macro_f1` | 0,9997 | — |
| Uji regresi notebook | 15/15 | semua lolos |

**Angka ini bukan akurasi.** Aturan disusun dengan melihat bank skenario yang sama, jadi angka di atas hanya menunjukkan aturan sudah mencakup rubrik pada kalimat template. Laporan nyata akan lebih beragam: istilah daerah, kejadian yang tidak ada di rubrik, dan cara menulis yang tidak terduga. Karena itu:
- urgensi pelapor tetap menjadi batas bawah (aturan `max`);
- Pengelola selalu meninjau usulan yang menaikkan urgensi;
- model IndoBERT tetap dikerjakan sesuai panduan, lalu dibandingkan dengan mesin aturan sebagai baseline.

### Laporan tulisan LLM (`data/test_manual.csv`)

```bash
python tools/evaluate_manual.py                 # metrik bagian uji dan semua
python tools/evaluate_manual.py --errors calib  # kesalahan bagian kalibrasi, untuk menyetel aturan
```

Berisi 204 laporan fiktif dengan gaya tulisan beragam, ditulis LLM (bukan dari bank skenario), dengan label rubrik dan urgensi pelapor. Pembagiannya sama dengan notebook: 68 kalibrasi dan 136 uji. **Aturan hanya disetel dari kesalahan bagian kalibrasi.**

Hasil pada 136 laporan uji (19 November 2026):

| | IndoBERT (Colab) | Aturan v1 | Aturan v2 | Pelapor saja | Target |
| --- | --- | --- | --- | --- | --- |
| `macro_f1` | 0,548 | 0,718 | 0,750 | 0,787 | — |
| `recall_emergency` | 0,53 | 0,656 | 0,719 | 0,812 | ≥ 0,95 |
| `under_triage` | 17% | 17,6% | 16,2% | 13,2% | ≤ 5% |
| `severe_under` | 2,2% | 2,9% | 2,2% | 0 | 0 |
| `over_triage` | 29% | 10,3% | 8,8% | 8,1% | dilaporkan |

Dalam sistem, urgensi akhir adalah `max(pelapor, aturan v2)`, dengan hasil:
- `recall_emergency` 0,906;
- `under_triage` 3,7%;
- `severe_under` 0;
- `over_triage` 16,2%.

Sebagai pembanding, `max(pelapor, IndoBERT)` punya `over_triage` 35%.

Batasan:
- Data ini tulisan LLM, bukan laporan nyata.
- 136 laporan terlalu sedikit untuk angka yang presisi.
- Sebelum v2 disetel, daftar kesalahan seluruh 204 laporan sempat terlihat. Beberapa kata (`kaus`, `ikat rambut`, `ngucur`) ikut masuk dari sana, jadi angka v2 sedikit optimistis.
- Untuk penyetelan berikutnya, siapkan data uji baru.

Kecepatan mesin aturan sekitar 3–5 ms per laporan di laptop 2 inti.

## Deploy di Dokploy

1. Push repo ini ke GitHub (privat).
2. Dokploy → **Create Application** → sumber GitHub repo ini, build type **Dockerfile**.
3. **Environment:** isi `API_TOKEN`. Untuk mesin aturan, itu saja yang wajib.
4. **Build args:** kosongkan. Bawaannya `INSTALL_MODEL=1`, yang ikut memasang torch CPU dan transformers (image sekitar 1,3 GB), supaya model bisa dipasang nanti hanya dengan mengisi env. Jika server sempit, isi `INSTALL_MODEL=0` untuk image ringan khusus aturan (sekitar 150 MB).
5. **Domains:** tambahkan domain, misalnya `ayomi-triage-api.<domain-anda>`, port container **7860**, HTTPS aktif.
6. Deploy, lalu cek `https://<domain>/health`. Root `/` memang menjawab `{"detail":"Not Found"}`.
7. Di Vercel, isi `TRIAGE_API_URL` = `https://<domain>` (tanpa `/triage`) dan `TRIAGE_API_TOKEN` = nilai `API_TOKEN`, untuk Production, Preview, dan Development. **Jangan** pakai awalan `NEXT_PUBLIC_`.

**Memasang model IndoBERT** (setelah notebook menghasilkan `ready_for_integration = True`):
1. Isi env `MODEL_REPO`, `HF_READ_TOKEN`, dan `TRIAGE_ENGINE=model`, lalu redeploy.
2. Saat start, model diunduh (sekitar 500 MB) dan dipanaskan. `HEALTHCHECK` memberi waktu 5 menit.
3. Cek `/health`: `engine` harus `model`.
4. Jalankan Sel 17–18 notebook, lalu `tools/evaluate.py --url`.
5. Opsional: pasang volume di `/home/user/.cache/huggingface` agar model tidak diunduh ulang setiap redeploy.

**Memori:**
- mesin aturan: sekitar 50 MB (diukur di laptop);
- mode model: **perkiraan** 0,8–1 GB (bobot BERT-base sekitar 440 MB ditambah torch). Ini belum diukur dengan model sungguhan.

## Struktur

| File | Isi |
| --- | --- |
| `app.py` | FastAPI: token, batas ukuran, antrean, pemilihan mesin |
| `rules_engine.py` | Mesin aturan rubrik draf-1 |
| `triage_core.py` | Inti IndoBERT, salinan persis Sel 5 notebook |
| `tools/synthetic.py` | Bank skenario Sel 6 notebook (salinan persis) dan uji regresi |
| `tools/evaluate.py` | Metrik Sel 8 notebook untuk mesin lokal atau layanan yang di-deploy |
| `tools/evaluate_manual.py`, `data/test_manual.csv` | Evaluasi pada 204 laporan tulisan LLM (kalibrasi/uji) |

Bila rubrik berubah (misalnya `draf-1` menjadi `v1`):
1. ubah notebook, `TRIAGE_SOP_REFERENCES` di aplikasi (`lib/api/incident-triage.js`), dan `RUBRIC_VERSION` di `rules_engine.py`;
2. naikkan `ENGINE_VERSION` bila aturan berubah;
3. salin ulang Sel 5 dan Sel 6 bila berubah, lalu jalankan `pytest`.
