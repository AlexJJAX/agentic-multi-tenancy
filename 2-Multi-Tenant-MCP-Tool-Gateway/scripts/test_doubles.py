"""Deterministic OpenAI dependency doubles for tests and automated evaluations."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from langchain_core.embeddings import Embeddings

from app.agent.rag import RAGHit
from app.gateway.routing import GatewayRouter
from app.shared.models import Principal
from app.targets.orders.service import QueryOrdersInput
from app.targets.properties.service import QueryPropertiesInput

WORD_PATTERN = re.compile(r"[a-z0-9]+")
ORDER_ID_PATTERN = re.compile(r"\b[A-Z]-\d{4}\b")
PROPERTY_ID_PATTERN = re.compile(r"\bP[A-Z]-\d{3}\b")


class DeterministicEmbeddings(Embeddings):
    """Token-hash embedding double that never performs network I/O."""

    dimensions = 384

    @classmethod
    def _embed(cls, text: str) -> list[float]:
        vector = [0.0] * cls.dimensions
        for token in WORD_PATTERN.findall(text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % cls.dimensions
            vector[index] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


def _synthesize(
    message: str,
    *,
    order_records: list[dict[str, Any]],
    property_records: list[dict[str, Any]],
) -> str | None:
    lower = message.lower()
    if order_records and "smallest amount" in lower:
        return str(min(order_records, key=lambda item: Decimal(item["amount"]))["order_id"])
    if order_records and "updated most recently" in lower:
        return str(max(order_records, key=lambda item: item["updated_at"])["order_id"])
    if property_records and "neither active nor inactive" in lower:
        match = next(
            (item for item in property_records if item["status"] not in {"active", "inactive"}),
            None,
        )
        return str(match["city"]) if match else ""
    if property_records and "comes first by property id" in lower:
        active = [item for item in property_records if item["status"] == "active"]
        return str(min(active, key=lambda item: item["property_id"])["property_id"])
    if order_records and "sum the monetary amounts" in lower:
        total = sum((Decimal(item["amount"]) for item in order_records), start=Decimal("0"))
        return f"{total:.2f}"
    if property_records and "distinct cities" in lower:
        return str(len({item["city"] for item in property_records}))
    if order_records and property_records and "are the counts equal" in lower:
        order_count = sum(
            item["status"] in {"paid", "refunded", "returned"} for item in order_records
        )
        property_count = sum(
            item["status"] in {"active", "inactive"} for item in property_records
        )
        return str(order_count == property_count)
    if order_records and "calendar days separate" in lower:
        dates = [
            datetime.fromisoformat(str(item["updated_at"]).replace("Z", "+00:00")).date()
            for item in order_records
        ]
        return str((max(dates) - min(dates)).days)
    if order_records and property_records and "waiting on a refund" in lower:
        order = next(item for item in order_records if item["status"] == "refund_pending")
        property_record = next(
            item for item in property_records if item["status"] == "maintenance"
        )
        return f"{order['order_id']}/{property_record['property_id']}"
    if order_records and "paid or refunded status" in lower and "larger amount" in lower:
        eligible = [
            item for item in order_records if item["status"] in {"paid", "refunded"}
        ]
        return str(max(eligible, key=lambda item: Decimal(item["amount"]))["status"])
    return None


class DeterministicChatBackend:
    """Chat backend double that still exercises the real tenant-scoped gateway."""

    async def respond(
        self,
        *,
        principal: Principal,
        message: str,
        hits: list[RAGHit],
        history: list[dict[str, Any]],
        request_id: str,
        gateway_router: GatewayRouter,
    ) -> tuple[str, list[dict[str, Any]], list[str]]:
        del history
        tool_sources: list[dict[str, Any]] = []
        tools: list[str] = []
        answer_parts: list[str] = []
        order_records: list[dict[str, Any]] = []
        property_records: list[dict[str, Any]] = []
        order_match = ORDER_ID_PATTERN.search(message)
        property_match = PROPERTY_ID_PATTERN.search(message)
        lower = message.lower()
        if order_match or "order" in lower:
            result = await gateway_router.query_orders(
                principal=principal,
                arguments=QueryOrdersInput(order_id=order_match.group(0) if order_match else None),
                request_id=request_id,
            )
            tools.append("query_orders")
            order_records = result["records"]
            ids = [record["order_id"] for record in order_records]
            tool_sources.append({"type": "tool", "name": "query_orders", "record_ids": ids})
            if order_records:
                rendered = "; ".join(
                    f"{record['order_id']} is {record['status']} "
                    f"({record['amount']} {record['currency']})"
                    for record in order_records
                )
                answer_parts.append(f"Order records: {rendered}.")
            else:
                answer_parts.append("No matching order record is visible to this account.")
        if property_match or "property" in lower or "properties" in lower:
            result = await gateway_router.query_properties(
                principal=principal,
                arguments=QueryPropertiesInput(
                    property_id=property_match.group(0) if property_match else None
                ),
                request_id=request_id,
            )
            tools.append("query_properties")
            property_records = result["records"]
            ids = [record["property_id"] for record in property_records]
            tool_sources.append(
                {"type": "tool", "name": "query_properties", "record_ids": ids}
            )
            if property_records:
                rendered = "; ".join(
                    f"{record['property_id']} — {record['name']}, {record['city']} "
                    f"({record['status']})"
                    for record in property_records
                )
                answer_parts.append(f"Visible property records: {rendered}.")
            else:
                answer_parts.append("No matching property record is visible to this account.")
        synthesized = _synthesize(
            message,
            order_records=order_records,
            property_records=property_records,
        )
        if synthesized is not None:
            answer_parts = [synthesized]
        elif not answer_parts:
            if hits:
                hit = hits[0]
                answer_parts.append(f"{hit.content}\n\n[{hit.source} — {hit.section}]")
            else:
                answer_parts.append(
                    "The tenant knowledge base does not contain enough information."
                )
        return "\n\n".join(answer_parts), tool_sources, tools
