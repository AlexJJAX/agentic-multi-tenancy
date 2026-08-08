"""Injected deterministic inference dependencies for the pytest suite."""

from __future__ import annotations

import pytest

from eval_harness.evaluator import EvaluationDependencies
from tests.doubles import deterministic_dependencies


@pytest.fixture
def evaluation_dependencies() -> EvaluationDependencies:
    """Inject all inference collaborators used by evaluation tests."""

    return deterministic_dependencies()
