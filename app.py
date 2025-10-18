# app.py
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

# ----------------- 設定 -----------------
DB_FOLDER = "db"
os.makedirs(DB_FOLDER, exist_ok=True)

CONFIG_FILE = os.path.join(DB_FOLDER, "config.json")
VOTE_FILE = os.path.join(DB_FOLDER, "votes.csv")
TOPIC_FILE = os.path.join(DB_FOLDER, "topics.csv")
HOUSEHOLD_FILE = os.path.join(DB_FOLDER, "households.csv")
ADMIN_FILE = "admin_config.json"  # 管理員帳密 JSON

# QR 連結前綴（你提供的網址）
QR_BASE_URL = "https://voting-streamlit-app.onrender.com/?vote="

# ----------------- 時區 -----------------
def get_taipei_time():
    return datetime.now(timezone("Asia/Taipei"))

# ----------------- config 存讀 -----------------
def save_config(key, value):
    data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except:
            data = {}
    data[key] = value
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_config(key):
    if not os.path.exists(CONFIG_FILE):
        return None
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get(key)
    except:
        return None

# ----------------- 檔案存取 -----------------
def save_topics_to_db(df):
    # 如果只有「議題」一欄，幫忙產生 id 欄
    df = df.copy()
    if '議題' in df.columns and 'id' not in df.columns:
        df.insert(0, 'id', range(1, len(df) + 1))
    df.to_csv(TOPIC_FILE, index=False, encoding="utf-8-sig")
    return True

def save_households_to_db(df):
    df.to_csv(HOUSEHOLD_FILE, index=False, encoding="utf-8-sig")
    return True

def load_data_from_db(file_path):
    if not os.path.exists(file_path):
        return pd.DataFrame()
    try:
        return pd.read_csv(file_path)
    except:
        return pd.DataFrame()

# ----------------- 管理員帳密檢查 -----------------
def check_login(username, password):
    try:
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            users = json.load(f)
        return username in users and users[username] == password
    except Exception:
        return False

# ----------------- 生成帶標籤的 QR 圖片 -----------------
def generate_qr_with_label(vote_url, household_id, qr_box_size=6, label_height=48):
    # 建立 QR
    qr = qrcode.QRCode(
        version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=qr_box_size, border=4
    )
    qr.add_data(vote_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    width, height = qr_img.size
    new_height = height + label_height
    new_img = Image.new("RGB", (width, new_height), "white")
    new_img.paste(qr_img, (0, 0))

    draw = ImageDraw.Draw(new_img)
    # 嘗試用常見字型，找不到則 fallback
    try:
        font = ImageFont.truetype("arial.ttf", 28)
    except:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        except:
            font = ImageFont.load_default()

    text = str(household_id)
    # Pillow 新版可用 textlength，舊版 fallback to textsize
    try:
        text_width = draw.textlength(text, font=font)
    except:
        text_width, _ = draw.textsize(text, font=font)

    text_x = (width - text_width) / 2
    text_y = height + (label_height - 28) / 2
    draw.text((text_x, text_y), text, font=font, fill="black")
    return new_img

# ----------------- 產生 ZIP（在按鈕點擊時執行） -----------------
def create_qr_zip_bytes(households_df):
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for _, row in households_df.iterrows():
            if "戶號" not in row or pd.isna(row["戶號"]):
                continue
            hid = str(row["戶號"]).strip()
            vote_url = QR_BASE_URL + hid
            img = generate_qr_with_label(vote_url, hid)
            img_bytes = io.BytesIO()
            img.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            zf.writestr(f"{hid}.png", img_bytes.getvalue())
            # 同時放一個 txt 檔案（選擇性，但常用）
            zf.writestr(f"{hid}.txt", vote_url)
    mem.seek(0)
    return mem

# ----------------- 投票功能（住戶端） -----------------
def vote_page(household_id):
    st.header("🏠 住戶投票")
    st.write(f"您的戶號：**{household_id}**")

    topics_df = load_data_from_db(TOPIC_FILE)
    households_df = load_data_from_db(HOUSEHOLD_FILE)
    if topics_df.empty:
        st.warning("目前尚無議題可投，請聯絡管理員。")
        return

    # 讀取歷史投票
    votes_df = load_data_from_db(VOTE_FILE)
    if votes_df.empty:
        votes_df = pd.DataFrame(columns=["timestamp", "household_id", "topic_id", "topic_name", "vote"])

    # 顯示每個議題的投票狀態與按鈕
    for _, row in topics_df.iterrows():
        tid = row.get("id", str(_ + 1))
        tname = row.get("議題", f"議題 {tid}")
        st.markdown(f"### {tname}")

        # 檢查是否已投票
        already = votes_df[
            (votes_df["household_id"].astype(str) == str(household_id)) &
            (votes_df["topic_id"].astype(str) == str(tid))
        ]
        if not already.empty:
            prev = already.iloc[-1]
            st.info(f"您已投過票：**{prev['vote']}**（時間：{prev['timestamp']}）")
            continue

        cols = st.columns([1,1])
        with cols[0]:
            if st.button(f"👍 同意（{tname}）", key=f"{household_id}_{tid}_yes"):
                # append vote
                new = {
                    "timestamp": get_taipei_time().strftime("%Y-%m-%d %H:%M:%S"),
                    "household_id": household_id,
                    "topic_id": tid,
                    "topic_name": tname,
                    "vote": "同意"
                }
                # append to CSV
                append_vote(new)
                st.success("已記錄：同意")
                st.experimental_rerun()
        with cols[1]:
            if st.button(f"👎 不同意（{tname}）", key=f"{household_id}_{tid}_no"):
                new = {
                    "timestamp": get_taipei_time().strftime("%Y-%m-%d %H:%M:%S"),
                    "household_id": household_id,
                    "topic_id": tid,
                    "topic_name": tname,
                    "vote": "不同意"
                }
                append_vote(new)
                st.success("已記錄：不同意")
                st.experimental_rerun()

# ----------------- 把單筆投票存到 CSV -----------------
def append_vote(record: dict):
    # 若檔案不存在，先建立並寫入 header
    df_new = pd.DataFrame([record])
    if not os.path.exists(VOTE_FILE):
        df_new.to_csv(VOTE_FILE, index=False, encoding="utf-8-sig")
    else:
        df_existing = load_data_from_db(VOTE_FILE)
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined.to_csv(VOTE_FILE, index=False, encoding="utf-8-sig")

# ----------------- 管理員後台 -----------------
def admin_dashboard():
    st.title("🛠️ 管理員後台")

    tab1, tab2, tab3 = st.tabs(["📂 上傳資料", "📋 投票控制", "📊 統計結果"])

    # ---- 上傳資料 ----
    with tab1:
        st.subheader("上傳住戶清單（需包含欄位：戶號、區分比例）")
        household_file = st.file_uploader("上傳住戶 Excel 檔", type=["xlsx"], key="households_uploader")
        if household_file is not None:
            try:
                import openpyxl
                df = pd.read_excel(household_file)
                if "戶號" not in df.columns:
                    st.error("Excel 必須包含「戶號」欄位")
                else:
                    save_households_to_db(df)
                    st.success("✅ 住戶清單上傳成功")
                    st.write(f"已儲存 {len(df)} 筆住戶資料")

                    # 顯示一個按鈕：需要時才生成 ZIP
                    if st.button("📦 產生並下載 戶號 QR Code ZIP（含戶號標籤）"):
                        with st.spinner("正在生成 QR Code 與壓縮檔..."):
                            zip_bytes = create_qr_zip_bytes(df)
                            st.download_button(
                                "⬇️ 下載 QR Code ZIP",
                                data=zip_bytes,
                                file_name="household_qrcodes.zip",
                                mime="application/zip",
                            )
            except ImportError:
                st.error("請安裝 openpyxl：pip install openpyxl")

        st.subheader("上傳議題清單（欄位：議題）")
        topic_file = st.file_uploader("上傳議題 Excel 檔", type=["xlsx"], key="topics_uploader")
        if topic_file is not None:
            try:
                import openpyxl
                df = pd.read_excel(topic_file)
                if "議題" not in df.columns:
                    st.error("Excel 必須包含「議題」欄位")
                else:
                    # 若沒有 id，save_topics_to_db 會自動建立 id
                    save_topics_to_db(df)
                    st.success("✅ 議題清單上傳成功")
                    st.write(f"已儲存 {len(df)} 筆議題")
            except ImportError:
                st.error("請安裝 openpyxl：pip install openpyxl")

    # ---- 投票控制 ----
    with tab2:
        st.subheader("投票開關與截止時間")
        voting_open = load_config('voting_open') == 'True'
        # streamlit 沒有內建 toggle 在所有版本，降級使用 checkbox
        toggle_val = st.checkbox("開啟投票", value=voting_open)
        save_config('voting_open', str(toggle_val))
        st.info("🔄 投票狀態：" + ("✅ 開啟" if toggle_val else "⛔ 關閉"))

        st.divider()
        st.subheader("設定投票截止時間（台北時間）")
        current_end = load_config('end_time')
        if current_end:
            st.write(f"目前截止時間：**{current_end}**（台北）")
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
            st.info(f"系統將設定為：{end_dt.strftime('%Y-%m-%d %H:%M:%S')}（台北時間）")

        if st.button("儲存截止時間"):
            save_config('end_time', end_dt.strftime("%Y-%m-%d %H:%M:%S %z"))
            st.success("✅ 截止時間已儲存")

    # ---- 統計結果 ----
    with tab3:
        st.subheader("投票結果統計（依議題）")
        votes_df = load_data_from_db(VOTE_FILE)
        topics_df = load_data_from_db(TOPIC_FILE)
        households_df = load_data_from_db(HOUSEHOLD_FILE)

        if topics_df.empty:
            st.info("尚未上傳議題。")
            return

        total_voters = len(households_df) if not households_df.empty else 0

        # 計算每個議題的同意/不同意
        for _, row in topics_df.iterrows():
            tid = row.get("id", str(_ + 1))
            tname = row.get("議題", f"議題 {tid}")
            if votes_df.empty:
                agree = 0
                disagree = 0
            else:
                subset = votes_df[votes_df["topic_id"].astype(str) == str(tid)]
                agree = len(subset[subset["vote"] == "同意"])
                disagree = len(subset[subset["vote"] == "不同意"])

            agree_ratio = (agree / total_voters) if total_voters > 0 else 0
            disagree_ratio = (disagree / total_voters) if total_voters > 0 else 0

            st.markdown(f"### 🗳️ {tname}")
            st.write(f"📋 總戶數：{total_voters}")
            st.write(f"🧾 已投票人數：{agree + disagree}")
            st.write(f"👍 同意人數：{agree}，同意比例：{agree_ratio:.4%}")
            st.write(f"👎 不同意人數：{disagree}，不同意比例：{disagree_ratio:.4%}")
            st.divider()

# ----------------- 主流程 -----------------
def main():
    st.set_page_config(page_title="🏠 社區投票系統", layout="wide")
    params = st.experimental_get_query_params()
    vote_param = params.get("vote", [None])[0]

    # 如果有 ?vote=...，直接顯示住戶投票頁（不需登入）
    if vote_param:
        vote_page(vote_param)
        return

    # 否則顯示管理登入與後台
    st.title("🏠 社區投票系統")
    tab_login, tab_admin = st.tabs(["🔐 管理員登入", "📊 管理後台"])

    with tab_login:
        st.subheader("請輸入管理員帳號密碼")
        username = st.text_input("帳號", key="admin_user")
        password = st.text_input("密碼", type="password", key="admin_pw")
        if st.button("登入"):
            if check_login(username, password):
                st.session_state["admin_logged_in"] = True
                st.success("✅ 登入成功！請切換到「管理後台」")
            else:
                st.error("❌ 帳號或密碼錯誤")

    with tab_admin:
        if st.session_state.get("admin_logged_in", False):
            admin_dashboard()
        else:
            st.warning("請先登入管理員帳號")

if __name__ == "__main__":
    main()
