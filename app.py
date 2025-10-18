import streamlit as st
import pandas as pd
import qrcode
import io
import zipfile
import json
import os
from datetime import datetime, timedelta
from pytz import timezone
from PIL import Image
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.dialects import postgresql as pg_types
from contextlib import contextmanager

# ===============================
# 初始化設定
# ===============================
st.set_page_config(page_title="社區投票系統", layout="wide")

ADMIN_FILE = "admin_config.json"
DATABASE_URL = os.environ.get("DATABASE_URL")

try:
    if not DATABASE_URL:
        st.error("⚠️ 環境變數 'DATABASE_URL' 缺失，請設定資料庫連線字串。")
        st.stop()
    engine = create_engine(DATABASE_URL)
except Exception as e:
    st.error(f"無法建立資料庫連線引擎：{e}")
    st.stop()

# ===============================
# 工具函式
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
    try:
        with get_db_connection() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS households (
                    戶號 VARCHAR(50) PRIMARY KEY,
                    區分比例 NUMERIC(10, 4)
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

def load_data_from_db(table_name):
    try:
        df = pd.read_sql(f"SELECT * FROM {table_name}", engine)
        return df
    except Exception:
        return pd.DataFrame()

def save_households_to_db(df):
    try:
        df[['戶號', '區分比例']].to_sql('households', engine, if_exists='replace', index=False,
            dtype={'戶號': pg_types.VARCHAR(50), '區分比例': pg_types.NUMERIC(10, 4)})
        return True
    except Exception as e:
        st.error(f"寫入住戶清單失敗: {e}")
        return False

def save_topics_to_db(df):
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

def generate_qr_zip(households_df, base_url):
    if households_df.empty:
        st.warning("尚未上傳住戶清單，無法產生 QR Code。")
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
# 投票首頁
# ===============================
def voter_page():
    st.title("🏠 社區投票系統")

    params = st.query_params
    unit = params.get("unit")

    if not unit:
        st.warning("未偵測到戶號參數，請使用專屬 QR Code 登入。")
        return

    unit = str(unit)
    st.info(f"目前登入戶號：{unit}")

    households_df = load_data_from_db('households')
    if households_df.empty or unit not in households_df['戶號'].values:
        st.error("無效的戶號，請聯繫管理員。")
        return

    voting_open_str = load_config('voting_open')
    voting_open = voting_open_str == 'True'
    if not voting_open:
        st.warning("投票尚未開始或已截止。")
        return

    end_time_str = load_config('end_time')
    if end_time_str:
        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S %z").astimezone(timezone("Asia/Taipei"))
        now = get_taipei_time()
        if now > end_time:
            st.error(f"投票已於 {end_time.strftime('%Y-%m-%d %H:%M:%S')} 截止。")
            return
        st.write(f"🗳️ 投票截止時間：**{end_time.strftime('%Y-%m-%d %H:%M:%S')}**")

    topics_df = load_data_from_db('topics')
    active_topics = topics_df[topics_df['is_active'] == True]
    votes_df = load_data_from_db('votes')
    voted_topic_ids = votes_df[votes_df['戶號'] == unit]['topic_id'].tolist()

    for _, topic_row in active_topics.iterrows():
        topic_id = topic_row['id']
        topic_content = topic_row['議題']
        st.markdown(f"### {topic_content}")

        if topic_id in voted_topic_ids:
            st.success("✅ 您已完成此議題的投票。")
        else:
            vote_option = st.radio(f"選擇對『{topic_content}』的意見：", ("同意", "不同意"), key=f"vote_{topic_id}", horizontal=True)
            if st.button(f"提交投票 ({topic_content})", key=f"submit_{topic_id}"):
                if record_vote_to_db(unit, topic_id, vote_option, get_taipei_time()):
                    st.success(f"投票成功！您選擇了：{vote_option}")
                    st.query_params.clear()
                    st.rerun()

# ===============================
# 管理員登入與後台
# ===============================
def admin_login():
    st.header("🔐 管理員登入")
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False

    username = st.text_input("帳號")
    password = st.text_input("密碼", type="password")

    if st.button("登入"):
        if not os.path.exists(ADMIN_FILE):
            st.error("找不到 admin_config.json。")
            return
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            admin_data = json.load(f)
        if username in admin_data and password == str(admin_data[username]):
            st.session_state.is_admin = True
            st.session_state.admin_user = username
            st.success(f"登入成功！歡迎 {username}")
            st.rerun()
        else:
            st.error("帳號或密碼錯誤。")

def admin_dashboard():
    st.title("🛠️ 管理員後台")

    tab1, tab2, tab3 = st.tabs(["📂 上傳資料", "📋 投票控制", "📊 統計結果"])

    # --- 上傳資料 ---
    with tab1:
        st.subheader("上傳住戶清單")
        household_file = st.file_uploader("上傳住戶 Excel 檔", type=["xlsx"])
        if household_file:
            df = pd.read_excel(household_file)
            if save_households_to_db(df):
                st.success("住戶清單上傳成功！")

        st.subheader("上傳議題清單")
        topic_file = st.file_uploader("上傳議題 Excel 檔", type=["xlsx"])
        if topic_file:
            df = pd.read_excel(topic_file)
            if save_topics_to_db(df):
                st.success("議題清單上傳成功！")

    # --- 投票控制 ---
    with tab2:
        st.subheader("投票控制")
        voting_open = load_config('voting_open') == 'True'
        if st.toggle("開啟投票", value=voting_open, key="voting_switch"):
            save_config('voting_open', 'True')
            st.success("投票已開啟")
        else:
            save_config('voting_open', 'False')
            st.warning("投票已關閉")

        end_time = st.datetime_input("設定投票截止時間（台北時區）", get_taipei_time() + timedelta(days=1))
        if st.button("儲存截止時間"):
            save_config('end_time', end_time.strftime("%Y-%m-%d %H:%M:%S %z"))
            st.success("截止時間已更新")

    # --- 投票統計 ---
    with tab3:
        st.subheader("投票結果統計")
        votes_df = load_data_from_db('votes')
        topics_df = load_data_from_db('topics')
        households_df = load_data_from_db('households')

        if votes_df.empty or topics_df.empty:
            st.info("尚無投票資料。")
        else:
            for _, row in topics_df.iterrows():
                topic_id = row['id']
                topic = row['議題']
                votes_topic = votes_df[votes_df['topic_id'] == topic_id]
                total_voters = len(households_df)
                total_votes = len(votes_topic)
                agree = len(votes_topic[votes_topic['投票結果'] == '同意'])
                disagree = len(votes_topic[votes_topic['投票結果'] == '不同意'])
                agree_ratio = agree / total_voters if total_voters > 0 else 0
                disagree_ratio = disagree / total_voters if total_voters > 0 else 0

                st.markdown(f"#### 🗳️ {topic}")
                st.write(f"總戶數：{total_voters}")
                st.write(f"已投票人數：{total_votes}")
                st.write(f"同意：{agree} ({agree_ratio:.4%})")
                st.write(f"不同意：{disagree} ({disagree_ratio:.4%})")
                st.divider()

# ===============================
# 主控流程
# ===============================
page = st.sidebar.selectbox("選擇頁面", ["住戶投票頁", "管理員登入", "管理員後台"])

if page == "住戶投票頁":
    voter_page()
elif page == "管理員登入":
    admin_login()
elif page == "管理員後台":
    if st.session_state.get("is_admin", False):
        admin_dashboard()
    else:
        st.warning("請先登入管理員帳號。")
