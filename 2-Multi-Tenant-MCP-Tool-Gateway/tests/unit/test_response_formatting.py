"""Assistant answer formatting regression tests."""

from __future__ import annotations

import pytest

from app.agent.formatting import strip_inline_source_references


@pytest.mark.parametrize(
    ("answer", "expected"),
    (
        (
            "A soft reset preserves paired accounts. [source — Soft reset]",
            "A soft reset preserves paired accounts.",
        ),
        (
            "Perform a soft reset before trying again [source — Connectivity troubleshooting]. "
            "If that fails, use a factory reset [source — Factory reset].",
            "Perform a soft reset before trying again. If that fails, use a factory reset.",
        ),
        (
            "Refunds take 5–10 business days "
            "[knowledge/tenant-A.md — Refund timelines].",
            "Refunds take 5–10 business days.",
        ),
        (
            "A soft reset preserves paired accounts. [source — Soft reset]. Try again.",
            "A soft reset preserves paired accounts. Try again.",
        ),
        (
            "Order [A-1001] remains visible in [Advanced mode].",
            "Order [A-1001] remains visible in [Advanced mode].",
        ),
    ),
)
def test_inline_source_references_are_removed_without_damaging_prose(
    answer: str,
    expected: str,
) -> None:
    assert strip_inline_source_references(answer) == expected
