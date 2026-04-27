"""Diagnostic: hit the Lakebase REST API directly and dump every
project / branch / instance the caller can see.

Run on your laptop:
    python scripts/list_lakebase_rest.py
"""
from __future__ import annotations

import json
import sys

from databricks.sdk import WorkspaceClient


def who_am_i(w: WorkspaceClient) -> None:
    try:
        me = w.current_user.me()
        print(f"Authed as user:    {me.user_name}  (id={me.id})")
    except Exception as e:
        print(f"current_user.me() failed: {e}")

    # If this is an SP, show the client_id
    try:
        cfg = w.config
        print(f"Host:              {cfg.host}")
        print(f"Auth type:         {cfg.auth_type}")
        print(f"Client ID (if SP): {getattr(cfg, 'client_id', None)}")
    except Exception:
        pass
    print()


def try_get(w: WorkspaceClient, path: str) -> None:
    print("=" * 72)
    print(f"GET {path}")
    print("=" * 72)
    try:
        res = w.api_client.do("GET", path)
        print(json.dumps(res, indent=2, default=str))
    except Exception as e:
        print(f"  {type(e).__name__}: {e}")
    print()


def main() -> None:
    w = WorkspaceClient()
    who_am_i(w)

    # Every Lakebase-ish REST path I know of — some will 404 or 403,
    # that's fine, we're fishing.
    for path in [
        "/api/2.0/database/instances",
        "/api/2.0/database/projects",
        "/api/2.0/database/synced_tables",
        "/api/2.0/database/catalogs",
        "/api/2.0/lakebase/projects",
        "/api/2.0/lakebase/instances",
    ]:
        try_get(w, path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
