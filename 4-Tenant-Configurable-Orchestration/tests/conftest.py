"""Injected deterministic model collaborators for workflow tests."""

from __future__ import annotations

import re
from typing import Any

import pytest

from orchestration.config import TenantAgentConfig
from orchestration.graph import Plan, WorkflowDependencies


class DeterministicPlanner:
    """Structured planner double with stable intent routing."""

    def plan(self, query: str) -> Plan:
        lower = query.casefold()
        if "order" in lower or re.search(r"\b[A-Z]-\d{4}\b", query):
            return Plan(
                tool="query_orders",
                rationale="The request asks for an order record.",
                arguments={"query": query},
            )
        if "calculate" in lower or re.search(r"\d+\s*[+\-*/]\s*\d+", query):
            return Plan(
                tool="calculator",
                rationale="The request contains a bounded arithmetic expression.",
                arguments={"query": query},
            )
        return Plan(
            tool="query_rag",
            rationale="The request asks for tenant knowledge.",
            arguments={"query": query},
        )


class DeterministicResponseGenerator:
    """Response double that exposes approved, tenant-scoped results for assertions."""

    def generate(
        self,
        *,
        query: str,
        plan: Plan,
        tool_result: dict[str, Any],
        config: TenantAgentConfig,
    ) -> str:
        del query
        return (
            f"{config.persona}\n\n"
            f"Executed {plan.tool} within {config.tenant_id}: {tool_result}"
        )


@pytest.fixture
def workflow_dependencies() -> WorkflowDependencies:
    """Inject both model-dependent graph collaborators."""

    return WorkflowDependencies(
        planner=DeterministicPlanner(),
        response_generator=DeterministicResponseGenerator(),
    )
