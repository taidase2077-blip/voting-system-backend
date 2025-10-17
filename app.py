import streamlit as st

# ⚠️ 必須放在第一個 Streamlit 指令
st.set_page_config(page_title="社區投票系統", layout="wide")

import pandas as pd
import qrcode
import io
import zipfile
import json
import os
from datetime import datetime, timedelta
from pytz import timezone
from streamlit_autorefresh import st_autorefresh
from PIL import Image, ImageDraw, ImageFont

# 引入資料庫相關套件
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from contextlib import contextmanager

# ===============================
# 初始化設定
# ===============================
ADMIN_FILE = "admin_config.json"

# 從 Render 環境變數中獲取資料庫連線 URL
# 格式應為 postgresql://user:password@host/database
DATABASE_URL = os.environ.get("DATABASE_URL")

# 全域資料庫引擎初始化
try:
    if not DATABASE_URL:
        st.error("環境變數 'DATABASE_URL' 缺失。請在 Render 上設定此變數。")
        st.stop()
    engine = create_engine(DATABASE_URL)
except Exception as e:
    st.error(f"無法建立資料庫連線引擎，請檢查 DATABASE_URL: {e}")
    st.stop()

# ===============================
# 工具函式：資料庫操作與連線管理
# ===============================

@contextmanager
def get_db_connection():
    """提供一個上下文管理器來安全地處理資料庫連線"""
    conn = None
    try:
        conn = engine.connect()
        yield conn
    except SQLAlchemyError as e:
        st.error(f"資料庫操作失敗: {e}")
        if conn:
            conn.rollback() # 如果發生錯誤，嘗試回滾
    finally:
        if conn:
            conn.close()

def init_db_tables():
    """初始化資料庫表格（如果不存在），在服務啟動時運行"""
    try:
        with get_db_connection() as conn:
            # 1. 住戶清單 (households)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS households (
                    戶號 VARCHAR(50) PRIMARY KEY,
                    備註 VARCHAR(255)
                );
            """))
            # 2. 議題清單 (topics) - 簡化為只有一個議題
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS topics (
                    id SERIAL PRIMARY KEY,
                    topic_title TEXT DEFAULT '社區年度決議事項',
                    is_active BOOLEAN DEFAULT TRUE
                );
            """))
            # 3. 投票記錄 (votes) - 記錄每一戶的投票
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS votes (
                    id SERIAL PRIMARY KEY,
                    戶號 VARCHAR(50) UNIQUE,
                    投票結果 VARCHAR(10), -- '同意' 或 '不同意'
                    投票時間 TIMESTAMP WITH TIME ZONE
                );
            """))
            # 4. 投票截止時間 (config)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS config (
                    key VARCHAR(50) PRIMARY KEY,
                    value TEXT
                );
            """))
            conn.commit()
    except Exception as e:
        st.error(f"資料庫表格初始化失敗: {e}")

# 服務啟動時，自動執行表格檢查與建立
init_db_tables()


def load_data_from_db(table_name):
    """從資料庫讀取資料並轉換為 DataFrame"""
    try:
        # 使用 pandas 內建的 read_sql 函式
        df = pd.read_sql(f"SELECT * FROM {table_name}", engine)
        return df
    except Exception as e:
        # st.error(f"讀取資料庫表格 {table_name} 失敗: {e}")
        return pd.DataFrame() # 返回空 DataFrame 以避免崩潰

def save_households_to_db(df):
    """將 DataFrame (住戶清單) 寫入 households 表格"""
    try:
        # 使用 if_exists='replace' 覆蓋舊資料，這很適合上傳新的住戶清單
        df.to_sql('households', engine, if_exists='replace', index=False, dtype={'戶號': 'VARCHAR(50)', '備註': 'VARCHAR(255)'})
        return True
    except Exception as e:
        st.error(f"寫入住戶清單到資料庫失敗: {e}")
        return False

def record_vote_to_db(unit_id, vote_result, vote_time):
    """記錄一筆投票到 votes 表格 (使用 UPSERT 處理重複投票)"""
    try:
        with get_db_connection() as conn:
            # 使用 ON CONFLICT (戶號) DO UPDATE 來實現「一人一票」
            conn.execute(text("""
                INSERT INTO votes (戶號, 投票結果, 投票時間) 
                VALUES (:unit, :result, :time)
                ON CONFLICT (戶號) DO UPDATE SET
                    投票結果 = EXCLUDED.投票結果,
                    投票時間 = EXCLUDED.投票時間;
            """), {"unit": unit_id, "result": vote_result, "time": vote_time})
            conn.commit()
        return True
    except Exception as e:
        st.error(f"記錄投票失敗: {e}")
        return False
        
def load_config(key):
    """讀取配置 (如截止時間)"""
    try:
        with get_db_connection() as conn:
            result = conn.execute(text("SELECT value FROM config WHERE key = :key"), {"key": key}).scalar_one_or_none()
        return result
    except Exception:
        return None

def save_config(key, value):
    """儲存配置 (如截止時間)"""
    try:
        with get_db_connection() as conn:
            conn.execute(text("""
                INSERT INTO config (key, value) VALUES (:key, :value)
                ON CONFLICT (key) DO UPDATE SET value = :value;
            """), {"key": key, "value": value})
            conn.commit()
        return True
    except Exception as e:
        st.error(f"儲存配置失敗: {e}")
        return False


def get_taipei_time():
    return datetime.now(timezone("Asia/Taipei"))

# ===============================
# 工具函式 (QR Code 仍保留，但檔案 I/O 已移除)
# ===============================
def generate_qr_zip(households_df, base_url):
    """產生含戶號文字的 QR Code ZIP（戶號顯示於上方）"""
    if households_df.empty:
        st.warning("尚未上傳住戶清單，無法產生 QR Code。")
        return None

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zf:
        for _, row in households_df.iterrows():
            # 確保 '戶號' 欄位存在
            if '戶號' not in row:
                st.error("住戶清單檔案必須包含 '戶號' 欄位。")
                return None
            
            house_id = str(row["戶號"]).strip()
            # 確保 QR Code 連結格式正確
            if not base_url.startswith('http'):
                 st.error("基本網址必須包含 http:// 或 https://")
                 return None
                 
            qr_link = f"{base_url}?unit={house_id}"

            # 產生 QR Code 圖片邏輯 (保持不變)
            qr_img = qrcode.make(qr_link).convert("RGB")
            w, h = qr_img.size

            new_h = h + 50
            new_img = Image.new("RGB", (w, new_h), "white")

            draw = ImageDraw.Draw(new_img)
            # 使用 Streamlit 環境中預設可用的字體
            try:
                font = ImageFont.truetype("Arial.ttf", 28)
            except:
                font = ImageFont.load_default()

            text_w, text_h = draw.textsize(house_id, font=font)
            draw.text(
                ((w - text_w) / 2, (50 - text_h) / 2),
                house_id,
                font=font,
                fill="black"
            )

            new_img.paste(qr_img, (0, 50))
            
            img_bytes = io.BytesIO()
            new_img.save(img_bytes, format="PNG")
            img_bytes.seek(0)
            zf.writestr(f"{house_id}.png", img_bytes.read())

    zip_buffer.seek(0)
    return zip_buffer


# ===============================
# 首頁 (Voter Page)
# ===============================
def voter_page():
    st.title("🏠 社區投票系統")
    params = st.query_params
    unit = params.get("unit", [None])[0] if isinstance(params.get("unit"), list) else params.get("unit")

    # 1. 檢查是否偵測到戶號
    if not unit:
        st.warning("未偵測到戶號參數，請由專屬 QR Code 登入。")
        return

    st.info(f"目前登入戶號：{unit}")
    
    # 2. 檢查該戶號是否存在
    households_df = load_data_from_db('households')
    if households_df.empty or unit not in households_df['戶號'].values:
        st.error("無效的戶號，請聯繫管理員。")
        return

    # 3. 檢查投票是否開放
    # 這裡的 st.session_state.voting_open 應該從 config 表中讀取實際的投票狀態
    voting_open_str = load_config('voting_open')
    voting_open = voting_open_str == 'True' if voting_open_str else False
    
    if not voting_open:
        st.warning("投票尚未開始或已截止。")
        return
        
    # 4. 檢查是否已過截止時間
    end_time_str = load_config('end_time')
    if end_time_str:
        try:
            end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M:%S %z").astimezone(timezone("Asia/Taipei"))
            now = get_taipei_time()
            if now > end_time:
                st.error(f"投票已於 {end_time.strftime('%Y-%m-%d %H:%M:%S')} 截止。")
                return
            else:
                st.write(f"🗳️ 投票將於 **{end_time.strftime('%Y-%m-%d %H:%M:%S')}** 截止。")
        except:
            pass # 忽略錯誤，繼續

    # 5. 檢查是否已投過票
    votes_df = load_data_from_db('votes')
    if unit in votes_df['戶號'].values:
        st.success("您已完成投票。感謝您的參與！")
        return
        
    # 6. 投票介面
    st.header("您是否同意社區年度決議事項？")
    vote_option = st.radio("請選擇您的投票結果：", ("同意", "不同意"), key="user_vote")
    
    if st.button("提交投票"):
        if record_vote_to_db(unit, vote_option, get_taipei_time()):
            st.success(f"投票成功！您選擇了：{vote_option}")
            st.rerun() # 重新運行頁面，顯示已投票狀態

# ===============================
# 管理員登入
# (此部分保持不變，仍依賴 admin_config.json 檔案)
# ===============================
def admin_login():
    st.header("🔐 管理員登入")

    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False

    username = st.text_input("帳號")
    password = st.text_input("密碼", type="password")

    if st.button("登入"):
        if not os.path.exists(ADMIN_FILE):
            st.error("找不到 admin_config.json，請確認檔案存在。")
            return

        try:
            with open(ADMIN_FILE, "r", encoding="utf-8") as f:
                admin_data = json.load(f)
        except Exception as e:
            st.error(f"讀取 admin_config.json 失敗：{e}")
            return

        # 這裡不使用 hash，請確保 admin_config.json 的密碼安全
        if username in admin_data and password == str(admin_data[username]):
            st.session_state.is_admin = True
            st.session_state.admin_user = username
            st.success(f"登入成功！歡迎管理員 {username}")
            st.rerun()
        else:
            st.error("帳號或密碼錯誤。")

# ===============================
# 管理後台
# ===============================
def admin_dashboard():
    st.title("🧩 管理後台")

    # 1️⃣ 投票控制
    st.subheader("投票控制")
    # 從資料庫讀取當前狀態
    voting_open = load_config('voting_open') == 'True'
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🟢 開啟投票"):
            save_config('voting_open', 'True')
            st.success("投票已開啟！")
            st.rerun()
    with col2:
        if st.button("🔴 停止投票"):
            save_config('voting_open', 'False')
            st.warning("投票已停止。")
            st.rerun()

    st.write(f"目前狀態：{'✅ 開放中' if voting_open else '⛔ 已停止'}")

    # 2️⃣ 上傳住戶清單
    st.subheader("上傳住戶清單 (必須包含 '戶號' 欄位)")
    uploaded_households = st.file_uploader("選擇 households.csv", type=["csv"], key="upload_households")
    if uploaded_households:
        try:
            df = pd.read_csv(uploaded_households)
            if '戶號' not in df.columns:
                 st.error("檔案必須包含 '戶號' 欄位，請檢查您的 CSV。")
            elif save_households_to_db(df): # 使用新的 DB 寫入函式
                st.success("✅ 住戶清單已上傳並覆蓋資料庫中的舊資料。")
            else:
                st.error("寫入資料庫失敗，請檢查連線或檔案格式。")
        except Exception as e:
            st.error(f"讀取或處理檔案失敗: {e}")

    # 3️⃣ 議題清單 (簡化處理，不再需要單獨上傳 topics.csv)
    st.subheader("議題清單")
    st.info("此系統目前簡化為單一議題：『您是否同意社區年度決議事項？』")

    # 4️⃣ 住戶 QR Code 產生
    st.subheader("住戶 QR Code 投票連結")
    base_url = st.text_input("投票網站基本網址（例如：https://smartvoteapp.onrender.com）", "https://your-render-url.onrender.com")

    if st.button("📦 產生 QR Code ZIP"):
        households_df = load_data_from_db('households') # 從 DB 讀取住戶清單
        if not households_df.empty:
            qr_zip_data = generate_qr_zip(households_df, base_url)
            if qr_zip_data:
                st.session_state["qr_zip_data"] = qr_zip_data.getvalue()
                st.success("✅ QR Code ZIP 產生完成！")
            else:
                 st.error("QR Code 產生失敗，請檢查基本網址或戶號格式。")
        else:
            st.error("請先上傳住戶清單。")

    if "qr_zip_data" in st.session_state:
        st.download_button(
            label="📥 下載 QR Code ZIP",
            data=st.session_state["qr_zip_data"],
            file_name="QR_Codes.zip",
            mime="application/zip"
        )
        del st.session_state["qr_zip_data"] # 下載後清除

    # 5️⃣ 設定投票截止時間
    st.subheader("設定投票截止時間")
    now = get_taipei_time()
    option = st.selectbox("選擇截止時間（以目前時間為基準）", [5, 10, 15, 20, 25, 30], format_func=lambda x: f"{x} 分鐘後")
    end_time = now + timedelta(minutes=option)

    if st.button("儲存截止時間"):
        end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S %z")
        if save_config('end_time', end_time_str):
            st.success(f"截止時間已設定為 {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
    # 6️⃣ 投票結果統計
    st.subheader("📈 投票結果統計（每 10 秒自動更新）")
    st_autorefresh(interval=10 * 1000, key="refresh_votes")

    votes_df = load_data_from_db('votes')
    households_df = load_data_from_db('households')

    if not votes_df.empty and not households_df.empty:
        total_households = len(households_df)
        voted_households = votes_df["戶號"].nunique()
        remaining = total_households - voted_households

        # 這裡使用 voted_households 作為基礎，因為不是每一戶都會投票
        agree = (votes_df["投票結果"] == "同意").sum()
        disagree = (votes_df["投票結果"] == "不同意").sum()
        total_votes = agree + disagree

        col_ratio_1, col_ratio_2, col_ratio_3 = st.columns(3)
        col_ratio_1.metric("🏠 總戶數", total_households)
        col_ratio_2.metric("🗳 已投票戶數", voted_households)
        col_ratio_3.metric("⏳ 剩餘可投票戶數", remaining)

        st.markdown("---")
        
        # 僅計算已投票戶數中的比例
        agree_ratio = agree / total_votes * 100 if total_votes > 0 else 0
        disagree_ratio = disagree / total_votes * 100 if total_votes > 0 else 0
        
        col_res_1, col_res_2 = st.columns(2)
        col_res_1.metric("✅ 同意票數", f"{agree} 戶", delta=f"{agree_ratio:.2f}%")
        col_res_2.metric("❌ 不同意票數", f"{disagree} 戶", delta=f"{disagree_ratio:.2f}%")
        
    else:
        st.info("目前尚無投票資料或未上傳住戶清單。請先上傳住戶清單。")

# ===============================
# 主邏輯
# ===============================
def main():
    st.sidebar.title("功能選單")
    menu = st.sidebar.radio("請選擇：", ["🏠 首頁", "🔐 管理員登入", "📋 管理後台"])

    if menu == "🏠 首頁":
        voter_page()
    elif menu == "🔐 管理員登入":
        admin_login()
    elif menu == "📋 管理後台":
        if st.session_state.get("is_admin", False):
            admin_dashboard()
        else:
            st.warning("請先登入管理員帳號。")

if __name__ == "__main__":
    main()
