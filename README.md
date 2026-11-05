# ops-triage-agent

[![CI](https://github.com/Hiyasr/ops-triage-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Hiyasr/ops-triage-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

**A tool-using LLM agent that triages production incidents, built so its reliability can be measured.**
It investigates logs, metrics and an ops database, separates the root cause from downstream victims,
and files a structured ticket. The engineering around the model is the point: validated tools,
guardrails, retries, tracing, cost accounting and a 30-scenario benchmark with ground truth.

> **Status:** agent, guardrails, benchmark, tests and CI are complete. Evaluation of real models is in
> progress; the model rows in the results table are filled in only from measured runs.

## How it works

```
alert ─► agent loop ─► LLM ──tool_use──► ToolBox (Pydantic-validated)
            │  ▲                          list_services · read_logs(grep) · get_metrics
            │  └──── tool_result ◄─────── query_db (SELECT-only) · create_ticket (once)
            │
            ├─ guardrails   step limit · token budget · write-query rejection · single ticket
            ├─ resilience   API retries with backoff · tool errors returned to the model, never raised
            └─ tracing      one JSONL event per LLM step and tool call ─► Streamlit trace viewer
```

| Tool | Purpose | Safety |
|---|---|---|
| `list_services` | enumerate services that have logs | read-only |
| `read_logs` | recent lines of a service, optional regex filter | line cap, output truncated |
| `get_metrics` | cpu, memory, disk, error rate, DB connections | read-only |
| `query_db` | `deployments` and `job_runs` tables | a single `SELECT` only; writes, `PRAGMA` and multi-statements are rejected |
| `create_ticket` | final structured ticket | enum-validated root cause, accepted once per incident |

Invalid tool arguments come back to the model as error results, so it can correct itself instead of crashing the run.

## Quickstart (offline, no API key)

```bash
pip install -e ".[dev]"
pytest -q
python scripts/run_eval.py --backend heuristic     # non-LLM baseline
```

## Evaluate a real model

```bash
export ANTHROPIC_API_KEY=...        # PowerShell: $env:ANTHROPIC_API_KEY="..."
python scripts/run_eval.py --backend anthropic --model <model id>    # writes results/eval_<model>.json
pip install -e ".[ui]" && streamlit run scripts/trace_viewer.py      # inspect traces step by step
```

For cost per task, fill the per-million-token prices for your models in `prices.json`.

## Benchmark design

30 synthetic incidents (6 root causes x 5 variants), generated deterministically from `--seed`.

- **Root causes:** database connection exhaustion, disk full, bad deploy, upstream timeout, memory leak, expired credentials.
- **Realism:** multi-service logs with noise, benign red herrings (for example a retry that succeeded) and downstream victim errors.
- **12 hard scenarios:** the culprit's logs contain no signature, so the cause is visible only in metrics or the deployments table, and a decoy symptom is planted in an uninvolved service.

Success means the ticket's `root_cause` equals the ground truth. Also reported: culprit-service
accuracy, steps, tool errors, tokens, cost per task, stop reasons and the most common confusions.

## Results

| agent | task success | culprit accuracy | avg steps | avg tokens | cost / task |
|---|---|---|---|---|---|
| keyword-grep heuristic (offline baseline) | 73.3% | 73.3% | 7.0 | 140 | n/a |
| LLM, model TBD | TBD | TBD | TBD | TBD | TBD |
| LLM, model TBD | TBD | TBD | TBD | TBD | TBD |

The heuristic baseline is a real measurement. It never calls an LLM: it reads every service's logs and
matches known signatures.

**Baseline success by failure type**

| root cause | success |
|---|---|
| upstream timeout | 100% |
| expired credentials | 100% |
| database connection exhaustion | 60% |
| disk full | 60% |
| bad deploy | 60% |
| memory leak | 60% |

The baseline fails only on hard scenarios. When logs carry no signature it defaults to
`upstream_timeout`. That is the gap an agent that checks metrics and the deployments table should close.

## Failure analysis

_To be written after the real-model runs: a categorized count of failed scenarios (stopped before
checking metrics, fooled by the decoy, blamed a downstream victim, invalid ticket, hit the step limit)
with example traces._

## Limitations

- Synthetic logs are cleaner than production logs.
- Every scenario has a single root cause.
- 30 scenarios per seed is a small sample. Differences of a few points between models are noise unless
  confirmed across several seeds, with confidence intervals reported.
- The heuristic baseline is a floor, not a competitor.

## Project layout

```
opsagent/     scenarios, tools, agent loop, LLM backends, tracing, evaluation
scripts/      run_eval (baseline or real model), trace_viewer (Streamlit)
tests/        guardrails, validation, step/token limits, tracing, baseline benchmark
prices.json   per-million-token prices used for cost accounting
results/      evaluation outputs (traces are git-ignored)
```

## CI

`.github/workflows/ci.yml` runs the test suite on every push and pull request.
