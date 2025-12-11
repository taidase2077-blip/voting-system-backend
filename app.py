import streamlit as st
import pandas as pd
import json
import os
import io
import zipfile
import qrcode
from datetime import datetime
from pytz import timezone
from PIL import Image, ImageDraw, ImageFont

# ---------- 🔧 安全路徑設定（Render 必備） ----------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FOLDER = os.path.join(BASE_DIR, "db")
ADMIN_FILE = os.path.join(BASE_DIR, "admin_config.json")

CONFIG_FILE = os.path.join(DB_FOLDER, "config.json")
VOTE_FILE = os.path.join(DB_FOLDER, "votes.csv")
TOPIC_FILE = os.path.join(DB_FOLDER, "topics.csv")
HOUSEHOLD_FILE = os.path.join(DB_FOLDER, "households.csv")

# ---------- 🧩 初始化資料夾 ----------
if os.path.exists(DB_FOLDER) and not os.path.isdir(DB_FOLDER):
    os.remove(DB_FOLDER)
os.makedirs(DB_FOLDER, exist_ok=True)


# ---------- 🕒 取得台北時間 ----------
def get_taipei_time():
    return datetime.now(timezone("Asia/Taipei"))


# ---------- 🗂️ 設定檔讀寫 ----------
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


# ---------- 📁 資料庫讀寫 ----------
def save_topics_to_db(df):
    df.to_csv(TOPIC_FILE, index=False, encoding="utf-8-sig")
    return True

def save_households_to_db(df):
    df.to_csv(HOUSEHOLD_FILE, index=False, encoding="utf-8-sig")
    return True

def load_data_from_db(file_path, expected_columns=None):
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=expected_columns or [])
    df = pd.read_csv(file_path, encoding="utf-8")
    if expected_columns:
        for col in expected_columns:
            if col not in df.columns:
                df[col] = ""
    return df


# ---------- 🔐 後台登入 ----------
def check_login(username, password):
    try:
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        return username in users and users[username] == password
    except Exception:
        return False


# ---------- 🧾 產生 QR ----------
def generate_qr_with_label(vote_url, household_id):
    qr = qrcode.QRCode(
        version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4
    )
    qr.add_data(vote_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    width, height = qr_img.size
    new_height = height + 60
    new_img = Image.new("RGB", (width, new_height), "white")
    new_img.paste(qr_img, (0, 0))

    draw = ImageDraw.Draw(new_img)
    font = ImageFont.load_default()
    text_width = draw.textlength(str(household_id), font=font)
    draw.text(((width - text_width) / 2, height + 10), str(household_id), font=font, fill="black")

    return new_img

def generate_qr_zip(df):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipf:
        for _, row in df.iterrows():
            if "戶號" not in row or pd.isna(row["戶號"]):
                continue
            household_id = str(row["戶號"]).strip()

            # 動態取得 Render Domain
            domain = st.secrets.get("APP_DOMAIN", "https://voting-streamlit-app.onrender.com")
            vote_url = f"{domain}?vote={household_id}"

            qr_img = generate_qr_with_label(vote_url, household_id)
            img_bytes = io.BytesIO()
            qr_img.save(img_bytes, format="PNG")
            zipf.writestr(f"{household_id}.png", img_bytes.getvalue())
    buffer.seek(0)
    return buffer


# ---------- 🗳️ 投票頁 ----------
def voting_page(household_id):
    st.title("🏠 社區投票系統")
    st.write(f"👤 戶號：**{household_id}**")

    votes_df = load_data_from_db(VOTE_FILE, expected_columns=["戶號", "議題", "投票結果", "投票時間"])
    topics_df = load_data_from_db(TOPIC_FILE)

    if topics_df.empty:
        st.info("目前尚無投票議題。")
        return

    household_votes = votes_df[votes_df["戶號"].astype(str) == household_id]
    voted_topics = household_votes["議題"].tolist()

    st.write("請選擇您的投票意見：")
    all_voted = True

    for _, row in topics_df.iterrows():
        topic = row.get("議題", "未命名議題")
        st.subheader(f"🗳️ {topic}")

        if topic in voted_topics:
            result = household_votes[household_votes["議題"] == topic]["投票結果"].iloc[0]
            st.success(f"✅ 您已投票：**{result}**")
        else:
            all_voted = False
            col1, col2 = st.columns(2)

            if col1.button("👍 同意", key=f"agree_{topic}"):
                record_vote(household_id, topic, "同意")
                st.rerun()

            if col2.button("👎 不同意", key=f"disagree_{topic}"):
                record_vote(household_id, topic, "不同意")
                st.rerun()

        st.divider()

    if all_voted:
        st.warning("⚠️ 您已完成所有議題投票，感謝您的參與。")


# ---------- 📝 寫入投票紀錄 ----------
def record_vote(household_id, topic, result):
    df = load_data_from_db(VOTE_FILE, expected_columns=["戶號", "議題", "投票結果", "投票時間"])
    new_row = {
        "戶號": household_id,
        "議題": topic,
        "投票結果": result,
        "投票時間": get_taipei_time().strftime("%Y-%m-%d %H:%M:%S"),
    }
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    df.to_csv(VOTE_FILE, index=False, encoding="utf-8-sig")


# ---------- 🛠️ 後台主畫面（此處略） ----------
def admin_dashboard():
    st.title("🛠️ 管理員後台")
    st.write("（內容同前，略）")


# ---------- 🔐 初始化管理員 ----------
def initialize_admin_config():
    if not os.path.exists(ADMIN_FILE):
        default_admin = {"admin": "123456"}
        with open(ADMIN_FILE, "w", encoding="utf-8") as f:
            json.dump(default_admin, f, ensure_ascii=False, indent=2)


# ---------- 🚀 主程式 ----------
def main():
    initialize_admin_config()
    st.set_page_config(page_title="🏠 社區投票系統", layout="wide")

    params = st.query_params

    # voting mode
    household_id = params.get("vote")
    if household_id:
        voting_page(str(household_id))
        return

    # admin mode
    st.title("🏠 社區投票系統")

    if "admin_logged_in" not in st.session_state:
        st.session_state["admin_logged_in"] = False

    tab_login, tab_admin = st.tabs(["🔐 管理員登入", "📊 管理後台"])

    with tab_login:
        st.subheader("請輸入管理員帳號密碼")
        username = st.text_input("帳號")
        password = st.text_input("密碼", type="password")
        if st.button("登入"):
            if check_login(username, password):
                st.session_state["admin_logged_in"] = True
                st.success("登入成功！")
            else:
                st.error("帳號或密碼錯誤")

    with tab_admin:
        if st.session_state["admin_logged_in"]:
            admin_dashboard()
        else:
            st.warning("請先登入管理員帳號")


if __name__ == "__main__":
    main()
