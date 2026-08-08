"""Tenant-specific graph construction, planning, approval, and execution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, TypedDict, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict, SecretStr

from orchestration.config import TenantAgentConfig, ToolName, load_tenant_config
from orchestration.settings import Settings, settings
from orchestration.tools import TOOL_REGISTRY, ToolFunction


class Plan(BaseModel):
    """Structured planner output validated before graph routing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool: ToolName
    rationale: str
    arguments: dict[str, str]


class AgentState(TypedDict, total=False):
    """Raw graph state; prompts/rendering are derived inside nodes."""

    tenant_id: str
    user_id: str
    query: str
    persona: str
    guardrails: list[str]
    plan: dict[str, Any]
    approved: bool
    denial_reason: str
    tool_result: dict[str, Any]
    response: str
    status: Literal["planning", "awaiting_approval", "denied", "complete"]


@dataclass(frozen=True)
class Principal:
    """Trusted identity context supplied by authentication, not by the query."""

    user_id: str
    tenant_id: str


class Planner(Protocol):
    """Create a structured plan from model-controlled request text."""

    def plan(self, query: str) -> Plan: ...


class ResponseGenerator(Protocol):
    """Render the approved tool result as a tenant-configured answer."""

    def generate(
        self,
        *,
        query: str,
        plan: Plan,
        tool_result: dict[str, Any],
        config: TenantAgentConfig,
    ) -> str: ...


class OpenAIPlanner:
    """Live OpenAI planner whose output is validated against ``Plan``."""

    def __init__(self, model: ChatOpenAI) -> None:
        self.model = model.with_structured_output(Plan)

    def plan(self, query: str) -> Plan:
        result = self.model.invoke(
            [
                SystemMessage(
                    content=(
                        "Select exactly one tool for the request. query_orders reads order "
                        "records, query_rag reads tenant knowledge, and calculator handles "
                        "bounded arithmetic. Tenant authorization is enforced after planning."
                    )
                ),
                HumanMessage(content=query),
            ]
        )
        return result if isinstance(result, Plan) else Plan.model_validate(result)


class OpenAIResponseGenerator:
    """Live OpenAI answer generation after capability approval and tool execution."""

    def __init__(self, model: ChatOpenAI) -> None:
        self.model = model

    def generate(
        self,
        *,
        query: str,
        plan: Plan,
        tool_result: dict[str, Any],
        config: TenantAgentConfig,
    ) -> str:
        response = self.model.invoke(
            [
                SystemMessage(
                    content=(
                        f"Persona: {config.persona}\n"
                        f"Guardrails: {'; '.join(config.guardrails)}\n"
                        "Answer only from the approved tenant-scoped tool result."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Request: {query}\n"
                        f"Approved plan: {plan.model_dump_json()}\n"
                        f"Tool result: {tool_result}"
                    )
                ),
            ]
        )
        content = response.content
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "\n".join(part for part in parts if part).strip()
        return str(content).strip()


@dataclass(frozen=True)
class WorkflowDependencies:
    """Model collaborators supplied live by the CLI or as doubles by tests."""

    planner: Planner
    response_generator: ResponseGenerator


def _live_dependencies(app_settings: Settings) -> WorkflowDependencies:
    api_key = app_settings.require_openai_api_key()
    model = ChatOpenAI(
        model=app_settings.openai_chat_model,
        api_key=SecretStr(api_key),
        timeout=app_settings.openai_timeout_seconds,
    )
    return WorkflowDependencies(
        planner=OpenAIPlanner(model),
        response_generator=OpenAIResponseGenerator(model),
    )


def build_tenant_workflow(
    principal: Principal,
    *,
    config_root: Path | None = None,
    tool_registry: dict[str, ToolFunction] | None = None,
    dependencies: WorkflowDependencies | None = None,
    app_settings: Settings | None = None,
) -> TenantWorkflow:
    """Compile a graph containing only nodes allowed for the authenticated tenant."""

    config = load_tenant_config(principal.tenant_id, config_root)
    selected_dependencies = dependencies or _live_dependencies(app_settings or settings)
    registry = tool_registry or TOOL_REGISTRY
    missing = set(config.allowed_tools).difference(registry)
    if missing:
        raise ValueError(f"Allowed tool implementation missing: {sorted(missing)}")

    def plan_node(state: AgentState) -> dict[str, Any]:
        plan = selected_dependencies.planner.plan(state["query"])
        return {"plan": plan.model_dump(), "status": "planning"}

    def enforce_capabilities(state: AgentState) -> dict[str, Any]:
        tool = str(state["plan"]["tool"])
        if tool not in config.allowed_tools:
            return {
                "denial_reason": (
                    f"{tool} is outside {config.tenant_id}'s declared capability set"
                ),
                "status": "denied",
            }
        return {"status": "awaiting_approval"}

    def route_after_enforcement(state: AgentState) -> str:
        return "finalize" if state.get("denial_reason") else "review_plan"

    def review_plan(state: AgentState) -> dict[str, Any]:
        if not config.require_plan_approval:
            return {"approved": True}
        decision = interrupt(
            {
                "action": "Approve this tenant-scoped plan",
                "tenant_id": config.tenant_id,
                "plan": state["plan"],
                "allowed_tools": list(config.allowed_tools),
                "guardrails": list(config.guardrails),
            }
        )
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else False
        return {
            "approved": approved,
            "denial_reason": "" if approved else "Plan rejected by reviewer",
            "status": "planning" if approved else "denied",
        }

    def route_after_review(state: AgentState) -> str:
        if not state.get("approved"):
            return "finalize"
        return str(state["plan"]["tool"])

    def tool_node(tool_name: str):  # type: ignore[no-untyped-def]
        def execute(state: AgentState) -> dict[str, Any]:
            result = registry[tool_name](state["tenant_id"], state["query"])
            return {"tool_result": result}

        return execute

    def finalize(state: AgentState) -> dict[str, Any]:
        if state.get("denial_reason"):
            return {
                "response": f"Blocked: {state['denial_reason']}.",
                "status": "denied",
            }
        response = selected_dependencies.response_generator.generate(
            query=state["query"],
            plan=Plan.model_validate(state["plan"]),
            tool_result=state.get("tool_result", {}),
            config=config,
        )
        return {"response": response, "status": "complete"}

    builder = (
        StateGraph(AgentState)
        .add_node("plan", plan_node)
        .add_node("enforce_capabilities", enforce_capabilities)
        .add_node("review_plan", review_plan)
        .add_node("finalize", finalize)
        .add_edge(START, "plan")
        .add_edge("plan", "enforce_capabilities")
        .add_conditional_edges(
            "enforce_capabilities",
            route_after_enforcement,
            ["review_plan", "finalize"],
        )
        .add_conditional_edges(
            "review_plan",
            route_after_review,
            [*config.allowed_tools, "finalize"],
        )
        .add_edge("finalize", END)
    )
    for tool_name in config.allowed_tools:
        builder.add_node(tool_name, tool_node(tool_name))
        builder.add_edge(tool_name, "finalize")
    graph = builder.compile(checkpointer=InMemorySaver())
    return TenantWorkflow(principal=principal, config=config, graph=graph)


@dataclass
class TenantWorkflow:
    """Small invoke/resume façade that always supplies the trusted identity context."""

    principal: Principal
    config: TenantAgentConfig
    graph: Any

    def start(self, *, query: str, thread_id: str) -> dict[str, Any]:
        """Run until completion, capability denial, or a human interrupt."""

        initial: AgentState = {
            "tenant_id": self.principal.tenant_id,
            "user_id": self.principal.user_id,
            "query": query,
            "persona": self.config.persona,
            "guardrails": list(self.config.guardrails),
            "approved": False,
            "denial_reason": "",
            "tool_result": {},
            "response": "",
            "status": "planning",
        }
        return cast(
            dict[str, Any],
            self.graph.invoke(
                initial,
                {"configurable": {"thread_id": thread_id}},
            ),
        )

    def resume(
        self,
        *,
        thread_id: str,
        approved: bool,
    ) -> dict[str, Any]:
        """Resume the same checkpoint with a reviewer decision."""

        return cast(
            dict[str, Any],
            self.graph.invoke(
                Command(resume={"approved": approved}),
                {"configurable": {"thread_id": thread_id}},
            ),
        )
