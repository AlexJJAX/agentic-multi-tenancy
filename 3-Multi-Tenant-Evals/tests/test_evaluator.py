"""Regression tests for scoring and hard tenant boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest

from eval_harness.cli import load_cases
from eval_harness.corpus import load_corpus
from eval_harness.evaluator import evaluate

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def corpus():  # type: ignore[no-untyped-def]
    return load_corpus(ROOT / "knowledge")


@pytest.fixture
def cases():  # type: ignore[no-untyped-def]
    return load_cases(ROOT / "evals")


def test_candidate_reports_metrics_for_each_tenant(
    corpus,
    cases,
    evaluation_dependencies,
) -> None:  # type: ignore[no-untyped-def]
    report = evaluate(
        cases=cases,
        collections=corpus,
        dependencies=evaluation_dependencies,
        rewrite_enabled=True,
        top_k=1,
    )
    assert set(report.per_tenant) == {"tenant-A", "tenant-B"}
    assert report.overall.faithfulness == 1.0
    assert report.overall.isolation_pass_rate == 1.0


def test_contextual_rewrite_never_reduces_overall_recall(
    corpus,
    cases,
    evaluation_dependencies,
) -> None:  # type: ignore[no-untyped-def]
    baseline = evaluate(
        cases=cases,
        collections=corpus,
        dependencies=evaluation_dependencies,
        rewrite_enabled=False,
        top_k=1,
    )
    candidate = evaluate(
        cases=cases,
        collections=corpus,
        dependencies=evaluation_dependencies,
        rewrite_enabled=True,
        top_k=1,
    )
    assert candidate.overall.retrieval_recall >= baseline.overall.retrieval_recall


def test_collection_selection_cannot_surface_other_tenant(
    corpus,
    cases,
    evaluation_dependencies,
) -> None:  # type: ignore[no-untyped-def]
    report = evaluate(
        cases=cases,
        collections=corpus,
        dependencies=evaluation_dependencies,
        rewrite_enabled=True,
        top_k=4,
    )
    for result in report.cases:
        assert all(
            chunk_id.startswith(f"{result.tenant_id}:")
            for chunk_id in result.retrieved_chunk_ids
        )
