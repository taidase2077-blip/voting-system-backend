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

# ---------- 🧩 初始化資料 ----------
DB_FOLDER = "db"
os.makedirs(DB_FOLDER, exist_ok=True)

CONFIG_FILE = os.path.join(DB_FOLDER, "config.json")
VOTE_FILE = os.path.join(DB_FOLDER, "votes.csv")
TOPIC_FILE = os.path.join(DB_FOLDER, "topics.csv")
HOUSEHOLD_FILE = os.path.join(DB_FOLDER, "households.csv")
ADMIN_FILE = "admin_config.json"  # 管理員帳密

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

# ---------- 📂 檔案讀寫 ----------
def load_data_from_db(file_path, expected_columns=None):
    if not os.path.exists(file_path):
        return pd.DataFrame(columns=expected_columns or [])
    df = pd.read_csv(file_path)
    if expected_columns:
        for col in expected_columns:
            if col not in df.columns:
                df[col] = ""
    return df

def save_topics_to_db(df):
    df.to_csv(TOPIC_FILE, index=False, encoding="utf-8-sig")
    return True

def save_households_to_db(df):
    df.to_csv(HOUSEHOLD_FILE, index=False, encoding="utf-8-sig")
    return True

# ---------- 🧮 登入檢查 ----------
def check_login(username, password):
    try:
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        return username in users and users[username] == password
    except Exception:
        return False

# ---------- 🧰 產生帶戶號文字的 QR Code ----------
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
    text_y = height + 10
    draw.text((text_x, text_y), text, font=font, fill="black")

    return new_img

# ---------- 🧰 產生 QR Code ZIP ----------
def generate_qr_zip(df):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zipf:
        total = len(df)
        progress = st.progress(0, text="正在生成 QR Code 圖片...")
        for i, row in enumerate(df.iterrows()):
            _, r = row
            if "戶號" not in r or pd.isna(r["戶號"]):
                continue
            household_id = str(r["戶號"]).strip()
            vote_url = f"https://voting-streamlit-app.onrender.com?vote={household_id}"
            qr_img = generate_qr_with_label(vote_url, household_id)
            img_bytes = io.BytesIO()
            qr_img.save(img_bytes, format="PNG")
            zipf.writestr(f"{household_id}.png", img_bytes.getvalue())
            progress.progress((i + 1) / total)
        progress.empty()
    buffer.seek(0)
    return buffer

# ---------- 🗳️ 投票頁面 ----------
def voting_page(household_id):
    st.title("🏠 社區投票系統")

    st.write(f"👤 戶號：{household_id}")

    topics_df = load_data_from_db(TOPIC_FILE, expected_columns=["id", "議題"])
    votes_df = load_data_from_db(VOTE_FILE, expected_columns=["戶號", "topic_id", "投票結果"])
    households_df = load_data_from_db(HOUSEHOLD_FILE, expected_columns=["戶號"])

    if household_id not in households_df["戶號"].astype(str).values:
        st.error("⚠️ 查無此戶號，請確認您的 QR Code 是否正確。")
        return

    end_time_str = load_config("end_time")
    if end_time_str:
        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S %z")
        now = get_taipei_time()
        if now > end_time:
            st.warning("🕒 投票已截止！")
            return

    if load_config("voting_open") != "True":
        st.warning("目前尚未開放投票。")
        return

    # 防止重複投票
    if household_id in votes_df["戶號"].astype(str).values:
        st.info("✅ 您已投過票，感謝參與！")
        return

    with st.form("vote_form"):
        st.write("請選擇您的投票意見：")
        results = {}
        for _, row in topics_df.iterrows():
            choice = st.radio(
                f"🗳️ {row['議題']}",
                ["同意", "不同意"],
                key=f"vote_{row['id']}",
                horizontal=True,
            )
            results[row["id"]] = choice
        submit = st.form_submit_button("提交投票")

        if submit:
            new_votes = []
            for topic_id, res in results.items():
                new_votes.append({"戶號": household_id, "topic_id": topic_id, "投票結果": res})
            new_df = pd.DataFrame(new_votes)
            all_votes = pd.concat([votes_df, new_df], ignore_index=True)
            all_votes.to_csv(VOTE_FILE, index=False, encoding="utf-8-sig")
            st.success("✅ 投票完成，感謝您的參與！")

# ---------- 🧰 管理員後台 ----------
def admin_dashboard():
    st.title("🛠️ 管理員後台")
    tab1, tab2, tab3 = st.tabs(["📂 上傳資料", "📋 投票控制", "📊 統計結果"])

    # === 📂 上傳資料 ===
    with tab1:
        st.subheader("上傳住戶清單")
        household_file = st.file_uploader("上傳住戶 Excel 檔", type=["xlsx"])
        if household_file:
            with st.spinner("正在處理住戶清單..."):
                import openpyxl
                df = pd.read_excel(household_file)
                if "戶號" not in df.columns:
                    st.error("⚠️ Excel 檔必須包含「戶號」欄位")
                else:
                    save_households_to_db(df)
                    st.success("✅ 住戶清單上傳成功")

                    qr_zip = generate_qr_zip(df)
                    st.download_button(
                        label="📦 下載戶號 QR Code ZIP（含戶號標籤）",
                        data=qr_zip,
                        file_name="household_qrcodes.zip",
                        mime="application/zip",
                    )

        st.subheader("上傳議題清單")
        topic_file = st.file_uploader("上傳議題 Excel 檔", type=["xlsx"])
        if topic_file:
            with st.spinner("正在處理議題清單..."):
                import openpyxl
                df = pd.read_excel(topic_file)
                save_topics_to_db(df)
                st.success("✅ 議題清單上傳成功")

    # === 📋 投票控制 ===
    with tab2:
        st.subheader("投票開關控制")
        voting_open = load_config("voting_open") == "True"
        toggle_val = st.toggle("開啟投票", value=voting_open)
        save_config("voting_open", str(toggle_val))
        st.info("🔄 投票狀態：" + ("✅ 開啟" if toggle_val else "⛔ 關閉"))

        st.divider()
        st.subheader("設定投票截止時間（台北時間）")
        current_end_str = load_config("end_time")
        if current_end_str:
            st.write(f"目前截止時間：**{current_end_str}**（台北）")

        now_taipei = get_taipei_time()
        st.write(f"🕒 現在時間：{now_taipei.strftime('%Y-%m-%d %H:%M:%S')}（台北）")

        mode = st.selectbox("選擇設定方式：", ["自訂分鐘數", "固定時間選擇"], index=0)

        if mode == "自訂分鐘數":
            minutes = st.number_input("請輸入幾分鐘後截止", min_value=1, max_value=180, value=10, step=1)
            end_dt = now_taipei + timedelta(minutes=minutes)
        else:
            date_val = st.date_input("選擇截止日期", now_taipei.date())
            time_val = st.time_input("選擇截止時間", (now_taipei + timedelta(minutes=10)).time())
            end_dt = datetime.combine(date_val, time_val).astimezone(timezone("Asia/Taipei"))

        if st.button("儲存截止時間"):
            save_config("end_time", end_dt.strftime("%Y-%m-%d %H:%M:%S %z"))
            st.success(f"✅ 截止時間已設定為：{end_dt.strftime('%Y-%m-%d %H:%M:%S')}（台北時間）")

    # === 📊 統計結果 ===
    with tab3:
        st.subheader("投票結果統計")
        votes_df = load_data_from_db(VOTE_FILE, expected_columns=["戶號", "topic_id", "投票結果"])
        topics_df = load_data_from_db(TOPIC_FILE, expected_columns=["id", "議題"])
        households_df = load_data_from_db(HOUSEHOLD_FILE, expected_columns=["戶號"])

        if votes_df.empty or topics_df.empty:
            st.info("目前尚無投票資料。")
        else:
            for _, row in topics_df.iterrows():
                topic = row["議題"]
                topic_votes = votes_df[votes_df["topic_id"] == row["id"]]
                total_voters = len(households_df)
                total_votes = len(topic_votes)
                agree = len(topic_votes[topic_votes["投票結果"] == "同意"])
                disagree = len(topic_votes[topic_votes["投票結果"] == "不同意"])
                agree_ratio = agree / total_voters if total_voters > 0 else 0
                disagree_ratio = disagree / total_voters if total_voters > 0 else 0

                st.markdown(f"### 🗳️ {topic}")
                st.write(f"📋 總戶數：{total_voters}")
                st.write(f"🧾 已投票人數：{total_votes}")
                st.write(f"👍 同意：{agree} ({agree_ratio:.2%})")
                st.write(f"👎 不同意：{disagree} ({disagree_ratio:.2%})")
                st.divider()

# ---------- 🧭 主程式 ----------
def main():
    st.set_page_config(page_title="🏠 社區投票系統", layout="wide")

    params = st.query_params
    household_id = None
    if "vote" in params:
        household_id = params.get("vote", [None])[0]

    if household_id:
        voting_page(household_id)
    else:
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
