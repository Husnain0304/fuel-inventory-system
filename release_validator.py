"""Offline release checks. This file never connects to or changes the database."""
from __future__ import annotations
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
EXCLUDED = {"approvals.py", "notifications.py", "reports.py", "utils.py", "release_validator.py"}
REQUIRED = {"app.py", "database.py", "schema_bootstrap.py", "inventory_health.py", "storage_control.py", "stock_transit.py", "receipt_costing.py", "END_TO_END_TEST_GUIDE.md", "DEPLOYMENT_GUIDE.md", "ROLLBACK_GUIDE.md"}
FORBIDDEN = ("DELETE FROM transactions", "WIPE ALL TRANSACTION", "Bulk Delete Operations")

def main() -> int:
    failures=[]
    missing=sorted(name for name in REQUIRED if not (ROOT/name).exists())
    if missing: failures.append("Missing required files: "+", ".join(missing))
    for path in sorted(ROOT.glob("*.py")):
        if path.name in EXCLUDED: continue
        try: ast.parse(path.read_text(encoding="utf-8"),filename=path.name)
        except Exception as error: failures.append(f"{path.name}: {error}")
    searchable="\n".join(p.read_text(encoding="utf-8",errors="replace") for p in ROOT.glob("*.py") if p.name not in EXCLUDED)
    for phrase in FORBIDDEN:
        if phrase.lower() in searchable.lower(): failures.append(f"Unsafe legacy control remains: {phrase}")
    if failures:
        print("RELEASE VALIDATION FAILED")
        for failure in failures: print("-",failure)
        return 1
    print("RELEASE VALIDATION PASSED")
    print("Required files exist, Python source parses, and destructive legacy controls are absent.")
    return 0

if __name__=="__main__": sys.exit(main())
