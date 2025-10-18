import streamlit as st
import pandas as pd
import json
import os
import io
import zipfile
import qrcode
from datetime import datetime, timedelta
from pytz import timezone
from PIL import Image, ImageDraw, ImageFont

# ===============================
# 🧩 初始化設定
# ===============================
DB_FOLDER = "db"
os.makedirs(DB_FOLDER, exist_ok=True)

CONFIG_FILE = os.path.join(DB_FOLDER, "config.json")
VOTE_FILE = os.path.join(DB_FOLDER, "votes.csv")
TOPIC_FILE = os.path.join(DB_FOLDER, "topics.csv")
HOUSEHOLD_FILE = os.path.join(DB_FOLDER, "households.csv")
ADMIN_FILE = "admin_config.json"  # 管理員帳密

# ===============================
# 🕒 時間工具
# ===============================
def get_taipei_time():
    return datetime.now(timezone("Asia/Taipei"))

# ===============================
# ⚙️ 設定檔處理
# ===============================
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

# ===============================
# 📂 資料存取
# ===============================
def save_topics_to_db(df):
    df.to_csv(TOPIC_FILE, index=False, encoding="utf-8-sig")

def save_households_to_db(df):
    df.to_csv(HOUSEHOLD_FILE, index=False, encoding="utf-8-sig")

def load_data_from_db(file_path, expected_columns=None):
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=expected_columns or [])
    df = pd.read_csv(file_path)
    if expected_columns:
        for col in expected_columns:
            if col not in df.columns:
                df[col] = ""
    return df

# ===============================
# 🧮 登入檢查
# ===============================
def check_login(username, password):
    try:
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        return username in users and users[username] == password
    except Exception:
        return False

# ===============================
# 🧰 產生 QR Code（含戶號）
# ===============================
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
    try:
        font = ImageFont.truetype("arial.ttf", 36)
    except:
        font = ImageFont.load_default()
    text = str(household_id)
    text_width = draw.textlength(text, font=font)
    text_x = (width - text_width) / 2
    draw.text((text_x, height + 10), text, font=font, fill="black")

    return new_img

# ===============================
# 📦 產生 QR Code ZIP
# ===============================
def generate_qr_zip(df):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipf:
        for _, row in df.iterrows():
            if "戶號" not in row or pd.isna(row["戶號"]):
                continue
            household_id = str(row["戶號"]).strip()
            vote_url = f"https://voting-streamlit-app.onrender.com?vote={household_id}"
            qr_img = generate_qr_with_label(vote_url, household_id)
            img_bytes = io.BytesIO()
            qr_img.save(img_bytes, format="PNG")
            zipf.writestr(f"{household_id}.png", img_bytes.getvalue())
    buffer.seek(0)
    return buffer

# ===============================
# 🗳️ 投票紀錄
# ===============================
def record_vote_batch(household_id, votes_dict):
    df = load_data_from_db(VOTE_FILE, expected_columns=["戶號", "議題", "投票結果", "投票時間"])
    now = get_taipei_time().strftime("%Y-%m-%d %H:%M:%S")

    new_rows = []
    for topic, result in votes_dict.items():
        new_rows.append({
            "戶號": household_id,
            "議題": topic,
            "投票結果": result,
            "投票時間": now
        })

    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    df.to_csv(VOTE_FILE, index=False, encoding="utf-8-sig")

# ===============================
# 🏠 住戶投票頁
# ===============================
def voting_page(household_id):
    st.title("🏠 社區投票系統")
    st.write(f"👤 戶號：**{household_id}**")

    # 讀取投票開關
    voting_open = load_config("voting_open") == "True"
    if not voting_open:
        st.warning("⚠️ 投票尚未開放，請稍後再試。")
        return

    # 讀取截止時間
    end_time_str = load_config("end_time")
    if end_time_str:
        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S %z")
        if get_taipei_time() > end_time:
            st.warning("⛔ 投票時間已截止。")
            return

    votes_df = load_data_from_db(VOTE_FILE, expected_columns=["戶號", "議題", "投票結果", "投票時間"])
    topics_df = load_data_from_db(TOPIC_FILE)

    if topics_df.empty:
        st.info("目前尚無投票議題。")
        return

    voted_topics = votes_df[votes_df["戶號"].astype(str) == household_id]["議題"].tolist()

    if len(voted_topics) == len(topics_df):
        st.warning("⚠️ 您已完成所有議題投票，無法重複投票。")
        return

    st.write("請為每一個議題選擇您的意見，全部選完後再送出：")

    choices = {}
    for _, row in topics_df.iterrows():
        topic = row.get("議題", "未命名議題")
        if topic in voted_topics:
            continue
        choice = st.radio(
            f"🗳️ {topic}",
            ["未選擇", "同意", "不同意"],
            index=0,
            horizontal=True,
            key=f"vote_{topic}"
        )
        if choice != "未選擇":
            choices[topic] = choice

    if st.button("📤 送出投票"):
        if len(choices) < len(topics_df) - len(voted_topics):
            st.warning("⚠️ 請確保所有議題都已選擇意見後再送出。")
        else:
            record_vote_batch(household_id, choices)
            st.success("✅ 投票完成！感謝您的參與。")
            st.rerun()

# ===============================
# 🧰 管理員後台
# ===============================
def admin_dashboard():
    st.title("🛠️ 管理員後台")
    tab1, tab2, tab3 = st.tabs(["📂 上傳資料", "📋 投票控制", "📊 統計結果"])

    # ---- 上傳資料 ----
    with tab1:
        st.subheader("上傳住戶清單")
        household_file = st.file_uploader("上傳住戶 Excel 檔", type=["xlsx"])
        if household_file:
            import openpyxl
            df = pd.read_excel(household_file)
            if "戶號" not in df.columns:
                st.error("⚠️ Excel 必須包含「戶號」欄位")
            else:
                save_households_to_db(df)
                st.success("✅ 住戶清單上傳成功")

                if st.button("📦 產生 QR Code ZIP"):
                    qr_zip = generate_qr_zip(df)
                    st.download_button("⬇️ 下載 ZIP", data=qr_zip, file_name="qrcodes.zip", mime="application/zip")

        st.divider()
        st.subheader("上傳議題清單")
        topic_file = st.file_uploader("上傳議題 Excel 檔", type=["xlsx"])
        if topic_file:
            import openpyxl
            df = pd.read_excel(topic_file)
            save_topics_to_db(df)
            st.success("✅ 議題清單上傳成功")

    # ---- 投票控制 ----
    with tab2:
        st.subheader("投票開關")
        toggle_val = st.toggle("開啟投票", value=(load_config("voting_open") == "True"))
        save_config("voting_open", str(toggle_val))
        st.info("🔄 投票狀態：" + ("✅ 開啟" if toggle_val else "⛔ 關閉"))

        st.divider()
        st.subheader("設定截止時間（台北時間）")
        now_taipei = get_taipei_time()
        option = st.selectbox("設定截止時間", ["5分鐘後", "10分鐘後", "15分鐘後", "自訂"], index=1)
        if option == "自訂":
            date_val = st.date_input("日期", now_taipei.date())
            time_val = st.time_input("時間", (now_taipei + timedelta(minutes=10)).time())
            end_dt = datetime.combine(date_val, time_val).astimezone(timezone("Asia/Taipei"))
        else:
            mins = int(option.split("分鐘")[0])
            end_dt = now_taipei + timedelta(minutes=mins)

        if st.button("儲存截止時間"):
            save_config("end_time", end_dt.strftime("%Y-%m-%d %H:%M:%S %z"))
            st.success(f"✅ 截止時間設定為 {end_dt.strftime('%Y-%m-%d %H:%M:%S')}")

    # ---- 統計結果 ----
    with tab3:
        votes_df = load_data_from_db(VOTE_FILE, expected_columns=["戶號", "議題", "投票結果", "投票時間"])
        topics_df = load_data_from_db(TOPIC_FILE)
        households_df = load_data_from_db(HOUSEHOLD_FILE)

        if votes_df.empty:
            st.info("尚無投票資料")
        else:
            for _, row in topics_df.iterrows():
                topic = row["議題"]
                topic_votes = votes_df[votes_df["議題"] == topic]
                total_voters = len(households_df)
                total_votes = len(topic_votes)
                agree = len(topic_votes[topic_votes["投票結果"] == "同意"])
                disagree = len(topic_votes[topic_votes["投票結果"] == "不同意"])

                st.markdown(f"### 🗳️ {topic}")
                st.write(f"總戶數：{total_voters}")
                st.write(f"投票數：{total_votes}")
                st.write(f"👍 同意：{agree}  ({agree/total_voters:.2%})")
                st.write(f"👎 不同意：{disagree}  ({disagree/total_voters:.2%})")
                st.divider()

# ===============================
# 🧭 主程式
# ===============================
def main():
    st.set_page_config(page_title="🏠 社區投票系統", layout="wide")
    params = st.query_params
    if "vote" in params:
        household_id = params.get("vote", [None])[0]
        voting_page(household_id)
        return

    st.title("🏠 社區投票系統")
    tab_login, tab_admin = st.tabs(["🔐 管理員登入", "📊 管理後台"])

    with tab_login:
        username = st.text_input("帳號")
        password = st.text_input("密碼", type="password")
        if st.button("登入"):
            if check_login(username, password):
                st.session_state["admin_logged_in"] = True
                st.success("登入成功，請切換到管理後台。")
            else:
                st.error("帳號或密碼錯誤")

    with tab_admin:
        if st.session_state.get("admin_logged_in", False):
            admin_dashboard()
        else:
            st.warning("請先登入")

if __name__ == "__main__":
    main()
