"""Run one tenant-configured plan and optionally approve it."""

from __future__ import annotations

import argparse
import json
from uuid import uuid4

from orchestration.graph import Principal, build_tenant_workflow


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant", choices=["tenant-A", "tenant-B"], required=True)
    parser.add_argument("--user", default="local-demo-user")
    parser.add_argument("--query", required=True)
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()

    workflow = build_tenant_workflow(
        Principal(user_id=args.user, tenant_id=args.tenant)
    )
    thread_id = str(uuid4())
    result = workflow.start(query=args.query, thread_id=thread_id)
    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value
        print(json.dumps(payload, indent=2))
        if not args.approve:
            print("Plan paused. Re-run with --approve to demonstrate an approved execution.")
            return 0
        result = workflow.resume(thread_id=thread_id, approved=True)
    print(result["response"])
    return 0 if result["status"] != "denied" else 2


if __name__ == "__main__":
    raise SystemExit(main())
