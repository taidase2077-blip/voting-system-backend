import streamlit as st
import pandas as pd
import sqlite3
import json
import sys
import subprocess
from datetime import datetime, timedelta
from pytz import timezone

# ===============================
# 🧩 檢查 openpyxl 套件（避免匯入錯誤）
# ===============================
try:
    import openpyxl
except ImportError:
    st.warning("⚠️ 尚未安裝 openpyxl，正在嘗試自動安裝中...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl

# ===============================
# 🧱 資料庫初始化
# ===============================
def init_db():
    conn = sqlite3.connect("voting.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS households (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        戶號 TEXT UNIQUE
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        議題 TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        unit TEXT,
        topic_id INTEGER,
        投票結果 TEXT,
        timestamp TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS config (
        key TEXT PRIMARY KEY,
        value TEXT
    )""")
    conn.commit()
    conn.close()

# ===============================
# 🕒 時間與設定
# ===============================
def get_taipei_time():
    return datetime.now(timezone("Asia/Taipei"))

def save_config(key, value):
    conn = sqlite3.connect("voting.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def load_config(key):
    conn = sqlite3.connect("voting.db")
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

# ===============================
# 📂 資料操作
# ===============================
def save_households_to_db(df):
    conn = sqlite3.connect("voting.db")
    c = conn.cursor()
    for _, row in df.iterrows():
        try:
            c.execute("INSERT OR IGNORE INTO households (戶號) VALUES (?)", (str(row['戶號']),))
        except Exception:
            pass
    conn.commit()
    conn.close()
    return True

def save_topics_to_db(df):
    conn = sqlite3.connect("voting.db")
    c = conn.cursor()
    for _, row in df.iterrows():
        try:
            c.execute("INSERT INTO topics (議題) VALUES (?)", (str(row['議題']),))
        except Exception:
            pass
    conn.commit()
    conn.close()
    return True

def load_data_from_db(table):
    conn = sqlite3.connect("voting.db")
    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
    conn.close()
    return df

# ===============================
# 🗳️ 投票頁面
# ===============================
def voter_page():
    st.title("🏠 社區投票系統")

    params = st.query_params
    unit = params.get("unit", [None])[0] if "unit" in params else None

    if not unit:
        st.warning("⚠️ 找不到住戶戶號，請由 QR Code 進入。")
        return

    households = load_data_from_db("households")
    if unit not in households["戶號"].astype(str).values:
        st.error("❌ 無效的住戶戶號。")
        return

    voting_open = load_config("voting_open") == "True"
    end_time_str = load_config("end_time")

    if not voting_open:
        st.info("⛔ 投票尚未開放。")
        return

    if end_time_str:
        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S %z")
        if get_taipei_time() > end_time:
            st.warning("🕒 投票已截止。")
            return

    st.write(f"👋 歡迎，{unit} 戶！請選擇您對下列議題的意見：")

    topics = load_data_from_db("topics")
    votes = load_data_from_db("votes")
    voted_topics = votes[votes["unit"] == unit]["topic_id"].tolist()

    conn = sqlite3.connect("voting.db")
    c = conn.cursor()

    for _, row in topics.iterrows():
        topic_id = row["id"]
        topic = row["議題"]
        st.markdown(f"### 🗳️ {topic}")

        if topic_id in voted_topics:
            st.success("您已完成投票。")
        else:
            choice = st.radio(
                f"請選擇您的意見（{topic}）",
                ["同意", "不同意"],
                key=f"vote_{topic_id}"
            )
            if st.button(f"送出投票 - {topic}", key=f"submit_{topic_id}"):
                c.execute(
                    "INSERT INTO votes (unit, topic_id, 投票結果, timestamp) VALUES (?, ?, ?, ?)",
                    (unit, topic_id, choice, get_taipei_time().strftime("%Y-%m-%d %H:%M:%S %z"))
                )
                conn.commit()
                st.success("✅ 投票完成！")
                st.rerun()

    conn.close()

# ===============================
# 🔑 管理員登入（讀取 admin_config.json）
# ===============================
def admin_login():
    st.title("🔐 管理員登入")

    try:
        with open("admin_config.json", "r", encoding="utf-8") as f:
            admin_data = json.load(f)
    except Exception as e:
        st.error("❌ 無法讀取 admin_config.json，請確認檔案存在且格式正確。")
        st.stop()

    username = st.text_input("帳號")
    password = st.text_input("密碼", type="password")

    if st.button("登入"):
        if username in admin_data and admin_data[username] == password:
            st.session_state["admin_logged_in"] = True
            st.session_state["admin_user"] = username
            st.success(f"歡迎登入，{username}！")
            st.rerun()
        else:
            st.error("帳號或密碼錯誤。")

# ===============================
# 🛠️ 管理員後台
# ===============================
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
                st.success("✅ 住戶清單上傳成功")

        st.subheader("上傳議題清單")
        topic_file = st.file_uploader("上傳議題 Excel 檔", type=["xlsx"])
        if topic_file:
            df = pd.read_excel(topic_file)
            if save_topics_to_db(df):
                st.success("✅ 議題清單上傳成功")

    # --- 投票控制 ---
    with tab2:
        st.subheader("投票控制")

        voting_open = load_config("voting_open") == "True"
        toggle_val = st.toggle("開啟投票", value=voting_open)
        save_config("voting_open", str(toggle_val))
        st.info("🔄 投票狀態：" + ("✅ 已開啟" if toggle_val else "⛔ 已關閉"))

        st.divider()
        st.subheader("設定投票截止時間（台北時間）")

        current_end_str = load_config("end_time")
        if current_end_str:
            st.write(f"目前截止時間：**{current_end_str}**")
        else:
            st.write("尚未設定截止時間。")

        now_taipei = get_taipei_time()
        st.write(f"🕒 現在時間：{now_taipei.strftime('%Y-%m-%d %H:%M:%S')}")

        option = st.selectbox(
            "選擇距現在的截止時間：",
            ["自訂時間", "5 分鐘後", "10 分鐘後", "15 分鐘後", "20 分鐘後", "25 分鐘後", "30 分鐘後"],
            index=2
        )

        if option == "自訂時間":
            date_val = st.date_input("截止日期", now_taipei.date())
            time_val = st.time_input("截止時間", (now_taipei + timedelta(minutes=10)).time())
            end_dt = datetime.combine(date_val, time_val).astimezone(timezone("Asia/Taipei"))
        else:
            minutes = int(option.split("分鐘")[0])
            end_dt = now_taipei + timedelta(minutes=minutes)
            st.info(f"⏰ 系統將設定截止時間為：{end_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        if st.button("儲存截止時間"):
            save_config("end_time", end_dt.strftime("%Y-%m-%d %H:%M:%S %z"))
            st.success(f"✅ 已設定截止時間：{end_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    # --- 投票統計 ---
    with tab3:
        st.subheader("投票結果統計")

        votes_df = load_data_from_db("votes")
        topics_df = load_data_from_db("topics")
        households_df = load_data_from_db("households")

        if votes_df.empty or topics_df.empty:
            st.info("目前尚無投票資料。")
        else:
            for _, row in topics_df.iterrows():
                topic_id = row["id"]
                topic = row["議題"]
                votes_topic = votes_df[votes_df["topic_id"] == topic_id]
                total_voters = len(households_df)
                total_votes = len(votes_topic)
                agree = len(votes_topic[votes_topic["投票結果"] == "同意"])
                disagree = len(votes_topic[votes_topic["投票結果"] == "不同意"])
                agree_ratio = agree / total_voters if total_voters else 0
                disagree_ratio = disagree / total_voters if total_voters else 0

                st.markdown(f"#### 🗳️ {topic}")
                st.write(f"📋 總戶數：{total_voters}")
                st.write(f"🧾 已投票人數：{total_votes}")
                st.write(f"👍 同意：{agree} ({agree_ratio:.4%})")
                st.write(f"👎 不同意：{disagree} ({disagree_ratio:.4%})")
                st.divider()

# ===============================
# 🚀 主程式入口
# ===============================
init_db()
st.sidebar.title("選單")

params = st.query_params
unit = params.get("unit", [None])[0] if "unit" in params else None

if "admin_logged_in" not in st.session_state:
    st.session_state["admin_logged_in"] = False

if unit:
    voter_page()
else:
    page = st.sidebar.radio("請選擇頁面", ["投票頁面", "管理員登入", "管理員後台"])
    if page == "投票頁面":
        voter_page()
    elif page == "管理員登入":
        admin_login()
    elif page == "管理員後台":
        if st.session_state.get("admin_logged_in"):
            admin_dashboard()
        else:
            st.warning("請先登入管理員帳號。")
