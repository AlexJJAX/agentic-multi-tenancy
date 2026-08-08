"""Golden data must not lie about the tenant directory that owns it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval_harness.cli import load_cases


def test_rejects_tenant_mismatch_in_golden_directory(tmp_path: Path) -> None:
    tenant_dir = tmp_path / "tenant-A"
    tenant_dir.mkdir()
    (tenant_dir / "golden.jsonl").write_text(
        json.dumps(
            {
                "case_id": "crossed",
                "tenant_id": "tenant-B",
                "question": "secret",
                "expected_sections": ["x"],
                "expected_terms": ["y"],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="crosses tenant directory boundary"):
        load_cases(tmp_path)
