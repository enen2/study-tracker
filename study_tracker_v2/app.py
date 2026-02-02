import datetime as dt
from pathlib import Path
import pandas as pd
import yaml
import streamlit as st
import matplotlib.pyplot as plt

import feedparser
import requests

BASE = Path(__file__).resolve().parent
PLAN_PATH = BASE / "plan.yaml"
PROGRESS_PATH = BASE / "progress.csv"
MILESTONES_PATH = BASE / "milestones.csv"
REFLECTIONS_PATH = BASE / "reflections.csv"
FEEDS_PATH = BASE / "feeds.yaml"

def load_yaml(path: Path, default=None):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_progress():
    if PROGRESS_PATH.exists():
        df = pd.read_csv(PROGRESS_PATH)
        if len(df) == 0:
            return df
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df
    return pd.DataFrame(columns=["date","module","minutes","note"])

def save_progress(df: pd.DataFrame):
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.date.astype(str)
    out.to_csv(PROGRESS_PATH, index=False)

def load_milestones():
    if MILESTONES_PATH.exists():
        return pd.read_csv(MILESTONES_PATH)
    return pd.DataFrame(columns=["week","done_date","note"])

def save_milestones(df: pd.DataFrame):
    df.to_csv(MILESTONES_PATH, index=False)

def load_reflections():
    if REFLECTIONS_PATH.exists():
        df = pd.read_csv(REFLECTIONS_PATH)
        if len(df) == 0:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        return df
    return pd.DataFrame(columns=["timestamp","date","topic","mood","text","tags"])

def save_reflections(df: pd.DataFrame):
    df.to_csv(REFLECTIONS_PATH, index=False)

def planned_minutes_per_day(plan):
    modules = plan["meta"]["modules"]
    return {m: int(modules[m]["planned_minutes_per_day"]) for m in modules}

def cumulative_planned(plan, start_date, end_date):
    p = planned_minutes_per_day(plan)
    days = (end_date - start_date).days + 1
    totals = {m: p[m] * days for m in p}
    totals["total"] = sum(totals.values())
    return totals

def cumulative_actual(df, start_date, end_date):
    if len(df) == 0:
        return {"total": 0}
    mask = (df["date"] >= start_date) & (df["date"] <= end_date)
    sub = df.loc[mask]
    totals = sub.groupby("module")["minutes"].sum().to_dict()
    totals["total"] = int(sub["minutes"].sum()) if len(sub) else 0
    return totals

def week_index(plan, today):
    start = dt.date.fromisoformat(plan["meta"]["start_date"])
    delta_days = (today - start).days
    if delta_days < 0:
        return 0
    return delta_days // 7 + 1

@st.cache_data(ttl=3600)
def fetch_rss(url: str, max_items: int = 10, timeout: int = 8):
    headers = {"User-Agent": "study-tracker/1.0 (+streamlit)"}
    try:
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        parsed = feedparser.parse(r.text)
        items = []
        for e in parsed.entries[:max_items]:
            title = getattr(e, "title", "").strip()
            link = getattr(e, "link", "").strip()
            published = getattr(e, "published", "") or getattr(e, "updated", "")
            items.append({"title": title, "link": link, "published": published})
        return items, None
    except Exception as ex:
        return [], str(ex)

def render_week_plan(wk: dict):
    focus = wk.get("focus", [])
    deliverable = wk.get("deliverable", "")
    daily = wk.get("daily_tasks", {})
    resources = wk.get("resources", [])

    st.markdown("### 🎯 Focus")
    for f in focus:
        st.markdown(f"- {f}")

    st.markdown("### 🧩 Deliverable")
    st.info(deliverable)

    st.markdown("### 📅 Daily tasks (清单)")
    order = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    rows = []
    for d in order:
        if d in daily:
            rows.append({"Day": d, "Task": daily[d]})
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.write("No daily tasks found for this week.")

    st.markdown("### 🔗 Resources")
    for r in resources:
        name = r.get("name","(resource)")
        url = r.get("url","")
        if url:
            st.markdown(f"- [{name}]({url})")
        else:
            st.markdown(f"- {name}")

st.set_page_config(page_title="Study Tracker", layout="wide")
plan = load_yaml(PLAN_PATH)
feeds = load_yaml(FEEDS_PATH, default={"sections": [], "fetch": {"max_items_per_feed": 10, "timeout_seconds": 8}})
df = load_progress()
ms = load_milestones()
rf = load_reflections()

start_date = dt.date.fromisoformat(plan["meta"]["start_date"])
today = dt.date.today()
current_week = week_index(plan, today)
weeks = plan.get("weeks", [])

st.title("📚 Study Tracker (Plan + Daily Logs)")
tab1, tab2, tab3 = st.tabs(["✅ 日常记录", "🗺️ 课表/进度", "🧠 研究雷达 + 反思"])

with tab1:
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("✅ Log today's study")
        log_date = st.date_input("Date", value=today, key="log_date")
        module_names = list(plan["meta"]["modules"].keys())
        default_mod = "stats" if "stats" in module_names else module_names[0]
        module = st.selectbox("Module", module_names, index=module_names.index(default_mod), key="module")
        minutes = st.slider("Minutes", min_value=5, max_value=240, value=30, step=5, key="minutes")
        note = st.text_input("Note (optional)", value="", key="note")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Add log", use_container_width=True):
                new = pd.DataFrame([{"date": log_date, "module": module, "minutes": minutes, "note": note}])
                df2 = pd.concat([df, new], ignore_index=True)
                save_progress(df2)
                st.success("Saved ✅  (progress.csv updated)")
                st.rerun()
        with c2:
            if st.button("Quick add (planned today)", use_container_width=True):
                p = planned_minutes_per_day(plan)
                rows = [{"date": log_date, "module": m, "minutes": int(mins), "note": "planned"} for m, mins in p.items() if mins > 0]
                df2 = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
                save_progress(df2)
                st.success("Added planned minutes ✅")
                st.rerun()

        st.markdown("---")
        st.subheader("🏁 Weekly deliverable")
        st.write(f"Current week: **Week {current_week}**")
        done = st.checkbox("I completed this week's deliverable", key="deliverable_done")
        done_note = st.text_input("Deliverable note (optional)", value="", key="deliverable_note")
        if st.button("Save deliverable status", key="save_deliv"):
            if done:
                ms2 = ms.copy()
                ms2 = ms2[ms2["week"] != current_week]
                ms2 = pd.concat([ms2, pd.DataFrame([{"week": current_week, "done_date": str(log_date), "note": done_note}])], ignore_index=True)
                save_milestones(ms2)
                st.success("Deliverable marked done ✅")
            else:
                st.info("Unchecked — no changes made.")

    with right:
        st.subheader("🗺️ This week's plan (清单式)")
        wk = next((w for w in weeks if w.get("week") == current_week), None)
        if wk is None:
            st.info("Week not found in plan.yaml. Edit plan.yaml to add more weeks.")
        else:
            render_week_plan(wk)

with tab2:
    st.subheader("📈 Are you on track?")
    planned_day = planned_minutes_per_day(plan)
    planned_total = cumulative_planned(plan, start_date, today)
    actual_total = cumulative_actual(df, start_date, today)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Planned minutes (cum.)", f"{planned_total['total']}")
    col2.metric("Actual minutes (cum.)", f"{actual_total.get('total', 0)}")
    delta = actual_total.get("total", 0) - planned_total["total"]
    col3.metric("Ahead / Behind", f"{delta}", delta=f"{delta}")
    col4.metric("Current week", f"{current_week}")

    st.markdown("### Daily total minutes")
    if len(df) == 0:
        st.info("No logs yet. Add a log in the first tab.")
    else:
        tmp = df.copy()
        tmp["date"] = pd.to_datetime(tmp["date"])
        daily = tmp.groupby(tmp["date"].dt.date)["minutes"].sum().reset_index().sort_values("date")
        planned_per_day = sum(planned_day.values())
        daily["planned"] = planned_per_day

        fig = plt.figure()
        plt.plot(daily["date"], daily["minutes"], label="actual")
        plt.plot(daily["date"], daily["planned"], label="planned")
        plt.xticks(rotation=45, ha="right")
        plt.ylabel("minutes")
        plt.legend()
        st.pyplot(fig, clear_figure=True)

    st.markdown("### Module breakdown (cumulative)")
    rows = []
    for m in planned_day.keys():
        rows.append({"module": m, "planned": planned_total.get(m, 0), "actual": actual_total.get(m, 0), "ahead_behind": actual_total.get(m, 0) - planned_total.get(m, 0)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("🧾 Logs (latest first)")
    if len(df) == 0:
        st.write("No logs yet.")
    else:
        st.dataframe(df.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

with tab3:
    left, right = st.columns([1.2, 0.8], gap="large")
    with left:
        st.subheader("🧠 Research Radar (最新进展)")
        st.caption("RSS需要联网；源列表可在 feeds.yaml 里增删。")
        max_items = int(feeds.get("fetch", {}).get("max_items_per_feed", 10))
        timeout = int(feeds.get("fetch", {}).get("timeout_seconds", 8))

        for sec in feeds.get("sections", []):
            with st.expander(f"📌 {sec.get('name','Section')}", expanded=False):
                st.write(sec.get("description",""))
                for item in sec.get("items", []):
                    title = item.get("title","source")
                    url = item.get("url","")
                    typ = item.get("type","link")
                    if typ == "link":
                        st.markdown(f"- [{title}]({url})")
                    elif typ == "rss":
                        st.markdown(f"**{title}**  ·  [{url}]({url})")
                        entries, err = fetch_rss(url, max_items=max_items, timeout=timeout)
                        if err:
                            st.warning(f"RSS fetch failed: {err}")
                        else:
                            for e in entries:
                                t = e["title"] or "(no title)"
                                l = e["link"] or url
                                p = e["published"]
                                if p:
                                    st.markdown(f"- [{t}]({l})  \n  <small>{p}</small>", unsafe_allow_html=True)
                                else:
                                    st.markdown(f"- [{t}]({l})")
                    else:
                        st.markdown(f"- [{title}]({url})")

    with right:
        st.subheader("✍️ Notes / Reflections")
        st.caption("保存到 reflections.csv（可下载）。")
        topic = st.selectbox("Topic", ["paper","stats","algo","project","other"], index=0)
        mood = st.selectbox("Mood", ["🙂 good","😐 ok","😕 stuck","🔥 excited"], index=1)
        tags = st.text_input("Tags (comma-separated)", value="")
        text = st.text_area("Your reflection", height=220, placeholder="例如：今天读到一个方法…我觉得可以用于…下一步想试…")
        if st.button("Save reflection"):
            now = dt.datetime.now()
            new = pd.DataFrame([{"timestamp": now.isoformat(timespec="seconds"), "date": str(today), "topic": topic, "mood": mood, "text": text.strip(), "tags": tags.strip()}])
            rf2 = pd.concat([rf, new], ignore_index=True)
            save_reflections(rf2)
            st.success("Saved ✅ (reflections.csv updated)")
            st.rerun()

        st.markdown("### Recent reflections")
        if len(rf) == 0:
            st.write("No reflections yet.")
        else:
            show = rf.sort_values("timestamp", ascending=False).head(15)
            st.dataframe(show, use_container_width=True, hide_index=True)

        st.download_button("Download reflections.csv", data=REFLECTIONS_PATH.read_bytes(), file_name="reflections.csv", mime="text/csv")

st.caption("Tip: edit plan.yaml; edit feeds.yaml to change sources.")
