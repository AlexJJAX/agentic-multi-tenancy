"""Read-only demo tools with tenant scope required outside model-controlled arguments."""

from __future__ import annotations

import ast
import operator
import re
from collections.abc import Callable
from typing import Any

ToolFunction = Callable[[str, str], dict[str, Any]]
ORDER_ID = re.compile(r"\b[A-Z]-\d{4}\b")

ORDERS = {
    "tenant-A": {
        "A-1001": {"order_id": "A-1001", "status": "paid", "amount": "89.00 GBP"},
        "A-1002": {
            "order_id": "A-1002",
            "status": "refund_pending",
            "amount": "32.50 GBP",
        },
    },
    "tenant-B": {
        "B-2001": {
            "order_id": "B-2001",
            "status": "payment_failed",
            "amount": "249.00 GBP",
        }
    },
}

KNOWLEDGE = {
    "tenant-A": {
        "source": "tenant-A/payments.md",
        "content": "Approved card refunds return to the original method within five business days.",
    },
    "tenant-B": {
        "source": "tenant-B/devices.md",
        "content": "A factory reset removes Wi-Fi settings and paired accounts.",
    },
}


def query_orders(tenant_id: str, query: str) -> dict[str, Any]:
    """Read only order IDs inside the trusted tenant partition."""

    records = ORDERS.get(tenant_id, {})
    match = ORDER_ID.search(query)
    selected = [records[match.group(0)]] if match and match.group(0) in records else []
    return {"tool": "query_orders", "records": selected}


def query_rag(tenant_id: str, _query: str) -> dict[str, Any]:
    """Return only the selected tenant's small demo knowledge source."""

    hit = KNOWLEDGE[tenant_id]
    return {"tool": "query_rag", "hits": [hit]}


_BINARY_OPERATORS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _calculate(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _calculate(node.left)
        right = _calculate(node.right)
        return _BINARY_OPERATORS[type(node.op)](left, right)
    raise ValueError("Calculator accepts only numbers and +, -, *, /")


def calculator(_tenant_id: str, query: str) -> dict[str, Any]:
    """Evaluate a bounded arithmetic expression without Python eval."""

    expression = re.sub(r"[^0-9+\-*/(). ]", "", query).strip()
    if not expression or len(expression) > 80:
        raise ValueError("No bounded arithmetic expression was supplied")
    parsed = ast.parse(expression, mode="eval")
    result = _calculate(parsed.body)
    return {"tool": "calculator", "expression": expression, "result": result}


TOOL_REGISTRY: dict[str, ToolFunction] = {
    "query_orders": query_orders,
    "query_rag": query_rag,
    "calculator": calculator,
}
