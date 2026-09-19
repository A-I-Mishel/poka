"""Dump router fallthrough stats (scrubbed, no PII) for vocab mining.

Usage: python scripts/mine_fallthrough.py [--limit 50]
Read-only: prints total/routed/fallthrough + top scrubbed patterns.
Add missing verbs/synonyms to services/normalize.py, not ad-hoc keyword lists.
"""

import argparse
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.router import get_fallthrough_stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    stats = get_fallthrough_stats(limit=args.limit)
    print(f"total={stats['total']} fallthrough={stats['fallthrough']}")
    for pattern, count in stats.get("top", []):
        print(f"{count:5d}  {pattern}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
