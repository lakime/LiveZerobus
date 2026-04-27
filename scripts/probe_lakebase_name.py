"""Try every plausible LAKEBASE_INSTANCE value against generate_database_credential.

Whichever one returns a token without BadRequest is the answer.

Run on your laptop:
    python scripts/probe_lakebase_name.py
"""
from __future__ import annotations

from databricks.sdk import WorkspaceClient

CANDIDATES = [
    "myzerobus",                               # project name (most likely)
    "myzerobus-production",                    # project + branch
    "production",                              # branch name alone
    "066869af-64ad-4f81-89ce-854b7fdeeb15",    # project UUID
    "ep-frosty-flower-e2o5hjfp",               # endpoint subdomain (known to fail)
]


def main() -> None:
    w = WorkspaceClient()
    print(f"Authed as: {w.config.client_id}")
    print()
    for name in CANDIDATES:
        print(f"-> trying instance_name = {name!r}")
        try:
            cred = w.database.generate_database_credential(
                request_id="probe",
                instance_names=[name],
            )
            tok = cred.token or ""
            print(f"   SUCCESS — token len={len(tok)}, expires={cred.expiration_time}")
            print(f"   ### USE THIS VALUE ###  LAKEBASE_INSTANCE={name}")
        except Exception as e:
            print(f"   {type(e).__name__}: {e}")
        print()


if __name__ == "__main__":
    main()
