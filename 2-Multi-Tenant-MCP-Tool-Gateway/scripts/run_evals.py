#!/usr/bin/env python3
"""Run the stable Tenant A profile with explicitly injected model test doubles."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.lifespan import RuntimeDependencies  # noqa: E402
from app.main import create_app  # noqa: E402
from app.settings import Settings  # noqa: E402
from scripts.test_doubles import (  # noqa: E402
    DeterministicChatBackend,
    DeterministicEmbeddings,
)


def _normalize(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def load_profile(path: Path) -> list[tuple[str, str]]:
    """Parse independent question/answer pairs from the checked-in XML profile."""

    # The profile is checked into this repository and is not user-controlled.
    root = ElementTree.parse(path).getroot()  # noqa: S314
    cases: list[tuple[str, str]] = []
    for pair in root.findall("qa_pair"):
        question = pair.findtext("question", default="").strip()
        answer = pair.findtext("answer", default="").strip()
        if not question or not answer:
            raise ValueError("Each qa_pair must contain a non-empty question and answer")
        cases.append((question, answer))
    return cases


def run(profile: Path) -> dict[str, object]:
    """Execute the real identity, chat, gateway, target, store, and audit paths."""

    results: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="multi-tenant-evals-") as temporary:
        runtime = Path(temporary)
        settings = Settings(
            _env_file=None,
            testing=True,
            openai_api_key="",
            sqlite_path=runtime / "demo.db",
            identity_private_key_path=runtime / "keys" / "identity_private.pem",
            identity_public_key_path=runtime / "keys" / "identity_public.pem",
            gateway_capability_private_key_path=runtime / "keys" / "gateway_private.pem",
            gateway_capability_public_key_path=runtime / "keys" / "gateway_public.pem",
            log_level="WARNING",
        )
        dependencies = RuntimeDependencies(
            embeddings=DeterministicEmbeddings(),
            chat_backend=DeterministicChatBackend(),
        )
        with TestClient(
            create_app(settings, runtime_dependencies=dependencies),
            base_url="http://localhost:8000",
        ) as client:
            login = client.post(
                "/auth/login",
                json={"username": "alice@tenant-a.demo", "password": "alice-demo"},
            )
            login.raise_for_status()
            session = client.post("/api/sessions", json={"title": "Automated eval"}).json()
            for index, (question, expected) in enumerate(load_profile(profile), start=1):
                response = client.post(
                    "/api/chat",
                    json={"session_id": session["session_id"], "message": question},
                )
                response.raise_for_status()
                payload = response.json()
                actual = str(payload["answer"])
                results.append(
                    {
                        "case": index,
                        "question": question,
                        "expected": expected,
                        "actual": actual,
                        "passed": _normalize(actual) == _normalize(expected),
                        "tools": payload["trace"]["tools"],
                        "source_count": len(payload["sources"]),
                    }
                )

    passed = sum(bool(item["passed"]) for item in results)
    total = len(results)
    return {
        "profile": str(profile.relative_to(PROJECT_ROOT)),
        "mode": "deterministic-injected-test-doubles",
        "generated_at": datetime.now(UTC).isoformat(),
        "metrics": {
            "passed": passed,
            "total": total,
            "exact_match": round(passed / total, 4) if total else 0.0,
        },
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        type=Path,
        default=PROJECT_ROOT / "evaluations" / "tenant_a_gateway.xml",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "evaluations" / "results" / "latest.json",
    )
    args = parser.parse_args()

    report = run(args.profile.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    metrics = report["metrics"]
    print(
        f"Exact match: {metrics['passed']}/{metrics['total']} "
        f"({float(metrics['exact_match']):.0%})"
    )
    print(f"Report: {args.output}")
    return 0 if metrics["passed"] == metrics["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
