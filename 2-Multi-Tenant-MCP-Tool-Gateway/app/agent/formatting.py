"""Presentation-safe formatting for assistant answer text."""

from __future__ import annotations

import re

INLINE_SOURCE_REFERENCE_PATTERN = re.compile(
    r"\[(?:source|[^\]\n]*\.(?:md|markdown|txt))\s*(?:—|–|-|:)\s*[^\]\n]+\]"
    r"(?P<trailing>[.,;:]?)",
    re.IGNORECASE,
)


def strip_inline_source_references(answer: str) -> str:
    """Remove redundant source labels while preserving surrounding prose punctuation."""

    def replacement(match: re.Match[str]) -> str:
        trailing = match.group("trailing")
        prefix = answer[: match.start()].rstrip()
        previous = prefix[-1] if prefix else ""
        if trailing and previous not in ".!?;:":
            return trailing
        return ""

    cleaned = INLINE_SOURCE_REFERENCE_PATTERN.sub(replacement, answer)
    cleaned = re.sub(r"[ \t]+([.,;:!?])", r"\1", cleaned)
    cleaned = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", cleaned)
    return "\n".join(line.rstrip() for line in cleaned.splitlines()).strip()
