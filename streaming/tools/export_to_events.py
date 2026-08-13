"""Turn a real xlsx export into the event stream the consumer reads.

This exists so both paths can be fed the *same* input: the batch pipeline reads
the export directly, the streaming path reads these events. Any divergence in the
resulting artifacts is then attributable to the pipeline, not to the data.

`emitted_at` — the version, per ADR-0007 — comes from the export filename's
timestamp (`...-24062026_051729.xlsx` -> 05:17:29 on 24/06/2026). That is the
same source snapshot time the mutability finding rests on: the two exports were
generated 95 seconds apart, and the later one's rows supersede the earlier's.

    python streaming/tools/export_to_events.py data/raw/excel_*051729.xlsx > /tmp/export.ndjson
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "betflow"))

from src.load import read_export  # noqa: E402

FILENAME_STAMP = re.compile(r"-(\d{2})(\d{2})(\d{4})_(\d{2})(\d{2})(\d{2})")


def version_from_filename(path: Path) -> int:
    """`...-24062026_051729.xlsx` -> epoch ms for 2026-06-24 05:17:29 UTC."""
    match = FILENAME_STAMP.search(path.name)
    if not match:
        return 0
    day, month, year, hour, minute, second = (int(g) for g in match.groups())
    stamp = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return int(stamp.timestamp() * 1000)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("exports", nargs="+", type=Path)
    args = parser.parse_args()

    written = 0
    for path in args.exports:
        version = version_from_filename(path)
        frame = read_export(path)

        # Column access by name: the export's headers contain spaces and
        # parentheses, so itertuples would rename them positionally (`_9`, `_11`)
        # and a column reorder upstream would silently swap fields.
        for record in frame.to_dict(orient="records"):
            placed = record["Betslip date (utc)"]
            event = record["Event date (utc)"]
            if placed is None or str(placed) == "NaT":
                continue
            if str(event) == "NaT":
                event = placed

            sys.stdout.write(
                json.dumps(
                    {
                        "uid": str(record["Uid"]),
                        "placed_at": placed.isoformat(timespec="milliseconds"),
                        "event_at": event.isoformat(timespec="milliseconds"),
                        "bet_type": str(record["BetType"]),
                        "match_id": int(record["MatchId"]),
                        "fixture": str(record["MATCH"]),
                        "competition": str(record["Competition"]),
                        "market": str(record["Market"]),
                        "player": str(record["Player"]),
                        "selection": str(record["Option"]),
                        # `region` carries the raw Management unit: `_enrich`
                        # normalises it downstream, exactly as for the batch path.
                        "region": str(record["Management unit"]),
                        "currency": str(record["Currency Code"]),
                        "price": float(record["Price"]),
                        "turnover": float(record["TURNOVER"]),
                        "ggr": float(record["GGR"]),
                        "net_revenue": float(record["Net Revenue"]),
                        "event_kind": "placement",
                        "source": path.name,
                        # Derived, not defaulted. Writing 0 here classified all
                        # 5,539 in-play legs as pre-match, which silently
                        # inflated the sharp test's scoring units by 5.2%: an
                        # in-play leg has no valid pre-kick-off reference, so it
                        # must not enter a price-reference group (ADR-0005).
                        "is_inplay": int(placed > event),
                        "minutes_to_kickoff": round(
                            (placed - event).total_seconds() / 60.0, 2
                        ),
                        # The version (ADR-0007): source snapshot time, taken
                        # from the export filename. Rows from the later export
                        # supersede the earlier one's by carrying a higher value.
                        "emitted_at": version,
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )
            written += 1

        print(f"{path.name}: {written:,} events (version {version})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
