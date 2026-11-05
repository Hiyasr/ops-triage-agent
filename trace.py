from __future__ import annotations
import json
import time
from pathlib import Path


class Tracer:
    """Append-only JSONL trace. One line per event; every tool call is recorded."""

    def __init__(self, path: str | Path | None, run_id: str):
        self.path, self.run_id, self.events = (Path(path) if path else None), run_id, []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, kind: str, **data):
        ev = {"ts": time.time(), "run": self.run_id, "kind": kind, **data}
        self.events.append(ev)
        if self.path:
            with self.path.open("a") as f:
                f.write(json.dumps(ev, default=str) + "\n")
