"""streamlit run scripts/trace_viewer.py  — browse agent traces step by step."""
import json, sys
from pathlib import Path
import streamlit as st

st.title("Ops triage agent — trace viewer")
files = sorted(Path("results").glob("trace_*.jsonl"))
if not files:
    st.info("Run scripts/run_eval.py first."); st.stop()
f = st.selectbox("Trace file", files)
events = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
runs = sorted({e["run"] for e in events})
run = st.selectbox("Scenario", runs)
for e in [e for e in events if e["run"] == run]:
    if e["kind"] == "tool":
        with st.expander(f"step {e['step']} · {e['name']}" + (" · ERROR" if e["error"] else "")):
            st.code(json.dumps(e["args"], indent=1)); st.text(e["result"])
    elif e["kind"] == "assistant":
        for b in e["blocks"]:
            if b["type"] == "text": st.markdown(f"**assistant:** {b['text']}")
    elif e["kind"] == "result":
        st.success("SUCCESS" if e["success"] else f"FAILED (predicted {e['predicted']}, truth {e['truth']})")
