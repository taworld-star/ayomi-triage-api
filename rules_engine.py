"""Mesin aturan untuk triage insiden (rubrik draf-1).

Dipakai sementara selama model IndoBERT belum lulus kriteria di panduan
(docs/panduan-incident-triage.md bagian 6). Keluarannya mengikuti kontrak AI v1
`incident_triage` yang sama dengan model, jadi aplikasi tidak perlu berubah saat
mesin diganti.

Cara kerja:
1. Uraian, fakta, dan pertolongan pertama dipecah per kalimat (sama dengan
   `_sentences` di inti model), lalu tiap kalimat dinormalkan: huruf kecil,
   singkatan dan kata informal (tdk, udah, keselek, kejedot), serta salah ketik
   berupa dua huruf tertukar pada kata kunci.
2. Kalimat yang meminta prioritas tertentu ("tolong catat low saja") dibuang
   bagiannya (rubrik aturan 8).
3. Setiap tanda (flag) dicari per kalimat. Tanda tidak dihitung bila didahului
   negasi ("tidak muntah", "tanpa sesak") atau kata pengandaian ("tanda sesak").
4. Aturan rubrik menggabungkan tanda menjadi level. Level akhir adalah yang
   tertinggi (rubrik aturan 9). Ragu condong ke level lebih tinggi.

Kutipan bukti selalu kalimat asli dari laporan, sehingga lolos pemeriksaan
EVIDENCE_MISMATCH di server Ayomi. Mesin ini tidak mendiagnosis.
"""
import re

LABELS = ["low", "medium", "high", "emergency"]
LABEL_ID = {"low": "rendah", "medium": "sedang", "high": "tinggi", "emergency": "darurat"}
RUBRIC_VERSION = "draf-1"
ENGINE_VERSION = "triage-rules-draf-1-v2"   # naikkan bila aturan berubah
MIN_WORDS = 4

# Sama dengan inti model (triage_core.py), agar missing_information konsisten.
_CONDITION = re.compile(r"(sekarang|saat ini|skrg|kondisi|tenang|bermain lagi|main lagi|tidur|napas|bernapas|sadar|menangis|nangis|lemas|ceria|aktif)", re.I)
_EMPTY_AID = re.compile(r"\s*(-|belum( ada)?( tindakan)?( dicatat)?|tidak ada)?\.?\s*", re.I)


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?;])\s+|\n+", text or "") if len(s.strip()) >= 3]


# ------------------------------------------------------------------ normalisasi
_REPLACE = [
    (r"\[anak\]", "anak"),
    (r"\b(?:tdk|gak|ga|gk|nggak|ngga|enggak|engga|tak)\b", "tidak"),
    (r"\b(?:blm|blum)\b", "belum"),
    (r"\b(?:sdh|udah|udh|dah)\b", "sudah"),
    (r"\byg\b", "yang"), (r"\bdgn\b", "dengan"), (r"\bkrn\b", "karena"), (r"\bskrg\b", "sekarang"),
    (r"\b(?:stlh|sesudah)\b", "setelah"), (r"\blg\b", "lagi"), (r"\bdikit\b", "sedikit"), (r"\btd\b", "tadi"),
    (r"\bortu\b", "orang tua"), (r"\bjatoh\b", "jatuh"),
    (r"\b(?:kejedot|kebentur|kepentok|kejeduk|kejedug)\b", "terbentur"),
    (r"\bkeselek\b", "tersedak"), (r"\bnangis\b", "menangis"), (r"\bbaret\b", "lecet"),
    (r"\bcengeng\b", "rewel"), (r"\bmencret\b", "diare"), (r"\bkecebur\b", "tercebur"),
    (r"\bbernafas", "bernapas"), (r"\bnafas", "napas"),
    (r"\b(\d+)\s*x\b", r"\1 kali"), (r"\bmuntah2\b", "muntah berulang"),
    (r"\b(?:anget|angat)\b", "hangat"), (r"\bnelen\b", "menelan"), (r"\bketelen\b", "tertelan"),
    (r"\bngucur\w*", "mengucur"), (r"\bnyahut\b", "menyahut"),
]
_REPLACE = [(re.compile(p), r) for p, r in _REPLACE]
_INFORMAL = ["keselek", "kejedot", "kebentur", "kepentok", "kejeduk", "kejedug", "nangis", "mencret", "cengeng", "kecebur",
             "bernafas", "baret", "jatoh", "muntah2", "anget", "nelen", "ketelen", "ngucur", "nyahut"]
# Tanda konteks tidak dibatalkan oleh negasi di depannya ("tidak terdaftar memaksa menjemput").
_NO_SUPPRESS = {"pickup_ctx", "food_ctx", "search_ctx", "absent_end", "unauthorized"}

# Kalimat yang meminta prioritas tertentu: bagiannya dibuang sebelum dinilai.
_INJECTION = re.compile(
    r"(?:abaikan|lupakan)\s+(?:semua\s+)?(?:aturan|instruksi|perintah)\w*(?:\s+sebelumnya)?(?:\s+dan\s+\w+\s+\w+)?"
    r"|(?:sistem|system)\s*:\s*[^.!?;]*"
    r"|(?:mohon|tolong|harap)?\s*(?:dicatat|catat|set|ubah|ganti|tulis|tandai|jadikan|turunkan|naikkan|anggap)\b[^.!?;]{0,30}?"
    r"\b(?:urgensi|prioritas|label|level|status)\b[^.!?;]{0,20}?\b(?:low|medium|high|emergency|rendah|sedang|tinggi|darurat)\b(?:\s+saja)?"
    r"|(?:mohon|tolong)?\s*(?:dicatat|catat|tulis)\s+(?:sebagai\s+)?(?:low|medium|high|emergency)\b(?:\s+saja)?"
    r"|tidak\s+(?:usah|perlu)\s+dianggap\s+(?:darurat|serius|penting|tinggi)")

_NEGATORS = {"tidak", "bukan", "tanpa", "belum", "jangan"}
_HYPOTHETICAL = {"tanda", "tanda-tanda", "gejala", "apakah", "jika", "kalau", "bila", "seandainya", "risiko",
                 "waspada", "kemungkinan", "mencegah", "cegah", "antisipasi", "khawatir"}
_BREAKERS = {"lama", "kemudian", "lalu", "tapi", "tetapi", "namun", "setelah", "dan", "sampai", "hingga",
             "karena", "sebab", "akibat", "sehingga", "malah", "justru", "tiba-tiba"}
_FOOD_WORDS = {"makanan", "nasi", "biskuit", "roti", "air", "ludah", "susu", "bubur", "makan", "minum"}
_W = r"(?:[\w\-]+\s+)"   # satu kata lalu spasi

# ------------------------------------------------------------------ tanda
FLAGS = {
    # darurat
    "choking": r"\btersedak\w*",
    "airway": r"\b(?:tidak bisa|tidak dapat|sulit|susah|sukar|tidak mampu)\s+(?:bernapas|napas|bersuara|menangis|batuk|bicara|berbicara)\b"
              r"|\b(?:tidak|berhenti)\s+bernapas\b|\bhenti\s+napas\b|\bsesak\w*|\bmegap\w*|\btersengal\w*"
              r"|\bnapas\w*\s+(?:berbunyi|ngik|mengi|tersengal|megap|tersumbat|sangat cepat)\b|\bmemegang\w*\s+leher\b",
    "blue": r"\b(?:membiru|kebiruan|kebiru-biruan)\b|\b(?:bibir|wajah|muka|mulut|lidah|kulit|badan|tubuh)\w*\s+" + _W + r"{0,2}biru\b"
            r"|\b(?:agak|jadi|menjadi|mulai)\s+biru\b",
    "unconscious": r"\b(?:tidak|belum)\s+(?:sadar|sadarkan diri|merespons|merespon|respons|respon|bereaksi|menanggapi|menyahut|menjawab panggilan)\b"
                   r"|\btergeletak\b"
                   r"|\bpingsan\b|\b(?:sulit|susah|tidak bisa)\s+dibangunkan\b|\bterkulai\b"
                   r"|\bmata\w*\s+tidak\s+(?:mau\s+)?(?:membuka|terbuka)\b",
    "seizure": r"\b(?:kejang|kelojotan|mendelik)\w*",
    "face_swelling": r"\b(?:bibir|wajah|muka|lidah|tenggorokan)\w*\s+" + _W + r"{0,3}bengkak\w*"
                     r"|\bbengkak\w*\s+(?:di\s+)?(?:bibir|wajah|muka|lidah|tenggorokan)\b|\b(?:sulit|susah|sakit)\s+menelan\b",
    "hoarse": r"\bserak\b",
    "food_ctx": r"\b(?:setelah|habis|abis|selesai)\s+(?:makan|snack|menyantap|minum susu|mencicipi|mengunyah)\w*"
                r"|\balergi\w*|\b(?:telur|kacang|udang|kepiting|seafood|susu sapi|ikan laut|gandum)\b",
    "missing": r"\b(?:tidak|belum)\s+(?:ditemukan|ketemu|terlihat|kelihatan)\b|\bterakhir\s+(?:terlihat|dilihat|kelihatan)\b"
               r"|\b(?:menghilang|kabur)\b",
    "child_gone": r"\bhilang\b",
    "search_ctx": r"\b(?:dicari|disisir|menyisir|pencarian|absen|dihitung|menghitung)\b",
    "absent_end": r"\btidak ada\b(?=\s*(?:$|[.,;!?]|dan\b|lagi\b|di\s+(?:ruang|kelas|area|tempat|halaman|kamar)))",
    "pickup_ctx": r"\b(?:jemput|menjemput|dijemput|penjemput|penjemputan|dibawa|membawa)\w*",
    "unauthorized": r"\btidak\s+(?:terdaftar|dikenal|dikenali|berwenang|diizinkan|diberi izin)\b"
                    r"|\btanpa\s+(?:izin|kode|konfirmasi|identitas|sepengetahuan)\b|\btidak ada\s+(?:di|dalam)\s+daftar\b"
                    r"|\bbukan\s+(?:penjemput|wali|orang tua|keluarga)\w*|\borang\s+asing\b|\bmengaku\w*|\bmemaksa\w*"
                    r"|\bmenolak\s+(?:menunjukkan|memperlihatkan)\b",
    "dangerous_ingestion": None,   # pemeriksaan khusus, lihat _dangerous_ingestion
    "head_injury": r"\b(?:terbentur|benturan|terantuk|membentur|terhantam|kena|jatuh|terjatuh)\w*\s+" + _W + r"{0,3}?"
                   r"(?:kepala|dahi|kening|jidat|pelipis|ubun)\w*"
                   r"|\b(?:kepala|dahi|kening|jidat|pelipis)\w*\s+" + _W + r"{0,2}?"
                   r"(?:terbentur|membentur|terantuk|benjol|memar|lebam|berdarah|luka|sobek|robek|bengkak|kena)\w*"
                   r"|\b(?:memar|benjol|luka|lebam|bengkak)\w*\s+(?:di\s+)?(?:kepala|dahi|kening|jidat|pelipis)\w*|\bbenjol\w*",
    "head_red_flag": r"\bmuntah\w*\s+(?:sudah\s+|sebanyak\s+|hingga\s+|sampai\s+|lebih dari\s+)?"
                     r"(?:berulang|berkali\w*|terus|lagi|beberapa|[2-9]|1\d|dua|tiga|empat|lima|enam)\b|\bmuntah-muntah\b"
                     r"|\b(?:sangat|terus|selalu|sering)\s+mengantuk\b|\bmengantuk\s+(?:sekali|terus|berat|banget)\b"
                     r"|\b(?:sulit|susah)\s+dibangunkan\b|\bbicara\w*\s+(?:tidak jelas|pelo|kacau|melantur)\b|\bpelo\b"
                     r"|\bkeluar\s+(?:cairan|darah)\s+dari\s+(?:telinga|hidung)\b|\b(?:pandangan|penglihatan)\w*\s+(?:kabur|ganda)\b"
                     r"|\bkejang\w*|\btidak sadar\b|\bpingsan\b|\blinglung\b|\bpusing\s+(?:berat|sekali|terus)\b",
    "severe_bleeding": r"\b(?:darah|perdarahan|pendarahan)\w*\s+" + _W + r"{0,5}?(?:tidak|belum)\s+(?:mau\s+|juga\s+)?berhenti\b"
                       r"|\b(?:darah|perdarahan|pendarahan)\w*\s+(?:yang\s+)?(?:banyak|mengucur|deras|hebat)\b"
                       r"|\bdarah\w*\s+terus\s+keluar\b|\bberdarah\s+(?:banyak|terus|hebat|deras)\b|\bmengucur\w*|\b(?:banyak|deras)\s+darah\b",
    "drowning": r"\b(?:tenggelam|terendam|tercebur|tertelungkup)\w*|\bjatuh\s+ke\s+(?:kolam|bak|ember|got|selokan|sungai)\b",
    "emergency_services": r"\b(?:layanan darurat|ambulans|ambulan|igd|ugd|gawat darurat|nomor darurat)\b|\b(?:112|119)\b",
    # tinggi
    "high_fever_word": r"\b(?:demam|panas)\w*\s+(?:tinggi|sekali|banget)\b",
    "fever_word": r"\bdemam\w*|\bmeriang\b|\b(?:badan|tubuh|dahi|kening)\w*\s+" + _W + r"{0,2}?(?:panas|hangat|demam)\b"
                  r"|\b(?:agak|sedikit|lumayan|mulai)\s+(?:panas|hangat|demam)\b",
    "repeated_gi": r"\b(?:muntah|diare|bab cair)\w*\s+(?:sudah\s+|sebanyak\s+|hingga\s+|sampai\s+|lebih dari\s+)?"
                   r"(?:berulang|berkali\w*|terus|lagi|beberapa|[2-9]|1\d|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh)\b"
                   r"|\bmuntah-muntah\b|\bdiare\w*",
    "skin_reaction": r"\b(?:ruam|bentol|biduran|kaligata|gatal|kemerahan|merah-merah|bintik merah|bercak merah)\w*",
    "wound": r"\b(?:berdarah|sobek|robek|menganga)\w*|\bluka\w*\s+(?:terbuka|dalam|robek|sobek|menganga)\b"
             r"|\b(?:cukup|agak|sangat|tapi|namun)\s+dalam\b|\b(?:tertusuk|tusukan)\w*|\bkulit\w*\s+(?:terbuka|robek|sobek|terkelupas)\b|\bdarah\w*",
    "limb": r"\btidak\s+(?:mau|bisa|dapat)\s+(?:menggerakkan|digerakkan|bergerak|berjalan|jalan|menapak|berdiri|mengangkat)\w*"
            r"|\bbengkak\w*|\bpatah\b|\bterkilir\b|\bkeseleo\b|\b(?:bentuk|posisi)\w*\s+(?:aneh|bengkok|tidak normal)\b"
            r"|\b(?:menangis|kesakitan|menjerit)\w*\s+(?:setiap\s+kali|tiap\s+kali|saat|ketika|kalau|bila)\s+" + _W + r"{0,1}"
            r"(?:disentuh|dipegang|digerakkan)\b|\bkesakitan\b|\bterjepit\s+pintu\b|\bpincang\b",
    "burn": r"\b(?:luka bakar|melepuh|lepuh|tersiram|tersengat|kesetrum|tersetrum|tersundut)\w*"
            r"|\b(?:air|kuah|teh|kopi|minyak|sup|susu|uap|termos|setrika|kompor|knalpot|panci|nasi)\w*\s+" + _W + r"{0,1}panas\b"
            r"|\bmenyentuh\s+(?:termos|setrika|kompor|knalpot|panci|oven)\b",
    "left_area": r"\b(?:keluar|kabur|lolos|berjalan sendiri|lari)\w*\s+" + _W + r"{0,3}?"
                 r"(?:gerbang|pagar|parkir\w*|jalan raya|jalan besar|luar daycare|luar gedung)\b"
                 r"|\bke\s+luar\s+(?:pagar|gerbang)\b|\btanpa\s+pengawasan\b|\bkeluar\s+(?:dari\s+)?area\b"
                 r"|\bkeluar\s+(?:lewat|melalui)\s+(?:pintu|jendela|gerbang|pagar)\b"
                 r"|\b(?:ditemukan|berada|terlihat)\s+sendirian\b|\bsendirian\s+di\s+(?:parkir\w*|jalan\w*|luar|depan|gerbang)",
    "swallowed": r"\b(?:menelan|tertelan|termakan)\w*|\bmemasukkan\s+" + _W + r"{1,3}ke\s+(?:mulut|hidung|telinga)\b"
                 r"|\bmasuk\s+ke\s+(?:hidung|telinga)\b",
    "eye": None,                   # pemeriksaan khusus, lihat _eye
    "burn_extent": r"\b(?:luas|lebar|melebar|luasnya)\b|\btelapak tangan\b|\bsebagian besar\b",
    "breath_fast": r"\bnapas\w*\s+" + _W + r"{0,2}?(?:cepat|berat|pendek|ngos-ngosan)\b",
    "asthma": r"\basma\w*|\binhaler\b|\bnebuli\w*",
    "skin_spread": r"\b(?:menyebar|meluas|seluruh|sekujur)\b"
                   r"|\b(?:tangan|kaki|perut|punggung|dada|leher|wajah|muka|lengan|paha|badan)\w*\s+dan\s+"
                   r"(?:tangan|kaki|perut|punggung|dada|leher|wajah|muka|lengan|paha|badan)\b",
    "lethargy": r"\b(?:lemas|lemah|lesu|lunglai)\b",
    "dehydration": r"\bbibir\w*\s+kering\b|\bmata\w*\s+cekung\b|\btidak\s+(?:mau|bisa)\s+minum\b"
                   r"|\bmenolak\s+minum\b(?!\s+susu)|\bjarang\s+(?:pipis|kencing)\b",
    # sedang
    "scrape": r"\b(?:lecet|luka kecil|luka ringan)\w*",
    "single_vomit": r"\bmuntah\w*|\bgumoh\b",
    "loose_stool": r"\b(?:bab|pup|eek|buang air besar)\w*\s+" + _W + r"{0,2}?(?:cair|lembek|encer)\b",
    "nosebleed": r"\bmimisan\b|\bhidung\w*\s+" + _W + r"{0,2}berdarah\b|\bdarah\s+(?:dari|di)\s+hidung\b",
    "conflict": r"\b(?:digigit|didorong|dipukul|ditendang|dicubit|dicakar|dijambak|berkelahi|rebutan|bertengkar|menggigit"
                r"|mendorong|memukul|menendang|mencakar|dilempar)\w*|\bkena\s+(?:pukul|tendang|gigit)\b",
    "respiratory": r"\b(?:batuk|pilek|bersin|ingus|flu|meler)\w*|\bhidung\s+tersumbat\b",
    "distress": r"\b(?:menangis|rewel)\w*\s+" + _W + r"{0,2}?(?:lama|seharian|terus|tidak berhenti|sepanjang|berjam|histeris)\w*"
                r"|\b(?:terus|selalu)\s+(?:menangis|rewel|mencari)\w*|\bmencari\s+(?:orang tua|ibu|ayah|mama|papa|bunda)\w*|\bhisteris\b",
    "refuse_food": r"\b(?:menolak|tidak mau)\s+(?:makan|minum susu|menyusu|minum)\b"
                   r"(?!\s+(?:sayur|buah|lauk|ikan|daging|wortel|bayam|sayuran|nasi|snack|kue))",
    "diaper": r"\b(?:ruam|lecet|kemerahan|merah|iritasi)\w*\s+" + _W + r"{0,3}?(?:popok|pantat|bokong|selangkangan)\b"
              r"|\b(?:popok|pantat|bokong)\w*\s+" + _W + r"{0,3}?(?:ruam|lecet|kemerahan|merah|iritasi)\w*",
    "bruise": r"\b(?:memar|lebam|terjepit|terbentur|terantuk|benjol|keseleo|terkilir)\w*",
}
FLAGS = {name: (re.compile(rx) if rx else None) for name, rx in FLAGS.items()}

# Tanda yang ditolak bila di dalam cocokannya sendiri ada negasi ("jatuh tanpa terbentur kepala").
_SPAN_NEGATION = {"head_injury", "face_swelling", "left_area", "burn", "diaper", "nosebleed"}
_LIST_WORDS = {"atau", "maupun", "ataupun", "serta"}   # "tidak ada luka atau memar": negasi berlaku ke semua
_ITEMS = re.compile(r"\b(?:botol|mainan|sepatu|sandal|baju|tas|barang|topi|kaos|kaus|jaket|dot|sendok|buku|pensil|kotak|bekal"
                    r"|popok|tempat minum|celana|kacamata|jepit|ikat rambut|kalung|gelang|boneka|selimut|bantal|handuk"
                    r"|sisir|gelas|piring|tumbler|kunci|ponsel|uang|kartu|seragam|kerudung|jilbab|krayon|stiker)\w*")
_CHILD = re.compile(r"\b(?:anak|ananda|adik|adek|bayi|dia)\w*")


def _object_lost(seg, start):
    """Yang hilang atau belum ketemu adalah barang ("botol minum hilang", "ikat rambut anak hilang")."""
    items = list(_ITEMS.finditer(seg[:start]))
    if not items:
        return False
    first, *later = seg[items[-1].end():start].split(",")
    # Anak disebut setelah koma ("botol tertinggal, anaknya hilang"): yang hilang anak.
    if any(_CHILD.search(part) for part in later):
        return False
    if not _CHILD.search(first):
        return True
    # "botol minum anak hilang": anak sebagai pemilik, tanpa kata penghubung di antaranya.
    words = re.findall(r"[a-z0-9\-]+", first)
    return len(words) <= 3 and not (set(words) & (_BREAKERS | {"sedangkan", "sementara"}))


_TRAUMA = re.compile(r"\b(?:jatuh|terjatuh|terbentur|terantuk|digigit|dipukul|ditendang|terjepit|tersandung)\w*")
_NUMBER_WORDS = re.compile(r"\b(?:satu kali|sekali|1 kali)\b")


def _suppressed(seg, start):
    """Negasi atau pengandaian dalam tiga kata sebelum tanda (kata "atau" tidak dihitung),
    kecuali terpotong kata penghubung seperti "lalu" atau "kemudian"."""
    counted = 0
    for token in reversed(re.findall(r"[a-z0-9\-]+", seg[:start])[-8:]):
        if token in _LIST_WORDS:
            continue
        counted += 1
        if counted > 3:
            return False
        if token in _BREAKERS:
            return False
        if token in _NEGATORS or token in _HYPOTHETICAL:
            return True
    return False


def _accept(name, seg, m):
    text = m.group(0)
    if name in _SPAN_NEGATION and re.search(r"\b(?:tidak|tanpa|bukan|belum)\b", text):
        return False
    after = seg[m.end():m.end() + 40]
    before = seg[max(0, m.start() - 40):m.start()]
    if name == "blue":
        return not re.search(r"\b(?:kuku|jari|memar|lebam|baju|kaos|celana|mainan|pensil|krayon)\w*", seg)
    if name in ("missing", "child_gone") and _object_lost(seg, m.start()):
        return False
    if name == "missing":
        if text.startswith(("tidak", "belum")) and re.match(
                r"\s+(?:ada\s+)?(?:luka|tanda|memar|benjol|darah|bengkak|kelainan|gejala|benda|apa|masalah|bekas|kemasan|sakit|lemas|pucat|cedera)", after):
            return False
        if text == "kabur" and re.search(r"(?:pandangan|penglihatan|mata)\w*\s*$", before):
            return False
        return True
    if name == "child_gone":
        if re.search(r"\b(?:demam|panas|ruam|bengkak|sakit|nyeri|gatal|batuk|pilek|nafsu makan|selera|bentol|memar|rasa)\w*\s+" + _W + r"{0,2}$", before + " "):
            return False
        return bool(re.search(r"\b(?:anak|ananda|kecil|dia|adik)\w*\s+" + _W + r"{0,1}$", before + " ")
                    or re.match(r"\s+(?:dari|di)\s+(?:area|daycare|ruang|halaman|taman|kelas|sekolah|pagar|gerbang|tempat|kamar|lokasi)", after)
                    or re.match(r"\s+(?:saat|ketika|waktu)\b", after))
    if name == "severe_bleeding" and not re.search(r"(?:tidak|belum)\s", text):
        return not re.match(r"[\s,]*(?:\w+\s+){0,2}?(?:tapi|namun|lalu|dan)?\s*(?:sudah|akhirnya)\s+(?:berhenti|mampet)", after)
    if name == "face_swelling":
        return not _TRAUMA.search(seg)
    if name == "drowning" and text.startswith("tertelungkup"):
        return bool(re.search(r"\b(?:air|ember|kolam|bak|baskom|got)\b", seg))
    if name == "repeated_gi" and text.startswith("diare"):
        return not _NUMBER_WORDS.match(after.strip())
    if name in ("skin_reaction", "wound"):
        if name == "skin_reaction":
            # "krim ruam" adalah nama barang, bukan gejala.
            return not (re.search(r"\b(?:popok|pantat|bokong|selangkangan)\b", seg)
                        or re.search(r"\b(?:krim|salep|bedak|obat|lotion)\s+$", before))
        return not re.search(r"\b(?:hidung|mimisan)\w*", seg)
    if name == "burn" and text.startswith("tersiram"):
        return bool(re.search(r"\b(?:panas|mendidih|teh|kopi|kuah|minyak|sup)\b", seg))
    if name == "limb":
        if text.startswith("bengkak") and re.search(r"\b(?:gusi|gigi|nyamuk)\w*", seg):
            return False
        if text in ("keseleo", "terkilir") and re.search(r"\bmasih\s+(?:bisa|dapat|mau)\s+(?:berjalan|jalan|lari|berlari)\b", seg) \
                and re.search(r"\b(?:sedikit|ringan|normal)\b", seg):
            return False
    if name == "breath_fast":
        # "napas tidak cepat", "napas normal, tidak berat"
        return not re.search(r"\b(?:tidak|normal|teratur|biasa)\b", text)
    if name == "scrape":
        # lecet lama dari rumah ("bekas kemarin, sudah kering")
        return not re.search(r"\b(?:bekas|kemarin|sudah kering|dari rumah)\b", seg)
    if name == "swallowed":
        nxt = re.findall(r"[a-z]+", after)[:2]
        return not (nxt and nxt[0] in _FOOD_WORDS)
    return True


_INGEST_VERB = re.compile(r"\b(?:menelan|tertelan|termakan|terminum|meminum|minum|memakan|menjilat|mengemut|mengunyah)\b"
                          r"|\b(?:masuk\w*|memasukkan)\s+" + _W + r"{0,3}ke\s+(?:dalam\s+)?mulut\b")
_STRONG_VERB = re.compile(r"\b(?:menelan|tertelan|termakan|memakan|mengunyah)\b")
_CHEMICAL = re.compile(r"\b(?:baterai|batere|batrai|magnet|cairan\s+(?:pembersih|kimia)|pembersih|karbol|deterjen|detergen|pemutih"
                       r"|disinfektan|alkohol|bensin|minyak tanah|racun|pestisida|obat nyamuk|kapur barus|kamper|kapur ajaib"
                       r"|sabun cuci|pewangi)\w*")
_PILL = re.compile(r"\b(?:obat|pil|tablet|kapsul)\b")
_PILL_RISK = re.compile(r"\b(?:butir|milik|orang dewasa|dewasa|tidak sengaja|tanpa sengaja|dari tas|sebotol|setengah botol|banyak)\b")
_CHEM_SMELL = re.compile(r"\bmulut\w*\s+" + _W + r"{0,2}(?:berbau|bau)\s+(?:cairan|kimia|pembersih|bensin|minyak|sabun|deterjen|detergen|pemutih|karbol|obat nyamuk)\w*")


def _dangerous_ingestion(seg):
    if _CHEM_SMELL.search(seg):
        return True
    for verb in _INGEST_VERB.finditer(seg):
        if _suppressed(seg, verb.start()):
            continue
        if _CHEMICAL.search(seg):
            return True
        if _PILL.search(seg) and (_STRONG_VERB.match(verb.group(0)) or _PILL_RISK.search(seg)):
            return True
    return False


_EYE_HARM = re.compile(r"\b(?:cakar|dicakar|tercakar|mencakar|colok|tercolok|dicolok|tergores|digores|kena|terkena|tusuk|tertusuk"
                       r"|dilempar|terlempar|pasir|cairan|sabun|kuku)\w*")


def _eye(seg):
    m = re.search(r"\bmata\w*\b", seg)
    return bool(m and _EYE_HARM.search(seg) and not re.search(r"\b(?:mendelik|tertutup|mengantuk|membuka|terbuka|cekung)\b", seg)
                and not _suppressed(seg, m.start()))


_TEMP_CTX = re.compile(r"\b(?:suhu|demam|panas|termometer|menunjukkan|hangat|temperatur)\w*")
_TEMP_NUM = re.compile(r"(?<![\d.,:])(\d{2,3})(?:[.,](\d{1,2}))?(?![\d:])")
_NOT_TEMP = re.compile(r"\s*(?:menit|jam|bulan|tahun|kali|detik|kg|gram|cm|ml|hari|orang|anak|%)")


def _temperatures(seg):
    out = []
    for m in _TEMP_NUM.finditer(seg):
        whole, frac = m.group(1), m.group(2)
        value = float(f"{whole}.{frac}") if frac else float(whole)
        if len(whole) == 3 and not frac:
            value /= 10            # "392" = 39,2 setelah tanda baca dibuang
        if not 34 <= value <= 43:
            continue
        after = seg[m.end():m.end() + 12]
        if _NOT_TEMP.match(after):
            continue
        if re.match(r"\s*(?:°|derajat|c\b|celsius)", after) or _TEMP_CTX.search(seg[max(0, m.start() - 30):m.start()]):
            out.append(value)
    return out


# ------------------------------------------------------------------ aturan rubrik
# (level, kode, alasan, semua tanda wajib, salah satu tanda). Urutan = prioritas kutipan bukti.
RULES = [
    (3, "choking_airway", "tersedak dengan tanda sulit bernapas atau membiru", ["choking"], ["airway", "blue"]),
    (3, "airway", "tanda sulit bernapas", [], ["airway"]),
    (3, "cyanosis", "bibir atau wajah membiru", [], ["blue"]),
    (3, "unconscious", "tidak sadar atau tidak merespons", [], ["unconscious"]),
    (3, "seizure", "kejang", [], ["seizure"]),
    (3, "allergy_severe", "reaksi alergi dengan bengkak wajah/bibir atau sulit menelan", [], ["face_swelling"]),
    (3, "allergy_hoarse", "suara serak setelah makan, tanda reaksi alergi berat", ["hoarse", "food_ctx"], []),
    (3, "missing_child", "anak tidak ditemukan", [], ["missing", "child_gone"]),
    (3, "missing_search", "anak tidak ada saat dihitung atau dicari", ["search_ctx", "absent_end"], []),
    (3, "unauthorized_pickup", "anak dijemput atau dibawa pihak yang tidak berwenang", ["pickup_ctx", "unauthorized"], []),
    (3, "dangerous_ingestion", "menelan baterai, magnet, obat, atau cairan kimia", [], ["dangerous_ingestion"]),
    (3, "head_red_flag", "benturan kepala diikuti tanda bahaya", ["head_injury", "head_red_flag"], []),
    (3, "severe_bleeding", "perdarahan yang tidak berhenti atau banyak", [], ["severe_bleeding"]),
    (3, "drowning", "tenggelam atau terendam air", [], ["drowning"]),
    (3, "burn_extensive", "luka bakar yang luas", ["burn", "burn_extent"], []),
    (3, "emergency_services", "layanan darurat sedang atau sudah dihubungi", [], ["emergency_services"]),
    (2, "choking", "tersedak (tetap tinggi walaupun sudah teratasi)", [], ["choking"]),
    (2, "high_fever", "demam 39 °C atau lebih", [], ["high_fever_word", "high_fever_num"]),
    (2, "infant_fever", "demam pada bayi di bawah 12 bulan", ["infant"], ["fever_word", "fever_num"]),
    (2, "head_injury", "benturan kepala (minimal tinggi)", [], ["head_injury"]),
    (2, "repeated_gi", "muntah atau diare berulang", [], ["repeated_gi"]),
    (2, "allergy_mild", "ruam atau bentol setelah makan tanpa sesak", ["skin_reaction", "food_ctx"], []),
    (2, "wound", "luka terbuka atau berdarah", [], ["wound"]),
    (2, "breathing_fast", "napas cepat atau berat tanpa tanda sesak berat", [], ["breath_fast"]),
    (2, "asthma_symptoms", "batuk atau pilek pada anak dengan riwayat asma", ["asthma", "respiratory"], []),
    (2, "skin_widespread", "ruam atau bentol yang menyebar (dugaan reaksi alergi)", ["skin_reaction", "skin_spread"], []),
    (2, "limb", "dugaan cedera tangan atau kaki", [], ["limb"]),
    (2, "burn", "luka bakar", [], ["burn"]),
    (2, "left_area", "anak sempat keluar area tanpa pengawasan", [], ["left_area"]),
    (2, "swallowed_object", "menelan benda kecil", [], ["swallowed"]),
    (2, "eye", "cedera di dekat mata", [], ["eye"]),
    (2, "lethargy", "anak lemas", [], ["lethargy"]),
    (2, "dehydration", "tanda kurang cairan disertai demam, muntah, atau diare", ["dehydration"],
     ["fever_word", "fever_num", "single_vomit", "repeated_gi"]),
    (1, "fever", "demam ringan", [], ["fever_word", "fever_num"]),
    (1, "scrape", "lecet atau luka kecil", [], ["scrape"]),
    (1, "vomit_once", "muntah satu kali", [], ["single_vomit"]),
    (1, "loose_stool", "BAB cair atau lembek satu kali", [], ["loose_stool"]),
    (1, "nosebleed", "mimisan", [], ["nosebleed"]),
    (1, "conflict", "digigit, didorong, atau dipukul teman tanpa luka terbuka", [], ["conflict"]),
    (1, "respiratory", "batuk atau pilek", [], ["respiratory"]),
    (1, "distress", "rewel atau menangis lama, menolak makan atau minum", [], ["distress", "refuse_food", "dehydration"]),
    (1, "diaper_rash", "ruam popok", [], ["diaper"]),
    (1, "skin", "ruam atau bentol", [], ["skin_reaction"]),
    (1, "bruise", "memar atau terbentur ringan", [], ["bruise"]),
]

# Kosakata untuk memperbaiki salah ketik dua huruf tertukar: kata kunci aturan saja.
_VOCAB = set()
for _rx in FLAGS.values():
    if _rx is not None:
        _VOCAB.update(re.findall(r"[a-z]{5,}", re.sub(r"\\[a-zA-Z]", " ", _rx.pattern)))
for _rx in (_INGEST_VERB, _CHEMICAL, _PILL, _EYE_HARM, _TEMP_CTX):
    _VOCAB.update(re.findall(r"[a-z]{5,}", re.sub(r"\\[a-zA-Z]", " ", _rx.pattern)))
_VOCAB.update(_INFORMAL)
_VOCAB.update({w + "nya" for w in list(_VOCAB)})
_VOCAB.update(_NEGATORS | _HYPOTHETICAL | _BREAKERS)
_VOCAB.update({"bernapas", "napasnya", "bibirnya", "wajahnya", "kepalanya", "dahinya", "keningnya", "badannya", "termometer",
               "derajat", "dibangunkan", "ditemukan", "terdaftar", "penjemput", "menjemput", "dijemput"})


def _swaps(word):
    return {word[:i] + word[i + 1] + word[i] + word[i + 2:] for i in range(len(word) - 1)}


def _fix_typos(text):
    """Kata kunci dengan satu pasang huruf tertukar (dua pasang untuk kata >= 6 huruf)."""
    def fix(m):
        word = m.group(0)
        if len(word) < 5 or word in _VOCAB:
            return word
        once = _swaps(word)
        found = sorted(once & _VOCAB)
        if not found:
            # Dua pasang tertukar: kata >= 6 huruf, atau kata negasi ("tdika" -> "tidak").
            found = sorted({c for w in once for c in _swaps(w)} & (_VOCAB if len(word) >= 6 else _NEGATORS))
        return found[0] if found else word
    return re.sub(r"[a-z]+", fix, text)


def normalize(text):
    text = _fix_typos((text or "").lower())
    for rx, repl in _REPLACE:
        text = rx.sub(repl, text)
    return _INJECTION.sub(" ", text)


def _segments(inp):
    segs = [("description", s) for s in _sentences(inp["description"])]
    segs += [("fact", s) for fact in inp["observed_facts"] for s in _sentences(fact)]
    segs += [("first_aid", s) for s in _sentences(inp["first_aid_already_done"])]
    return segs


def detect(inp):
    """Tanda yang ditemukan: {nama: [indeks kalimat]} dan daftar kalimat asli."""
    segs = _segments(inp)
    hits = {}
    for i, (_, original) in enumerate(segs):
        seg = normalize(original)
        for name, rx in FLAGS.items():
            if rx is None:
                found = _dangerous_ingestion(seg) if name == "dangerous_ingestion" else _eye(seg)
            else:
                found = any((name in _NO_SUPPRESS or not _suppressed(seg, m.start())) and _accept(name, seg, m)
                            for m in rx.finditer(seg))
            if found:
                hits.setdefault(name, []).append(i)
        temps = _temperatures(seg)
        if temps:
            if max(temps) >= 39:
                hits.setdefault("high_fever_num", []).append(i)
            if max(temps) >= 37.5:
                hits.setdefault("fever_num", []).append(i)
    age = inp.get("age_months")
    if age is not None and age < 12:
        hits["infant"] = []
    return hits, [s for _, s in segs]


def match_rules(hits):
    return [rule for rule in RULES
            if all(f in hits for f in rule[3]) and (not rule[4] or any(f in hits for f in rule[4]))]


def missing_information(inp, text):
    missing = []
    if not _CONDITION.search(text):
        missing.append("Kondisi anak saat ini")
    if _EMPTY_AID.fullmatch(inp.get("first_aid_already_done") or ""):
        missing.append("Pertolongan pertama yang sudah dilakukan")
    return missing


def triage(inp):
    """Hasil sesuai kontrak AI v1 dan info tambahan (aturan yang cocok)."""
    refs_by_id = {s["id"]: f'{s["id"]}@{s["version"]}' for s in inp.get("sop_references", [])}
    text = " ".join([inp["description"], *inp["observed_facts"], inp["first_aid_already_done"] or ""])
    missing = missing_information(inp, text)
    words = len(re.findall(r"\w+", " ".join([inp["description"], *inp["observed_facts"]])))
    if words < MIN_WORDS:
        refs = [refs_by_id[k] for k in ("incident-workflow",) if k in refs_by_id]
        return {"urgency": None,
                "reason": "Uraian laporan terlalu singkat untuk dinilai; urgensi dari pelapor tetap dipakai.",
                "evidence_quotes": [], "sop_refs": refs,
                "missing_information": missing or ["Uraian kejadian yang lebih lengkap"],
                "operational_actions": ["request_more_information"] + (["follow_approved_sop"] if refs else []),
                "needs_human_review": True}, {"matched_rules": []}

    hits, segs = detect(inp)
    matched = match_rules(hits)
    level = max((rule[0] for rule in matched), default=0)
    urgency = LABELS[level]
    quotes, top = [], None
    if level > 0:
        top = next(rule for rule in matched if rule[0] == level)
        indexes = sorted({i for f in top[3] + top[4] for i in hits.get(f, [])})
        quotes = [segs[i] for i in indexes][:2]
    refs = [refs_by_id[k] for k in (f"triage-{urgency}", "incident-workflow") if k in refs_by_id]
    caregiver = inp.get("caregiver_urgency")
    raises = caregiver in LABELS and level > LABELS.index(caregiver)
    actions = (["notify_manager"] if level >= 2 or raises else []) \
        + (["request_more_information"] if missing and level >= 1 else []) + (["follow_approved_sop"] if refs else [])
    if quotes:
        reason = f'Usulan prioritas {LABEL_ID[urgency]} menurut rubrik ({top[2]}), berdasarkan bagian laporan: "{quotes[0]}".'
    elif level == 0:
        reason = "Usulan prioritas rendah: tidak ditemukan tanda yang memerlukan prioritas lebih tinggi menurut rubrik."
    else:
        reason = f"Usulan prioritas {LABEL_ID[urgency]} menurut rubrik ({top[2]})."
    return ({"urgency": urgency, "reason": reason, "evidence_quotes": quotes, "sop_refs": refs,
             "missing_information": missing, "operational_actions": actions, "needs_human_review": True},
            {"matched_rules": [rule[1] for rule in matched]})
