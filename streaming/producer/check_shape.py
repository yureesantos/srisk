"""Assert the generated stream reproduces the real export's shape.

This is branch 1's done criterion, not a smoke test. The producer is only useful
if its output exercises the metrics the same way real data does: a stream with
the right column types but the wrong distributions would give a Gini near zero,
fire no anomaly detector, and make every downstream measurement meaningless.

Ranges rather than equalities, deliberately. The SQL generator and this Python
one draw from different RNGs, so identical constants do not produce identical
distributions — only the same shape. The bands below are wide enough to allow
that and narrow enough to catch a genuine drift.

    python -m streaming.producer --count 300000 --sink stdout | \
        python -m streaming.producer.check_shape
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

# Reuse the batch pipeline's own Gini rather than reimplementing it: the number
# has to be comparable with the 0.803 measured there, and two implementations
# would be two things to trust.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "betflow"))
from src.betflow import gini_lorenz  # noqa: E402

# Measured on data/raw/ — the targets every band below is drawn around.
TARGET_GINI_EUR = 0.803
TARGET_MEDIAN_LEGS = 4
TARGET_CURRENCY = {"EUR": 0.880, "PEN": 0.118, "USD": 0.002}

BANDS = {
    "gini_eur": (0.78, 0.86),
    "median_legs_per_uid": (2, 8),
    "eur_share": (0.86, 0.90),
    "pen_share": (0.10, 0.14),
    "simple_share": (0.74, 0.82),
}


def main() -> int:
    turnover_by_uid: dict[str, float] = defaultdict(float)
    legs_by_uid: Counter = Counter()
    currency = Counter()
    bet_type = Counter()
    kinds = Counter()
    dims = {k: set() for k in ("competition", "fixture", "market", "player", "selection", "region")}
    reversal_signature_ok = 0
    reversal_total = 0
    rows = 0

    for line in sys.stdin:
        if not line.strip():
            continue
        e = json.loads(line)
        rows += 1
        kinds[e["event_kind"]] += 1
        currency[e["currency"]] += 1
        bet_type[e["bet_type"]] += 1
        for k in dims:
            dims[k].add(e[k])
        if e["currency"] == "EUR":
            turnover_by_uid[e["uid"]] += e["turnover"]
            legs_by_uid[e["uid"]] += 1
        if e["event_kind"] == "reversal":
            reversal_total += 1
            # The measured signature: 14 of 14 revised rows in the real export
            # had GGR equal to TURNOVER (ADR-0007).
            if abs(e["ggr"] - e["turnover"]) < 0.005:
                reversal_signature_ok += 1

    if not rows:
        print("no input", file=sys.stderr)
        return 2

    gini = gini_lorenz(np.array(list(turnover_by_uid.values())))["gini"]
    counts = np.array(sorted(legs_by_uid.values()))
    median_legs = float(np.median(counts))
    ratio = counts.max() / max(median_legs, 1)

    measured = {
        "gini_eur": gini,
        "median_legs_per_uid": median_legs,
        "eur_share": currency["EUR"] / rows,
        "pen_share": currency["PEN"] / rows,
        "simple_share": bet_type["SIMPLE"] / rows,
    }

    print(f"events            {rows:,}")
    print(f"distinct uids     {len(legs_by_uid):,} (EUR)")
    print(f"max/median legs   {ratio:,.0f}x   (export: 560x)")
    print(f"reversals         {reversal_total:,}  signature ok: {reversal_signature_ok:,}")
    for name, count in sorted(dims.items()):
        print(f"cardinality {name:<12} {len(count):,}")
    print()

    failures = []
    for key, (lo, hi) in BANDS.items():
        value = measured[key]
        ok = lo <= value <= hi
        print(f"{'PASS' if ok else 'FAIL'}  {key:<22} {value:>8.3f}  band [{lo}, {hi}]")
        if not ok:
            failures.append(key)

    if reversal_total and reversal_signature_ok != reversal_total:
        print(f"FAIL  reversal signature: {reversal_signature_ok}/{reversal_total} have ggr == turnover")
        failures.append("reversal_signature")

    print()
    if failures:
        print(f"SHAPE CHECK FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("SHAPE CHECK PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
