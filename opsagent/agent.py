"""Agent loop with guardrails: step limit, token budget, validated tools, error recovery, tracing."""
from __future__ import annotations
import json
import time
from dataclasses import dataclass
from pathlib import Path
from .scenarios import Scenario
from .tools import ToolBox, tool_schemas
from .trace import Tracer

SYSTEM = """You are an on-call SRE assistant triaging a production incident.
Investigate with the tools: list services, read logs (use grep), check metrics, query the ops database.
Several services may show errors; some are downstream victims. Find the ROOT cause and the culprit service,
then call create_ticket exactly once. root_cause must be one of the allowed enum values. Do not guess
before you have evidence from logs or metrics. Never run write queries."""


@dataclass
class RunResult:
    scenario: str
    truth: str
    predicted: str | None
    culprit_ok: bool
    success: bool
    steps: int
    tool_calls: int
    tool_errors: int
    input_tokens: int
    output_tokens: int
    seconds: float
    stop_reason: str


def load_prices(model: str, path: str = "prices.json") -> tuple[float, float]:
    try:
        p = json.loads(Path(path).read_text()).get(model, {})
        return float(p.get("input", 0)), float(p.get("output", 0))
    except Exception:
        return 0.0, 0.0


def run_agent(llm, scenario: Scenario, max_steps: int = 12, max_tokens_budget: int = 60_000,
              trace_path: str | None = None) -> RunResult:
    tools, box = tool_schemas(), ToolBox(scenario)
    tr = Tracer(trace_path, scenario.id)
    messages = [{"role": "user", "content": "Alert: elevated error rates across several services. Investigate and file a ticket."}]
    t0 = time.perf_counter()
    in_tok = out_tok = n_calls = n_err = steps = 0
    stop = "step_limit"
    while steps < max_steps:
        steps += 1
        try:
            blocks, usage = llm.step(SYSTEM, messages, tools)
        except Exception as e:
            tr.log("llm_error", error=str(e)); stop = "llm_error"; break
        in_tok += usage["input"]; out_tok += usage["output"]
        tr.log("assistant", step=steps, blocks=blocks, usage=usage)
        messages.append({"role": "assistant", "content": blocks})
        uses = [b for b in blocks if b["type"] == "tool_use"]
        if not uses:
            stop = "finished"; break
        results = []
        for u in uses:
            t1 = time.perf_counter()
            text, is_err = box.call(u["name"], u["input"])
            n_calls += 1; n_err += int(is_err)
            tr.log("tool", step=steps, name=u["name"], args=u["input"], error=is_err,
                   result=text[:500], ms=round((time.perf_counter() - t1) * 1000, 2))
            results.append({"type": "tool_result", "tool_use_id": u["id"], "content": text, "is_error": is_err})
        messages.append({"role": "user", "content": results})
        if in_tok + out_tok > max_tokens_budget:
            stop = "token_budget"; break
    t = box.tickets[0] if box.tickets else None
    ok = bool(t and t.root_cause == scenario.root_cause)
    res = RunResult(scenario.id, scenario.root_cause, t.root_cause if t else None,
                    bool(t and t.culprit_service == scenario.culprit), ok, steps, n_calls, n_err,
                    in_tok, out_tok, time.perf_counter() - t0, stop)
    tr.log("result", **res.__dict__)
    return res
