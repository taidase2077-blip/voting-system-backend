import streamlit as st
import pandas as pd
import qrcode
import io
import zipfile
import os
import json
from datetime import datetime
from urllib.parse import urlencode
from pytz import timezone
from streamlit_autorefresh import st_autorefresh

# ===============================
# 初始化設定
# ===============================
st.set_page_config(page_title="社區投票系統🏠", layout="centered")
tz = timezone("Asia/Taipei")

if "votes" not in st.session_state:
    st.session_state.votes = pd.DataFrame(columns=["戶號", "議題", "投票", "時間"])

if "admin_logged_in" not in st.session_state:
    st.session_state.admin_logged_in = False

DATA_FILE = "votes.csv"
ISSUE_FILE = "issues.json"
ADMIN_FILE = "admin_config.json"

# ===============================
# 資料存取函式
# ===============================
def save_votes():
    st.session_state.votes.to_csv(DATA_FILE, index=False, encoding="utf-8-sig")

def load_votes():
    if os.path.exists(DATA_FILE):
        st.session_state.votes = pd.read_csv(DATA_FILE)
    else:
        st.session_state.votes = pd.DataFrame(columns=["戶號", "議題", "投票", "時間"])

def load_issues():
    if os.path.exists(ISSUE_FILE):
        with open(ISSUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def load_admins():
    if os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

# ===============================
# 產生 QR Code 壓縮包
# ===============================
def generate_qrcodes(issues, base_url="https://voting-streamlit-app.onrender.com"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for i in range(1, 11):  # 假設 1~10 戶
            params = {"unit": str(i)}
            url = f"{base_url}?{urlencode(params)}"
            qr = qrcode.make(url)
            img_buffer = io.BytesIO()
            qr.save(img_buffer, format="PNG")
            zipf.writestr(f"{i}.png", img_buffer.getvalue())
    buffer.seek(0)
    return buffer

# ===============================
# 首頁
# ===============================
def home_page():
    st.title("🏠 社區投票系統")
    query_params = st.query_params

    if "unit" not in query_params:
        st.warning("未偵測到戶號參數，請由專屬 QR Code 登入。")
        return

    unit = query_params["unit"]
    issues = load_issues()

    if not issues:
        st.info("目前尚無投票議題。")
        return

    st.header(f"住戶 {unit} 的投票頁面")
    st.divider()

    load_votes()

    for issue in issues:
        st.subheader(issue)
        existing_vote = st.session_state.votes[
            (st.session_state.votes["戶號"] == unit)
            & (st.session_state.votes["議題"] == issue)
        ]

        if not existing_vote.empty:
            vote_choice = existing_vote.iloc[0]["投票"]
            st.success(f"您已投過票：{vote_choice}")
            continue  # 防止重複投票

        col1, col2 = st.columns(2)
        if col1.button("同意", key=f"agree_{issue}"):
            record_vote(unit, issue, "同意")
            st.success("已記錄：同意")
            st.rerun()
        if col2.button("不同意", key=f"disagree_{issue}"):
            record_vote(unit, issue, "不同意")
            st.success("已記錄：不同意")
            st.rerun()

# ===============================
# 投票紀錄函式
# ===============================
def record_vote(unit, issue, vote):
    load_votes()
    if not st.session_state.votes[
        (st.session_state.votes["戶號"] == unit)
        & (st.session_state.votes["議題"] == issue)
    ].empty:
        return  # 已投過票，不再重複紀錄

    new_row = {
        "戶號": unit,
        "議題": issue,
        "投票": vote,
        "時間": datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S"),
    }
    st.session_state.votes = pd.concat(
        [st.session_state.votes, pd.DataFrame([new_row])], ignore_index=True
    )
    save_votes()

# ===============================
# 管理員登入頁面
# ===============================
def admin_login():
    st.title("🔐 管理員登入")
    admins = load_admins()
    username = st.text_input("帳號")
    password = st.text_input("密碼", type="password")

    if st.button("登入"):
        if username in admins and admins[username] == password:
            st.session_state.admin_logged_in = True
            st.rerun()
        else:
            st.error("帳號或密碼錯誤")

# ===============================
# 管理頁面
# ===============================
def admin_page():
    st.title("🛠 管理介面")
    issues = load_issues()
    load_votes()

    # 議題設定
    st.subheader("📝 投票議題設定")
    new_issue = st.text_input("新增議題")
    if st.button("加入議題"):
        if new_issue and new_issue not in issues:
            issues.append(new_issue)
            with open(ISSUE_FILE, "w", encoding="utf-8") as f:
                json.dump(issues, f, ensure_ascii=False, indent=2)
            st.success("已新增議題")
            st.rerun()

    if issues:
        st.write("目前議題：")
        for issue in issues:
            st.write(f"- {issue}")

    # QR Code 生成
    st.subheader("📦 產生戶號 QR Code ZIP")
    if st.button("生成並下載 ZIP"):
        buf = generate_qrcodes(issues)
        st.download_button("點此下載 QR Code 壓縮包", buf, "qrcodes.zip")

    # 統計結果
    st.subheader("📊 投票統計結果")
    if not st.session_state.votes.empty:
        for issue in issues:
            df = st.session_state.votes[st.session_state.votes["議題"] == issue]
            agree = len(df[df["投票"] == "同意"])
            disagree = len(df[df["投票"] == "不同意"])
            total = agree + disagree
            agree_pct = f"{(agree/total*100):.4f}%" if total > 0 else "0.0000%"
            disagree_pct = f"{(disagree/total*100):.4f}%" if total > 0 else "0.0000%"
            st.write(f"**{issue}**：同意 {agree}（{agree_pct}），不同意 {disagree}（{disagree_pct}）")

        st.download_button(
            "下載投票結果 CSV",
            st.session_state.votes.to_csv(index=False, encoding="utf-8-sig"),
            "votes.csv",
        )

    if st.button("登出"):
        st.session_state.admin_logged_in = False
        st.rerun()

# ===============================
# 主程式流程
# ===============================
def main():
    query_params = st.query_params
    if "admin" in query_params:
        if not st.session_state.admin_logged_in:
            admin_login()
        else:
            admin_page()
    else:
        home_page()

if __name__ == "__main__":
    main()
