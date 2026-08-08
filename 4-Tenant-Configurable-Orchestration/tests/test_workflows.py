"""Capability construction, interrupt, resume, and isolation tests."""

from __future__ import annotations

from orchestration.graph import Principal, build_tenant_workflow


def test_tenant_a_graph_contains_only_declared_tool_nodes(workflow_dependencies) -> None:  # type: ignore[no-untyped-def]
    workflow = build_tenant_workflow(
        Principal(user_id="alice", tenant_id="tenant-A"),
        dependencies=workflow_dependencies,
    )
    nodes = set(workflow.graph.get_graph().nodes)
    assert {"query_orders", "query_rag"}.issubset(nodes)
    assert "calculator" not in nodes


def test_allowed_plan_pauses_then_executes_after_approval(workflow_dependencies) -> None:  # type: ignore[no-untyped-def]
    workflow = build_tenant_workflow(
        Principal(user_id="alice", tenant_id="tenant-A"),
        dependencies=workflow_dependencies,
    )
    paused = workflow.start(query="Show order A-1001", thread_id="approved-order")
    assert "__interrupt__" in paused
    assert paused["tool_result"] == {}
    payload = paused["__interrupt__"][0].value
    assert payload["plan"]["tool"] == "query_orders"
    assert payload["allowed_tools"] == ["query_orders", "query_rag"]

    completed = workflow.resume(thread_id="approved-order", approved=True)
    assert completed["status"] == "complete"
    assert completed["tool_result"]["records"][0]["order_id"] == "A-1001"
    assert "B-2001" not in completed["response"]


def test_rejected_plan_never_executes_tool(workflow_dependencies) -> None:  # type: ignore[no-untyped-def]
    workflow = build_tenant_workflow(
        Principal(user_id="bob", tenant_id="tenant-B"),
        dependencies=workflow_dependencies,
    )
    paused = workflow.start(query="Calculate 12 * 4", thread_id="rejected-calc")
    assert "__interrupt__" in paused
    rejected = workflow.resume(thread_id="rejected-calc", approved=False)
    assert rejected["status"] == "denied"
    assert rejected["tool_result"] == {}
    assert "Plan rejected" in rejected["response"]


def test_forbidden_tool_is_blocked_before_interrupt_or_execution(workflow_dependencies) -> None:  # type: ignore[no-untyped-def]
    workflow = build_tenant_workflow(
        Principal(user_id="bob", tenant_id="tenant-B"),
        dependencies=workflow_dependencies,
    )
    result = workflow.start(query="Show order B-2001", thread_id="forbidden-order")
    assert "__interrupt__" not in result
    assert result["status"] == "denied"
    assert result["tool_result"] == {}
    assert "outside tenant-B's declared capability set" in result["response"]


def test_tenant_b_rag_source_is_scoped_after_resume(workflow_dependencies) -> None:  # type: ignore[no-untyped-def]
    workflow = build_tenant_workflow(
        Principal(user_id="bob", tenant_id="tenant-B"),
        dependencies=workflow_dependencies,
    )
    workflow.start(query="What does a factory reset remove?", thread_id="tenant-b-rag")
    result = workflow.resume(thread_id="tenant-b-rag", approved=True)
    assert result["tool_result"]["hits"][0]["source"].startswith("tenant-B/")
    assert "tenant-A/" not in result["response"]
