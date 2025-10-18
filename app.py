import streamlit as st

# ⚠️ 必須放在第一個 Streamlit 指令
st.set_page_config(page_title="社區投票系統", layout="wide")

import pandas as pd
import qrcode
import io
import zipfile
import json
import os
from datetime import datetime
from pytz import timezone
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects import postgresql as pg_types 
from contextlib import contextmanager

# ===============================
# 初始化設定
# ===============================
ADMIN_FILE = "admin_config.json"

DATABASE_URL = os.environ.get("DATABASE_URL")
try:
    if not DATABASE_URL:
        st.error("⚠️ 環境變數 'DATABASE_URL' 缺失。請在 Render 上設定此變數。")
        st.stop()
    engine = create_engine(DATABASE_URL)
except Exception as e:
    st.error(f"無法建立資料庫連線引擎，請檢查 DATABASE_URL: {e}")
    st.stop()


# ===============================
# 資料庫連線管理
# ===============================
@contextmanager
def get_db_connection():
    conn = None
    try:
        conn = engine.connect()
        yield conn
    except SQLAlchemyError as e:
        st.error(f"資料庫操作失敗: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


def init_db_tables():
    """初始化所有表格"""
    try:
        with get_db_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS households (
                    戶號 VARCHAR(50) PRIMARY KEY,
                    區分比例 NUMERIC(10,4)
                );
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS topics (
                    id SERIAL PRIMARY KEY,
                    議題 TEXT,
                    is_active BOOLEAN DEFAULT TRUE
                );
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY,
                    戶號 VARCHAR(50),
                    topic_id INTEGER,
                    投票結果 VARCHAR(10),
                    投票時間 TIMESTAMP WITH TIME ZONE,
                    UNIQUE (戶號, topic_id)
                );
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS config (
                    key VARCHAR(50) PRIMARY KEY,
                    value TEXT
                );
            """))
            conn.commit()
    except Exception as e:
        st.error(f"初始化資料庫表格失敗: {e}")

init_db_tables()


# ===============================
# 資料操作函式
# ===============================
def load_data_from_db(table_name):
    try:
        return pd.read_sql(f"SELECT * FROM {table_name}", engine)
    except Exception:
        return pd.DataFrame()


def save_households_to_db(df):
    required_cols = ['戶號', '區分比例']
    if not all(col in df.columns for col in required_cols):
        st.error("Excel 必須包含「戶號」與「區分比例」欄位")
        return False
    try:
        df_to_save = df[required_cols].copy()
        df_to_save.to_sql('households', engine, if_exists='replace', index=False,
                          dtype={'戶號': pg_types.VARCHAR(50), '區分比例': pg_types.NUMERIC(10, 4)})
        return True
    except Exception as e:
        st.error(f"寫入住戶清單失敗: {e}")
        return False


def save_topics_to_db(df):
    if '議題' not in df.columns:
        st.error("Excel 必須包含「議題」欄位")
        return False
    try:
        df_to_save = df[['議題']].copy()
        df_to_save['is_active'] = True
        df_to_save.to_sql('topics', engine, if_exists='replace', index=False,
                          dtype={'議題': pg_types.TEXT(), 'is_active': pg_types.BOOLEAN()})
        return True
    except Exception as e:
        st.error(f"寫入議題清單失敗: {e}")
        return False


def record_vote_to_db(unit_id, topic_id, vote_result, vote_time):
    """每戶每議題僅能投一次票 (UPSERT)"""
    try:
        with get_db_connection() as conn:
            conn.execute(text("""
                INSERT INTO votes (戶號, topic_id, 投票結果, 投票時間)
                VALUES (:unit, :topic, :result, :time)
                ON CONFLICT (戶號, topic_id) DO NOTHING;
            """), {"unit": unit_id, "topic": topic_id, "result": vote_result, "time": vote_time})
            conn.commit()
        return True
    except Exception as e:
        st.error(f"記錄投票失敗: {e}")
        return False


def load_config(key):
    try:
        with get_db_connection() as conn:
            result = conn.execute(text("SELECT value FROM config WHERE key = :key"), {"key": key}).scalar_one_or_none()
        return result
    except Exception:
        return None


def save_config(key, value):
    try:
        with get_db_connection() as conn:
            conn.execute(text("""
                INSERT INTO config (key, value)
                VALUES (:key, :value)
                ON CONFLICT (key) DO UPDATE SET value = :value;
            """), {"key": key, "value": value})
            conn.commit()
        return True
    except Exception as e:
        st.error(f"儲存設定失敗: {e}")
        return False


def get_taipei_time():
    return datetime.now(timezone("Asia/Taipei"))


# ===============================
# QR Code 產生 (ZIP)
# ===============================
def generate_qr_zip(households_df, base_url):
    if households_df.empty:
        st.warning("尚未上傳住戶清單。")
        return None

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zf:
        for _, row in households_df.iterrows():
            house_id = str(row["戶號"]).strip()
            qr_link = f"{base_url}?unit={house_id}"
            qr_img = qrcode.make(qr_link).convert("RGB")
            img_bytes = io.BytesIO()
            qr_img.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            zf.writestr(f"{house_id}.png", img_bytes.read())
    zip_buffer.seek(0)
    return zip_buffer


# ===============================
# 投票頁面
# ===============================
def voter_page():
    st.title("🏠 社區投票系統")

    params = st.experimental_get_query_params()
    unit = params.get("unit", [None])[0]

    if not unit:
        st.warning("請使用專屬 QR Code 登入投票。")
        return

    households_df = load_data_from_db('households')
    if households_df.empty or unit not in households_df['戶號'].values:
        st.error("無效的戶號，請聯繫管理員。")
        return

    st.info(f"目前登入戶號：{unit}")

    voting_open_str = load_config('voting_open')
    if voting_open_str != 'True':
        st.warning("投票尚未開放或已截止。")
        return

    topics_df = load_data_from_db('topics')
    active_topics = topics_df[topics_df['is_active'] == True]
    if active_topics.empty:
        st.info("目前沒有開放的議題。")
        return

    votes_df = load_data_from_db('votes')
    voted_topic_ids = votes_df[votes_df['戶號'] == unit]['topic_id'].tolist()

    for _, row in active_topics.iterrows():
        topic_id, topic_text = row['id'], row['議題']
        st.markdown(f"### 議題 {topic_id}: {topic_text}")

        if topic_id in voted_topic_ids:
            st.success("✅ 已投票，無法重複投票。")
        else:
            option = st.radio("請選擇：", ("同意", "不同意"), key=f"opt_{topic_id}", horizontal=True)
            if st.button(f"提交對議題 {topic_id} 的投票", key=f"btn_{topic_id}"):
                record_vote_to_db(unit, topic_id, option, get_taipei_time())
                st.success("投票成功！感謝您的參與。")
                st.experimental_rerun()


# ===============================
# 管理員登入頁面
# ===============================
def admin_login():
    st.header("🔐 管理員登入")
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False

    username = st.text_input("帳號")
    password = st.text_input("密碼", type="password")
    if st.button("登入"):
        if not os.path.exists(ADMIN_FILE):
            st.error("找不到 admin_config.json")
            return
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            admin_data = json.load(f)
        if username in admin_data and password == str(admin_data[username]):
            st.session_state.is_admin = True
            st.session_state.admin_user = username
            st.success(f"歡迎，{username}")
            st.experimental_rerun()
        else:
            st.error("帳號或密碼錯誤。")


# ===============================
# 管理員後台
# ===============================
def admin_panel():
    st.title("🛠️ 管理員後台")

    tab1, tab2, tab3 = st.tabs(["上傳清單", "QR Code 產生", "投票統計"])

    # --- 上傳清單 ---
    with tab1:
        st.subheader("上傳住戶清單")
        house_file = st.file_uploader("上傳 Excel（包含 戶號、區分比例）", type=["xlsx"])
        if house_file:
            df = pd.read_excel(house_file)
            if save_households_to_db(df):
                st.success("住戶清單上傳成功。")

        st.subheader("上傳議題清單")
        topic_file = st.file_uploader("上傳 Excel（包含 議題 欄位）", type=["xlsx"])
        if topic_file:
            df = pd.read_excel(topic_file)
            if save_topics_to_db(df):
                st.success("議題清單上傳成功。")

        st.subheader("開啟／關閉投票")
        status = load_config("voting_open")
        current = True if status == "True" else False
        toggle = st.toggle("開放投票", value=current)
        save_config("voting_open", str(toggle))

    # --- QR Code 產生 ---
    with tab2:
        st.subheader("產生 QR Code ZIP")
        households_df = load_data_from_db('households')
        base_url = st.text_input("投票網址（例如：https://example.com）")
        if st.button("產生 QR Code ZIP"):
            buf = generate_qr_zip(households_df, base_url)
            if buf:
                st.download_button("下載 QR Code ZIP", data=buf, file_name="qrcodes.zip")

    # --- 投票統計 ---
    with tab3:
        st.subheader("投票結果統計")
        votes_df = load_data_from_db('votes')
        topics_df = load_data_from_db('topics')
        households_df = load_data_from_db('households')

        if votes_df.empty or topics_df.empty:
            st.info("尚無投票資料。")
        else:
            total_households = len(households_df)
            for _, topic in topics_df.iterrows():
                topic_id = topic['id']
                topic_name = topic['議題']
                topic_votes = votes_df[votes_df['topic_id'] == topic_id]
                agree = len(topic_votes[topic_votes['投票結果'] == "同意"])
                disagree = len(topic_votes[topic_votes['投票結果'] == "不同意"])
                voted = len(topic_votes)
                remaining = total_households - voted
                agree_ratio = (agree / total_households) if total_households > 0 else 0
                disagree_ratio = (disagree / total_households) if total_households > 0 else 0

                st.markdown(f"### 🗳️ {topic_name}")
                st.write(f"同意人數：{agree}")
                st.write(f"不同意人數：{disagree}")
                st.write(f"同意比例：{agree_ratio:.4f}")
                st.write(f"不同意比例：{disagree_ratio:.4f}")
                st.write(f"總投票人數：{voted}（剩餘未投票 {remaining} 戶）")
                st.divider()


# ===============================
# 主控制邏輯
# ===============================
params = st.experimental_get_query_params()
unit = params.get("unit", [None])[0] if "unit" in params else None

if unit:
    voter_page()
else:
    st.sidebar.title("系統選單")
    if st.session_state.get("is_admin", False):
        page = st.sidebar.radio("請選擇頁面", ["投票頁面", "管理員後台", "登出"])
        if page == "投票頁面":
            voter_page()
        elif page == "管理員後台":
            admin_panel()
        elif page == "登出":
            st.session_state.is_admin = False
            st.experimental_rerun()
    else:
        page = st.sidebar.radio("請選擇頁面", ["投票頁面", "管理員登入"])
        if page == "投票頁面":
            voter_page()
        elif page == "管理員登入":
            admin_login()
