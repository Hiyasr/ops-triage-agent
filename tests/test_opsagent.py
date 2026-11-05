import json
from opsagent.scenarios import make_scenarios, make_scenario, ROOT_CAUSES
from opsagent.tools import ToolBox, tool_schemas
from opsagent.agent import run_agent
from opsagent.llm import HeuristicLLM
from opsagent.evaluate import evaluate


def test_scenarios_cover_all_causes_and_are_deterministic():
    sc = make_scenarios(30)
    assert {s.root_cause for s in sc} == set(ROOT_CAUSES)
    assert make_scenario(3).logs == make_scenario(3).logs


def test_tool_schemas_are_valid_anthropic_shape():
    for t in tool_schemas():
        assert {"name", "description", "input_schema"} <= t.keys()
        assert t["input_schema"]["type"] == "object"


def test_db_guardrails_block_writes():
    box = ToolBox(make_scenario(0))
    for bad in ["DROP TABLE deployments", "SELECT 1; DELETE FROM deployments", "UPDATE deployments SET version='x'",
                "PRAGMA table_info(deployments)"]:
        text, err = box.call("query_db", {"sql": bad})
        assert "rejected" in text, bad
    text, err = box.call("query_db", {"sql": "SELECT service, version FROM deployments"})
    assert not err and "service" in text


def test_invalid_args_returned_as_error_not_raised():
    box = ToolBox(make_scenario(0))
    text, err = box.call("read_logs", {"service": "api-gateway", "last_n": 9999})
    assert err and "invalid arguments" in text
    text, err = box.call("read_logs", {"service": "nope"})
    assert err and "not found" in text
    text, err = box.call("fly_to_moon", {})
    assert err


def test_ticket_validation_and_single_ticket():
    box = ToolBox(make_scenario(0))
    good = dict(title="Disk full on host", culprit_service="billing", root_cause="disk_full",
                severity="high", summary="Disk at 99 percent", suggested_fix="Free space")
    assert box.call("create_ticket", {**good, "root_cause": "aliens"})[1]
    assert not box.call("create_ticket", good)[1]
    assert "already filed" in box.call("create_ticket", good)[0]


def test_step_limit_guardrail():
    class Loop:
        def step(self, *a):
            return [{"type": "tool_use", "id": "x", "name": "list_services", "input": {}}], {"input": 1, "output": 1}
    r = run_agent(Loop(), make_scenario(0), max_steps=3)
    assert r.stop_reason == "step_limit" and r.steps == 3 and not r.success


def test_token_budget_guardrail():
    class Hog:
        def step(self, *a):
            return [{"type": "tool_use", "id": "x", "name": "list_services", "input": {}}], {"input": 50_000, "output": 50_000}
    assert run_agent(Hog(), make_scenario(0), max_steps=10, max_tokens_budget=1000).stop_reason == "token_budget"


def test_llm_failure_is_handled():
    class Boom:
        def step(self, *a):
            raise RuntimeError("api down")
    assert run_agent(Boom(), make_scenario(0)).stop_reason == "llm_error"


def test_trace_written(tmp_path):
    p = tmp_path / "t.jsonl"
    run_agent(HeuristicLLM(), make_scenario(1), trace_path=str(p))
    kinds = [json.loads(l)["kind"] for l in p.read_text().splitlines()]
    assert "tool" in kinds and kinds[-1] == "result"


def test_heuristic_baseline_beats_chance():
    res = evaluate(HeuristicLLM(), n=30)
    # grep-style baseline must be decent but NOT perfect: hard variants need metrics / DB evidence
    assert res["n"] == 30 and 0.5 <= res["task_success_rate"] < 1.0
    assert set(res["success_by_failure_type"]) == set(ROOT_CAUSES)
