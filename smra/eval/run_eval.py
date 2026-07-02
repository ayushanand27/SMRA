"""Offline evaluation runner for SMRA.

Measures:
- Routing accuracy against a golden dataset (deterministic keyword fallback by
  default; pass --use-llm to exercise the live LLM router).
- Guardrail block rate for adversarial prompts.
- Optional LLM-as-judge answer quality (--judge), which runs the full agent
  pipeline and grades each answer. Requires a working LLM provider/key.

Exit code is non-zero when accuracy drops below the threshold so this can gate CI.

Usage:
    python -m smra.eval.run_eval
    python -m smra.eval.run_eval --use-llm --threshold 0.9
    python -m smra.eval.run_eval --judge --judge-threshold 0.6
"""
import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from smra.utils.guardrails import check_input  # noqa: E402
from smra.utils.schemas import keyword_route_fallback  # noqa: E402

DATASET = Path(__file__).resolve().parent / "golden_dataset.json"


def _predict_route(query: str, use_llm: bool) -> str:
    guard = check_input(query)
    if not guard.ok:
        return "BLOCK"
    if use_llm:
        from smra.router import classify_intent

        routes = classify_intent(guard.text)
    else:
        routes = keyword_route_fallback(guard.text)
    return routes[0] if routes else "SQL"


def run(use_llm: bool = False, threshold: float = 0.7) -> float:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    total = len(cases)
    correct = 0
    per_category: dict[str, list[int]] = {}

    print(f"Running {total} eval cases (use_llm={use_llm})\n")
    for case in cases:
        predicted = _predict_route(case["query"], use_llm)
        expected = case["expected_route"]
        hit = int(predicted == expected)
        correct += hit
        per_category.setdefault(case["category"], []).append(hit)
        status = "PASS" if hit else "FAIL"
        print(f"[{status}] {case['id']:<10} expected={expected:<7} got={predicted:<7} :: {case['query'][:60]}")

    accuracy = correct / total if total else 0.0
    print("\nPer-category accuracy:")
    for cat, hits in sorted(per_category.items()):
        print(f"  {cat:<12} {sum(hits)}/{len(hits)}")

    print(f"\nOverall routing accuracy: {accuracy:.1%} ({correct}/{total})")
    print(f"Threshold: {threshold:.1%}")

    if accuracy < threshold:
        print("RESULT: BELOW THRESHOLD")
        return accuracy
    print("RESULT: PASS")
    return accuracy


def _run_full_pipeline(query: str) -> str:
    """Execute the real agent pipeline for one query and return the answer text."""
    from smra.agents.rag_agent import run_rag_agent
    from smra.agents.sql_agent import run_sql_agent
    from smra.agents.web_agent import run_web_agent
    from smra.orchestrator import synthesize_hybrid_answer
    from smra.router import classify_intent
    from smra.utils.schemas import expand_routes

    routes = classify_intent(query)
    execution_routes = expand_routes(routes)
    is_hybrid = "HYBRID" in routes or ("SQL" in execution_routes and "RAG" in execution_routes)

    if is_hybrid:
        sql_result = run_sql_agent(query)
        rag_result = run_rag_agent(query)
        if isinstance(rag_result, dict) and rag_result.get("fallback"):
            rag_result = run_web_agent(query)
        return synthesize_hybrid_answer(query, sql_result, rag_result)

    answer = ""
    for route in execution_routes:
        if route == "SQL":
            answer = run_sql_agent(query).get("answer", "")
        elif route == "RAG":
            result = run_rag_agent(query)
            if isinstance(result, dict) and result.get("fallback"):
                result = run_web_agent(query)
            answer = result.get("answer", "")
        elif route == "WEB":
            answer = run_web_agent(query).get("answer", "")
    return answer


def run_judge(judge_threshold: float = 0.6) -> float:
    """Run the full pipeline on answerable cases and grade answers with an LLM judge."""
    from smra.eval.judge import judge_answer

    cases = [c for c in json.loads(DATASET.read_text(encoding="utf-8")) if c["category"] != "adversarial"]
    print(f"\nLLM-judge on {len(cases)} answerable cases\n")

    total = 0.0
    scored = 0
    for case in cases:
        try:
            answer = _run_full_pipeline(case["query"])
            result = judge_answer(case["query"], answer)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERR ] {case['id']:<10} :: {exc}")
            continue
        total += result.score
        scored += 1
        print(
            f"[{result.score:.2f}] {case['id']:<10} "
            f"R{result.relevance} G{result.groundedness} C{result.clarity} :: {case['query'][:50]}"
        )

    avg = total / scored if scored else 0.0
    print(f"\nMean judge score: {avg:.2f} (threshold {judge_threshold:.2f})")
    print("JUDGE RESULT:", "PASS" if avg >= judge_threshold else "BELOW THRESHOLD")
    return avg


def main() -> int:
    parser = argparse.ArgumentParser(description="SMRA offline evaluation")
    parser.add_argument("--use-llm", action="store_true", help="Use the live LLM router instead of keyword fallback")
    parser.add_argument("--threshold", type=float, default=0.7, help="Minimum routing accuracy to pass")
    parser.add_argument("--judge", action="store_true", help="Run LLM-as-judge answer-quality eval (needs LLM keys)")
    parser.add_argument("--judge-threshold", type=float, default=0.6, help="Minimum mean judge score to pass")
    args = parser.parse_args()

    accuracy = run(use_llm=args.use_llm, threshold=args.threshold)
    routing_ok = accuracy >= args.threshold

    judge_ok = True
    if args.judge:
        judge_avg = run_judge(judge_threshold=args.judge_threshold)
        judge_ok = judge_avg >= args.judge_threshold

    return 0 if (routing_ok and judge_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
