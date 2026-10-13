"""Reviewer UI (local). Run:  streamlit run review_ui/app.py
In AWS the same app runs on ECS behind SSO, or decisions arrive from Amazon A2I and
call uif.review.apply_decision directly."""

import getpass
import json
import re

import streamlit as st

from uif.context import Context
from uif.contracts import GuardedDoc, Validated
from uif.review import apply_decision, open_tasks

st.set_page_config(page_title="UIF review", layout="wide")


@st.cache_resource
def ctx() -> Context:
    return Context.from_config()


c = ctx()
tasks = open_tasks(c, limit=200)
st.title("Review queue")
st.caption(f"{len(tasks)} open task(s). Text shown is tokenized; raw documents stay in the restricted zone.")
if not tasks:
    st.success("Nothing to review.")
    st.stop()

labels = [f"{t['file_name']} — {t['reason']}" for t in tasks]
pick = st.sidebar.radio("Task", range(len(tasks)), format_func=lambda i: labels[i])
task = tasks[pick]
val = c.get_model("validated", Validated, doc_id=task["doc_id"])
pages = {p.page: p.text for p in c.get_model("guarded", GuardedDoc, doc_id=task["doc_id"]).pages}
fact_ids = json.loads(c.providers.warehouse.query(
    "select fact_ids from review_task where task_id = ?", [task["task_id"]])[0][0] or "[]")
facts = [f for f in val.facts if f.fact_id in fact_ids]

left, right = st.columns([2, 3])
with left:
    st.subheader(task["reason"])
    st.write(f"Document type: **{task['doc_type']}**")
    for f in facts:
        st.metric(f.field_path, json.dumps(f.value_norm), f"confidence {f.confidence:.2f}")
        st.write("Evidence:", f"page {f.evidence_page}", f"“{f.evidence_quote}”")
    corrected = st.text_input("Corrected value (JSON or plain text)", key=task["task_id"])
    reviewer = st.text_input("Reviewer", value=getpass.getuser())
    a, b, r = st.columns(3)
    decision = None
    if a.button("Accept"):
        decision, value = "accepted", None
    if b.button("Correct", disabled=not corrected):
        try:
            value = json.loads(corrected)
        except json.JSONDecodeError:
            value = corrected
        decision = "corrected"
    if r.button("Reject"):
        decision, value = "rejected", None
    if decision:
        st.toast(apply_decision(c, task["task_id"], decision, reviewer, value))
        st.rerun()

with right:
    page_no = facts[0].evidence_page if facts and facts[0].evidence_page else min(pages)
    page_no = st.selectbox("Page", sorted(pages), index=sorted(pages).index(page_no))
    text = pages[page_no]
    for f in facts:
        if f.evidence_quote and f.evidence_page == page_no:
            text = re.sub(re.escape(f.evidence_quote), lambda m: f"**:orange[{m.group(0)}]**", text, flags=re.I)
    st.markdown(text.replace("\n", "  \n"))
