# MCP evaluation profile

`tenant_a_gateway.xml` contains ten independent, read-only, stable questions verified against
the checked-in seed data. The automated runner boots the complete ASGI application with
explicitly injected deterministic embedding and chat doubles, authenticates as
`alice@tenant-a.demo`, and exercises the same chat → gateway → target → store boundaries as
the browser:

```bash
uv run python scripts/run_evals.py
```

It writes an exact-match report to `evaluations/results/latest.json` and exits non-zero when
any expected answer changes. No bearer token, runtime key, or database is written to the repo.
Use the normal live runtime separately when measuring model variability; the checked-in report
is explicitly the injected-double regression baseline, not a claim about a hosted model.

The questions deliberately require filtering, comparison, aggregation, or synthesis across
`query_orders` and `query_properties`. They never require writes and their answers remain stable
until the explicit seed fixtures change.
