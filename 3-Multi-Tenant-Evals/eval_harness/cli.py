"""Command-line runner for golden per-tenant RAG evaluations."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from eval_harness.corpus import load_corpus
from eval_harness.evaluator import EvaluationDependencies, evaluate
from eval_harness.inference import (
    OpenAIAnswerGenerator,
    OpenAIQueryRewriter,
    create_live_embeddings,
)
from eval_harness.models import EvalCase
from eval_harness.settings import settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_cases(evals_root: Path) -> list[EvalCase]:
    """Load every tenant golden file and validate its tenant boundary."""

    cases: list[EvalCase] = []
    for path in sorted(evals_root.glob("*/golden.jsonl")):
        directory_tenant = path.parent.name
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            payload: dict[str, Any] = json.loads(line)
            if payload["tenant_id"] != directory_tenant:
                raise ValueError(
                    f"{path}:{line_number} crosses tenant directory boundary"
                )
            cases.append(
                EvalCase(
                    case_id=str(payload["case_id"]),
                    tenant_id=str(payload["tenant_id"]),
                    question=str(payload["question"]),
                    expected_sections=tuple(payload["expected_sections"]),
                    expected_terms=tuple(payload["expected_terms"]),
                    history=tuple(payload.get("history", [])),
                )
            )
    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-k", type=int, default=1)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "reports" / "latest.json",
    )
    args = parser.parse_args()

    settings.require_openai_api_key()
    dependencies = EvaluationDependencies(
        embeddings=create_live_embeddings(settings),
        query_rewriter=OpenAIQueryRewriter(settings),
        answer_generator=OpenAIAnswerGenerator(settings),
    )
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
            "judge": "live OpenAI grounded answer with lexical evidence scoring",
            "chat_model": settings.openai_chat_model,
            "embedding_model": settings.openai_embedding_model,
            "query_rewrite_model": settings.openai_query_rewrite_model,
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

    print("Per-tenant candidate metrics")
    for tenant_id, metrics in candidate.per_tenant.items():
        print(
            f"  {tenant_id}: recall={metrics.retrieval_recall:.0%}, "
            f"coverage={metrics.answer_coverage:.0%}, "
            f"faithfulness={metrics.faithfulness:.0%}, "
            f"isolation={metrics.isolation_pass_rate:.0%}"
        )
    delta = candidate.overall.retrieval_recall - baseline.overall.retrieval_recall
    print(f"Overall retrieval recall delta: {delta:+.0%}")
    print(f"Report: {args.output}")
    return 0 if candidate.overall.isolation_pass_rate == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
