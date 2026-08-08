"""Generate the deterministic regression report with injected test doubles."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval_harness.cli import load_cases
from eval_harness.corpus import load_corpus
from eval_harness.evaluator import evaluate
from tests.doubles import deterministic_dependencies

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "reports" / "latest.json",
    )
    args = parser.parse_args()

    dependencies = deterministic_dependencies()
    cases = load_cases(PROJECT_ROOT / "evals")
    collections = load_corpus(PROJECT_ROOT / "knowledge")
    baseline = evaluate(
        cases=cases,
        collections=collections,
        dependencies=dependencies,
        rewrite_enabled=False,
        top_k=args.top_k,
    )
    candidate = evaluate(
        cases=cases,
        collections=collections,
        dependencies=dependencies,
        rewrite_enabled=True,
        top_k=args.top_k,
    )
    report = {
        "methodology": {
            "judge": "deterministic extractive answer test double",
            "retriever": "deterministic token-hash embedding test double",
            "top_k": args.top_k,
            "metrics": [
                "retrieval_recall",
                "answer_coverage",
                "faithfulness",
                "isolation_pass_rate",
            ],
        },
        "baseline": baseline.to_dict(),
        "candidate": candidate.to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if candidate.overall.isolation_pass_rate == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
