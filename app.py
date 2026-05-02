from supabase import create_client
import streamlit as st
import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta
import re
import pandas as pd

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
def login_user(email, password):
    try:
        response = supabase.auth.sign_in_with_password({
            "email": email.strip(),
            "password": password.strip()
        })

        return {
            "user": {
                "id": response.user.id,
                "email": response.user.email
            },
            "access_token": response.session.access_token
        }

    except Exception as e:
        st.error("Supabase giriş hatası:")
        st.write(e)
        return None


def create_auth_user_and_profile(email, password, role):
    """
    Streamlit Cloud'da service_role kullanmadan kullanıcı oluşturur.
    Supabase Auth sign_up user döndürürse profiles tablosunu hemen upsert eder.
    Eğer Supabase e-posta onayı açıksa kullanıcı ilk girişten önce mail onayı gerekebilir.
    """
    email = email.strip().lower()
    password = password.strip()

    response = supabase.auth.sign_up({
        "email": email,
        "password": password
    })

    created_user_id = None
    if getattr(response, "user", None) is not None:
        created_user_id = response.user.id

    if created_user_id:
        supabase.table("profiles").upsert({
            "id": created_user_id,
            "email": email,
            "role": role
        }).execute()

    return response
if "user" not in st.session_state:
    st.session_state.user = None

DB_PATH = Path("aday_takip.db")
DEFAULT_EXCEL = Path("data/meslekler_aday_takip_duzenli.xlsx")

st.set_page_config(
    page_title="Aday Takip Sistemi",
    page_icon="🌿",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -------------------- OTURUM ZAMAN AŞIMI --------------------
SESSION_TIMEOUT_MINUTES = 10
now_ts = datetime.now()

if "last_activity" not in st.session_state:
    st.session_state.last_activity = now_ts

if st.session_state.user is not None:
    inactive_for = now_ts - st.session_state.last_activity
    if inactive_for > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
        st.session_state.user = None
        st.session_state.last_activity = now_ts
        st.warning("10 dakika işlem yapılmadığı için oturum kapatıldı. Lütfen tekrar giriş yap.")
        st.rerun()
    else:
        st.session_state.last_activity = now_ts
if st.session_state.user is None:
    st.title("Giriş Yap")

    email = st.text_input("E-posta")
    password = st.text_input("Şifre", type="password")

    if st.button("Giriş"):
        user = login_user(email, password)

        if user:
            st.session_state.user = user
            st.success("Giriş başarılı")
            st.rerun()
        else:
            st.error("Hatalı giriş")

    st.stop()


user_id = st.session_state.user["user"]["id"]

profile = supabase.table("profiles").select("*").eq("id", user_id).execute()

if profile.data:
    user_role = profile.data[0]["role"]
else:
    user_role = "goruntuleme"

st.sidebar.success(f"Rol: {user_role}")
CSS = """
<style>
.stApp {
    background: linear-gradient(135deg, #fbf7f1 0%, #f4f8fb 48%, #f8f1fb 100%);
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #eaf7f1 0%, #f7eefb 100%);
}
.hero {
    padding: 22px 26px;
    border-radius: 24px;
    background: linear-gradient(120deg, #dff3ea, #eee7fb, #fde8dc);
    box-shadow: 0 8px 24px rgba(80, 96, 120, 0.10);
    margin-bottom: 18px;
}
.hero h1 { margin:0; color:#2f3542; font-size:34px; }
.hero p { margin:8px 0 0 0; color:#5d6470; font-size:16px; }
.card {
    padding: 18px 20px;
    border-radius: 22px;
    background: rgba(255,255,255,0.82);
    box-shadow: 0 8px 24px rgba(80, 96, 120, 0.08);
    border: 1px solid rgba(255,255,255,0.85);
    margin-bottom: 16px;
}
.stButton > button {
    border-radius: 14px;
    border: 0;
    background: linear-gradient(120deg, #7aa89f, #a78bca);
    color: white;
    font-weight: 700;
}
[data-testid="stMetricValue"] { color:#4f837a; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# -------------------- DB --------------------

def connect():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def execute(sql, params=()):
    conn = connect()
    cur = conn.cursor()
    cur.execute(sql, params)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS evaluators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL UNIQUE,
        role TEXT DEFAULT 'Değerlendirici',
        phone TEXT,
        status TEXT DEFAULT 'Aktif',
        note TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_type TEXT NOT NULL,
        exam_date TEXT NOT NULL,
        exam_time TEXT NOT NULL,
        exam_place TEXT,
        myk_exam_id TEXT,
        qualification_id INTEGER,
        firm_id INTEGER,
        evaluator_id INTEGER,
        observer_required INTEGER DEFAULT 0,
        observer_id INTEGER,
        status TEXT DEFAULT 'Planlandı',
        note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (qualification_id) REFERENCES qualifications(id),
        FOREIGN KEY (firm_id) REFERENCES firms(id),
        FOREIGN KEY (evaluator_id) REFERENCES evaluators(id),
        FOREIGN KEY (observer_id) REFERENCES evaluators(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_session_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        candidate_process_id INTEGER NOT NULL,
        candidate_id INTEGER NOT NULL,
        attendance_status TEXT DEFAULT 'Planlandı',
        result_status TEXT DEFAULT 'Sonuç Bekliyor',
        score REAL,
        note TEXT,
        UNIQUE(session_id, candidate_process_id),
        FOREIGN KEY (session_id) REFERENCES exam_sessions(id),
        FOREIGN KEY (candidate_process_id) REFERENCES candidate_processes(id),
        FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_session_qualifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        qualification_id INTEGER NOT NULL,
        UNIQUE(session_id, qualification_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cash_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_date TEXT DEFAULT CURRENT_DATE,
        transaction_type TEXT NOT NULL,
        category TEXT,
        firm_id INTEGER,
        candidate_id INTEGER,
        session_id INTEGER,
        amount REAL NOT NULL DEFAULT 0,
        vat_included INTEGER DEFAULT 1,
        payment_status TEXT DEFAULT 'Bekliyor',
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (firm_id) REFERENCES firms(id),
        FOREIGN KEY (candidate_id) REFERENCES candidates(id),
        FOREIGN KEY (session_id) REFERENCES exam_sessions(id)
    )
    """)


    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_session_qualifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        qualification_id INTEGER NOT NULL,
        UNIQUE(session_id, qualification_id)
    )
    """)

    conn.commit()
    conn.close()

def many(sql, rows):
    conn = connect()
    cur = conn.cursor()
    cur.executemany(sql, rows)
    conn.commit()
    conn.close()

def df_query(sql, params=()):
    conn = connect()
    df = pd.read_sql_query(sql, conn, params=params)
    conn.close()
    return df

def init_db():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS firms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        status TEXT DEFAULT 'Aktif',
        note TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS qualifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT DEFAULT '',
        name TEXT NOT NULL,
        alt_units TEXT DEFAULT '',
        sector TEXT DEFAULT '',
        status TEXT DEFAULT 'Aktif',
        note TEXT,
        UNIQUE(code, name, alt_units)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_fees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        firm_id INTEGER NOT NULL,
        qualification_id INTEGER NOT NULL,
        fee_without_vat REAL DEFAULT 0,
        vat_rate REAL DEFAULT 20,
        fee_with_vat REAL DEFAULT 0,
        currency TEXT DEFAULT 'TRY',
        source_section TEXT,
        source_row INTEGER,
        note TEXT,
        UNIQUE(firm_id, qualification_id),
        FOREIGN KEY (firm_id) REFERENCES firms(id),
        FOREIGN KEY (qualification_id) REFERENCES qualifications(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tc_no TEXT UNIQUE,
        full_name TEXT NOT NULL,
        birth_date TEXT,
        age INTEGER,
        phone TEXT,
        note TEXT,
        created_at TEXT DEFAULT CURRENT_DATE
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS candidate_processes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_id INTEGER NOT NULL,
        qualification_id INTEGER NOT NULL,
        firm_id INTEGER NOT NULL,
        fee_id INTEGER,
        fee_without_vat REAL DEFAULT 0,
        vat_rate REAL DEFAULT 20,
        fee_with_vat REAL DEFAULT 0,

        candidate_payment_amount REAL DEFAULT 0,
        candidate_payment_received INTEGER DEFAULT 0,
        firm_payment_amount REAL DEFAULT 0,
        firm_payment_sent INTEGER DEFAULT 0,

        first_right_status TEXT DEFAULT 'Planlanmadı',
        first_exam_date TEXT,
        second_right_status TEXT DEFAULT 'Planlanmadı',
        second_exam_date TEXT,

        entitlement_status TEXT DEFAULT 'Bekliyor',
        certificate_fee_paid INTEGER DEFAULT 0,
        certificate_print_status TEXT DEFAULT 'Başlamadı',
        certificate_delivery_status TEXT DEFAULT 'Teslim edilmedi',

        general_status TEXT DEFAULT 'Aktif',
        note TEXT,
        created_at TEXT DEFAULT CURRENT_DATE,

        FOREIGN KEY (candidate_id) REFERENCES candidates(id),
        FOREIGN KEY (qualification_id) REFERENCES qualifications(id),
        FOREIGN KEY (firm_id) REFERENCES firms(id),
        FOREIGN KEY (fee_id) REFERENCES exam_fees(id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS candidate_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        source_type TEXT DEFAULT 'Firma',
        status TEXT DEFAULT 'Aktif',
        note TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS import_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_name TEXT,
        imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
        rows_imported INTEGER,
        message TEXT
    )
    """)

    conn.commit()
    conn.close()

def reset_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    ensure_v4_tables()
    seed_default_evaluators()


def ensure_v4_tables():
    conn = connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS evaluators (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL UNIQUE,
        role TEXT DEFAULT 'Değerlendirici',
        phone TEXT,
        status TEXT DEFAULT 'Aktif',
        note TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_type TEXT NOT NULL,
        exam_date TEXT NOT NULL,
        exam_time TEXT NOT NULL,
        exam_place TEXT,
        myk_exam_id TEXT,
        qualification_id INTEGER,
        firm_id INTEGER,
        evaluator_id INTEGER,
        observer_required INTEGER DEFAULT 0,
        observer_id INTEGER,
        status TEXT DEFAULT 'Planlandı',
        note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_session_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        candidate_process_id INTEGER NOT NULL,
        candidate_id INTEGER NOT NULL,
        attendance_status TEXT DEFAULT 'Planlandı',
        result_status TEXT DEFAULT 'Sonuç Bekliyor',
        score REAL,
        note TEXT,
        UNIQUE(session_id, candidate_process_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS exam_session_qualifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        qualification_id INTEGER NOT NULL,
        UNIQUE(session_id, qualification_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS candidate_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        source_type TEXT DEFAULT 'Firma',
        status TEXT DEFAULT 'Aktif',
        note TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS cash_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_date TEXT DEFAULT CURRENT_DATE,
        transaction_type TEXT NOT NULL,
        category TEXT,
        firm_id INTEGER,
        candidate_id INTEGER,
        session_id INTEGER,
        amount REAL NOT NULL DEFAULT 0,
        vat_included INTEGER DEFAULT 1,
        payment_status TEXT DEFAULT 'Bekliyor',
        description TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


def seed_default_evaluators():
    ensure_v4_tables()
    defaults = [
        ("Değerlendirici 1", "Değerlendirici"),
        ("Değerlendirici 2", "Değerlendirici"),
        ("Gözetmen 1", "Gözetmen"),
    ]
    for name, role in defaults:
        execute("""
            INSERT OR IGNORE INTO evaluators(full_name, role, status, note)
            VALUES (?, ?, 'Aktif', 'Varsayılan')
        """, (name, role))

def ensure_column(table, column, definition):
    conn = connect()
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [row[1] for row in cur.fetchall()]
    if column not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()
    conn.close()

def ensure_schema_updates():
    ensure_column("candidates", "source_id", "INTEGER")
    ensure_column("cash_ledger", "person_name", "TEXT")


# Uygulama başlamadan önce veritabanını ve eksik kolonları hazırla
init_db()
ensure_v4_tables()
seed_default_evaluators()
ensure_schema_updates()


# -------------------- helpers --------------------

def normalize_text(value):
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ").strip())

def parse_money(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace("₺", "").replace("TL", "").replace("TRY", "").strip()
    text = text.replace(".", "").replace(",", ".")
    m = re.search(r"\d+(\.\d+)?", text)
    return float(m.group(0)) if m else None

def parse_code_and_name(raw_name):
    text = normalize_text(raw_name)
    # Bu Excel’de bazı satırlar "19UY0402-4/00 Cep Telefonu..." şeklinde.
    m = re.match(r"^((?:\d{2}UY\d{4}-\d)(?:/\d{2})?)\s+(.+)$", text, flags=re.IGNORECASE)
    if m:
        return m.group(1).upper(), normalize_text(m.group(2))
    return "", text

def calculate_vat(without_vat, with_vat):
    without_vat = parse_money(without_vat)
    with_vat = parse_money(with_vat)

    if without_vat and with_vat:
        vat_rate = round(((with_vat / without_vat) - 1) * 100, 2) if without_vat else 20
        return round(without_vat, 2), vat_rate, round(with_vat, 2)

    if without_vat and not with_vat:
        vat_rate = 20
        with_vat = without_vat * 1.20
        return round(without_vat, 2), vat_rate, round(with_vat, 2)

    if with_vat and not without_vat:
        vat_rate = 20
        without_vat = with_vat / 1.20
        return round(without_vat, 2), vat_rate, round(with_vat, 2)

    return 0, 20, 0

def calculate_age(birth_date):
    today = date.today()
    return today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

def get_options(sql, params=()):
    df = df_query(sql, params)
    return {str(r["label"]): int(r["id"]) for _, r in df.iterrows()}

def options_with_select(options_dict, select_label="Seç"):
    return {select_label: None, **options_dict}

def safe_delete(table, row_id):
    execute(f"DELETE FROM {table} WHERE id=?", (int(row_id),))

def to_excel_bytes(df):
    from io import BytesIO
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Veri")
    return output.getvalue()

def download_df_button(df, filename):
    st.download_button(
        "Excel indir",
        data=to_excel_bytes(df),
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def to_multi_excel_bytes(sheets: dict):
    from io import BytesIO
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = str(sheet_name)[:31]
            if df is None:
                df = pd.DataFrame()
            df.to_excel(writer, index=False, sheet_name=safe_name)
    return output.getvalue()


def money_fmt(x):
    try:
        return f"{float(x):,.2f} TL"
    except Exception:
        return "0,00 TL"


def sync_auto_ledger_for_process(process_id):
    """
    Aday sürecindeki ödeme checkbox'larına göre otomatik cari kaydı üretir.
    Aynı süreç için eski otomatik kayıtları silip güncel duruma göre yeniden oluşturur.
    Manuel cari kayıtlarına dokunmaz.
    """
    process_id = int(process_id)

    process_df = df_query("""
        SELECT cp.id AS process_id,
               cp.candidate_id,
               cp.firm_id,
               cp.candidate_payment_amount,
               cp.candidate_payment_received,
               cp.firm_payment_amount,
               cp.firm_payment_sent,
               c.full_name AS candidate_name,
               f.name AS firm_name
        FROM candidate_processes cp
        JOIN candidates c ON c.id=cp.candidate_id
        JOIN firms f ON f.id=cp.firm_id
        WHERE cp.id=?
    """, (process_id,))

    if process_df.empty:
        return

    r = process_df.iloc[0]

    execute(
        "DELETE FROM cash_ledger WHERE candidate_process_id=? AND auto_generated=1",
        (process_id,)
    )

    candidate_payment_amount = float(r["candidate_payment_amount"] or 0)
    firm_payment_amount = float(r["firm_payment_amount"] or 0)

    if int(r["candidate_payment_received"] or 0) == 1 and candidate_payment_amount > 0:
        execute("""
            INSERT INTO cash_ledger(
                transaction_date, transaction_type, category, firm_id, candidate_id, session_id,
                person_name, candidate_process_id, auto_generated,
                amount, vat_included, payment_status, description
            )
            VALUES (CURRENT_DATE, 'Gelir', 'Aday Ödemesi', ?, ?, NULL, ?, ?, 1, ?, 1, 'Yapıldı', ?)
        """, (
            int(r["firm_id"]),
            int(r["candidate_id"]),
            str(r["candidate_name"] or ""),
            process_id,
            candidate_payment_amount,
            "Aday sürecinden otomatik oluşturuldu"
        ))

    if int(r["firm_payment_sent"] or 0) == 1 and firm_payment_amount > 0:
        execute("""
            INSERT INTO cash_ledger(
                transaction_date, transaction_type, category, firm_id, candidate_id, session_id,
                person_name, candidate_process_id, auto_generated,
                amount, vat_included, payment_status, description
            )
            VALUES (CURRENT_DATE, 'Gider', 'Firmaya Ödeme', ?, ?, NULL, ?, ?, 1, ?, 1, 'Yapıldı', ?)
        """, (
            int(r["firm_id"]),
            int(r["candidate_id"]),
            str(r["firm_name"] or ""),
            process_id,
            firm_payment_amount,
            "Aday sürecinden otomatik oluşturuldu"
        ))



def evaluator_has_conflict(evaluator_id, exam_date, exam_time, exclude_session_id=None):
    if exclude_session_id:
        df = df_query("""
            SELECT id, session_type, myk_exam_id, exam_place
            FROM exam_sessions
            WHERE evaluator_id=? AND exam_date=? AND exam_time=? AND id<>? AND status!='İptal'
        """, (int(evaluator_id), str(exam_date), str(exam_time), int(exclude_session_id)))
    else:
        df = df_query("""
            SELECT id, session_type, myk_exam_id, exam_place
            FROM exam_sessions
            WHERE evaluator_id=? AND exam_date=? AND exam_time=? AND status!='İptal'
        """, (int(evaluator_id), str(exam_date), str(exam_time)))
    return df

def get_exam_candidate_count(session_id):
    df = df_query("SELECT COUNT(*) AS c FROM exam_session_candidates WHERE session_id=?", (int(session_id),))
    return int(df["c"][0]) if not df.empty else 0

def auto_update_observer_required(session_id):
    count = get_exam_candidate_count(session_id)
    required = 1 if count > 8 else 0
    execute("UPDATE exam_sessions SET observer_required=? WHERE id=?", (required, int(session_id)))
    return required, count



def process_has_active_exam(process_ids, session_type):
    if not process_ids:
        return pd.DataFrame()

    placeholders = ",".join(["?"] * len(process_ids))
    params = [session_type] + [int(x) for x in process_ids]

    return df_query(f"""
        SELECT esc.candidate_process_id,
               es.id AS session_id,
               es.session_type,
               es.exam_date,
               es.exam_time,
               es.myk_exam_id,
               es.status
        FROM exam_session_candidates esc
        JOIN exam_sessions es ON es.id=esc.session_id
        WHERE es.session_type=?
          AND es.status!='İptal'
          AND esc.candidate_process_id IN ({placeholders})
    """, tuple(params))


def create_exam_session_with_candidates(
    session_type,
    exam_date,
    exam_time,
    exam_place,
    myk_exam_id,
    selected_qids,
    firm_id,
    evaluator_id,
    status,
    note,
    selected_ref_process_ids,
    reference_candidate_id
):
    execute("""
        INSERT INTO exam_sessions(
            session_type, exam_date, exam_time, exam_place, myk_exam_id,
            qualification_id, firm_id, evaluator_id, status, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        session_type, str(exam_date), str(exam_time), exam_place, myk_exam_id,
        selected_qids[0], firm_id, evaluator_id, status, note
    ))

    new_session_id = int(df_query("SELECT MAX(id) AS id FROM exam_sessions")["id"][0])

    for qid in selected_qids:
        execute("""
            INSERT OR IGNORE INTO exam_session_qualifications(session_id, qualification_id)
            VALUES (?, ?)
        """, (new_session_id, qid))

    for process_id in selected_ref_process_ids:
        execute("""
            INSERT OR IGNORE INTO exam_session_candidates(session_id, candidate_process_id, candidate_id)
            VALUES (?, ?, ?)
        """, (new_session_id, process_id, reference_candidate_id))

    auto_update_observer_required(new_session_id)

    # Aday süreç kartındaki 1. hak / 2. hak tarihlerini otomatik güncelle.
    for process_id in selected_ref_process_ids:
        proc = df_query("SELECT first_exam_date, first_right_status, second_exam_date, second_right_status FROM candidate_processes WHERE id=?", (int(process_id),))
        if not proc.empty:
            first_date = proc["first_exam_date"][0]
            second_date = proc["second_exam_date"][0]

            if not first_date:
                execute("""
                    UPDATE candidate_processes
                    SET first_exam_date=?, first_right_status=?
                    WHERE id=?
                """, (str(exam_date), "Planlandı", int(process_id)))
            elif not second_date:
                execute("""
                    UPDATE candidate_processes
                    SET second_exam_date=?, second_right_status=?
                    WHERE id=?
                """, (str(exam_date), "Planlandı", int(process_id)))

    return new_session_id

def upsert_firm(name):
    name = normalize_text(name).upper()
    if not name:
        return None
    execute("INSERT OR IGNORE INTO firms(name, status, note) VALUES (?, 'Aktif', 'Excel import')", (name,))
    df = df_query("SELECT id FROM firms WHERE name=?", (name,))
    return int(df["id"][0]) if not df.empty else None

def upsert_qualification(code, name, alt_units, sector):
    code = normalize_text(code).upper()
    name = normalize_text(name)
    alt_units = normalize_text(alt_units)
    sector = normalize_text(sector)

    if not name:
        return None

    execute("""
        INSERT OR IGNORE INTO qualifications(code, name, alt_units, sector, status, note)
        VALUES (?, ?, ?, ?, 'Aktif', 'meslekler_aday_takip_duzenli.xlsx')
    """, (code, name, alt_units, sector))

    df = df_query("""
        SELECT id FROM qualifications
        WHERE code=? AND name=? AND alt_units=?
        ORDER BY id LIMIT 1
    """, (code, name, alt_units))
    return int(df["id"][0]) if not df.empty else None

def import_meslekler_excel(path_or_file):
    df = pd.read_excel(path_or_file, sheet_name="Temiz Liste")
    required = ["Firma", "Ulusal Yeterlilik", "Fiyat KDV Hariç", "Fiyat KDV Dahil"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError("Eksik kolonlar: " + ", ".join(missing))

    imported = 0
    skipped = 0

    for _, row in df.iterrows():
        firm = normalize_text(row.get("Firma", ""))
        raw_qualification = normalize_text(row.get("Ulusal Yeterlilik", ""))
        alt_units = normalize_text(row.get("Alt Birimler", ""))
        sector = normalize_text(row.get("Alan/Sektör", ""))
        source_section = normalize_text(row.get("Kaynak Bölüm", ""))
        source_row = row.get("Kaynak Satır", None)

        if not firm or not raw_qualification:
            skipped += 1
            continue

        code, q_name = parse_code_and_name(raw_qualification)
        without_vat, vat_rate, with_vat = calculate_vat(
            row.get("Fiyat KDV Hariç", None),
            row.get("Fiyat KDV Dahil", None)
        )

        firm_id = upsert_firm(firm)
        qualification_id = upsert_qualification(code, q_name, alt_units, sector)

        if not firm_id or not qualification_id:
            skipped += 1
            continue

        try:
            source_row_int = int(source_row) if not pd.isna(source_row) else None
        except Exception:
            source_row_int = None

        execute("""
            INSERT OR REPLACE INTO exam_fees(
                firm_id, qualification_id, fee_without_vat, vat_rate, fee_with_vat,
                currency, source_section, source_row, note
            )
            VALUES (?, ?, ?, ?, ?, 'TRY', ?, ?, ?)
        """, (
            firm_id, qualification_id, without_vat, vat_rate, with_vat,
            source_section, source_row_int, "Temiz Liste sheetinden import"
        ))

        imported += 1

    execute("""
        INSERT INTO import_logs(source_name, rows_imported, message)
        VALUES (?, ?, ?)
    """, ("meslekler_aday_takip_duzenli.xlsx", imported, f"{imported} satır işlendi, {skipped} satır atlandı"))

    return imported, skipped


# -------------------- UI --------------------

st.markdown("""
<div class="hero">
<h1>🌿 Aday ve Sınav Takip Sistemi</h1>
<p>Aday, yeterlilik, alt birim, sınav planlama ve cari takibi.</p>
</div>
""", unsafe_allow_html=True)

# -------------------- ROL BAZLI MENÜ --------------------

if user_role == "admin":
    menu_options = [
        "Aday Kaydet",
        "Aday Süreçleri",
        "Sınav Planlama",
        "Sınav Takvimi",
        "Cari Gelir-Gider",
        "Excel Kaynak Yükleme",
        "Tanımlar ve Ücretler",
        "Raporlar",
        "Ayarlar"
    ]

elif user_role == "operasyon":
    menu_options = [
        "Aday Kaydet",
        "Aday Süreçleri",
        "Sınav Planlama",
        "Sınav Takvimi"
    ]

elif user_role == "muhasebe":
    menu_options = [
        "Cari Gelir-Gider",
        "Raporlar"
    ]

else:
    menu_options = [
        "Aday Süreçleri",
        "Sınav Takvimi"
    ]

menu = st.sidebar.radio("Menü", menu_options)

if st.sidebar.button("Çıkış Yap"):
    st.session_state.user = None
    st.rerun()


if menu == "Aday Kaydet":
    if user_role not in ["admin", "operasyon"]:
        st.error("Bu sayfaya erişim yetkin yok")
        st.stop()

    st.header("Aday Kaydet")

    meslek_options = get_options("""
        SELECT MIN(q.id) AS id,
               CASE
                 WHEN q.code IS NOT NULL AND q.code != ''
                   THEN q.code || ' - ' || q.name
                 ELSE q.name
               END AS label
        FROM qualifications q
        JOIN exam_fees ef ON ef.qualification_id=q.id
        WHERE q.status='Aktif'
        GROUP BY q.code, q.name
        ORDER BY label
    """)

    if not meslek_options:
        st.warning("Önce Excel Kaynak Yükleme sekmesinden dosyayı içe aktar.")
    else:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("1) Aday Bilgileri")
        c1, c2 = st.columns(2)
        with c1:
            full_name = st.text_input("Ad Soyad *")
            tc_no = st.text_input("TC No")
            birth_date = st.date_input("Doğum tarihi", value=date(2000, 1, 1), min_value=date(1930, 1, 1), max_value=date.today(), format="DD/MM/YYYY")
            age = calculate_age(birth_date)
            st.success(f"Otomatik yaş: {age}")
        with c2:
            phone = st.text_input("Telefon")
            source_options = options_with_select(get_options("SELECT id, name AS label FROM candidate_sources WHERE status='Aktif' ORDER BY name"), "Seç")
            source_label = st.selectbox("Aday kaynağı / kimden geldi", list(source_options.keys()))
            candidate_note = st.text_area("Aday notu")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("2) Meslek / Alt Birimler / Firma")

        meslek_label = st.selectbox("Meslek / Yeterlilik seçimi *", ["Seç"] + list(meslek_options.keys()))
        if meslek_label == "Seç":
            st.info("Lütfen meslek / yeterlilik seç.")
            st.stop()

        any_qid = meslek_options[meslek_label]
        selected_q = df_query("SELECT code, name FROM qualifications WHERE id=?", (any_qid,))
        selected_code = selected_q["code"][0]
        selected_name = selected_q["name"][0]

        alt_df = df_query("""
            SELECT q.id, q.alt_units
            FROM qualifications q
            JOIN exam_fees ef ON ef.qualification_id=q.id
            WHERE q.code=? AND q.name=? AND q.status='Aktif'
            GROUP BY q.id, q.alt_units
            ORDER BY CASE WHEN q.alt_units='' THEN 0 ELSE 1 END, q.alt_units
        """, (selected_code, selected_name))

        alt_label_to_id = {}
        for _, r in alt_df.iterrows():
            alt_text = normalize_text(r["alt_units"])
            label = "Alt birim yok / genel" if not alt_text else alt_text
            alt_label_to_id[label] = int(r["id"])

        selected_alt_labels = st.multiselect(
            "Alt birim seçimi — birden fazla seçilebilir",
            list(alt_label_to_id.keys()),
            default=list(alt_label_to_id.keys())[:1] if alt_label_to_id else []
        )

        selected_qualification_ids = [alt_label_to_id[x] for x in selected_alt_labels]

        firm_id = None
        selected_firm_name = ""
        fee_rows = []

        if not selected_qualification_ids:
            st.warning("En az bir alt birim/yeterlilik seçmelisin.")
        else:
            # Ortak firma kuralı: aday aynı kayıtta seçtiği tüm alt birimler için aynı firmaya bağlanır.
            firm_sets = []
            for qid in selected_qualification_ids:
                fdf = df_query("""
                    SELECT f.id, f.name
                    FROM exam_fees ef
                    JOIN firms f ON f.id=ef.firm_id
                    WHERE ef.qualification_id=?
                    ORDER BY f.name
                """, (qid,))
                firm_sets.append(set((int(r["id"]), str(r["name"])) for _, r in fdf.iterrows()))

            common_firms = set.intersection(*firm_sets) if firm_sets else set()
            firm_labels = {name: fid for fid, name in sorted(common_firms, key=lambda x: x[1])}

            if not firm_labels:
                st.error("Seçilen alt birimlerin tamamı için ortak firma bulunamadı. Alt birim seçimini azalt veya ücret tanımlarını kontrol et.")
            else:
                firm_label = st.selectbox("Firma seçimi *", ["Seç"] + list(firm_labels.keys()))
                if firm_label == "Seç":
                    st.info("Lütfen firma seç.")
                    firm_id = None
                    selected_firm_name = ""
                else:
                    firm_id = firm_labels[firm_label]
                    selected_firm_name = firm_label

                fee_rows = []
                if firm_id:
                    for qid in selected_qualification_ids:
                        row = df_query("""
                            SELECT ef.id AS fee_id, q.id AS qualification_id,
                                   CASE WHEN q.code != '' THEN q.code || ' - ' || q.name ELSE q.name END AS qualification,
                                   q.alt_units,
                                   ef.fee_without_vat, ef.vat_rate, ef.fee_with_vat
                            FROM exam_fees ef
                            JOIN qualifications q ON q.id=ef.qualification_id
                            WHERE ef.qualification_id=? AND ef.firm_id=?
                        """, (qid, firm_id))
                        if not row.empty:
                            fee_rows.append(row.iloc[0])

                fee_preview = pd.DataFrame(fee_rows)
                if not fee_preview.empty:
                    st.write("Seçilen alt birimlerin ücretleri:")
                    st.dataframe(
                        fee_preview[["qualification", "alt_units", "fee_without_vat", "vat_rate", "fee_with_vat"]],
                        width="stretch"
                    )
                    total_with_vat = float(fee_preview["fee_with_vat"].sum())
                    st.info(f"Toplam KDV dahil ücret: {total_with_vat:,.2f} TL")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("3) Ödemeler")
        p1, p2 = st.columns(2)
        with p1:
            candidate_payment_amount = st.number_input("Adaydan alınan toplam ödeme", min_value=0.0, step=100.0)
            candidate_payment_received = st.checkbox("Adaydan ödeme alındı")
        with p2:
            firm_payment_amount = st.number_input("Firmaya iletilen toplam ödeme", min_value=0.0, step=100.0)
            firm_payment_sent = st.checkbox("Firmaya ödeme iletildi")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("4) Sınav Hakları")
        status_options = ["Planlanmadı", "Planlandı", "Başarılı", "Başarısız", "Katılmadı", "İptal"]
        s1, s2 = st.columns(2)
        with s1:
            first_right_status = st.selectbox("1. hak durumu", status_options)
            first_exam_date = st.date_input("1. hak sınav tarihi", value=None, format="DD/MM/YYYY")
        with s2:
            second_right_status = st.selectbox("2. hak durumu", status_options)
            second_exam_date = st.date_input("2. hak sınav tarihi", value=None, format="DD/MM/YYYY")
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.subheader("5) Belge Süreci")
        b1, b2 = st.columns(2)
        with b1:
            entitlement_status = st.selectbox("Belge almaya hak kazanma", ["Bekliyor", "Hak kazandı", "Hak kazanamadı"])
            certificate_fee_paid = st.checkbox("Belge parasını ödedi")
        with b2:
            certificate_print_status = st.selectbox("Belge basım durumu", ["Başlamadı", "Basımda", "Geldi"])
            certificate_delivery_status = st.selectbox("Belge teslim durumu", ["Teslim edilmedi", "Teslim edildi"])
        process_note = st.text_area("Süreç notu")
        st.markdown('</div>', unsafe_allow_html=True)

        if st.button("Adayı ve Seçilen Alt Birim Süreçlerini Kaydet"):
            if not full_name.strip():
                st.error("Ad Soyad zorunludur.")
            elif not selected_qualification_ids or not firm_id:
                st.error("Meslek, en az bir alt birim/yeterlilik ve firma seçimi zorunludur.")
            else:
                execute("""
                    INSERT OR IGNORE INTO candidates(tc_no, full_name, birth_date, age, phone, source_id, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    tc_no.strip() or None,
                    full_name.strip().upper(),
                    str(birth_date),
                    age,
                    phone.strip(),
                    source_options[source_label],
                    candidate_note
                ))

                if tc_no.strip():
                    cand_df = df_query("SELECT id FROM candidates WHERE tc_no=?", (tc_no.strip(),))
                else:
                    cand_df = df_query("SELECT id FROM candidates WHERE full_name=? ORDER BY id DESC LIMIT 1", (full_name.strip().upper(),))
                candidate_id = int(cand_df["id"][0])

                created = 0
                for fr in fee_rows:
                    qid = int(fr["qualification_id"])
                    fee_id = int(fr["fee_id"])
                    fee_without_vat = float(fr["fee_without_vat"])
                    vat_rate = float(fr["vat_rate"])
                    fee_with_vat = float(fr["fee_with_vat"])

                    execute("""
                        INSERT INTO candidate_processes(
                            candidate_id, qualification_id, firm_id, fee_id,
                            fee_without_vat, vat_rate, fee_with_vat,
                            candidate_payment_amount, candidate_payment_received,
                            firm_payment_amount, firm_payment_sent,
                            first_right_status, first_exam_date,
                            second_right_status, second_exam_date,
                            entitlement_status, certificate_fee_paid,
                            certificate_print_status, certificate_delivery_status,
                            note
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        candidate_id, qid, firm_id, fee_id,
                        fee_without_vat, vat_rate, fee_with_vat,
                        candidate_payment_amount, 1 if candidate_payment_received else 0,
                        firm_payment_amount, 1 if firm_payment_sent else 0,
                        first_right_status, str(first_exam_date) if first_exam_date else None,
                        second_right_status, str(second_exam_date) if second_exam_date else None,
                        entitlement_status, 1 if certificate_fee_paid else 0,
                        certificate_print_status, certificate_delivery_status,
                        process_note
                    ))
                    new_process_id = int(df_query("SELECT MAX(id) AS id FROM candidate_processes")["id"][0])
                    sync_auto_ledger_for_process(new_process_id)
                    created += 1

                st.success(f"Aday kaydedildi. Oluşturulan alt birim/yeterlilik süreci: {created}. Cari otomatik güncellendi.")


elif menu == "Aday Süreçleri":
    st.header("Aday Süreçleri")
    search = st.text_input("Aday adı / TC ara")

    where = ""
    params = ()
    if search.strip():
        where = "WHERE c.full_name LIKE ? OR c.tc_no LIKE ?"
        params = (f"%{search.strip().upper()}%", f"%{search.strip()}%")

    df = df_query(f"""
        SELECT cp.id AS süreç_id, c.id AS aday_id, c.full_name AS aday, c.tc_no AS tc, c.birth_date AS doğum_tarihi,
               c.age AS yaş, c.phone AS telefon,
               cs.name AS aday_kaynağı,
               CASE WHEN q.code != '' THEN q.code || ' - ' || q.name ELSE q.name END AS yeterlilik,
               q.alt_units AS alt_birimler,
               f.name AS firma,
               cp.fee_without_vat AS kdv_hariç,
               cp.vat_rate AS kdv_oranı,
               cp.fee_with_vat AS kdv_dahil,
               cp.candidate_payment_amount AS adaydan_alınan,
               CASE cp.candidate_payment_received WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS aday_ödeme,
               cp.firm_payment_amount AS firmaya_iletilen,
               CASE cp.firm_payment_sent WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS firma_ödeme,
               cp.first_right_status AS birinci_hak,
               cp.second_right_status AS ikinci_hak,
               cp.entitlement_status AS belge_hakkı,
               CASE cp.certificate_fee_paid WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS belge_parası,
               cp.certificate_print_status AS basım,
               cp.certificate_delivery_status AS teslim,
               cp.note AS süreç_notu,
               c.note AS aday_notu,
               cp.created_at AS kayıt_tarihi
        FROM candidate_processes cp
        JOIN candidates c ON c.id=cp.candidate_id
        LEFT JOIN candidate_sources cs ON cs.id=c.source_id
        JOIN qualifications q ON q.id=cp.qualification_id
        JOIN firms f ON f.id=cp.firm_id
        {where}
        ORDER BY cp.id DESC
    """, params)
    st.dataframe(df, width="stretch")
    download_df_button(df, "aday_surecleri.xlsx")

    st.subheader("Aday / Süreç Güncelle")
    if not df.empty:
        selected_id = st.selectbox("Güncellenecek Süreç ID", ["Seç"] + [str(x) for x in df["süreç_id"].tolist()])
        if selected_id != "Seç":
            detail = df_query("""
                SELECT cp.*, c.full_name, c.tc_no, c.birth_date, c.age, c.phone, c.note AS candidate_note, c.source_id,
                       q.code, q.name AS qualification_name, q.alt_units,
                       f.name AS firm_name
                FROM candidate_processes cp
                JOIN candidates c ON c.id=cp.candidate_id
                JOIN qualifications q ON q.id=cp.qualification_id
                JOIN firms f ON f.id=cp.firm_id
                WHERE cp.id=?
            """, (int(selected_id),))

            if not detail.empty:
                row = detail.iloc[0]

                source_options = options_with_select(
                    get_options("SELECT id, name AS label FROM candidate_sources WHERE status='Aktif' ORDER BY name"),
                    "Seç"
                )
                source_labels = list(source_options.keys())
                current_source_label = "Seç"
                for label, sid in source_options.items():
                    if sid == row["source_id"]:
                        current_source_label = label
                        break

                with st.form("candidate_process_edit_form"):
                    st.markdown("### Aday Bilgileri")
                    c1, c2 = st.columns(2)
                    with c1:
                        edit_full_name = st.text_input("Ad Soyad", value=str(row["full_name"] or ""))
                        edit_tc_no = st.text_input("TC No", value=str(row["tc_no"] or ""))
                        current_birth = pd.to_datetime(row["birth_date"], errors="coerce")
                        edit_birth_date = st.date_input(
                            "Doğum tarihi",
                            value=current_birth.date() if not pd.isna(current_birth) else date(2000, 1, 1),
                            min_value=date(1930, 1, 1),
                            max_value=date.today(),
                            format="DD/MM/YYYY"
                        )
                        edit_age = calculate_age(edit_birth_date)
                        st.info(f"Otomatik yaş: {edit_age}")
                    with c2:
                        edit_phone = st.text_input("Telefon", value=str(row["phone"] or ""))
                        edit_source_label = st.selectbox(
                            "Aday kaynağı / kimden geldi",
                            source_labels,
                            index=source_labels.index(current_source_label) if current_source_label in source_labels else 0
                        )
                        edit_candidate_note = st.text_area("Aday notu", value=str(row["candidate_note"] or ""))

                    st.markdown("### Süreç Bilgileri")
                    st.info(f"Yeterlilik: {row['code'] or ''} {row['qualification_name']} / {row['alt_units'] or 'Genel'} | Firma: {row['firm_name']}")

                    s1, s2, s3 = st.columns(3)
                    with s1:
                        edit_candidate_payment_amount = st.number_input("Adaydan alınan ödeme", min_value=0.0, step=100.0, value=float(row["candidate_payment_amount"] or 0))
                        edit_candidate_payment_received = st.checkbox("Adaydan ödeme alındı", value=bool(row["candidate_payment_received"]))
                        edit_firm_payment_amount = st.number_input("Firmaya iletilen ödeme", min_value=0.0, step=100.0, value=float(row["firm_payment_amount"] or 0))
                        edit_firm_payment_sent = st.checkbox("Firmaya ödeme iletildi", value=bool(row["firm_payment_sent"]))
                    with s2:
                        status_options = ["Planlanmadı", "Planlandı", "Başarılı", "Başarısız", "Katılmadı", "İptal"]
                        edit_first = st.selectbox("1. hak", status_options, index=status_options.index(row["first_right_status"]) if row["first_right_status"] in status_options else 0)

                        current_first_exam = pd.to_datetime(row["first_exam_date"], errors="coerce")
                        edit_first_exam_date = st.date_input(
                            "1. hak sınav tarihi",
                            value=current_first_exam.date() if not pd.isna(current_first_exam) else None,
                            format="DD/MM/YYYY"
                        )

                        edit_second = st.selectbox("2. hak", status_options, index=status_options.index(row["second_right_status"]) if row["second_right_status"] in status_options else 0)

                        current_second_exam = pd.to_datetime(row["second_exam_date"], errors="coerce")
                        edit_second_exam_date = st.date_input(
                            "2. hak sınav tarihi",
                            value=current_second_exam.date() if not pd.isna(current_second_exam) else None,
                            format="DD/MM/YYYY"
                        )

                        entitlement_options = ["Bekliyor", "Hak kazandı", "Hak kazanamadı"]
                        edit_entitlement = st.selectbox("Belge hakkı", entitlement_options, index=entitlement_options.index(row["entitlement_status"]) if row["entitlement_status"] in entitlement_options else 0)
                    with s3:
                        edit_cert_paid = st.checkbox("Belge parasını ödedi", value=bool(row["certificate_fee_paid"]))
                        print_options = ["Başlamadı", "Basımda", "Geldi"]
                        edit_print_status = st.selectbox("Basım", print_options, index=print_options.index(row["certificate_print_status"]) if row["certificate_print_status"] in print_options else 0)
                        delivery_options = ["Teslim edilmedi", "Teslim edildi"]
                        edit_delivery = st.selectbox("Teslim", delivery_options, index=delivery_options.index(row["certificate_delivery_status"]) if row["certificate_delivery_status"] in delivery_options else 0)

                    edit_process_note = st.text_area("Süreç notu", value=str(row["note"] or ""))

                    submitted = st.form_submit_button("Aday ve Süreci Güncelle")

                if submitted:
                    if not edit_full_name.strip():
                        st.error("Ad Soyad zorunludur.")
                    else:
                        execute("""
                            UPDATE candidates
                            SET full_name=?, tc_no=?, birth_date=?, age=?, phone=?, source_id=?, note=?
                            WHERE id=?
                        """, (
                            edit_full_name.strip().upper(),
                            edit_tc_no.strip() or None,
                            str(edit_birth_date),
                            edit_age,
                            edit_phone.strip(),
                            source_options[edit_source_label],
                            edit_candidate_note,
                            int(row["candidate_id"])
                        ))

                        execute("""
                            UPDATE candidate_processes
                            SET candidate_payment_amount=?, candidate_payment_received=?,
                                firm_payment_amount=?, firm_payment_sent=?,
                                first_right_status=?, first_exam_date=?,
                                second_right_status=?, second_exam_date=?,
                                entitlement_status=?, certificate_fee_paid=?,
                                certificate_print_status=?, certificate_delivery_status=?,
                                note=?
                            WHERE id=?
                        """, (
                            edit_candidate_payment_amount,
                            1 if edit_candidate_payment_received else 0,
                            edit_firm_payment_amount,
                            1 if edit_firm_payment_sent else 0,
                            edit_first,
                            str(edit_first_exam_date) if edit_first_exam_date else None,
                            edit_second,
                            str(edit_second_exam_date) if edit_second_exam_date else None,
                            edit_entitlement,
                            1 if edit_cert_paid else 0,
                            edit_print_status,
                            edit_delivery,
                            edit_process_note,
                            int(selected_id)
                        ))

                        sync_auto_ledger_for_process(int(selected_id))

                        st.success("Aday ve süreç güncellendi. Cari otomatik güncellendi.")
                        st.rerun()


elif menu == "Sınav Planlama":
    if user_role not in ["admin", "operasyon"]:
        st.error("Bu sayfaya erişim yetkin yok")
        st.stop()

    st.header("Sınav Planlama")

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("1) Aday/Süreçten Sınav Oturumu Oluştur")

    process_df = df_query("""
        SELECT cp.id AS process_id,
               c.id AS candidate_id,
               c.full_name AS candidate_name,
               c.tc_no,
               q.id AS qualification_id,
               q.code,
               q.name AS qualification_name,
               q.alt_units,
               f.id AS firm_id,
               f.name AS firm_name
        FROM candidate_processes cp
        JOIN candidates c ON c.id=cp.candidate_id
        LEFT JOIN candidate_sources cs ON cs.id=c.source_id
        JOIN qualifications q ON q.id=cp.qualification_id
        JOIN firms f ON f.id=cp.firm_id
        ORDER BY c.full_name, q.name, q.alt_units
    """)

    evaluator_options = get_options("SELECT id, full_name || ' / ' || role AS label FROM evaluators WHERE status='Aktif' ORDER BY full_name")

    if process_df.empty:
        st.warning("Önce Aday Kaydet sekmesinden aday süreci oluşturmalısın.")
    elif not evaluator_options:
        st.warning("Önce Tanımlar ve Ücretler > Değerlendirici/Gözetmen sekmesinden değerlendirici eklemelisin.")
    else:
        process_labels = []
        for _, r in process_df.iterrows():
            qual_label = f"{r['code']} - {r['qualification_name']}" if normalize_text(r["code"]) else r["qualification_name"]
            alt_label = f" / {r['alt_units']}" if normalize_text(r["alt_units"]) else ""
            tc_label = f" / {r['tc_no']}" if normalize_text(r["tc_no"]) else ""
            process_labels.append(f"{r['candidate_name']}{tc_label} | {qual_label}{alt_label} | Firma: {r['firm_name']}")

        selected_process_label = st.selectbox("Referans aday/süreç seç", ["Seç"] + process_labels)
        if selected_process_label == "Seç":
            st.info("Lütfen referans aday/süreç seç.")
            st.stop()

        selected_process = process_df.iloc[process_labels.index(selected_process_label)]

        selected_process_id = int(selected_process["process_id"])
        reference_candidate_id = int(selected_process["candidate_id"])
        firm_id = int(selected_process["firm_id"])
        ref_code = selected_process["code"]
        ref_name = selected_process["qualification_name"]

        st.success(f"Otomatik firma: {selected_process['firm_name']}")
        st.info(f"Referans meslek: {ref_code + ' - ' if normalize_text(ref_code) else ''}{ref_name}")

        plan_mode = st.selectbox(
            "Planlama türü",
            ["Seç", "Teorik + Performans birlikte", "Sadece Teorik", "Sadece Performans"]
        )
        if plan_mode == "Seç":
            st.info("Lütfen planlama türü seç.")
            st.stop()

        # Aynı aday + aynı firma + aynı meslek için seçilebilir alt birimler.
        possible_q_df = df_query("""
            SELECT cp.id AS process_id, q.id AS qualification_id,
                   CASE WHEN q.alt_units='' THEN 'Alt birim yok / genel' ELSE q.alt_units END AS alt_label
            FROM candidate_processes cp
            JOIN qualifications q ON q.id=cp.qualification_id
            WHERE cp.candidate_id=? AND cp.firm_id=? AND q.code=? AND q.name=?
            ORDER BY q.alt_units
        """, (reference_candidate_id, firm_id, ref_code, ref_name))

        q_label_to_ids = {str(r["alt_label"]): (int(r["qualification_id"]), int(r["process_id"])) for _, r in possible_q_df.iterrows()}

        if plan_mode in ["Teorik + Performans birlikte", "Sadece Performans"]:
            selected_alt_labels = st.multiselect(
                "Performans sınavında yer alacak alt birimler",
                list(q_label_to_ids.keys()),
                default=list(q_label_to_ids.keys())
            )
        else:
            selected_alt_single = st.selectbox("Teorik sınav için alt birim/yeterlilik", ["Seç"] + list(q_label_to_ids.keys()))
            if selected_alt_single == "Seç":
                st.info("Lütfen teorik sınav için alt birim/yeterlilik seç.")
                st.stop()
            selected_alt_labels = [selected_alt_single]

        selected_qids = [q_label_to_ids[x][0] for x in selected_alt_labels]
        selected_ref_process_ids = [q_label_to_ids[x][1] for x in selected_alt_labels]

        if not selected_qids:
            st.warning("En az bir alt birim/yeterlilik seçmelisin.")

        with st.form("create_exam_session"):
            status = st.selectbox("Durum", ["Planlandı", "Tamamlandı", "İptal"])
            exam_place = st.text_input("Sınav yeri")
            eval_label = st.selectbox("Değerlendirici", ["Seç"] + list(evaluator_options.keys()))
            st.text_input("Firma", value=str(selected_process["firm_name"]), disabled=True)
            st.text_area("Seçilen alt birimler", value="\\n".join(selected_alt_labels), disabled=True)

            if plan_mode == "Teorik + Performans birlikte":
                st.markdown("### Teorik Sınav")
                t1, t2, t3 = st.columns(3)
                with t1:
                    teorik_date = st.date_input("Teorik sınav tarihi", value=date.today(), format="DD/MM/YYYY")
                with t2:
                    teorik_time = st.time_input("Teorik sınav saati")
                with t3:
                    teorik_myk_exam_id = st.text_input("Teorik MYK sınav ID")

                st.markdown("### Performans Sınavı")
                p1, p2, p3 = st.columns(3)
                with p1:
                    performans_date = st.date_input("Performans sınav tarihi", value=date.today(), format="DD/MM/YYYY")
                with p2:
                    performans_time = st.time_input("Performans sınav saati")
                with p3:
                    performans_myk_exam_id = st.text_input("Performans MYK sınav ID")

            else:
                st.markdown("### Sınav Bilgileri")
                c1, c2, c3 = st.columns(3)
                with c1:
                    exam_date = st.date_input("Sınav tarihi", value=date.today(), format="DD/MM/YYYY")
                with c2:
                    exam_time = st.time_input("Sınav saati")
                with c3:
                    myk_exam_id = st.text_input("MYK sınav ID")

            note = st.text_area("Sınav notu")

            if st.form_submit_button("Sınav Oturumu Oluştur ve Referans Adayı Ekle"):
                if not selected_qids:
                    st.error("Alt birim/yeterlilik seçmeden sınav oluşturulamaz.")
                elif eval_label == "Seç":
                    st.error("Değerlendirici seçmelisin.")
                else:
                    evaluator_id = evaluator_options[eval_label]

                    if plan_mode == "Teorik + Performans birlikte":
                        duplicate_teorik = process_has_active_exam(selected_ref_process_ids, "Teorik")
                        duplicate_performans = process_has_active_exam(selected_ref_process_ids, "Performans")
                        conflict_teorik = evaluator_has_conflict(evaluator_id, str(teorik_date), str(teorik_time))
                        conflict_performans = evaluator_has_conflict(evaluator_id, str(performans_date), str(performans_time))

                        same_time_conflict = (str(teorik_date) == str(performans_date)) and (str(teorik_time) == str(performans_time))

                        if not duplicate_teorik.empty or not duplicate_performans.empty:
                            st.error("Bu aday/süreç için aktif sınav planı zaten var. Aynı türden tekrar sınav açılmadı.")
                            if not duplicate_teorik.empty:
                                st.write("Mevcut teorik plan:")
                                st.dataframe(duplicate_teorik, width="stretch")
                            if not duplicate_performans.empty:
                                st.write("Mevcut performans plan:")
                                st.dataframe(duplicate_performans, width="stretch")
                        elif same_time_conflict:
                            st.error("Teorik ve performans sınavı aynı değerlendirici için aynı tarih/saatte planlanamaz.")
                        elif not conflict_teorik.empty:
                            st.error("Değerlendirici çakışması var. Bu değerlendirici teorik sınav saatinde başka sınava atanmış. Sınavlar oluşturulmadı.")
                            st.dataframe(conflict_teorik, width="stretch")
                        elif not conflict_performans.empty:
                            st.error("Değerlendirici çakışması var. Bu değerlendirici performans sınavı saatinde başka sınava atanmış. Sınavlar oluşturulmadı.")
                            st.dataframe(conflict_performans, width="stretch")
                        else:
                            teorik_id = create_exam_session_with_candidates(
                                "Teorik",
                                teorik_date,
                                teorik_time,
                                exam_place,
                                teorik_myk_exam_id,
                                selected_qids,
                                firm_id,
                                evaluator_id,
                                status,
                                note,
                                selected_ref_process_ids,
                                reference_candidate_id
                            )

                            performans_id = create_exam_session_with_candidates(
                                "Performans",
                                performans_date,
                                performans_time,
                                exam_place,
                                performans_myk_exam_id,
                                selected_qids,
                                firm_id,
                                evaluator_id,
                                status,
                                note,
                                selected_ref_process_ids,
                                reference_candidate_id
                            )

                            st.success(f"Teorik ve performans sınavları oluşturuldu. Teorik ID: {teorik_id}, Performans ID: {performans_id}")

                    else:
                        session_type = "Teorik" if plan_mode == "Sadece Teorik" else "Performans"
                        duplicate_df = process_has_active_exam(selected_ref_process_ids, session_type)
                        conflict_df = evaluator_has_conflict(evaluator_id, str(exam_date), str(exam_time))

                        if not duplicate_df.empty:
                            st.error(f"Bu aday/süreç için aktif {session_type} sınav planı zaten var. Tekrar sınav oturumu oluşturulmadı.")
                            st.dataframe(duplicate_df, width="stretch")
                        elif not conflict_df.empty:
                            st.error("Değerlendirici çakışması var. Bu değerlendirici aynı gün ve aynı saatte başka bir sınava atanmış. Sınav oturumu oluşturulmadı.")
                            st.dataframe(conflict_df, width="stretch")
                        else:
                            session_id = create_exam_session_with_candidates(
                                session_type,
                                exam_date,
                                exam_time,
                                exam_place,
                                myk_exam_id,
                                selected_qids,
                                firm_id,
                                evaluator_id,
                                status,
                                note,
                                selected_ref_process_ids,
                                reference_candidate_id
                            )
                            st.success(f"{session_type} sınav oturumu oluşturuldu. Oturum ID: {session_id}")
    st.markdown('</div>', unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("2) Mevcut Sınava Uygun Aday Ekle")

    sessions_df = df_query("""
        SELECT es.id,
               es.exam_date || ' ' || es.exam_time || ' / ' || es.session_type || ' / ' ||
               COALESCE(es.myk_exam_id, 'MYK ID yok') || ' / ' ||
               f.name || ' / ' ||
               CASE WHEN q.code != '' THEN q.code || ' - ' || q.name ELSE q.name END AS label,
               es.session_type, es.firm_id
        FROM exam_sessions es
        LEFT JOIN qualifications q ON q.id=es.qualification_id
        LEFT JOIN firms f ON f.id=es.firm_id
        ORDER BY es.exam_date DESC, es.exam_time DESC, es.id DESC
    """)

    if sessions_df.empty:
        st.info("Önce sınav oturumu oluştur.")
    else:
        session_labels = {str(r["label"]): int(r["id"]) for _, r in sessions_df.iterrows()}
        selected_session_label = st.selectbox("Sınav oturumu", ["Seç"] + list(session_labels.keys()))
        if selected_session_label == "Seç":
            st.info("Lütfen sınav oturumu seç.")
            st.stop()

        selected_session_id = session_labels[selected_session_label]
        selected_session = sessions_df[sessions_df["id"] == selected_session_id].iloc[0]

        allowed_q_df = df_query("""
            SELECT q.id AS qualification_id,
                   CASE WHEN q.code != '' THEN q.code || ' - ' || q.name ELSE q.name END AS qualification,
                   q.alt_units
            FROM exam_session_qualifications esq
            JOIN qualifications q ON q.id=esq.qualification_id
            WHERE esq.session_id=?
            ORDER BY q.alt_units
        """, (selected_session_id,))

        if allowed_q_df.empty:
            # Eski kayıtlar için geriye uyumluluk
            allowed_q_df = df_query("""
                SELECT q.id AS qualification_id,
                       CASE WHEN q.code != '' THEN q.code || ' - ' || q.name ELSE q.name END AS qualification,
                       q.alt_units
                FROM exam_sessions es
                JOIN qualifications q ON q.id=es.qualification_id
                WHERE es.id=?
            """, (selected_session_id,))

        allowed_qids = [int(x) for x in allowed_q_df["qualification_id"].tolist()]
        st.info("Bu sınava eklenebilecek alt birimler: " + " | ".join([f"{r['qualification']} / {r['alt_units'] or 'Genel'}" for _, r in allowed_q_df.iterrows()]))

        candidate_base = df_query("""
            SELECT DISTINCT c.id AS candidate_id,
                   c.full_name || COALESCE(' / ' || c.tc_no, '') AS label
            FROM candidate_processes cp
            JOIN candidates c ON c.id=cp.candidate_id
            WHERE cp.firm_id=?
              AND cp.qualification_id IN ({placeholders})
              AND cp.id NOT IN (
                  SELECT candidate_process_id
                  FROM exam_session_candidates
                  WHERE session_id=?
              )
            ORDER BY c.full_name
        """.format(placeholders=",".join(["?"] * len(allowed_qids))), tuple([int(selected_session["firm_id"])] + allowed_qids + [selected_session_id]))

        if candidate_base.empty:
            st.warning("Bu sınavın firma + seçili alt birim kombinasyonuna uygun eklenebilir aday yok.")
        else:
            candidate_label_map = {str(r["label"]): int(r["candidate_id"]) for _, r in candidate_base.iterrows()}
            selected_candidate_labels = st.multiselect("Uygun aday seç", list(candidate_label_map.keys()))

            if st.button("Seçilen uygun adayları bu sınava ekle"):
                added_process_count = 0
                for cand_label in selected_candidate_labels:
                    cand_id = candidate_label_map[cand_label]
                    proc_df = df_query("""
                        SELECT id
                        FROM candidate_processes
                        WHERE candidate_id=? AND firm_id=? AND qualification_id IN ({placeholders})
                          AND id NOT IN (
                              SELECT candidate_process_id
                              FROM exam_session_candidates
                              WHERE session_id=?
                          )
                    """.format(placeholders=",".join(["?"] * len(allowed_qids))), tuple([cand_id, int(selected_session["firm_id"])] + allowed_qids + [selected_session_id]))

                    for _, pr in proc_df.iterrows():
                        execute("""
                            INSERT OR IGNORE INTO exam_session_candidates(session_id, candidate_process_id, candidate_id)
                            VALUES (?, ?, ?)
                        """, (selected_session_id, int(pr["id"]), cand_id))
                        added_process_count += 1

                required, count = auto_update_observer_required(selected_session_id)
                if required:
                    st.warning(f"Bu MYK sınav ID/oturumu için kayıtlı süreç sayısı {count}. 8’den fazla olduğu için gözetmen seçilmelidir.")
                else:
                    st.success(f"Adaylar eklendi. Eklenen süreç: {added_process_count}. Toplam kayıt: {count}")

        current_count = get_exam_candidate_count(selected_session_id)
        st.metric("Bu sınavdaki kayıt/süreç sayısı", current_count)

        observer_options = {"Gözetmen seçilmedi": None, **get_options("SELECT id, full_name || ' / ' || role AS label FROM evaluators WHERE status='Aktif' ORDER BY full_name")}
        session_observer = df_query("SELECT observer_required FROM exam_sessions WHERE id=?", (selected_session_id,))
        if not session_observer.empty and int(session_observer["observer_required"][0]) == 1:
            st.warning("Gözetmen gerekli.")
            obs_label = st.selectbox("Gözetmen seç", list(observer_options.keys()), key="observer_select")
            if st.button("Gözetmeni Kaydet"):
                execute("UPDATE exam_sessions SET observer_id=? WHERE id=?", (observer_options[obs_label], selected_session_id))
                st.success("Gözetmen kaydedildi.")
    st.markdown('</div>', unsafe_allow_html=True)

    st.subheader("Planlanan Sınavlar")
    sessions_view = df_query("""
        SELECT es.id, es.session_type AS tür, es.exam_date AS tarih, es.exam_time AS saat,
               es.exam_place AS sınav_yeri, es.myk_exam_id AS myk_sınav_id,
               f.name AS firma,
               ev.full_name AS değerlendirici,
               CASE es.observer_required WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS gözetmen_gerekli,
               obs.full_name AS gözetmen,
               COUNT(esc.id) AS kayıt_sayısı,
               es.status AS durum
        FROM exam_sessions es
        LEFT JOIN firms f ON f.id=es.firm_id
        LEFT JOIN evaluators ev ON ev.id=es.evaluator_id
        LEFT JOIN evaluators obs ON obs.id=es.observer_id
        LEFT JOIN exam_session_candidates esc ON esc.session_id=es.id
        GROUP BY es.id
        ORDER BY es.exam_date DESC, es.exam_time DESC
    """)
    st.dataframe(sessions_view, width="stretch")
    download_df_button(sessions_view, "sinav_planlari.xlsx")


elif menu == "Sınav Takvimi":
    st.header("Sınav Takvimi")

    calendar_df = df_query("""
        SELECT es.id, es.exam_date AS tarih, es.exam_time AS saat, es.session_type AS tür,
               es.myk_exam_id AS myk_sınav_id,
               es.exam_place AS sınav_yeri,
               f.name AS firma,
               ev.full_name AS değerlendirici,
               obs.full_name AS gözetmen,
               COUNT(esc.id) AS kayıt_sayısı,
               es.status AS durum
        FROM exam_sessions es
        LEFT JOIN firms f ON f.id=es.firm_id
        LEFT JOIN evaluators ev ON ev.id=es.evaluator_id
        LEFT JOIN evaluators obs ON obs.id=es.observer_id
        LEFT JOIN exam_session_candidates esc ON esc.session_id=es.id
        GROUP BY es.id
        ORDER BY es.exam_date, es.exam_time
    """)

    if calendar_df.empty:
        st.info("Henüz planlanmış sınav yok.")
    else:
        calendar_df["tarih_dt"] = pd.to_datetime(calendar_df["tarih"], errors="coerce")
        valid_dates = calendar_df.dropna(subset=["tarih_dt"])

        if valid_dates.empty:
            st.warning("Sınav kayıtları var ama tarih formatı okunamadı. Tüm liste aşağıda gösteriliyor.")
            st.dataframe(calendar_df.drop(columns=["tarih_dt"], errors="ignore"), width="stretch")
            download_df_button(calendar_df.drop(columns=["tarih_dt"], errors="ignore"), "tum_sinav_takvimi.xlsx")
        else:
            today = date.today()
            default_monday = today - timedelta(days=today.weekday())

            if "calendar_week_start" not in st.session_state:
                st.session_state.calendar_week_start = default_monday

            nav1, nav2, nav3 = st.columns([1, 2, 1])
            with nav1:
                if st.button("← Önceki Hafta"):
                    st.session_state.calendar_week_start = st.session_state.calendar_week_start - timedelta(days=7)
            with nav3:
                if st.button("Sonraki Hafta →"):
                    st.session_state.calendar_week_start = st.session_state.calendar_week_start + timedelta(days=7)

            selected_week_start = st.date_input(
                "Hafta başlangıcı",
                value=st.session_state.calendar_week_start,
                format="DD/MM/YYYY"
            )

            week_start = selected_week_start - timedelta(days=selected_week_start.weekday())
            st.session_state.calendar_week_start = week_start
            week_end = week_start + timedelta(days=6)

            week_df = calendar_df[
                (calendar_df["tarih_dt"].dt.date >= week_start) &
                (calendar_df["tarih_dt"].dt.date <= week_end)
            ].copy()

            st.subheader(f"Haftalık Takvim: {week_start.strftime('%d/%m/%Y')} - {week_end.strftime('%d/%m/%Y')}")

            days = [
                ("Pazartesi", week_start),
                ("Salı", week_start + timedelta(days=1)),
                ("Çarşamba", week_start + timedelta(days=2)),
                ("Perşembe", week_start + timedelta(days=3)),
                ("Cuma", week_start + timedelta(days=4)),
                ("Cumartesi", week_start + timedelta(days=5)),
                ("Pazar", week_start + timedelta(days=6)),
            ]

            weekly_rows = []
            for day_name, day_date in days:
                day_items = week_df[week_df["tarih_dt"].dt.date == day_date]
                if day_items.empty:
                    weekly_rows.append({
                        "Gün": f"{day_name} ({day_date.strftime('%d/%m')})",
                        "Sınavlar": ""
                    })
                else:
                    items = []
                    for _, r in day_items.iterrows():
                        item = (
                            f"{r['saat']} | {r['tür']} | MYK: {r['myk_sınav_id'] or '-'} | "
                            f"{r['firma'] or '-'} | Yer: {r['sınav_yeri'] or '-'} | "
                            f"Değ.: {r['değerlendirici'] or '-'} | Kayıt: {r['kayıt_sayısı']}"
                        )
                        items.append(item)
                    weekly_rows.append({
                        "Gün": f"{day_name} ({day_date.strftime('%d/%m')})",
                        "Sınavlar": "\\n".join(items)
                    })

            weekly_table = pd.DataFrame(weekly_rows)
            st.dataframe(weekly_table, width="stretch", height=420)

            st.subheader("Haftadaki Sınavlar")
            show_cols = ["tarih", "saat", "tür", "myk_sınav_id", "sınav_yeri", "firma", "değerlendirici", "gözetmen", "kayıt_sayısı", "durum"]
            if week_df.empty:
                st.info("Seçili haftada sınav yok.")
            else:
                st.dataframe(week_df[show_cols], width="stretch")
                download_df_button(week_df[show_cols], "haftalik_sinav_takvimi.xlsx")

            st.subheader("Tüm Sınav Takvimi")
            full_cols = ["tarih", "saat", "tür", "myk_sınav_id", "sınav_yeri", "firma", "değerlendirici", "gözetmen", "kayıt_sayısı", "durum"]
            st.dataframe(calendar_df[full_cols], width="stretch")
            download_df_button(calendar_df[full_cols], "tum_sinav_takvimi.xlsx")



elif menu == "Cari Gelir-Gider":
    if user_role not in ["admin", "muhasebe"]:
        st.error("Bu sayfaya erişim yetkin yok")
        st.stop()

    st.header("Cari Gelir-Gider")
    ensure_schema_updates()

    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.subheader("Cari İşlem Ekle")

    firm_options = options_with_select(get_options("SELECT id, name AS label FROM firms ORDER BY name"), "Seç")
    candidate_options = options_with_select(get_options("SELECT id, full_name || COALESCE(' / ' || tc_no, '') AS label FROM candidates ORDER BY full_name"), "Seç")
    session_options = options_with_select(get_options("""
        SELECT id, exam_date || ' ' || exam_time || ' / ' || session_type || ' / ' || COALESCE(myk_exam_id, '') AS label
        FROM exam_sessions ORDER BY exam_date DESC, exam_time DESC
    """), "Seç")

    gelir_kategorileri = [
        "Aday Ödemesi",
        "Belge Ücreti",
        "Firma Tahsilatı",
        "Diğer Gelir"
    ]

    gider_kategorileri = [
        "Firmaya Ödeme",
        "Değerlendirici Ücreti",
        "Gözetmen Ücreti",
        "Sınav Yeri",
        "Malzeme Gideri",
        "Kargo",
        "Yol / Ulaşım",
        "Yemek",
        "Ofis Gideri",
        "Diğer Gider"
    ]

    c1, c2, c3 = st.columns(3)

    with c1:
        transaction_date = st.date_input("Tarih", value=date.today(), format="DD/MM/YYYY")
        transaction_type = st.selectbox("İşlem tipi", ["Seç", "Gelir", "Gider"], key="ledger_transaction_type")

        if transaction_type == "Gelir":
            category = st.selectbox("Kategori", ["Seç"] + gelir_kategorileri, key="ledger_category_income")
        elif transaction_type == "Gider":
            category = st.selectbox("Kategori", ["Seç"] + gider_kategorileri, key="ledger_category_expense")
        else:
            category = st.selectbox("Kategori", ["Seç"], key="ledger_category_empty")

    with c2:
        firm_label = st.selectbox("Firma", list(firm_options.keys()), key="ledger_firm")
        candidate_label = st.selectbox("Aday", list(candidate_options.keys()), key="ledger_candidate")
        session_label = st.selectbox("Sınav", list(session_options.keys()), key="ledger_session")

    with c3:
        person_name = st.text_input("Kişi / tedarikçi / açıklama adı", key="ledger_person")
        amount = st.number_input("Tutar", min_value=0.0, step=100.0, key="ledger_amount")
        vat_included = st.checkbox("KDV dahil", value=True, key="ledger_vat")
        payment_status = st.selectbox("Ödeme durumu", ["Seç", "Bekliyor", "Yapıldı", "İptal"], key="ledger_payment_status")

    description = st.text_area("Açıklama", key="ledger_description")

    if st.button("Cari İşlemi Kaydet"):
        if transaction_type == "Seç":
            st.error("İşlem tipi seçmelisin.")
        elif category == "Seç":
            st.error("Kategori seçmelisin.")
        elif payment_status == "Seç":
            st.error("Ödeme durumu seçmelisin.")
        elif amount <= 0:
            st.error("Tutar 0'dan büyük olmalı.")
        else:
            execute("""
                INSERT INTO cash_ledger(
                    transaction_date, transaction_type, category, firm_id, candidate_id, session_id,
                    person_name, candidate_process_id, auto_generated,
                    amount, vat_included, payment_status, description
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 0, ?, ?, ?, ?)
            """, (
                str(transaction_date), transaction_type, category,
                firm_options[firm_label], candidate_options[candidate_label], session_options[session_label],
                person_name.strip(),
                amount, 1 if vat_included else 0, payment_status, description
            ))
            st.success("Cari işlem kaydedildi.")
            st.rerun()

    st.markdown('</div>', unsafe_allow_html=True)

    ledger = df_query("""
        SELECT cl.id, cl.transaction_date AS tarih, cl.transaction_type AS tip, cl.category AS kategori,
               cl.person_name AS kişi_tedarikçi,
               f.name AS firma, c.full_name AS aday,
               es.exam_date || ' ' || es.exam_time || ' / ' || COALESCE(es.myk_exam_id, '') AS sınav,
               cl.amount AS tutar,
               CASE cl.vat_included WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS kdv_dahil,
               cl.payment_status AS ödeme_durumu,
               CASE COALESCE(cl.auto_generated,0) WHEN 1 THEN 'Otomatik' ELSE 'Manuel' END AS kayıt_tipi,
               cl.description AS açıklama
        FROM cash_ledger cl
        LEFT JOIN firms f ON f.id=cl.firm_id
        LEFT JOIN candidates c ON c.id=cl.candidate_id
        LEFT JOIN exam_sessions es ON es.id=cl.session_id
        ORDER BY cl.transaction_date DESC, cl.id DESC
    """)

    st.subheader("Cari Tablo")
    st.dataframe(ledger, width="stretch")
    download_df_button(ledger, "cari_gelir_gider.xlsx")

    if not ledger.empty:
        st.subheader("Cari İşlem Sil")
        delete_id = st.selectbox("Silinecek cari işlem ID", ["Seç"] + [str(x) for x in ledger["id"].tolist()])
        if delete_id != "Seç" and st.button("Seçili Cari İşlemi Sil"):
            execute("DELETE FROM cash_ledger WHERE id=?", (int(delete_id),))
            st.success("Cari işlem silindi.")
            st.rerun()

    income = df_query("SELECT COALESCE(SUM(amount),0) AS total FROM cash_ledger WHERE transaction_type='Gelir' AND payment_status='Yapıldı'")["total"][0]
    expense = df_query("SELECT COALESCE(SUM(amount),0) AS total FROM cash_ledger WHERE transaction_type='Gider' AND payment_status='Yapıldı'")["total"][0]
    pending = df_query("SELECT COALESCE(SUM(amount),0) AS total FROM cash_ledger WHERE payment_status='Bekliyor'")["total"][0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Tahsil edilmiş gelir", money_fmt(income))
    c2.metric("Ödenmiş gider", money_fmt(expense))
    c3.metric("Bekleyen cari", money_fmt(pending))



elif menu == "Excel Kaynak Yükleme":
    if user_role != "admin":
        st.error("Bu sayfaya erişim yetkin yok")
        st.stop()

    st.header("Excel Kaynak Yükleme")

    counts = {
        "Firma": int(df_query("SELECT COUNT(*) c FROM firms")["c"][0]),
        "Yeterlilik": int(df_query("SELECT COUNT(*) c FROM qualifications")["c"][0]),
        "Ücret Kaydı": int(df_query("SELECT COUNT(*) c FROM exam_fees")["c"][0]),
    }
    c1, c2, c3 = st.columns(3)
    c1.metric("Firma", counts["Firma"])
    c2.metric("Yeterlilik", counts["Yeterlilik"])
    c3.metric("Ücret Kaydı", counts["Ücret Kaydı"])

    if counts["Ücret Kaydı"] > 0:
        st.success("Kaynak veriler yüklü görünüyor. Yeniden yükleme yapmana gerek yok.")
        st.info("Yeni Excel yüklemek sadece eksik/yeni tanımları ekler ve aynı firma+yeterlilik ücretlerini günceller.")
    else:
        st.warning("Henüz kaynak veri yok. Excel yükleyip içe aktar.")

    uploaded = st.file_uploader("Kaynak Excel yükle", type=["xlsx"])
    if uploaded is not None and st.button("Yüklenen Excel’i içe aktar"):
        imported, skipped = import_meslekler_excel(uploaded)
        st.success(f"İçe aktarma tamamlandı. İşlenen satır: {imported}, atlanan satır: {skipped}")

    st.subheader("Import Log")
    logs = df_query("SELECT * FROM import_logs ORDER BY id DESC")
    st.dataframe(logs, width="stretch")


elif menu == "Tanımlar ve Ücretler":
    if user_role != "admin":
        st.error("Bu sayfaya erişim yetkin yok")
        st.stop()

    st.header("Tanımlar ve Ücretler")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Firmalar", "Aday Kaynakları", "Yeterlilikler", "Ücretler", "Değerlendirici/Gözetmen"])

    with tab1:
        st.subheader("Firma Ekle")
        with st.form("firm_add_form"):
            firm_name = st.text_input("Firma adı")
            firm_status = st.selectbox("Durum", ["Aktif", "Pasif"], key="firm_add_status")
            firm_note = st.text_area("Not", key="firm_add_note")
            if st.form_submit_button("Firma Kaydet"):
                if firm_name.strip():
                    execute("INSERT OR IGNORE INTO firms(name, status, note) VALUES (?, ?, ?)", (firm_name.strip().upper(), firm_status, firm_note))
                    st.success("Firma kaydedildi.")
                    st.rerun()
                else:
                    st.error("Firma adı zorunludur.")

        firms = df_query("SELECT id, name AS firma, status AS durum, note AS notlar FROM firms ORDER BY firma")
        st.dataframe(firms, width="stretch")
        download_df_button(firms, "firmalar.xlsx")

        if not firms.empty:
            st.subheader("Firma Güncelle / Sil")
            firm_id = st.selectbox("Firma seç", ["Seç"] + [str(x) for x in firms["id"].tolist()], key="firm_edit_select")
            if firm_id != "Seç":
                row = firms[firms["id"] == int(firm_id)].iloc[0]
                with st.form("firm_edit_form"):
                    edit_name = st.text_input("Firma adı", value=row["firma"])
                    edit_status = st.selectbox("Durum", ["Aktif", "Pasif"], index=0 if row["durum"] == "Aktif" else 1, key="firm_edit_status")
                    edit_note = st.text_area("Not", value="" if pd.isna(row["notlar"]) else str(row["notlar"]), key="firm_edit_note")
                    col_a, col_b = st.columns(2)
                    update_clicked = col_a.form_submit_button("Güncelle")
                    delete_clicked = col_b.form_submit_button("Sil")

                if update_clicked:
                    execute("UPDATE firms SET name=?, status=?, note=? WHERE id=?", (edit_name.strip().upper(), edit_status, edit_note, int(firm_id)))
                    st.success("Firma güncellendi.")
                    st.rerun()

                if delete_clicked:
                    try:
                        execute("DELETE FROM firms WHERE id=?", (int(firm_id),))
                        st.success("Firma silindi.")
                        st.rerun()
                    except Exception as e:
                        st.error("Bu firma bağlı kayıtlar nedeniyle silinemedi.")
                        st.write(e)

    with tab2:
        st.subheader("Aday Kaynağı Ekle")
        with st.form("source_add_form"):
            source_name = st.text_input("Kaynak adı / kimden geldi")
            source_type = st.selectbox("Kaynak tipi", ["Firma", "Şirket", "Kişi", "Kurum", "Diğer"])
            source_status = st.selectbox("Durum", ["Aktif", "Pasif"], key="source_add_status")
            source_note = st.text_area("Not", key="source_add_note")
            if st.form_submit_button("Kaynak Kaydet"):
                if source_name.strip():
                    execute("""
                        INSERT OR IGNORE INTO candidate_sources(name, source_type, status, note)
                        VALUES (?, ?, ?, ?)
                    """, (source_name.strip().upper(), source_type, source_status, source_note))
                    st.success("Aday kaynağı kaydedildi.")
                    st.rerun()
                else:
                    st.error("Kaynak adı zorunludur.")

        sources = df_query("SELECT id, name AS kaynak, source_type AS tip, status AS durum, note AS notlar FROM candidate_sources ORDER BY kaynak")
        st.dataframe(sources, width="stretch")
        download_df_button(sources, "aday_kaynaklari.xlsx")

        if not sources.empty:
            st.subheader("Aday Kaynağı Güncelle / Sil")
            source_id = st.selectbox("Kaynak seç", ["Seç"] + [str(x) for x in sources["id"].tolist()], key="source_edit_select")
            if source_id != "Seç":
                row = sources[sources["id"] == int(source_id)].iloc[0]
                with st.form("source_edit_form"):
                    edit_source_name = st.text_input("Kaynak adı", value=row["kaynak"])
                    source_types = ["Firma", "Şirket", "Kişi", "Kurum", "Diğer"]
                    edit_source_type = st.selectbox("Kaynak tipi", source_types, index=source_types.index(row["tip"]) if row["tip"] in source_types else 0)
                    edit_source_status = st.selectbox("Durum", ["Aktif", "Pasif"], index=0 if row["durum"] == "Aktif" else 1, key="source_edit_status")
                    edit_source_note = st.text_area("Not", value="" if pd.isna(row["notlar"]) else str(row["notlar"]), key="source_edit_note")
                    col_a, col_b = st.columns(2)
                    source_update_clicked = col_a.form_submit_button("Güncelle")
                    source_delete_clicked = col_b.form_submit_button("Sil")

                if source_update_clicked:
                    execute("UPDATE candidate_sources SET name=?, source_type=?, status=?, note=? WHERE id=?", (edit_source_name.strip().upper(), edit_source_type, edit_source_status, edit_source_note, int(source_id)))
                    st.success("Kaynak güncellendi.")
                    st.rerun()

                if source_delete_clicked:
                    try:
                        execute("DELETE FROM candidate_sources WHERE id=?", (int(source_id),))
                        st.success("Kaynak silindi.")
                        st.rerun()
                    except Exception as e:
                        st.error("Bu kaynak bağlı aday kayıtları nedeniyle silinemedi.")
                        st.write(e)

    with tab3:
        quals = df_query("""
            SELECT id, code AS kod, name AS yeterlilik, alt_units AS alt_birimler, sector AS alan_sektor, status AS durum
            FROM qualifications
            ORDER BY yeterlilik, alt_birimler
        """)
        st.dataframe(quals, width="stretch")
        download_df_button(quals, "yeterlilikler.xlsx")

    with tab4:
        fees = df_query("""
            SELECT ef.id, f.name AS firma,
                   CASE WHEN q.code != '' THEN q.code || ' - ' || q.name ELSE q.name END AS yeterlilik,
                   q.alt_units AS alt_birimler,
                   ef.fee_without_vat AS kdv_hariç,
                   ef.vat_rate AS kdv_oranı,
                   ef.fee_with_vat AS kdv_dahil,
                   ef.source_section AS kaynak,
                   ef.source_row AS kaynak_satır
            FROM exam_fees ef
            JOIN firms f ON f.id=ef.firm_id
            JOIN qualifications q ON q.id=ef.qualification_id
            ORDER BY f.name, q.name
        """)
        st.dataframe(fees, width="stretch")
        download_df_button(fees, "firma_yeterlilik_ucretleri.xlsx")

    with tab5:
        st.subheader("Değerlendirici / Gözetmen Ekle")
        with st.form("evaluator_form"):
            full_name = st.text_input("Ad Soyad")
            role = st.selectbox("Rol", ["Değerlendirici", "Gözetmen", "Değerlendirici/Gözetmen"])
            phone = st.text_input("Telefon")
            status = st.selectbox("Durum", ["Aktif", "Pasif"])
            note = st.text_area("Not")
            if st.form_submit_button("Kaydet"):
                if full_name.strip():
                    execute("""
                        INSERT OR IGNORE INTO evaluators(full_name, role, phone, status, note)
                        VALUES (?, ?, ?, ?, ?)
                    """, (full_name.strip().upper(), role, phone, status, note))
                    st.success("Kişi kaydedildi.")
                    st.rerun()
                else:
                    st.error("Ad Soyad zorunludur.")

        evals = df_query("SELECT id, full_name AS ad_soyad, role AS rol, phone AS telefon, status AS durum, note AS notlar FROM evaluators ORDER BY ad_soyad")
        st.dataframe(evals, width="stretch")
        download_df_button(evals, "degerlendirici_gozetmen.xlsx")

        if not evals.empty:
            st.subheader("Değerlendirici / Gözetmen Güncelle / Sil")
            eval_id = st.selectbox("Kişi seç", ["Seç"] + [str(x) for x in evals["id"].tolist()], key="eval_edit_select")
            if eval_id != "Seç":
                row = evals[evals["id"] == int(eval_id)].iloc[0]
                with st.form("eval_edit_form"):
                    edit_eval_name = st.text_input("Ad Soyad", value=row["ad_soyad"])
                    roles = ["Değerlendirici", "Gözetmen", "Değerlendirici/Gözetmen"]
                    edit_eval_role = st.selectbox("Rol", roles, index=roles.index(row["rol"]) if row["rol"] in roles else 0)
                    edit_eval_phone = st.text_input("Telefon", value="" if pd.isna(row["telefon"]) else str(row["telefon"]))
                    edit_eval_status = st.selectbox("Durum", ["Aktif", "Pasif"], index=0 if row["durum"] == "Aktif" else 1, key="eval_edit_status")
                    edit_eval_note = st.text_area("Not", value="" if pd.isna(row["notlar"]) else str(row["notlar"]), key="eval_edit_note")
                    col_a, col_b = st.columns(2)
                    eval_update_clicked = col_a.form_submit_button("Güncelle")
                    eval_delete_clicked = col_b.form_submit_button("Sil")

                if eval_update_clicked:
                    execute("UPDATE evaluators SET full_name=?, role=?, phone=?, status=?, note=? WHERE id=?", (edit_eval_name.strip().upper(), edit_eval_role, edit_eval_phone, edit_eval_status, edit_eval_note, int(eval_id)))
                    st.success("Kişi güncellendi.")
                    st.rerun()

                if eval_delete_clicked:
                    try:
                        execute("DELETE FROM evaluators WHERE id=?", (int(eval_id),))
                        st.success("Kişi silindi.")
                        st.rerun()
                    except Exception as e:
                        st.error("Bu kişi bağlı sınav kayıtları nedeniyle silinemedi.")
                        st.write(e)


elif menu == "Raporlar":
    if user_role not in ["admin", "muhasebe", "goruntuleme"]:
        st.error("Bu sayfaya erişim yetkin yok")
        st.stop()

    st.header("Raporlar")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Firma", int(df_query("SELECT COUNT(*) c FROM firms")["c"][0]))
    c2.metric("Yeterlilik", int(df_query("SELECT COUNT(*) c FROM qualifications")["c"][0]))
    c3.metric("Ücret Kaydı", int(df_query("SELECT COUNT(*) c FROM exam_fees")["c"][0]))
    c4.metric("Aday Süreci", int(df_query("SELECT COUNT(*) c FROM candidate_processes")["c"][0]))

    firma_ozet = df_query("""
        SELECT f.name AS firma, COUNT(*) AS ücret_kaydı,
               ROUND(AVG(ef.fee_with_vat), 2) AS ortalama_kdv_dahil,
               ROUND(MIN(ef.fee_with_vat), 2) AS min_kdv_dahil,
               ROUND(MAX(ef.fee_with_vat), 2) AS max_kdv_dahil
        FROM exam_fees ef
        JOIN firms f ON f.id=ef.firm_id
        GROUP BY f.name
        ORDER BY ücret_kaydı DESC
    """)
    st.subheader("Firma Ücret Özeti")
    st.dataframe(firma_ozet, width="stretch")
    download_df_button(firma_ozet, "firma_ucret_ozet.xlsx")


    st.subheader("Toplu Excel Dışa Aktarım")

    aday_surecleri_export = df_query("""
        SELECT cp.id AS süreç_id, c.full_name AS aday, c.tc_no AS tc, c.age AS yaş, c.phone AS telefon,
               cs.name AS aday_kaynağı,
               CASE WHEN q.code != '' THEN q.code || ' - ' || q.name ELSE q.name END AS yeterlilik,
               q.alt_units AS alt_birimler,
               f.name AS firma,
               cp.fee_without_vat AS kdv_hariç,
               cp.vat_rate AS kdv_oranı,
               cp.fee_with_vat AS kdv_dahil,
               cp.candidate_payment_amount AS adaydan_alınan,
               CASE cp.candidate_payment_received WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS aday_ödeme,
               cp.firm_payment_amount AS firmaya_iletilen,
               CASE cp.firm_payment_sent WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS firma_ödeme,
               cp.first_right_status AS birinci_hak,
               cp.second_right_status AS ikinci_hak,
               cp.entitlement_status AS belge_hakkı,
               CASE cp.certificate_fee_paid WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS belge_parası,
               cp.certificate_print_status AS basım,
               cp.certificate_delivery_status AS teslim,
               cp.created_at AS kayıt_tarihi
        FROM candidate_processes cp
        JOIN candidates c ON c.id=cp.candidate_id
        LEFT JOIN candidate_sources cs ON cs.id=c.source_id
        JOIN qualifications q ON q.id=cp.qualification_id
        JOIN firms f ON f.id=cp.firm_id
        ORDER BY cp.id DESC
    """)

    sinavlar_export = df_query("""
        SELECT es.id, es.session_type AS tür, es.exam_date AS tarih, es.exam_time AS saat,
               es.exam_place AS sınav_yeri, es.myk_exam_id AS myk_sınav_id,
               f.name AS firma,
               ev.full_name AS değerlendirici,
               CASE es.observer_required WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS gözetmen_gerekli,
               obs.full_name AS gözetmen,
               COUNT(esc.id) AS kayıt_sayısı,
               es.status AS durum
        FROM exam_sessions es
        LEFT JOIN firms f ON f.id=es.firm_id
        LEFT JOIN evaluators ev ON ev.id=es.evaluator_id
        LEFT JOIN evaluators obs ON obs.id=es.observer_id
        LEFT JOIN exam_session_candidates esc ON esc.session_id=es.id
        GROUP BY es.id
        ORDER BY es.exam_date DESC, es.exam_time DESC
    """)

    cari_export = df_query("""
        SELECT cl.id, cl.transaction_date AS tarih, cl.transaction_type AS tip, cl.category AS kategori,
               f.name AS firma, c.full_name AS aday,
               es.exam_date || ' ' || es.exam_time || ' / ' || COALESCE(es.myk_exam_id, '') AS sınav,
               cl.person_name AS kişi_tedarikçi,
               cl.amount AS tutar,
               CASE cl.vat_included WHEN 1 THEN 'Evet' ELSE 'Hayır' END AS kdv_dahil,
               cl.payment_status AS ödeme_durumu,
               cl.description AS açıklama
        FROM cash_ledger cl
        LEFT JOIN firms f ON f.id=cl.firm_id
        LEFT JOIN candidates c ON c.id=cl.candidate_id
        LEFT JOIN exam_sessions es ON es.id=cl.session_id
        ORDER BY cl.transaction_date DESC, cl.id DESC
    """)

    firmalar_export = df_query("SELECT id, name AS firma, status AS durum, note AS notlar FROM firms ORDER BY name")
    yeterlilikler_export = df_query("""
        SELECT id, code AS kod, name AS yeterlilik, alt_units AS alt_birimler, sector AS alan_sektor, status AS durum
        FROM qualifications
        ORDER BY name, alt_units
    """)
    ucretler_export = df_query("""
        SELECT ef.id, f.name AS firma,
               CASE WHEN q.code != '' THEN q.code || ' - ' || q.name ELSE q.name END AS yeterlilik,
               q.alt_units AS alt_birimler,
               ef.fee_without_vat AS kdv_hariç,
               ef.vat_rate AS kdv_oranı,
               ef.fee_with_vat AS kdv_dahil,
               ef.source_section AS kaynak,
               ef.source_row AS kaynak_satır
        FROM exam_fees ef
        JOIN firms f ON f.id=ef.firm_id
        JOIN qualifications q ON q.id=ef.qualification_id
        ORDER BY f.name, q.name
    """)

    all_sheets = {
        "Aday Süreçleri": aday_surecleri_export,
        "Sınavlar": sinavlar_export,
        "Cari": cari_export,
        "Firmalar": firmalar_export,
        "Yeterlilikler": yeterlilikler_export,
        "Ücretler": ucretler_export,
        "Firma Özet": firma_ozet
    }

    st.download_button(
        "Tüm verileri tek Excel olarak indir",
        data=to_multi_excel_bytes(all_sheets),
        file_name="aday_takip_tum_veriler.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


elif menu == "Ayarlar":
    if user_role != "admin":
        st.error("Bu sayfaya erişim yetkin yok")
        st.stop()

    st.header("Ayarlar")

    st.subheader("Kullanıcı Yönetimi")

    st.info("Yeni kullanıcı oluşturduktan sonra Supabase Authentication ekranında kullanıcının email confirmed durumunu kontrol et. E-posta onayı açıksa kullanıcı mail onayı vermeden giriş yapamaz.")

    st.markdown("### Yeni kullanıcı oluştur")
    with st.form("new_user_form"):
        new_user_email = st.text_input("Yeni kullanıcı e-posta")
        new_user_password = st.text_input("Geçici şifre", type="password")
        new_user_role = st.selectbox("Kullanıcı rolü", ["operasyon", "muhasebe", "goruntuleme", "admin"])
        create_user_clicked = st.form_submit_button("Kullanıcı Oluştur")

    if create_user_clicked:
        if not new_user_email.strip() or not new_user_password.strip():
            st.error("E-posta ve şifre zorunludur.")
        elif len(new_user_password.strip()) < 6:
            st.error("Şifre en az 6 karakter olmalı.")
        else:
            try:
                create_auth_user_and_profile(new_user_email, new_user_password, new_user_role)
                st.success("Kullanıcı oluşturuldu ve rol kaydı işlendi. Giriş olmazsa Supabase > Authentication > Users ekranından kullanıcıyı confirmed yap veya şifresini güncelle.")
                st.rerun()
            except Exception as e:
                st.error("Kullanıcı oluşturulamadı.")
                st.write(e)

    st.markdown("### Mevcut kullanıcı rolleri")

    try:
        profiles_response = supabase.table("profiles").select("id,email,role,created_at").order("email").execute()
        profiles_df = pd.DataFrame(profiles_response.data)

        if profiles_df.empty:
            st.info("Henüz profil kaydı yok.")
        else:
            st.dataframe(profiles_df[["email", "role", "created_at"]], width="stretch")

            with st.form("role_update_form"):
                role_email = st.selectbox("Rolü değiştirilecek kullanıcı", profiles_df["email"].tolist())
                current_role = profiles_df.loc[profiles_df["email"] == role_email, "role"].iloc[0]
                role_list = ["admin", "operasyon", "muhasebe", "goruntuleme"]
                default_index = role_list.index(current_role) if current_role in role_list else 2
                updated_role = st.selectbox("Yeni rol", role_list, index=default_index)
                update_role_clicked = st.form_submit_button("Rolü Güncelle")

            if update_role_clicked:
                user_id_to_update = profiles_df.loc[profiles_df["email"] == role_email, "id"].iloc[0]
                supabase.table("profiles").update({"role": updated_role}).eq("id", user_id_to_update).execute()
                st.success(f"{role_email} kullanıcısının rolü {updated_role} olarak güncellendi.")
                st.rerun()

    except Exception as e:
        st.error("Kullanıcı rolleri okunamadı/güncellenemedi.")
        st.write(e)

    st.write(f"Veritabanı: `{DB_PATH.resolve()}`")

    st.subheader("Tekrarlı meslekleri temizleme")
    st.info("Aynı kod + aynı meslek adı ile oluşmuş eski tekrarları temizlemek için en sağlıklı yol veritabanını sıfırlayıp Excel'i bu yeni sürümle tekrar içe aktarmaktır.")

    st.warning("Aşağıdaki işlem tüm local verileri siler.")
    confirm = st.checkbox("Tüm veriyi silmeyi onaylıyorum")
    if confirm and st.button("Veritabanını sıfırla"):
        reset_db()
        st.success("Veritabanı sıfırlandı. Şimdi Excel Kaynak Yükleme sekmesinden dosyayı tekrar içe aktar.")
