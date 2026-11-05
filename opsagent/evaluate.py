from __future__ import annotations
import statistics
from collections import Counter, defaultdict
from .agent import run_agent, load_prices
from .scenarios import make_scenarios


def evaluate(llm, n: int = 30, seed: int = 0, model_name: str = "heuristic", trace_path: str | None = None,
             max_steps: int = 12) -> dict:
    runs = [run_agent(llm, s, max_steps=max_steps, trace_path=trace_path) for s in make_scenarios(n, seed)]
    pin, pout = load_prices(model_name)
    by_type = defaultdict(list)
    for r in runs:
        by_type[r.truth].append(r.success)
    confusions = Counter((r.truth, r.predicted) for r in runs if not r.success)
    cost = sum(r.input_tokens * pin + r.output_tokens * pout for r in runs) / 1e6
    return {
        "model": model_name, "n": len(runs),
        "task_success_rate": sum(r.success for r in runs) / len(runs),
        "culprit_service_accuracy": sum(r.culprit_ok for r in runs) / len(runs),
        "avg_steps": statistics.mean(r.steps for r in runs),
        "avg_tool_errors": statistics.mean(r.tool_errors for r in runs),
        "avg_tokens": statistics.mean(r.input_tokens + r.output_tokens for r in runs),
        "cost_per_task_usd": (cost / len(runs)) if (pin or pout) else None,
        "stop_reasons": dict(Counter(r.stop_reason for r in runs)),
        "success_by_failure_type": {k: sum(v) / len(v) for k, v in by_type.items()},
        "top_confusions": [{"truth": t, "predicted": p, "count": c} for (t, p), c in confusions.most_common(5)],
        "runs": [r.__dict__ for r in runs],
    }
