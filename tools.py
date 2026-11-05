"""Tools exposed to the agent. Arguments are validated with Pydantic; failures are returned
to the model as error results (never raised), so the agent can recover."""
from __future__ import annotations
import re
from typing import Literal
from pydantic import BaseModel, Field, ValidationError
from .scenarios import Scenario, ROOT_CAUSES

MAX_RESULT_CHARS = 3000
MAX_DB_ROWS = 20


class ListServices(BaseModel):
    """List all services that have logs."""


class ReadLogs(BaseModel):
    """Read recent log lines of a service, optionally filtered by a case-insensitive regex."""
    service: str
    last_n: int = Field(40, ge=1, le=100)
    grep: str | None = None


class GetMetrics(BaseModel):
    """Get current metrics (cpu_pct, mem_pct, disk_pct, error_rate, db_connections) for a service."""
    service: str


class QueryDb(BaseModel):
    """Run ONE read-only SELECT against the ops database (tables: deployments, job_runs)."""
    sql: str


class CreateTicket(BaseModel):
    """File the final incident ticket. Call exactly once, when you are confident."""
    title: str = Field(min_length=5, max_length=120)
    culprit_service: str
    root_cause: Literal[tuple(ROOT_CAUSES)]  # type: ignore[valid-type]
    severity: Literal["low", "medium", "high"]
    summary: str = Field(min_length=10, max_length=600)
    suggested_fix: str = Field(min_length=5, max_length=400)


MODELS = {"list_services": ListServices, "read_logs": ReadLogs, "get_metrics": GetMetrics,
          "query_db": QueryDb, "create_ticket": CreateTicket}


def tool_schemas() -> list[dict]:
    out = []
    for name, m in MODELS.items():
        schema = m.model_json_schema()
        schema.pop("title", None)
        desc = (m.__doc__ or "").strip()
        schema.pop("description", None)
        out.append({"name": name, "description": desc, "input_schema": schema})
    return out


_SELECT_ONLY = re.compile(r"^\s*select\b", re.I)
_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|pragma|replace|vacuum)\b|;.+", re.I | re.S)


class ToolBox:
    def __init__(self, scenario: Scenario):
        self.s = scenario
        self.tickets: list[CreateTicket] = []

    def call(self, name: str, raw_args: dict) -> tuple[str, bool]:
        """Returns (result_text, is_error)."""
        model = MODELS.get(name)
        if model is None:
            return f"unknown tool '{name}'. Available: {sorted(MODELS)}", True
        try:
            args = model(**(raw_args or {}))
        except ValidationError as e:
            return "invalid arguments: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()), True
        try:
            text = getattr(self, f"_{name}")(args)
        except KeyError as e:
            return f"not found: {e}", True
        except Exception as e:  # tool bugs must not crash the loop
            return f"tool error: {type(e).__name__}: {e}", True
        return text[:MAX_RESULT_CHARS], False

    def _list_services(self, a: ListServices) -> str:
        return ", ".join(sorted(self.s.logs))

    def _read_logs(self, a: ReadLogs) -> str:
        if a.service not in self.s.logs:
            raise KeyError(f"service '{a.service}'")
        lines = self.s.logs[a.service]
        if a.grep:
            rx = re.compile(a.grep, re.I)
            lines = [l for l in lines if rx.search(l)]
        return "\n".join(lines[-a.last_n:]) or "(no matching lines)"

    def _get_metrics(self, a: GetMetrics) -> str:
        if a.service not in self.s.metrics:
            raise KeyError(f"service '{a.service}'")
        return ", ".join(f"{k}={v:.2f}" for k, v in self.s.metrics[a.service].items())

    def _query_db(self, a: QueryDb) -> str:
        if not _SELECT_ONLY.match(a.sql) or _FORBIDDEN.search(a.sql):
            return "rejected: only a single read-only SELECT statement is allowed"
        cur = self.s.db.execute(a.sql)
        cols = [c[0] for c in cur.description]
        rows = cur.fetchmany(MAX_DB_ROWS)
        return " | ".join(cols) + "\n" + "\n".join(" | ".join(map(str, r)) for r in rows)

    def _create_ticket(self, a: CreateTicket) -> str:
        if self.tickets:
            return "rejected: a ticket was already filed for this incident"
        self.tickets.append(a)
        return f"ticket created: {a.title}"
