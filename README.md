# opsagent — incident-triage agent with guardrails, tracing and a scripted eval

A tool-using LLM agent that investigates a production incident (logs, metrics, ops database),
separates the root cause from downstream victims, and files a structured ticket. The point of the
project is the engineering around the model: validated tools, guardrails, retries, tracing,
cost accounting, and a **30-scenario benchmark with ground truth**.

```
alert ─► agent loop ─► LLM ──tool_use──► ToolBox (Pydantic-validated)
            │  ▲                           list_services · read_logs(grep) · get_metrics
            │  └──── tool_result ◄─────────  query_db (SELECT-only) · create_ticket (once)
            ├─ guardrails: step limit · token budget · write-query rejection · single ticket
            ├─ resilience: API retries w/ backoff · tool errors returned to the model, never raised
            └─ tracing: JSONL event per LLM step and tool call  ─►  Streamlit trace viewer
```

## Quickstart (offline)
```bash
pip install -e ".[dev]"
pytest -q
python scripts/run_eval.py --backend heuristic      # non-LLM baseline, no API key
```

## Evaluate a real model
```bash
export ANTHROPIC_API_KEY=...
python scripts/run_eval.py --backend anthropic --model <model id>     # writes results/eval_<model>.json
# optional cost tracking: fill per-million-token prices in prices.json
pip install -e ".[ui]" && streamlit run scripts/trace_viewer.py
```

## Benchmark design
30 synthetic incidents (6 root causes x 5 variants), generated deterministically (`--seed`).
Each has multi-service logs with noise, benign red herrings, and downstream victim errors.
**12 scenarios are "hard"**: the culprit's logs contain no signature, so the cause is only visible in
metrics (disk/memory/DB connections) or the deployments table, and a decoy symptom is planted in an
uninvolved service. Success = ticket `root_cause` equals ground truth. We also report culprit-service
accuracy, steps, tool errors, tokens, cost per task, stop reasons and the top confusions.

## Results (the heuristic row is a real measurement; fill in model rows from YOUR runs)
| agent | task success | culprit acc. | avg steps | avg tokens | cost / task |
|---|---|---|---|---|---|
| keyword-grep heuristic (offline) | 73.3% | 73.3% | 7.0 | 140 | n/a |
| LLM (model: ____) | | | | | |

The heuristic fails only on hard scenarios (it defaults to `upstream_timeout` when logs have no
signature) — exactly the gap an agent that checks metrics and the deployments table should close.

## Write the failure analysis yourself
After a real run, open the traces for failed scenarios and categorize why (stopped before checking
metrics? fooled by the decoy? bad ticket enum?). That paragraph is worth more than the success rate.

## Limitations
Synthetic logs are cleaner than production; scenarios are single-root-cause; one seed gives 30
samples so report confidence intervals or run several seeds before claiming model A beats model B.
