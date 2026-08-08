# Project 3 · Per-Tenant RAG Evals

![Tests](https://img.shields.io/badge/tests-6%20passing-2E7D32)
![Coverage](https://img.shields.io/badge/coverage-82%25-00796B)
![Isolation](https://img.shields.io/badge/isolation-100%25-512BD4)

This project evaluates the quality and safety of a per-tenant RAG (Retrieval-Augmented Generation) pipeline. Specifically, it measures four metrics:

| Metric                  | What it checks                                                                                                 |
| ----------------------- | -------------------------------------------------------------------------------------------------------------- |
| **Retrieval Recall**    | Did the top-k retrieved chunks contain at least one of the expected knowledge-base sections for the question?  |
| **Answer Coverage**     | Did the generated answer include the expected facts/phrases (e.g. "five business days", "original packaging")? |
| **Faithfulness**        | Is the answer grounded in the retrieved context? (token-overlap between the answer and the chunks)             |
| **Isolation Pass Rate** | Did every returned chunk belong to the correct tenant? (i.e. no cross-tenant data leakage)                     |

How it works

- Each tenant (tenant-A, tenant-B) has its own Markdown knowledge corpus in `knowledge/` and a golden JSONL dataset in `evals/` with question–expected-answer pairs.

- The `evaluator.py` runs two strategies:
  - a raw-query baseline
  - a contextual-rewrite candidate (using OpenAI to rewrite queries with conversation history)

  and reports per-tenant metrics so regressions in one tenant aren't hidden by global averages.

- The golden data covers realistic multi-turn scenarios like refund follow-ups, return policies, subscriptions, and payment methods.

- The core concern it's designed to prove is `tenant isolation`: that Tenant B's knowledge never leaks into Tenant A's answers, and vice versa — while also tracking whether retrieval and generation quality are actually good enough to be useful.

CI uses constructor-injected deterministic doubles so isolation and scoring regressions remain stable and do not consume API calls.

## Run it

```bash
uv sync --all-extras
cp .env.example .env
# Set OPENAI_API_KEY in .env before the live evaluation.
uv run tenant-evals
uv run pytest -v
uv run ruff check eval_harness tests
uv run python tests/run_regression.py
```

The live run compares a raw-query baseline with an OpenAI contextual-rewrite candidate and
writes the full evidence trail to [`reports/latest.json`](reports/latest.json). Every result
includes the selected tenant, retrieval query, chunk IDs, sections, generated answer, and
metric values.

## Checked-in deterministic regression result

| Strategy           | Tenant A recall | Tenant B recall | Overall recall | Faithfulness | Isolation |
| ------------------ | --------------: | --------------: | -------------: | -----------: | --------: |
| Raw query          |           50.0% |          100.0% |          75.0% |       100.0% |    100.0% |
| Contextual rewrite |           75.0% |          100.0% |      **87.5%** |       100.0% |    100.0% |

The injected rewrite double fixes one Tenant A retrieval while a payment-method question remains a
known top-1 lexical miss. This is the intended analytical signal: the aggregate improves by
12.5 percentage points, but the per-tenant view still identifies where the next retrieval
experiment should focus. The suite currently has **6 passing tests and 82% line coverage**.

## Dataset boundary

```text
evals/
├── tenant-A/golden.jsonl
└── tenant-B/golden.jsonl
```

The loader rejects a row whose `tenant_id` differs from its parent directory. Retrieval then
selects exactly one in-memory collection, and scoring checks every returned chunk ID and tenant
field again. Global averages never replace per-tenant results; an asymmetric regression remains
visible.

## What the metrics mean

- `retrieval_recall`: at least one expected section appeared in top-k.
- `answer_coverage`: expected facts or phrases occurred in the extractive answer.
- `faithfulness`: answer-token support in the retrieved context.
- `isolation_pass_rate`: every returned chunk belonged to the requested tenant.

See the generated report for the measured baseline and candidate numbers. They describe the
small checked-in corpus and injected test doubles—not production model quality. Run
`tenant-evals` with a real key to produce a live-model report.

The executed
[`per-tenant-retrieval-ablation.ipynb`](../output/jupyter-notebook/per-tenant-retrieval-ablation.ipynb)
compares heading-aware chunks with three fixed-window size/overlap combinations. It keeps the
tenant boundary constant while showing that the best retrieval configuration can differ
between an FAQ-style corpus and a technical manual.
