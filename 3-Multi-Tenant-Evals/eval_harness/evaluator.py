"""Per-case scoring with explicit evidence and tenant-level aggregation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings

from eval_harness.inference import AnswerGenerator, QueryRewriter
from eval_harness.models import (
    CaseResult,
    Chunk,
    EvalCase,
    EvalReport,
    TenantMetrics,
)
from eval_harness.retrieval import retrieve, tokens


@dataclass(frozen=True)
class EvaluationDependencies:
    """Inference dependencies supplied live by the CLI or as doubles by tests."""

    embeddings: Embeddings
    query_rewriter: QueryRewriter
    answer_generator: AnswerGenerator


def _term_coverage(answer: str, expected_terms: tuple[str, ...]) -> float:
    normalized = answer.casefold()
    return (
        sum(term.casefold() in normalized for term in expected_terms) / len(expected_terms)
        if expected_terms
        else 1.0
    )


def _faithfulness(answer: str, hits: list[Chunk]) -> float:
    """Score the fraction of answer tokens present in retrieved evidence."""

    answer_tokens = set(tokens(answer))
    if not answer_tokens:
        return 0.0
    context_tokens = set(tokens(" ".join(hit.content for hit in hits)))
    return len(answer_tokens.intersection(context_tokens)) / len(answer_tokens)


def _aggregate(results: list[CaseResult]) -> TenantMetrics:
    count = len(results)
    if not count:
        return TenantMetrics(0, 0.0, 0.0, 0.0, 0.0)
    return TenantMetrics(
        cases=count,
        retrieval_recall=round(sum(item.retrieval_recall for item in results) / count, 4),
        answer_coverage=round(sum(item.answer_coverage for item in results) / count, 4),
        faithfulness=round(sum(item.faithfulness for item in results) / count, 4),
        isolation_pass_rate=round(
            sum(item.isolation_passed for item in results) / count,
            4,
        ),
    )


def evaluate(
    *,
    cases: list[EvalCase],
    collections: dict[str, list[Chunk]],
    dependencies: EvaluationDependencies,
    rewrite_enabled: bool,
    top_k: int = 1,
) -> EvalReport:
    """Evaluate a raw-query baseline or contextual-rewrite candidate."""

    results: list[CaseResult] = []
    by_tenant: dict[str, list[CaseResult]] = defaultdict(list)
    for case in cases:
        collection = collections.get(case.tenant_id)
        if collection is None:
            raise ValueError(f"No collection exists for {case.tenant_id}")
        query = (
            dependencies.query_rewriter.rewrite(case.question, case.history)
            if rewrite_enabled
            else case.question
        )
        hits = retrieve(
            collection,
            query,
            top_k=top_k,
            embeddings=dependencies.embeddings,
        )
        answer = dependencies.answer_generator.generate(case, hits)
        sections = {hit.section for hit in hits}
        result = CaseResult(
            case_id=case.case_id,
            tenant_id=case.tenant_id,
            retrieval_query=query,
            retrieved_chunk_ids=tuple(hit.chunk_id for hit in hits),
            retrieved_sections=tuple(hit.section for hit in hits),
            answer=answer,
            retrieval_recall=float(bool(sections.intersection(case.expected_sections))),
            answer_coverage=round(_term_coverage(answer, case.expected_terms), 4),
            faithfulness=round(_faithfulness(answer, hits), 4),
            isolation_passed=all(hit.tenant_id == case.tenant_id for hit in hits),
        )
        results.append(result)
        by_tenant[case.tenant_id].append(result)

    return EvalReport(
        strategy="contextual-rewrite" if rewrite_enabled else "raw-query",
        top_k=top_k,
        per_tenant={
            tenant_id: _aggregate(tenant_results)
            for tenant_id, tenant_results in sorted(by_tenant.items())
        },
        overall=_aggregate(results),
        cases=tuple(results),
    )
