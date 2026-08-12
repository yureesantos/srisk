"""Refresh job: collapsed table -> the same artifact the batch pipeline emits.

    python -m streaming.refresh --once --out /tmp/streaming_out/artifacts
    python -m streaming.refresh --interval 5

The analysis is **not** reimplemented. ClickHouse collapses and projects; the
frame then goes through the batch pipeline's own `_enrich` and `build_payload`,
so `prices.analyse`, `betflow.analyse` and `sharp.analyse` run unchanged. What
this module owns is the adapter, the freshness envelope, and the hash.

Freshness (ADR-0009): the batch guarantee was "this artifact is reproducible from
this dataset", resting on the input being frozen. Its streaming form is "this
artifact is reproducible by replaying the stream to this watermark" — the same
promise with the input identified by position rather than by file. The envelope
therefore carries a watermark where the batch payload carried a dataset
fingerprint.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "betflow"))

from src import pipeline as batch  # noqa: E402
from src.load import _enrich  # noqa: E402

from .source import DEFAULT_URL, read_legs, watermark  # noqa: E402

# Per-class refresh cadence, ADR-0009. The costs below are measured on 76,603
# collapsed rows and are the reason the classes are computed separately rather
# than in one pass:
#
#   class 1  enrich + betslip frame + breakdowns + timing     0.59s
#   class 2  + prices.analyse                                 0.18s
#   class 3  + betflow anomalies/concentration + sharp        3.30s   (sharp alone 2.24s)
#
# Running all three every tick costs 4.6s, which does not fit class 1's 1-5s
# cadence — so the cheapest and most-watched numbers would be paced by the most
# expensive one. Worse, it buys nothing: a Gini over a closed window does not
# move because twenty new bets arrived, so recomputing it every five seconds
# spends 2.24s to produce the same figure.
# `data_quality` sits in class 2 rather than class 1 because it reports on price
# coverage, so it needs `prices.analyse` to have run. Classification follows what
# a section actually depends on, not where it appears on screen.
CLASS_ARTIFACTS = {
    1: ("overview", "flow", "timing"),
    2: ("prices", "data_quality"),
    3: ("concentration", "anomalies", "sharp"),
}

# Default cadence per class, seconds. Class 2 is bounded below by the measured
# 95-second settlement churn (ADR-0007): refreshing GGR faster reports noise.
CLASS_INTERVAL = {1: 5.0, 2: 60.0, 3: 300.0}


def build_once(url: str, classes: set[int], where: str | None = None) -> dict:
    """Compute the requested classes only, and stamp the envelope.

    Class 3 dominates the cost (3.3s of 4.6s), so computing it on class 1's
    cadence would pace the most-watched numbers by the most expensive ones. The
    classes are therefore separable here, not merely labelled downstream.
    """
    started = time.monotonic()

    position = watermark(url=url)
    raw = read_legs(url=url, where=where)
    read_seconds = time.monotonic() - started

    if raw.empty:
        raise SystemExit("no rows in srisk.betslip_leg — run the consumer first")

    analysis_started = time.monotonic()

    # `_enrich` derives region, betslip_id, minutes_to_kickoff and the rest. It
    # is the batch pipeline's own function: betslip grain (ADR-0003) is
    # reconstructed by the code that was validated, not by a SQL translation.
    legs = _enrich(raw)

    # Price analysis feeds classes 2 and 3 (sharp needs price_value), so it runs
    # whenever either is requested — never for class 1 alone.
    needs_prices = bool({2, 3} & classes)
    movements, price_report = None, None
    if needs_prices:
        legs, movements, price_report = batch.prices_analyse(legs)

    # `betflow.analyse` builds every table in one call, including concentration
    # and the anomaly detectors — class 3 work. Calling it for a class-1 tick
    # would pay that cost anyway, which is the thing this separation exists to
    # avoid, so class 1 calls the same module's building blocks directly instead.
    # The functions are the batch pipeline's own; only the orchestration differs.
    bf = batch.betflow_module
    tables = batch.betflow_analyse(legs, movements) if (2 in classes or 3 in classes) else None
    betslips = bf._betslip_frame(legs).reset_index()
    report = _StreamLoadReport(len(raw), betslips=len(betslips))

    payload: dict = {}

    if 1 in classes:
        flow_tables = tables or _class1_tables(bf, legs, betslips)
        payload["overview"] = batch._build_overview(legs, betslips, report, flow_tables)
        payload["flow"] = {
            "by_market": batch._table_to_dict(flow_tables.by_market, "flow.by_market", "Legs by market"),
            "by_competition": batch._table_to_dict(
                flow_tables.by_competition, "flow.by_competition", "Legs by competition"
            ),
            "by_fixture": batch._table_to_dict(flow_tables.by_fixture, "flow.by_fixture", "Legs by fixture"),
            "by_region": batch._table_to_dict(flow_tables.by_region, "flow.by_region", "Betslips by region"),
            "by_bet_type": batch._table_to_dict(
                flow_tables.by_bet_type, "flow.by_bet_type", "Betslips by bet type"
            ),
            "by_selection": batch._table_to_dict(
                flow_tables.by_selection, "flow.by_selection", "Top selections"
            ),
            "by_player": batch._table_to_dict(flow_tables.by_player, "flow.by_player", "Top players"),
        }
        payload["timing"] = {
            "phases": batch._table_to_dict(flow_tables.phases, "timing.phases", "Legs by time phase"),
            "daily": batch._table_to_dict(
                batch.daily_series(betslips), "timing.daily", "Daily volume"
            ),
        }
    if 2 in classes:
        payload["prices"] = batch._build_prices(legs, movements, price_report)
        payload["data_quality"] = batch._build_quality(legs, report, tables, price_report)

    if 3 in classes:
        payload["concentration"] = batch._jsonify(tables.concentration)
        payload["anomalies"] = batch._build_anomalies(tables)
        scored, flagged, sharp_report = batch.sharp_analyse(legs)
        payload["sharp"] = batch._build_sharp(scored, flagged, sharp_report)

    payload = batch._round_numbers(batch._jsonify(payload))
    analysis_seconds = time.monotonic() - analysis_started

    payload["meta"] = _stream_meta(
        payload, position, read_seconds, analysis_seconds, sorted(classes)
    )
    return payload


def _class1_tables(bf, legs, betslips):
    """The dimensional breakdowns only — no concentration, no detectors.

    Same functions `betflow.analyse` calls, assembled without the class-3 work.
    Measured: 0.99s for the full `analyse` against 0.59s for this path, and the
    difference is entirely concentration and the anomaly detectors, which have no
    business running on a 5-second cadence.
    """
    resolved = bf.resolve_players(legs)
    frame = betslips if betslips.index.name is None else betslips.reset_index()
    return bf.BetflowTables(
        by_market=bf._breakdown(legs, "market_normalised", "leg"),
        by_competition=bf._breakdown(legs, "Competition", "leg"),
        by_fixture=bf._breakdown(legs, "MatchId", "leg", label_col="MATCH"),
        by_region=bf._breakdown(
            frame, "region", "betslip", count_name="betslips",
            money_col="turnover", currency_col="currency",
        ),
        by_bet_type=bf._breakdown(
            frame, "bet_type", "betslip", count_name="betslips",
            money_col="turnover", currency_col="currency",
        ),
        by_selection=bf._selection_breakdown(legs),
        by_player=bf._player_breakdown(legs, resolved),
        phases=bf._phase_table(legs),
        # Class 3 work, deliberately absent: an empty concentration dict and no
        # detectors. `_build_overview` does not read either.
        concentration={},
        anomalies={},
        report=bf.BetflowReport(betslips=len(frame), legs=len(legs)),
    )


class _StreamLoadReport:
    """Stands in for the batch LoadReport, which describes file loading.

    Under streaming there are no files to report on: dedup happened at ingest by
    identity (ADR-0007), not by comparing rows across exports. The counters the
    payload needs are present; the file-specific ones are empty, and that is
    stated rather than fabricated.
    """

    def __init__(self, rows: int, betslips: int = 0) -> None:
        self.rows_raw = {"stream": rows}
        self.rows_after_exact_dedup = {"stream": rows}
        self.exact_dups_removed = {"stream": 0}
        self.cross_file_overlap = 0
        self.rows_union = rows
        self.betslips = betslips
        self.legs = rows
        self.inflation_factor = 0.0
        self.inflation_by_currency = {}
        self.currencies = {}
        self.inplay_share = 0.0
        self.unparsed_dates = 0
        self.simple_with_multiple_legs = 0

    def as_dict(self) -> dict:
        return {
            "rows_raw": self.rows_raw,
            "rows_after_exact_dedup": self.rows_after_exact_dedup,
            "exact_dups_removed": self.exact_dups_removed,
            "cross_file_overlap": self.cross_file_overlap,
            "rows_union": self.rows_union,
            "betslips": self.betslips,
            "legs": self.legs,
            "inflation_factor": round(self.inflation_factor, 4),
            "inflation_by_currency": self.inflation_by_currency,
            "currencies": self.currencies,
            "inplay_share": round(self.inplay_share, 4),
            "unparsed_dates": self.unparsed_dates,
            "simple_with_multiple_legs": self.simple_with_multiple_legs,
            "note": "Streaming ingest: duplicates resolve by identity and version "
            "at merge time (ADR-0007), so file-level dedup counters do not apply.",
        }


def _stream_meta(
    payload: dict,
    position: dict,
    read_seconds: float,
    analysis_seconds: float,
    classes: list[int],
) -> dict:
    """The batch envelope, with the watermark replacing the dataset fingerprint."""
    import hashlib

    meta = batch._build_meta(payload, REPO / "data" / "raw")
    meta["classes"] = classes
    # Freshness is a property of the class, not of the payload (ADR-0009), so the
    # envelope states the cadence each computed class is refreshed on. A reader
    # that sees a Gini next to a turnover figure can tell the two are not the
    # same age.
    meta["class_interval_seconds"] = {str(c): CLASS_INTERVAL[c] for c in classes}

    # The dataset fingerprint identified an immutable file. Under streaming the
    # input is identified by position instead (ADR-0009), so the fingerprint is
    # replaced rather than left pointing at files this run never read.
    meta.pop("dataset_fingerprint", None)
    meta["watermark"] = position["watermark"]
    meta["rows_stored"] = position["rows_stored"]
    meta["identities"] = position["identities"]
    # Outstanding supersedences: rows the merge has not collapsed yet. Nonzero is
    # normal, and it is the number that explains a hash moving without new data.
    meta["pending_supersedence"] = position["rows_stored"] - position["identities"]
    meta["source"] = "stream"
    meta["timing"] = {
        "read_seconds": round(read_seconds, 3),
        "analysis_seconds": round(analysis_seconds, 3),
    }
    meta["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Rehash: the envelope changed, so the batch hash computed above no longer
    # describes what is served.
    canonical = json.dumps(
        {k: v for k, v in payload.items() if k != "meta"},
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    )
    meta["payload_hash"] = f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()[:16]}"
    return meta


def write(payload: dict, out: Path) -> None:
    """Write only the artifacts this pass computed.

    A class-1 tick must not touch `sharp.json`: overwriting it with nothing, or
    with a stale copy, would make a windowed statistic appear to refresh on the
    fast cadence — the exact misreading ADR-0009 exists to prevent.
    """
    out.mkdir(parents=True, exist_ok=True)
    for artifact, content in payload.items():
        body = content if artifact == "meta" else {
            "artifact": artifact,
            "schema_version": payload["meta"]["schema_version"],
            "generated_at": payload["meta"]["generated_at"],
            "watermark": payload["meta"]["watermark"],
            "payload_hash": payload["meta"]["payload_hash"],
            "environment": payload["meta"]["environment"],
            "data": content,
        }
        (out / f"{artifact}.json").write_text(json.dumps(body, indent=1, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="streaming.refresh")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--classes",
        default="all",
        help="'all', or a comma-separated subset: 1 (placement-complete), "
        "2 (settlement-complete), 3 (windowed). Costs differ by an order of "
        "magnitude — see CLASS_ARTIFACTS.",
    )
    parser.add_argument("--interval", type=float, help="override the class cadence")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", type=Path, default=REPO / "streaming" / "out" / "artifacts")
    parser.add_argument("--where", help="SQL predicate scoping a window")
    args = parser.parse_args(argv)

    classes = (
        set(CLASS_ARTIFACTS)
        if args.classes == "all"
        else {int(c) for c in args.classes.split(",")}
    )
    unknown = classes - set(CLASS_ARTIFACTS)
    if unknown:
        raise SystemExit(f"unknown class(es): {sorted(unknown)}")

    # Pace on the fastest requested class: a loop covering 1 and 3 must tick at
    # class 1's cadence, not class 3's.
    interval = args.interval or min(CLASS_INTERVAL[c] for c in classes)

    while True:
        started = time.monotonic()
        payload = build_once(args.url, classes, args.where)
        write(payload, args.out)
        elapsed = time.monotonic() - started
        meta = payload["meta"]
        print(
            f"[refresh] class {','.join(map(str, sorted(classes)))} "
            f"| {meta['payload_hash']} | watermark {meta['watermark']} "
            f"| {meta['identities']:,} identities "
            f"| pending {meta['pending_supersedence']:,} "
            f"| read {meta['timing']['read_seconds']}s "
            f"analysis {meta['timing']['analysis_seconds']}s "
            f"| total {elapsed:.2f}s",
            file=sys.stderr,
        )
        if args.once:
            return 0
        time.sleep(max(0.0, interval - elapsed))


if __name__ == "__main__":
    raise SystemExit(main())
