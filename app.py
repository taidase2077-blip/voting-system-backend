
import streamlit as st
import pandas as pd
import json, os, io
from datetime import datetime
from pytz import timezone
import matplotlib.pyplot as plt
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "db")
os.makedirs(DB, exist_ok=True)

VOTES = os.path.join(DB, "votes.csv")
TOPICS = os.path.join(DB, "topics.csv")
ADMIN = os.path.join(BASE_DIR, "admin_config.json")

def now():
    return datetime.now(timezone("Asia/Taipei")).strftime("%Y-%m-%d %H:%M:%S")

def load_csv(path, cols):
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    return pd.read_csv(path)

def save_vote(house, topic, choice):
    df = load_csv(VOTES, ["戶號","議題","選項","時間"])
    if not df[(df["戶號"]==house)&(df["議題"]==topic)].empty:
        return False
    df.loc[len(df)] = [house, topic, choice, now()]
    df.to_csv(VOTES, index=False, encoding="utf-8-sig")
    return True

def voting_page(house):
    st.title("住戶投票")
    topics = load_csv(TOPICS, ["議題","選項"])
    votes = load_csv(VOTES, ["戶號","議題","選項","時間"])
    for _, r in topics.iterrows():
        topic = r["議題"]
        options = json.loads(r["選項"])
        st.subheader(topic)
        if not votes[(votes["戶號"]==house)&(votes["議題"]==topic)].empty:
            st.success("已投票")
            continue
        choice = st.multiselect("選擇（可複選）", options, key=topic)
        if st.button("送出", key=topic+"_btn"):
            if choice:
                save_vote(house, topic, ",".join(choice))
                st.rerun()

def export_excel():
    df = load_csv(VOTES, ["戶號","議題","選項","時間"])
    wb = Workbook()
    ws = wb.active
    ws.title = "投票結果"
    headers = ["戶號","議題","選項","時間"]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(horizontal="center")
    for _, r in df.iterrows():
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

def admin_page():
    st.title("管理後台")
    tabs = st.tabs(["議題設定","統計","匯出"])
    with tabs[0]:
        st.info("議題 CSV 欄位：議題 / 選項(JSON陣列)")
        df = load_csv(TOPICS, ["議題","選項"])
        new = st.data_editor(df, num_rows="dynamic")
        if st.button("儲存"):
            new.to_csv(TOPICS, index=False, encoding="utf-8-sig")
            st.success("已儲存")
    with tabs[1]:
        df = load_csv(VOTES, ["戶號","議題","選項","時間"])
        if df.empty:
            st.info("尚無資料")
        else:
            for topic in df["議題"].unique():
                st.subheader(topic)
                counts = df[df["議題"]==topic]["選項"].str.split(",").explode().value_counts()
                fig, ax = plt.subplots()
                counts.plot(kind="bar", ax=ax)
                st.pyplot(fig)
    with tabs[2]:
        st.download_button("下載 Excel", export_excel(), "committee_report.xlsx")

def main():
    st.set_page_config(layout="wide")
    q = st.query_params
    if "vote" in q:
        voting_page(q["vote"])
    else:
        admin_page()

if __name__ == "__main__":
    main()
