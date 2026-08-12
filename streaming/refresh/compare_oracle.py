"""Compare the streaming artifact against the batch pipeline's, section by section.

The batch pipeline is the oracle: same input, same numbers, or one of them is
wrong. This is branch 3's done criterion.

The comparison is run over **one export** rather than both. The two files in
`data/raw/` overlap and disagree on 14 rows (ADR-0007), and the batch loader
resolves that overlap with file-level dedup while the streaming path resolves it
by identity and version. Comparing over the union would conflate two different
and both-correct semantics; comparing over one file removes the ambiguity
instead of arguing about it.

    python streaming/refresh/compare_oracle.py \\
        --batch /tmp/oracle_out/artifacts --streaming /tmp/stream_out/artifacts

Divergences are printed, not summarised: the point is to name exactly which
section disagrees, so a failure is a bisection rather than a debugging session.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

# Keys that are expected to differ and are not evidence of anything: they
# describe the run rather than the data.
IGNORED_KEYS = {
    "generated_at",
    "payload_hash",
    "dataset_fingerprint",
    "watermark",
    "rows_stored",
    "identities",
    "pending_supersedence",
    "source",
    "timing",
    "environment",
    "notes",
    "note",
    "sections",
    "schema_version",
    "artifact",
}

# Float comparison tolerance. Money is compared to the cent; statistics to 1e-9,
# which is well inside float noise but far outside a genuine methodological
# difference.
MONEY_TOLERANCE = 0.01
STAT_TOLERANCE = 1e-9


def load_artifacts(directory: Path) -> dict:
    payload = {}
    for path in sorted(directory.glob("*.json")):
        content = json.loads(path.read_text())
        payload[path.stem] = content.get("data", content)
    return payload


def compare(a, b, path: str, divergences: list) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key in IGNORED_KEYS:
                continue
            if key not in a:
                divergences.append((f"{path}.{key}", "missing in batch", b[key]))
            elif key not in b:
                divergences.append((f"{path}.{key}", a[key], "missing in streaming"))
            else:
                compare(a[key], b[key], f"{path}.{key}", divergences)
        return

    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            divergences.append((f"{path}[]", f"{len(a)} rows", f"{len(b)} rows"))
            return
        for index, (x, y) in enumerate(zip(a, b)):
            compare(x, y, f"{path}[{index}]", divergences)
        return

    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if isinstance(a, bool) or isinstance(b, bool):
            if a != b:
                divergences.append((path, a, b))
            return
        if math.isnan(a) and math.isnan(b):
            return
        tolerance = MONEY_TOLERANCE if abs(a) > 1000 else STAT_TOLERANCE
        if abs(a - b) > tolerance:
            divergences.append((path, a, b))
        return

    if a != b:
        divergences.append((path, a, b))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", type=Path, required=True)
    parser.add_argument("--streaming", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=40, help="divergences to print")
    args = parser.parse_args()

    batch = load_artifacts(args.batch)
    streaming = load_artifacts(args.streaming)

    print(f"batch artifacts     {sorted(batch)}")
    print(f"streaming artifacts {sorted(streaming)}")
    print()

    total = 0
    for section in sorted(set(batch) | set(streaming)):
        if section == "meta":
            continue
        if section not in batch or section not in streaming:
            print(f"  {section:<16} MISSING on one side")
            total += 1
            continue
        divergences: list = []
        compare(batch[section], streaming[section], section, divergences)
        status = "MATCH" if not divergences else f"{len(divergences)} divergences"
        print(f"  {section:<16} {status}")
        for entry in divergences[: args.limit]:
            print(f"      {entry[0]}\n        batch:     {entry[1]}\n        streaming: {entry[2]}")
        if len(divergences) > args.limit:
            print(f"      ... {len(divergences) - args.limit} more")
        total += len(divergences)

    print()
    if total:
        print(f"ORACLE COMPARISON: {total} divergences")
        return 1
    print("ORACLE COMPARISON: identical")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
