"""python scripts/run_eval.py --backend heuristic            # offline baseline
   ANTHROPIC_API_KEY=... python scripts/run_eval.py --backend anthropic --model <model id>"""
import argparse, json
from opsagent.evaluate import evaluate
from opsagent.llm import HeuristicLLM, AnthropicAgentLLM

ap = argparse.ArgumentParser()
ap.add_argument("--backend", choices=["heuristic", "anthropic"], default="heuristic")
ap.add_argument("--model", default=None)
ap.add_argument("-n", type=int, default=30)
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()

if a.backend == "heuristic":
    llm, name = HeuristicLLM(), "heuristic"
else:
    llm = AnthropicAgentLLM(a.model); name = llm.model
trace = f"results/trace_{name}.jsonl"
open(trace, "w").close()
res = evaluate(llm, a.n, a.seed, name, trace)
json.dump(res, open(f"results/eval_{name}.json", "w"), indent=2)
print({k: v for k, v in res.items() if k != "runs"})
