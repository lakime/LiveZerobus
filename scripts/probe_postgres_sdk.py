"""Diagnostic: explore the w.postgres API surface for Lakebase Autoscaling.

Run on your laptop:
    python3 scripts/probe_postgres_sdk.py
"""
from __future__ import annotations

import json
from databricks.sdk import WorkspaceClient


def main() -> None:
    w = WorkspaceClient()
    print(f"Authed as: {w.config.client_id}")
    print()

    # New Projects API lives under w.postgres (or similar name).
    # Print every top-level attr that looks like a service client.
    candidates = [a for a in dir(w) if not a.startswith("_") and a.lower() in (
        "postgres", "lakebase", "database_projects", "oltp"
    )]
    print("Candidate service attributes on WorkspaceClient:", candidates)
    print()

    for attr in candidates:
        svc = getattr(w, attr)
        print("=" * 72)
        print(f"w.{attr} — methods:")
        print("=" * 72)
        for m in sorted(dir(svc)):
            if not m.startswith("_"):
                print(f"  {m}")
        print()

        # Try listing projects
        for list_m in ("list_projects", "list"):
            fn = getattr(svc, list_m, None)
            if not callable(fn):
                continue
            try:
                items = list(fn())
                print(f"  {attr}.{list_m}() returned {len(items)} items:")
                for it in items:
                    try:
                        print(json.dumps(it.as_dict(), indent=2, default=str))
                    except Exception:
                        print(repr(it))
                    print("-" * 40)
            except Exception as e:
                print(f"  {attr}.{list_m}() raised: {type(e).__name__}: {e}")
            print()


if __name__ == "__main__":
    main()
