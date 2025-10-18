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
from sqlalchemy.dialects import postgresql as pg_types 
from contextlib import contextmanager

# ===============================
# 初始化設定
# ===============================
ADMIN_FILE = "admin_config.json"

# 從 Render 環境變數中獲取資料庫連線 URL
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
            conn.rollback()
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
                    區分比例 NUMERIC(10, 4) 
                );
            """))
            # 2. 議題清單 (topics)
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS topics (
                    id SERIAL PRIMARY KEY,
                    議題 TEXT,               
                    is_active BOOLEAN DEFAULT TRUE
                );
            """))
            # 3. 投票記錄 (votes)
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
        df = pd.read_sql(f"SELECT * FROM {table_name}", engine)
        return df
    except Exception as e:
        return pd.DataFrame() 

def save_households_to_db(df):
    """將 DataFrame (住戶清單) 寫入 households 表格"""
    required_cols = ['戶號', '區分比例']
    if not all(col in df.columns for col in required_cols):
        return False
        
    try:
        df_to_save = df[required_cols].copy()
        df_to_save.to_sql('households', engine, if_exists='replace', index=False, 
                  dtype={'戶號': pg_types.VARCHAR(50), 
                         '區分比例': pg_types.NUMERIC(10, 4)}) 
        return True
    except Exception as e:
        st.error(f"寫入住戶清單到資料庫失敗: {e}")
        return False

def save_topics_to_db(df):
    """將 DataFrame (議題清單) 寫入 topics 表格"""
    try:
        if '議題' not in df.columns:
            st.error("議題清單檔案必須包含 '議題' 欄位。")
            return False
            
        df_to_save = df[['議題']].copy()
        df_to_save['is_active'] = True 
        
        df_to_save.to_sql('topics', engine, if_exists='replace', index=False, 
                  dtype={'議題': pg_types.TEXT(), 
                         'is_active': pg_types.BOOLEAN()})
        return True
    except Exception as e:
        st.error(f"寫入議題清單到資料庫失敗: {e}")
        return False

def record_vote_to_db(unit_id, topic_id, vote_result, vote_time):
    """記錄一筆投票到 votes 表格 (使用 UPSERT 處理重複投票)"""
    try:
        with get_db_connection() as conn:
            conn.execute(text("""
                INSERT INTO votes (戶號, topic_id, 投票結果, 投票時間) 
                VALUES (:unit, :topic, :result, :time)
                ON CONFLICT (戶號, topic_id) DO UPDATE SET
                    投票結果 = EXCLUDED.投票結果,
                    投票時間 = EXCLUDED.投票時間;
            """), {"unit": unit_id, "topic": topic_id, "result": vote_result, "time": vote_time})
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
# 工具函式 (QR Code 最終版本 - 移除圖片上的文字，但保留 ZIP 壓縮)
# ===============================
def generate_qr_zip(households_df, base_url):
    """生成 QR Code ZIP，但不包含圖片上的文字繪製"""
    if households_df.empty:
        st.warning("尚未上傳住戶清單，無法產生 QR Code。")
        return None

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED) as zf:
        for _, row in households_df.iterrows():
            if '戶號' not in row:
                st.error("住戶清單檔案必須包含 '戶號' 欄位。")
                return None
            
            house_id = str(row["戶號"]).strip()
            if not base_url.startswith('http'):
                 st.error("基本網址必須包含 http:// 或 https://")
                 return None
                 
            qr_link = f"{base_url}?unit={house_id}"

            # *** 核心修正：只生成 QR Code 圖片，不進行任何繪圖操作 ***
            qr_img = qrcode.make(qr_link).convert("RGB")
            new_img = qr_img # 直接使用 QR code 圖片
            # *** 修正結束 ***
            
            img_bytes = io.BytesIO()
            new_img.save(img_bytes, format="PNG") 
            
            img_bytes.seek(0)
            # 檔案名包含戶號，確保列印後仍可識別
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

    if not unit:
        st.warning("未偵測到戶號參數，請由專屬 QR Code 登入。")
        return

    st.info(f"目前登入戶號：{unit}")
    
    households_df = load_data_from_db('households')
    if households_df.empty or unit not in households_df['戶號'].values:
        st.error("無效的戶號，請聯繫管理員。")
        return

    voting_open_str = load_config('voting_open')
    voting_open = voting_open_str == 'True' if voting_open_str else False
    
    if not voting_open:
        st.warning("投票尚未開始或已截止。")
        return
        
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
            pass 

    topics_df = load_data_from_db('topics')
    active_topics = topics_df[topics_df['is_active'] == True]
    
    if active_topics.empty:
        st.info("目前沒有任何開放的投票議題。")
        return
        
    st.header("進行投票")
    
    votes_df = load_data_from_db('votes')
    voted_topic_ids = votes_df[votes_df['戶號'] == unit]['topic_id'].tolist()
    
    
    for _, topic_row in active_topics.iterrows():
        topic_id = topic_row['id']
        topic_content = topic_row['議題']
        
        st.markdown(f"### 議題 {topic_id}: {topic_content}")
        
        if topic_id in voted_topic_ids:
            st.success("✅ 您已針對此議題完成投票。")
        else:
            vote_key = f"vote_{topic_id}"
            vote_option = st.radio("請選擇您的投票結果：", ("同意", "不同意"), key=vote_key, horizontal=True)
            
            if st.button(f"提交對議題 {topic_id} 的投票", key=f"submit_{topic_id}"):
                if record_vote_to_db(unit, topic_id, vote_option, get_taipei_time()):
                    st.success(f"投票成功！您選擇了：{vote_option}")
                    st.rerun() 

# ===============================
# 管理員登入 (保持不變)
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
    st.subheader("上傳住戶清單 (必須包含 '戶號' 及 '區分比例' 欄位)") 
    uploaded_households = st.file_uploader("選擇 households.csv", type=["csv"], key="upload_households")
    if uploaded_households:
        try:
            df = pd.read_csv(uploaded_households)
            required_cols = ['戶號', '區分比例']
            if not all(col in df.columns for col in required_cols):
                 st.error(f"檔案必須包含 {required_cols} 欄位，請檢查您的 CSV。")
            elif save_households_to_db(df): 
                st.success("✅ 住戶清單已上傳並覆蓋資料庫中的舊資料。")
            else:
                st.error("寫入資料庫失敗，請檢查連線、欄位名稱或資料類型。")
        except Exception as e:
            st.error(f"讀取或處理檔案失敗: {e}")
            
    # 3️⃣ 上傳議題清單
    st.subheader("上傳議題清單 (必須包含 '議題' 欄位)")
    st.warning("上傳新議題清單會覆蓋所有舊議題，請謹慎操作。")
    uploaded_topics = st.file_uploader("選擇 topics.csv", type=["csv"], key="upload_topics")
    if uploaded_topics:
        try:
            df = pd.read_csv(uploaded_topics)
            if save_topics_to_db(df): 
                st.success("✅ 議題清單已上傳並覆蓋資料庫中的舊議題。")
            else:
                pass
        except Exception as e:
            st.error(f"讀取或處理議題檔案失敗: {e}")


    # 4️⃣ 住戶 QR Code 產生
    st.subheader("住戶 QR Code 投票連結")
    # *** 修正 base_url 預設值 ***
    base_url = st.text_input("投票網站基本網址（例如：https://voting-streamlit-app.onrender.com）", "https://voting-streamlit-app.onrender.com")

    if st.button("📦 產生 QR Code ZIP"):
        households_df = load_data_from_db('households') 
        if not households_df.empty:
            qr_zip_data = generate_qr_zip(households_df, base_url)
            if qr_zip_data:
                st.session_state["qr_zip_data"] = qr_zip_data.getvalue()
                st.success("✅ QR Code ZIP 產生完成！")
                st.rerun() # 重新運行以顯示下載按鈕
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
        # 這裡不刪除，讓使用者可以再次下載
        # del st.session_state["qr_zip_data"] 
        
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
    topics_df = load_data_from_db('topics')

    if households_df.empty:
        st.info("請先上傳住戶清單。")
        return

    total_households = len(households_df)
    st.metric("🏠 總戶數", total_households)
    st.markdown("---")
    
    if votes_df.empty or topics_df.empty:
         st.info("目前尚無投票資料或議題。")
         return
         
    for _, topic_row in topics_df.iterrows():
        topic_id = topic_row['id']
        topic_content = topic_row['議題']
        
        st.markdown(f"#### 議題 {topic_id}: {topic_content}")
        
        topic_votes = votes_df[votes_df['topic_id'] == topic_id]
        
        voted_households = topic_votes["戶號"].nunique()
        remaining = total_households - voted_households
        
        agree = (topic_votes["投票結果"] == "同意").sum()
        disagree = (topic_votes["投票結果"] == "不同意").sum()
        total_votes = agree + disagree
        
        col_res_1, col_res_2, col_res_3 = st.columns(3)
        col_res_1.metric("🗳 已投票戶數", voted_households)
        col_res_2.metric("⏳ 剩餘可投票戶數", remaining)
        col_res_3.metric("總投票數", total_votes)
        
        if total_votes > 0:
            agree_ratio = agree / total_votes * 100
            disagree_ratio = disagree / total_votes * 100
            
            col_met_1, col_met_2 = st.columns(2)
            col_met_1.metric("✅ 同意票數", f"{agree} 戶", delta=f"{agree_ratio:.2f}%")
            col_met_2.metric("❌ 不同意票數", f"{disagree} 戶", delta=f"{disagree_ratio:.2f}%")
        else:
             st.info("此議題尚未收到投票。")
        st.markdown("***")


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
