"""LLM backends share one interface: step(system, messages, tools) -> (blocks, usage).
`blocks` are dicts: {"type":"text","text":...} or {"type":"tool_use","id","name","input"}."""
from __future__ import annotations
import itertools
import os
import re
import time


class AnthropicAgentLLM:
    def __init__(self, model: str | None = None, max_tokens: int = 1024):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("AGENT_MODEL", "claude-haiku-5-5")
        self.max_tokens = max_tokens

    def step(self, system, messages, tools):
        last = None
        for attempt in range(4):  # retry transient API failures with backoff
            try:
                r = self.client.messages.create(model=self.model, max_tokens=self.max_tokens,
                                                system=system, messages=messages, tools=tools)
                blocks = []
                for b in r.content:
                    if b.type == "text":
                        blocks.append({"type": "text", "text": b.text})
                    elif b.type == "tool_use":
                        blocks.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                return blocks, {"input": r.usage.input_tokens, "output": r.usage.output_tokens}
            except Exception as e:
                last = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"LLM call failed after retries: {last}")


KEYWORDS = {
    "db_connection_exhausted": [r"pool exhausted", r"connection slots"],
    "disk_full": [r"no space left", r"disk quota"],
    "bad_deploy": [r"nullpointer", r"after startup of release"],
    "upstream_timeout": [r"timeout after", r"circuit breaker"],
    "memory_leak": [r"outofmemory", r"oom killer"],
    "expired_credentials": [r"token expired", r"key expired", r"401 unauthorized"],
}


class HeuristicLLM:
    """Offline rule-based 'agent'. It makes real tool calls (list -> read all logs -> file ticket),
    so it exercises the harness and gives a non-LLM BASELINE to compare real models against."""

    def __init__(self):
        self._ids = itertools.count()

    def _id(self):
        return f"toolu_h{next(self._ids)}"

    def step(self, system, messages, tools):
        results = [b for m in messages if m["role"] == "user" and isinstance(m["content"], list)
                   for b in m["content"] if b.get("type") == "tool_result"]
        calls = [b for m in messages if m["role"] == "assistant" for b in m["content"] if b["type"] == "tool_use"]
        use = {"input": 10, "output": 10}
        if not calls:
            return [{"type": "tool_use", "id": self._id(), "name": "list_services", "input": {}}], use
        services = results[0]["content"].split(", ")
        read = [c["input"].get("service") for c in calls if c["name"] == "read_logs"]
        todo = [s for s in services if s not in read]
        if todo:
            return [{"type": "tool_use", "id": self._id(), "name": "read_logs",
                     "input": {"service": todo[0], "last_n": 100}}], use
        scores, where, best_n = {}, {}, {}
        for c, r in zip([c for c in calls if c["name"] == "read_logs"], results[1:]):
            for cause, pats in KEYWORDS.items():
                n = sum(len(re.findall(p, r["content"], re.I)) for p in pats)
                if n:
                    scores[cause] = scores.get(cause, 0) + n
                    if n > best_n.get(cause, 0):
                        best_n[cause], where[cause] = n, c["input"]["service"]
        cause = max(scores, key=scores.get) if scores else "upstream_timeout"
        ticket = {"title": f"Incident: {cause}", "culprit_service": where.get(cause) or services[0],
                  "root_cause": cause, "severity": "high",
                  "summary": f"Heuristic triage matched log signatures for {cause}.",
                  "suggested_fix": "Follow the runbook for this failure class."}
        if any(c["name"] == "create_ticket" for c in calls):
            return [{"type": "text", "text": f"Done: {cause}."}], use
        return [{"type": "tool_use", "id": self._id(), "name": "create_ticket", "input": ticket}], use
