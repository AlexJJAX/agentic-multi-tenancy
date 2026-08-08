# Repository Guidelines

## Project Structure & Module Organization

`app/` contains the FastAPI application. Keep HTTP routes in `app/api/`, business logic in `app/services/`, and retrieval/ingestion code in `app/rag/`. Shared settings, database setup, models, and Pydantic schemas live at the `app/` root. The browser UI is in `app/templates/index.html` and `app/static/`.

Tenant knowledge bases are Markdown files under `data/kb/<tenant-id>/`; preserve this boundary when adding content. `tests/` holds the pytest suite. Root-level `test_scores*.py` files are evaluation helpers, while `build_instructions/` contains the source product brief.

## Build, Test, and Development Commands

- `uv sync --all-extras` installs runtime and development dependencies.
- `cp .env.example .env` creates local configuration; set `OPENAI_API_KEY` before using live embeddings or chat.
- `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` starts the API and UI locally.
- `uv run pytest tests/ -v` runs the application test suite. Run a focused test with `uv run pytest tests/test_rag_isolation.py -v`.
- `uv run ruff check app tests` checks Python style and common errors.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations for public functions, `snake_case` for modules/functions/variables, and `PascalCase` for classes. Keep API handlers thin and place reusable behavior in services or RAG modules. Follow the surrounding import order and docstring style; run Ruff before proposing changes. Name tenant directories and IDs consistently (for example, `tenant-A`) and do not bypass tenant-scoped retrieval or citation checks.

## Testing Guidelines

Use pytest and name files `test_*.py`, test functions `test_*`, and test classes `Test*`. Add regression tests alongside the affected behavior. Tests must not depend on an OpenAI key: use mocks or fake embeddings as in `tests/test_rag_isolation.py`. Changes involving auth, ingestion, or retrieval must verify that data from one tenant cannot appear in another tenant's result.

## Commit & Pull Request Guidelines

This repository has no commits yet, so there is no established commit convention. Use concise imperative subjects, such as `Add tenant isolation test`. Keep each commit focused. Pull requests should explain the behavior change, list tests run, link relevant issues or requirements, and include UI screenshots for visual changes.

## Security & Configuration

Never commit `.env`, API keys, JWT secrets, or generated SQLite data. Use `.env.example` for documented defaults.

<!-- OPENWIKI:START -->

## OpenWiki

This repository uses OpenWiki for recurring code documentation. Start with `openwiki/quickstart.md`, then follow its links to architecture, workflows, domain concepts, operations, integrations, testing guidance, and source maps.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->
