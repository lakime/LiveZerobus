"""Diagnostic: enumerate every Lakebase-ish resource this workspace exposes.

Run from your laptop (same DATABRICKS_HOST / auth the CLI uses):
    python scripts/list_lakebase.py

It prints every `list_*` method on `WorkspaceClient.database` and tries to
call each one, dumping the results. Whatever comes back non-empty is what
`generate_database_credential(instance_names=[...])` expects for
LAKEBASE_INSTANCE.
"""
from __future__ import annotations

import json
import traceback
from databricks.sdk import WorkspaceClient


def jdump(obj):
    try:
        return json.dumps(obj.as_dict(), indent=2, default=str)
    except Exception:
        return repr(obj)


def main() -> None:
    w = WorkspaceClient()
    print(f"Host: {w.config.host}")
    print(f"Auth type: {w.config.auth_type}")
    print()

    listers = sorted(m for m in dir(w.database) if m.startswith("list_"))
    print(f"Available list_* methods on w.database:\n  " + "\n  ".join(listers))
    print()

    for name in listers:
        print("=" * 72)
        print(f"# {name}()")
        print("=" * 72)
        try:
            fn = getattr(w.database, name)
            # All list methods are generators — materialize
            items = list(fn())
            if not items:
                print("  (empty)")
                continue
            for item in items:
                print(jdump(item))
                print("-" * 40)
        except TypeError as e:
            print(f"  needs args: {e}")
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            traceback.print_exc()
        print()


if __name__ == "__main__":
    main()
