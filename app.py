import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, timedelta
from pytz import timezone

# ---------- 🧩 初始化資料 ----------
DB_FOLDER = "db"
os.makedirs(DB_FOLDER, exist_ok=True)

CONFIG_FILE = os.path.join(DB_FOLDER, "config.json")
VOTE_FILE = os.path.join(DB_FOLDER, "votes.csv")
TOPIC_FILE = os.path.join(DB_FOLDER, "topics.csv")
HOUSEHOLD_FILE = os.path.join(DB_FOLDER, "households.csv")
ADMIN_FILE = "admin_config.json"  # 這裡會用你的帳密檔案

# ---------- 🕒 時區處理 ----------
def get_taipei_time():
    return datetime.now(timezone("Asia/Taipei"))

# ---------- ⚙️ 設定管理 ----------
def save_config(key, value):
    data = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    data[key] = value
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_config(key):
    if not os.path.exists(CONFIG_FILE):
        return None
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get(key)

# ---------- 📂 檔案儲存 ----------
def save_topics_to_db(df):
    df.to_csv(TOPIC_FILE, index=False, encoding="utf-8-sig")
    return True

def save_households_to_db(df):
    df.to_csv(HOUSEHOLD_FILE, index=False, encoding="utf-8-sig")
    return True

def load_data_from_db(file_path):
    if not os.path.exists(file_path):
        return pd.DataFrame()
    return pd.read_csv(file_path)

# ---------- 🧮 登入檢查 ----------
def check_login(username, password):
    try:
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        return username in users and users[username] == password
    except Exception:
        return False

# ---------- 🧰 管理員後台 ----------
def admin_dashboard():
    st.title("🛠️ 管理員後台")

    tab1, tab2, tab3 = st.tabs(["📂 上傳資料", "📋 投票控制", "📊 統計結果"])

    # === 📂 上傳資料 ===
    with tab1:
        st.subheader("上傳住戶清單")
        household_file = st.file_uploader("上傳住戶 Excel 檔", type=["xlsx"])
        if household_file:
            try:
                import openpyxl  # 確保 openpyxl 已安裝
                df = pd.read_excel(household_file)
                save_households_to_db(df)
                st.success("✅ 住戶清單上傳成功")
            except ImportError:
                st.error("⚠️ 請安裝 openpyxl 套件：pip install openpyxl")

        st.subheader("上傳議題清單")
        topic_file = st.file_uploader("上傳議題 Excel 檔", type=["xlsx"])
        if topic_file:
            try:
                import openpyxl
                df = pd.read_excel(topic_file)
                save_topics_to_db(df)
                st.success("✅ 議題清單上傳成功")
            except ImportError:
                st.error("⚠️ 請安裝 openpyxl 套件：pip install openpyxl")

    # === 📋 投票控制 ===
    with tab2:
        st.subheader("投票開關控制")
        voting_open = load_config('voting_open') == 'True'
        toggle_val = st.toggle("開啟投票", value=voting_open)
        save_config('voting_open', str(toggle_val))
        st.info("🔄 投票狀態：" + ("✅ 開啟" if toggle_val else "⛔ 關閉"))

        st.divider()
        st.subheader("設定投票截止時間（台北時間）")

        current_end_str = load_config('end_time')
        if current_end_str:
            st.write(f"目前截止時間：**{current_end_str}**（台北）")
        else:
            st.write("尚未設定截止時間")

        now_taipei = get_taipei_time()
        st.write(f"🕒 現在時間：{now_taipei.strftime('%Y-%m-%d %H:%M:%S')}（台北）")

        option = st.selectbox(
            "選擇距現在的截止時間：",
            ["自訂時間", "5 分鐘後", "10 分鐘後", "15 分鐘後", "20 分鐘後", "25 分鐘後", "30 分鐘後"],
            index=2
        )

        if option == "自訂時間":
            date_val = st.date_input("選擇截止日期", now_taipei.date())
            time_val = st.time_input("選擇截止時間", (now_taipei + timedelta(minutes=10)).time())
            end_dt = datetime.combine(date_val, time_val).astimezone(timezone("Asia/Taipei"))
        else:
            minutes = int(option.split("分鐘")[0])
            end_dt = now_taipei + timedelta(minutes=minutes)
            st.info(f"⏰ 系統將設定為：{end_dt.strftime('%Y-%m-%d %H:%M:%S')}（台北時間）")

        if st.button("儲存截止時間"):
            save_config('end_time', end_dt.strftime("%Y-%m-%d %H:%M:%S %z"))
            st.success(f"✅ 截止時間已設定為：{end_dt.strftime('%Y-%m-%d %H:%M:%S')}（台北時間）")

    # === 📊 投票統計 ===
    with tab3:
        st.subheader("投票結果統計")

        votes_df = load_data_from_db(VOTE_FILE)
        topics_df = load_data_from_db(TOPIC_FILE)
        households_df = load_data_from_db(HOUSEHOLD_FILE)

        if votes_df.empty or topics_df.empty:
            st.info("目前尚無投票資料。")
        else:
            for _, row in topics_df.iterrows():
                topic = row['議題']
                topic_votes = votes_df[votes_df['topic_id'] == row['id']] if 'id' in row else votes_df
                total_voters = len(households_df)
                total_votes = len(topic_votes)
                agree = len(topic_votes[topic_votes['投票結果'] == '同意'])
                disagree = len(topic_votes[topic_votes['投票結果'] == '不同意'])
                agree_ratio = agree / total_voters if total_voters > 0 else 0
                disagree_ratio = disagree / total_voters if total_voters > 0 else 0

                st.markdown(f"### 🗳️ {topic}")
                st.write(f"📋 總戶數：{total_voters}")
                st.write(f"🧾 已投票人數：{total_votes}")
                st.write(f"👍 同意：{agree} ({agree_ratio:.4%})")
                st.write(f"👎 不同意：{disagree} ({disagree_ratio:.4%})")
                st.divider()

# ---------- 🧭 主程式 ----------
def main():
    st.set_page_config(page_title="🏠 社區投票系統", layout="wide")

    st.title("🏠 社區投票系統")

    tab_login, tab_admin = st.tabs(["🔐 管理員登入", "📊 管理後台"])

    with tab_login:
        st.subheader("請輸入管理員帳號密碼")
        username = st.text_input("帳號")
        password = st.text_input("密碼", type="password")
        if st.button("登入"):
            if check_login(username, password):
                st.session_state["admin_logged_in"] = True
                st.success("✅ 登入成功！請切換至『📊 管理後台』")
            else:
                st.error("❌ 帳號或密碼錯誤")

    with tab_admin:
        if st.session_state.get("admin_logged_in", False):
            admin_dashboard()
        else:
            st.warning("請先登入管理員帳號")

if __name__ == "__main__":
    main()
