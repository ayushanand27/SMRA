"""Offline evaluation runner for SMRA.

Measures:
- Routing accuracy against a golden dataset (deterministic keyword fallback by
  default; pass --use-llm to exercise the live LLM router).
- Guardrail block rate for adversarial prompts.

Exit code is non-zero when accuracy drops below the threshold so this can gate CI.

Usage:
    python -m smra.eval.run_eval
    python -m smra.eval.run_eval --use-llm --threshold 0.9
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


def main() -> int:
    parser = argparse.ArgumentParser(description="SMRA offline evaluation")
    parser.add_argument("--use-llm", action="store_true", help="Use the live LLM router instead of keyword fallback")
    parser.add_argument("--threshold", type=float, default=0.7, help="Minimum accuracy to pass")
    args = parser.parse_args()

    accuracy = run(use_llm=args.use_llm, threshold=args.threshold)
    return 0 if accuracy >= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
