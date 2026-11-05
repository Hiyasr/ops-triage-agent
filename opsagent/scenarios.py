"""Synthetic incident generator with ground truth. 6 failure types x variants = 30 scenarios.
Each scenario has per-service logs (signal + red-herring noise), metrics, and a SQLite
database (deployments, job_runs) the agent can query."""
from __future__ import annotations
import random
import sqlite3
from dataclasses import dataclass, field

ROOT_CAUSES = ["db_connection_exhausted", "disk_full", "bad_deploy",
               "upstream_timeout", "memory_leak", "expired_credentials"]
SERVICES = ["api-gateway", "billing", "orders", "search", "notifications", "auth"]

NOISE = [
    "INFO health check ok",
    "INFO request completed status=200 duration_ms={ms}",
    "DEBUG cache hit key=session:{n}",
    "WARN slow query duration_ms={ms} (below alert threshold)",
    "INFO retrying connection attempt=1 succeeded",   # red herring: benign
    "INFO user login ok uid={n}",
    "WARN deprecated endpoint /v1/items called",
]


@dataclass
class Scenario:
    id: str
    root_cause: str
    culprit: str
    logs: dict[str, list[str]]
    metrics: dict[str, dict[str, float]]
    db: sqlite3.Connection = field(repr=False, default=None)


HARD_GENERIC = ["ERROR request failed status=500", "ERROR internal server error id={n}"]
METRIC_ONLY = {"db_connection_exhausted", "disk_full", "bad_deploy", "memory_leak"}


def _signal(cause: str, rng: random.Random, svc: str, dep: str, hard: bool = False) -> list[str]:
    n = rng.randint(6, 12)
    if hard and cause in METRIC_ONLY:
        # no signature in logs: the answer is only visible in metrics / the deployments table
        return [rng.choice(HARD_GENERIC).format(n=rng.randint(1, 9999)) for _ in range(n)]
    lines = {
        "db_connection_exhausted": [
            "ERROR could not acquire connection: pool exhausted (max=20, in_use=20)",
            "ERROR FATAL remaining connection slots are reserved for non-replication superuser connections"],
        "disk_full": [
            "ERROR write failed: No space left on device (errno=28)",
            "ERROR failed to rotate log file: disk quota exceeded"],
        "bad_deploy": [
            "ERROR NullPointerException in OrderMapper.map() at v{v}",
            "ERROR unhandled exception after startup of release v{v}"],
        "upstream_timeout": [
            f"ERROR timeout after 30000ms calling upstream {dep}",
            f"ERROR circuit breaker OPEN for {dep}"],
        "memory_leak": [
            "ERROR java.lang.OutOfMemoryError: heap space",
            "WARN container killed by OOM killer (exit 137), restart count={n}"],
        "expired_credentials": [
            f"ERROR 401 Unauthorized calling {dep}: token expired",
            "ERROR credential rotation overdue: api key expired"],
    }[cause]
    return [rng.choice(lines).format(v=f"2.{rng.randint(1, 9)}.{rng.randint(0, 9)}", n=rng.randint(3, 9))
            for _ in range(n)]


def make_scenario(i: int, seed: int = 0) -> Scenario:
    rng = random.Random(seed * 1000 + i)
    cause = ROOT_CAUSES[i % len(ROOT_CAUSES)]
    hard = (i // len(ROOT_CAUSES)) >= 3   # variants 3 and 4 of each cause (12 of 30) are 'hard'
    svcs = rng.sample(SERVICES, 4)
    culprit = svcs[0]
    dep = svcs[1]
    logs, metrics = {}, {}
    for s in svcs:
        lines = [rng.choice(NOISE).format(ms=rng.randint(5, 900), n=rng.randint(1, 9999))
                 for _ in range(rng.randint(25, 40))]
        if s == culprit:
            for sig in _signal(cause, rng, s, dep, hard):
                lines.insert(rng.randint(len(lines) // 2, len(lines)), sig)
        elif s == dep and rng.random() < 0.6:
            # downstream victim: shows symptoms but not the cause (adds ambiguity)
            lines.insert(rng.randint(0, len(lines)), f"ERROR request failed: upstream {culprit} returned 500")
        if hard and s not in (culprit, dep):
            # decoy: a benign, recovered symptom that keyword-matchers mistake for a cause
            lines.insert(rng.randint(0, len(lines)), f"WARN timeout after 30000ms calling upstream {dep} (retry succeeded)")
        logs[s] = [f"2026-11-0{1 + j % 3}T{(j * 7) % 24:02d}:{(j * 13) % 60:02d}:00Z {l}"
                   for j, l in enumerate(lines)]
        metrics[s] = {"cpu_pct": rng.uniform(10, 60), "mem_pct": rng.uniform(30, 65),
                      "disk_pct": rng.uniform(20, 60), "error_rate": rng.uniform(0, 0.02),
                      "db_connections": rng.uniform(2, 12)}
    m = metrics[culprit]
    m["error_rate"] = rng.uniform(0.2, 0.6)
    if cause == "disk_full": m["disk_pct"] = rng.uniform(97, 100)
    if cause == "memory_leak": m["mem_pct"] = rng.uniform(94, 99)
    if cause == "db_connection_exhausted": m["db_connections"] = 20.0
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE deployments(service TEXT, version TEXT, deployed_at TEXT, deployed_by TEXT)")
    db.execute("CREATE TABLE job_runs(job TEXT, service TEXT, status TEXT, finished_at TEXT)")
    for s in svcs:
        db.execute("INSERT INTO deployments VALUES(?,?,?,?)",
                   (s, f"2.{rng.randint(0, 8)}.{rng.randint(0, 9)}", "2026-10-28T09:00:00Z", "ci"))
        db.execute("INSERT INTO job_runs VALUES(?,?,?,?)", ("nightly-sync", s, "ok", "2026-11-02T01:00:00Z"))
    if cause == "bad_deploy":
        db.execute("INSERT INTO deployments VALUES(?,?,?,?)", (culprit, "2.9.9", "2026-11-03T14:05:00Z", "ci"))
    db.commit()
    return Scenario(f"S{i:02d}", cause, culprit, logs, metrics, db)


def make_scenarios(n: int = 30, seed: int = 0) -> list[Scenario]:
    return [make_scenario(i, seed) for i in range(n)]
