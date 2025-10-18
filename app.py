import streamlit as st
import pandas as pd
import qrcode
import io
import zipfile
import json
import os
from datetime import datetime
from urllib.parse import urlencode, unquote
from streamlit_autorefresh import st_autorefresh

# ===============================
# 初始化設定
# ===============================
st.set_page_config(page_title="社區投票系統", layout="wide")

if "page" not in st.session_state:
    st.session_state.page = "home"

# 資料夾設定
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)
VOTES_FILE = os.path.join(DATA_DIR, "votes.csv")
TOPICS_FILE = os.path.join(DATA_DIR, "topics.csv")
ADMIN_FILE = os.path.join(DATA_DIR, "admin_config.json")

# 預設管理員帳號
if not os.path.exists(ADMIN_FILE):
    with open(ADMIN_FILE, "w", encoding="utf-8") as f:
        json.dump({"acidcocco": "131105"}, f, ensure_ascii=False, indent=2)

# ===============================
# 資料載入函式
# ===============================
def load_votes():
    if os.path.exists(VOTES_FILE):
        return pd.read_csv(VOTES_FILE, dtype=str)
    else:
        return pd.DataFrame(columns=["戶號", "議題", "選項", "時間"])

def save_vote(household_id, topic, choice):
    votes_df = load_votes()
    new_vote = pd.DataFrame([{
        "戶號": household_id,
        "議題": topic,
        "選項": choice,
        "時間": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }])
    votes_df = pd.concat([votes_df, new_vote], ignore_index=True)
    votes_df.to_csv(VOTES_FILE, index=False, encoding="utf-8-sig")

def load_topics():
    if os.path.exists(TOPICS_FILE):
        return pd.read_csv(TOPICS_FILE)
    else:
        df = pd.DataFrame({"議題": ["議題一：是否同意社區公設改善工程？"]})
        df.to_csv(TOPICS_FILE, index=False, encoding="utf-8-sig")
        return df

# ===============================
# 頁面 1：首頁
# ===============================
def home_page():
    st.title("🏠 社區投票系統")
    query_params = st.query_params.to_dict()
    household_id = unquote(query_params.get("unit", [None])[0]) if "unit" in query_params else None
    is_admin = str(query_params.get("admin", ["false"])[0]).lower() == "true"

    if is_admin:
        admin_login()
    elif household_id:
        voting_page(household_id)
    else:
        st.info("請使用 QR Code 進入投票頁面或登入管理端。")

# ===============================
# 管理員登入
# ===============================
def admin_login():
    st.header("👨‍💼 管理員登入")
    accounts = json.load(open(ADMIN_FILE, "r", encoding="utf-8"))
    username = st.text_input("帳號")
    password = st.text_input("密碼", type="password")
    if st.button("登入"):
        if username in accounts and accounts[username] == password:
            st.session_state.page = "admin"
            st.rerun()
        else:
            st.error("帳號或密碼錯誤")

# ===============================
# 投票頁
# ===============================
def voting_page(household_id):
    st.header("🏠 社區投票系統")
    st.write(f"👤 戶號：{household_id}")

    topics_df = load_topics()
    votes_df = load_votes()

    voted_topics = votes_df[votes_df["戶號"] == household_id]["議題"].tolist()
    remaining_topics = [t for t in topics_df["議題"].tolist() if t not in voted_topics]

    if not remaining_topics and not st.session_state.get("temp_votes"):
        st.warning("⚠️ 您已完成所有議題投票，無法重複投票。")
        return

    if "temp_votes" not in st.session_state:
        st.session_state.temp_votes = {}

    for topic in remaining_topics:
        st.subheader(f"🗳️ {topic}")
        col1, col2 = st.columns(2)
        if col1.button("👍 同意", key=f"agree_{topic}"):
            st.session_state.temp_votes[topic] = "同意"
        if col2.button("👎 不同意", key=f"disagree_{topic}"):
            st.session_state.temp_votes[topic] = "不同意"

    if st.button("📤 送出投票"):
        for topic, choice in st.session_state.temp_votes.items():
            save_vote(household_id, topic, choice)
        st.success("✅ 投票完成，感謝您的參與！")
        st.session_state.temp_votes = {}
        st.rerun()

# ===============================
# 管理頁
# ===============================
def admin_page():
    st.header("👨‍💼 管理介面")
    tabs = st.tabs(["議題設定", "產生 QR Code", "投票統計"])

    # --- 議題設定 ---
    with tabs[0]:
        topics_df = load_topics()
        st.subheader("📝 投票議題列表")
        edited_df = st.data_editor(topics_df, num_rows="dynamic", use_container_width=True)
        if st.button("💾 儲存議題"):
            edited_df.to_csv(TOPICS_FILE, index=False, encoding="utf-8-sig")
            st.success("已更新議題")

    # --- 產生 QR Code ---
    with tabs[1]:
        st.subheader("🏷️ 產生戶別 QR Code")
        base_url = st.text_input("投票網址（不含參數）", "https://voting-streamlit-app.onrender.com")
        units = st.text_area("請輸入戶號（每行一個）").strip().splitlines()
        if st.button("⚙️ 產生 QR Code"):
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zipf:
                for unit in units:
                    if unit.strip() == "":
                        continue
                    url = f"{base_url}?{urlencode({'unit': unit.strip()})}"
                    img = qrcode.make(url)
                    img_byte = io.BytesIO()
                    img.save(img_byte, format="PNG")
                    zipf.writestr(f"{unit}.png", img_byte.getvalue())
            zip_buffer.seek(0)
            st.download_button("📦 下載全部 QR Code (ZIP)", data=zip_buffer, file_name="qrcodes.zip", mime="application/zip")

    # --- 統計結果 ---
    with tabs[2]:
        st_autorefresh(interval=10000, key="refresh_stats")
        st.subheader("📊 投票統計")
        votes_df = load_votes()
        if votes_df.empty:
            st.info("尚無投票資料")
        else:
            result = votes_df.groupby(["議題", "選項"]).size().unstack(fill_value=0)
            st.dataframe(result, use_container_width=True)

# ===============================
# 主邏輯
# ===============================
if st.session_state.page == "home":
    home_page()
elif st.session_state.page == "admin":
    admin_page()
