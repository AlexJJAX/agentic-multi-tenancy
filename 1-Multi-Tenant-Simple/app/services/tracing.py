"""Secret-free LangSmith/LangChain trace metadata for the RAG request path."""

from langchain_core.runnables import RunnableConfig


def trace_config(
    *,
    tenant_id: str,
    session_id: str,
    stage: str,
) -> RunnableConfig:
    """Return correlation metadata inherited by traced LangChain runnables."""

    return {
        "run_name": f"tenant-rag-{stage}",
        "tags": ["multi-tenant-rag", stage, tenant_id],
        "metadata": {
            "tenant_id": tenant_id,
            "session_id": session_id,
            "stage": stage,
        },
    }
