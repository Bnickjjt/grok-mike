#!/usr/bin/env python3
"""SHA-gated install of grok-mike skills + runtime for Mike importers."""
from __future__ import annotations
import argparse, hashlib, json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = json.loads((ROOT / "EXPECTED_SHA256.json").read_text(encoding="utf-8"))

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()

def sha256_text(p: Path) -> str:
    return hashlib.sha256(p.read_text(encoding="utf-8").encode("utf-8")).hexdigest()

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workflows", required=True, help="Importer workflows directory")
    ap.add_argument("--mike-root", required=True, help="Destination mike-v1 root")
    args = ap.parse_args()
    wf = Path(args.workflows)
    mike = Path(args.mike_root)
    ok = True

    for name, exp in EXPECTED.items():
        if name.startswith("mike-v1-"):
            src = ROOT / "skills" / name / "SKILL.md"
            got = sha256_text(src)
            if got != exp:
                print(f"FAIL skill {name}: {got} != {exp}")
                ok = False
                continue
            dest = wf / name / "SKILL.md"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            print(f"ok skill {name}")
        else:
            src = ROOT / name
            got = sha256_file(src)
            if got != exp:
                print(f"FAIL file {name}: {got} != {exp}")
                ok = False
                continue
            dest = mike / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            print(f"ok file {name}")

    print("BOOTSTRAP_OK" if ok else "BOOTSTRAP_FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
