"""Validate catalog/fault_catalog.yaml against the raw_logs schema contract.

The fault catalog is a Single Source of Truth shared by the simulator (T6) and
the detector (T8). Its signatures may ONLY reference sensors that exist as
raw_logs columns (eng-review D3) — otherwise the detector cannot match them.
This script catches drift between the catalog and that schema contract.

Run (Windows venv; clear the global VLibras PYTHONPATH first — see CLAUDE notes):
    $env:PYTHONPATH=""; .venv\\Scripts\\python.exe -s scripts\\validate_catalog.py

Checks:
  - every signature `sensor` is a declared sensor_column (== raw_logs sensor cols)
  - referenced rag_docs files exist under docs/rag_sources/
  - severity levels use the raw_logs.status vocabulary (경고/오류/위험)
  - each fault / correlated scenario declares a fingerprint_type (D5 멱등 key)
Exits non-zero on any failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

# Windows consoles default to cp949; force UTF-8 so Korean text / symbols in
# diagnostics don't raise UnicodeEncodeError and abort the run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "fault_catalog.yaml"
RAG_DIR = ROOT / "docs" / "rag_sources"
VALID_LEVELS = {"경고", "오류", "위험"}


def main() -> int:
    data = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    sensors = set(data["sensor_columns"])
    errors: list[str] = []
    warnings: list[str] = []

    def check_sig(sig_list, where: str) -> None:
        for s in sig_list:
            if s["sensor"] not in sensors:
                errors.append(f"{where}: unknown sensor '{s['sensor']}' (not in sensor_columns)")

    def check_docs(docs, where: str) -> None:
        for d in docs or []:
            if not (RAG_DIR / d).exists():
                errors.append(f"{where}: rag_doc '{d}' missing under docs/rag_sources/")

    def check_levels(items, where: str) -> None:
        for it in items or []:
            lvl = it.get("level")
            if lvl and lvl not in VALID_LEVELS:
                errors.append(f"{where}: invalid level '{lvl}' (use 경고/오류/위험)")

    faults = data.get("faults", [])
    for f in faults:
        w = f"fault[{f['id']}]"
        if not f.get("fingerprint_type"):
            errors.append(f"{w}: missing fingerprint_type")
        check_sig(f["detection"]["signature"], w)
        check_docs(f.get("rag_docs"), w)
        for key, val in f.items():
            if key.startswith("severity_by_"):
                check_levels(val, f"{w}.{key}")
        if not f.get("rag_docs") and not f.get("rag_docs_pending"):
            warnings.append(f"{w}: no rag_docs and no rag_docs_pending")

    correlated = data.get("correlated_scenarios", [])
    for c in correlated:
        w = f"correlated[{c['id']}]"
        if not c.get("fingerprint_type"):
            errors.append(f"{w}: missing fingerprint_type")
        for p in c["detection"]["participants"]:
            check_sig(p["signature"], f"{w}/{p['device_type']}")
        check_docs(c.get("rag_docs"), w)
        sev = c.get("severity")
        if sev and sev not in VALID_LEVELS:
            errors.append(f"{w}: invalid severity '{sev}'")

    print(f"catalog: {CATALOG.relative_to(ROOT).as_posix()}")
    print(f"sensor_columns={len(sensors)}  faults={len(faults)}  correlated={len(correlated)}")
    fp = [f["fingerprint_type"] for f in faults] + [c["fingerprint_type"] for c in correlated]
    print(f"fingerprint_types: {fp}")
    pending = sum(len(f.get("rag_docs_pending", [])) for f in faults) + sum(
        len(c.get("rag_docs_pending", [])) for c in correlated
    )
    print(f"rag_docs_pending (for T3): {pending}")
    for wmsg in warnings:
        print(f"  WARN  {wmsg}")
    if errors:
        for e in errors:
            print(f"  FAIL  {e}")
        print(f"\n{len(errors)} error(s).")
        return 1
    print("\nOK - catalog is consistent with the raw_logs schema contract.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
