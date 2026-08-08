"""Typed, serializable evaluation contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Chunk:
    """One tenant-owned, heading-aware retrieval unit."""

    chunk_id: str
    tenant_id: str
    source: str
    section: str
    content: str


@dataclass(frozen=True)
class EvalCase:
    """Golden question with retrieval and answer-quality expectations."""

    case_id: str
    tenant_id: str
    question: str
    expected_sections: tuple[str, ...]
    expected_terms: tuple[str, ...]
    history: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseResult:
    """Metrics and evidence for one case."""

    case_id: str
    tenant_id: str
    retrieval_query: str
    retrieved_chunk_ids: tuple[str, ...]
    retrieved_sections: tuple[str, ...]
    answer: str
    retrieval_recall: float
    answer_coverage: float
    faithfulness: float
    isolation_passed: bool


@dataclass(frozen=True)
class TenantMetrics:
    """Aggregated metrics kept separate so weak tenants cannot hide in a global mean."""

    cases: int
    retrieval_recall: float
    answer_coverage: float
    faithfulness: float
    isolation_pass_rate: float


@dataclass(frozen=True)
class EvalReport:
    """Complete report for one retrieval strategy."""

    strategy: str
    top_k: int
    per_tenant: dict[str, TenantMetrics]
    overall: TenantMetrics
    cases: tuple[CaseResult, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""

        return asdict(self)
