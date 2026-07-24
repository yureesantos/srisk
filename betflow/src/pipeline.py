"""Orchestration and artifact emission — the contract layer.

This is the only module that writes files, and the JSON it emits is the contract
between the pipeline and both consumers: the notebook and the dashboard. If a
number differs between those two surfaces, that is a bug, and the mechanisms
here exist to make it impossible rather than unlikely.

**One payload, two encodings.** The whole run builds a single in-memory dict.
It is serialised twice — as per-section `.json` files (canonical: what the
notebook reads and what the audit trail keeps) and as one combined
`dashboard/src/data/payload.json` the UI imports at build time. Both come from
the same object in the same function call, so the second encoding cannot drift
into being a second source of truth.

**Pipeline reshapes and counts; it never originates a business number.**
Truncating, ranking, counting rows into declared bins and regrouping money
through `_money_by_currency` are allowed. A new statistic, threshold or money
aggregation is not — those belong upstream where they can be reasoned about.

**Every artifact carries a payload hash** over its content with the timestamp
excluded, so two runs on the same inputs hash identically. The hash is rendered
in the notebook header and the dashboard footer: if they disagree during a
review, it is visible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import betflow as betflow_module
from .betflow import Table, _money_by_currency, analyse as betflow_analyse, daily_series
from .load import load
from .prices import analyse as prices_analyse
from .sharp import analyse as sharp_analyse

SCHEMA_VERSION = 1

# Row caps for tables too large to ship to a browser. The full tables are always
# written to CSV, and every cap reports what it dropped (PRODUCT principle 5:
# a silent cap reads as "we covered everything" when it did not).
MAX_REPEAT_BACKING_ROWS = 50
MAX_CLUSTER_ROWS = 50
MAX_MOVEMENT_ROWS_PER_DIRECTION = 25

# Price-value histogram bins. Fixed edges rather than data-derived so the shape
# is comparable across runs; the outer bins are open-ended catch-alls for the
# heavy right tail (max observed value is +19.8).
VALUE_HISTOGRAM_EDGES = [
    -1.0, -0.50, -0.30, -0.20, -0.12, -0.06, -0.02, 0.0,
    0.02, 0.06, 0.12, 0.20, 0.30, 0.50, 1.0,
]

# Rounding is applied exactly once, here. Consumers display verbatim — double
# rounding is how "43.5% here, 43.4% there" happens.
MONEY_DECIMALS = 2
RATE_DECIMALS = 4

# Keys whose values are money and therefore must be currency-scoped.
MONEY_KEYS = {
    "turnover",
    "stake",
    "ggr",
    "turnover_within",
    "selection_turnover",
    "fixture_turnover",
}

_ALLOWED_CURRENCIES = {"EUR", "PEN", "USD"}


@dataclass
class BuildResult:
    payload: dict
    frames: dict
    failures: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Serialisation helpers
# --------------------------------------------------------------------------


def _jsonify(value):
    """Convert numpy/pandas scalars into JSON-native types.

    NaN becomes null rather than the literal `NaN` Python emits by default:
    `NaN` is invalid JSON but valid JavaScript, so leaving it in would let the
    dashboard work while any strict parser choked — the worst kind of
    divergence, because it hides until someone else reads the file.
    """
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return None if not math.isfinite(number) else number
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is None or isinstance(value, str) or isinstance(value, int):
        return value
    if value is pd.NaT or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _round_numbers(payload):
    """Apply the single rounding policy across the payload."""
    if isinstance(payload, dict):
        return {
            key: _round_money(key, value) if key in MONEY_KEYS else _round_numbers(value)
            for key, value in payload.items()
        }
    if isinstance(payload, list):
        return [_round_numbers(item) for item in payload]
    if isinstance(payload, float):
        return round(payload, RATE_DECIMALS)
    return payload


def _round_money(key, value):
    if isinstance(value, float):
        return round(value, MONEY_DECIMALS)
    return _round_numbers(value)


def _table_to_dict(
    table: Table, section_id: str, title: str, truncation: dict | None = None
) -> dict:
    return {
        "id": section_id,
        "title": title,
        "grain": table.grain,
        "rows": _jsonify(table.rows.to_dict(orient="records")),
        "notes": list(table.notes),
        "truncation": truncation,
    }


def _truncate(
    table: Table,
    section_id: str,
    title: str,
    limit: int,
    sort_by: list[str],
    ascending: list[bool],
    csv_path: str,
    describe_column: str | None = None,
) -> dict:
    """Ship the top `limit` rows and report exactly what was left behind."""
    rows = table.rows
    if not len(rows):
        return _table_to_dict(table, section_id, title)

    available = [column for column in sort_by if column in rows.columns]
    order = [ascending[sort_by.index(column)] for column in available]
    # Deterministic tie-breaking: without a total order, which rows ship can
    # differ between pandas versions.
    ordered = rows.sort_values(available, ascending=order, kind="mergesort")

    shipped = ordered.head(limit)
    omitted = ordered.iloc[limit:]
    truncation = {
        "total_rows": int(len(rows)),
        "shipped_rows": int(len(shipped)),
        "ranked_by": ", ".join(
            f"{column} {'asc' if asc else 'desc'}"
            for column, asc in zip(available, order)
        ),
        "omitted": {"rows": int(len(omitted))},
        "full_table": csv_path,
    }
    if len(omitted) and describe_column and describe_column in omitted.columns:
        truncation["omitted"]["range"] = [
            _jsonify(omitted[describe_column].min()),
            _jsonify(omitted[describe_column].max()),
        ]
        truncation["omitted"]["described_by"] = describe_column
    if len(omitted) and "currency" in omitted.columns and "stake" in omitted.columns:
        truncation["omitted"]["stake"] = _money_by_currency(omitted, "stake", "currency")

    return _table_to_dict(
        Table(grain=table.grain, rows=shipped, notes=table.notes),
        section_id,
        title,
        truncation,
    )


# --------------------------------------------------------------------------
# Payload assembly
# --------------------------------------------------------------------------


def _value_histogram(legs: pd.DataFrame) -> dict:
    """Counts of price value into fixed bins. Counting, not computing."""
    eligible = legs.loc[legs["price_value_eligible"], "price_value"].dropna()
    counts, _ = np.histogram(
        eligible.clip(VALUE_HISTOGRAM_EDGES[0], VALUE_HISTOGRAM_EDGES[-1]),
        bins=VALUE_HISTOGRAM_EDGES,
    )
    rows = [
        {
            "lower": VALUE_HISTOGRAM_EDGES[index],
            "upper": VALUE_HISTOGRAM_EDGES[index + 1],
            "legs": int(count),
        }
        for index, count in enumerate(counts)
    ]
    return {
        "id": "prices.value_histogram",
        "title": "Distribution of captured price value",
        "grain": "leg",
        "rows": rows,
        "notes": [
            "Values are clipped to the outer edges; the untruncated maximum is "
            f"{float(eligible.max()):.1f}.",
            "Zero is not the neutral point — the population beats its reference "
            "less than half the time by construction of the proxy.",
        ],
        "truncation": None,
    }


def build_payload(raw_dir: Path) -> BuildResult:
    """Run every layer and assemble the full artifact payload."""
    legs, load_report = load(raw_dir)
    legs, movements, price_report = prices_analyse(legs)
    tables = betflow_analyse(legs, movements)
    scored_windows, flagged_windows, sharp_report = sharp_analyse(legs)

    betslips = betflow_module._betslip_frame(legs).reset_index()
    daily = daily_series(betslips)

    overview = _build_overview(legs, betslips, load_report, tables)
    quality = _build_quality(legs, load_report, tables, price_report)
    flow = {
        "by_market": _table_to_dict(tables.by_market, "flow.by_market", "Legs by market"),
        "by_competition": _table_to_dict(
            tables.by_competition, "flow.by_competition", "Legs by competition"
        ),
        "by_fixture": _table_to_dict(
            tables.by_fixture, "flow.by_fixture", "Legs by fixture"
        ),
        "by_region": _table_to_dict(
            tables.by_region, "flow.by_region", "Betslips by region"
        ),
        "by_bet_type": _table_to_dict(
            tables.by_bet_type, "flow.by_bet_type", "Betslips by bet type"
        ),
        "by_selection": _table_to_dict(
            tables.by_selection, "flow.by_selection", "Top selections"
        ),
        "by_player": _table_to_dict(tables.by_player, "flow.by_player", "Top players"),
    }
    timing = {
        "phases": _table_to_dict(tables.phases, "timing.phases", "Legs by time phase"),
        "daily": _table_to_dict(daily, "timing.daily", "Daily volume"),
    }
    prices = _build_prices(legs, movements, price_report)
    concentration = _jsonify(tables.concentration)
    anomalies = _build_anomalies(tables)
    sharp = _build_sharp(scored_windows, flagged_windows, sharp_report)

    payload = {
        "overview": overview,
        "data_quality": quality,
        "flow": flow,
        "timing": timing,
        "prices": prices,
        "concentration": concentration,
        "anomalies": anomalies,
        "sharp": sharp,
    }
    payload = _round_numbers(_jsonify(payload))
    payload["meta"] = _build_meta(payload, raw_dir)

    frames = {
        "repeat_backing": tables.anomalies["repeat_backing"].rows,
        "same_second_clusters": tables.anomalies["same_second_clusters"].rows,
        "scored_windows": scored_windows.rows,
        "price_movement": movements,
    }
    return BuildResult(payload=payload, frames=frames)


def _build_overview(legs, betslips, load_report, tables) -> dict:
    known = betslips[betslips["currency"].notna()]
    monthly = (
        betslips.assign(month=betslips["placed_at"].dt.to_period("M").astype(str))
        .groupby("month")
        .size()
        .reset_index(name="betslips")
        .to_dict(orient="records")
    )
    return {
        "universe": {
            "id": "overview.universe",
            "title": "Analysed universe",
            "rows_raw_total": int(sum(load_report.rows_raw.values())),
            "legs": int(load_report.legs),
            "betslips": int(load_report.betslips),
            "fixtures": int(legs["MatchId"].nunique()),
            "competitions": int(legs["Competition"].nunique()),
            "date_min": str(legs["Betslip date (utc)"].min().date()),
            "date_max": str(legs["Betslip date (utc)"].max().date()),
            "notes": [
                "June carries 99.8% of betslips: this is a ~23-day book with a "
                "three-month tail, not a March-to-June series.",
            ],
        },
        "turnover": {
            "id": "overview.turnover",
            "title": "Turnover by currency",
            "grain": "betslip",
            "turnover": _money_by_currency(betslips, "turnover", "currency"),
            "ggr": _money_by_currency(betslips, "ggr", "currency"),
            "inflation_leg_vs_betslip": load_report.inflation_by_currency,
            "notes": [
                "No FX rate ships with the data, so no figure crosses a currency "
                "(ADR-0001). Spain and Peru are separate tracks.",
                f"{int(betslips['currency'].isna().sum()):,} betslips carry no "
                "currency: counted everywhere, summed nowhere.",
                "Leg-grain turnover runs above betslip grain because a combined "
                "bet repeats its stake on every leg — the ratio differs by track "
                "(EUR bets combine more than PEN bets).",
            ],
        },
        "monthly_betslips": {
            "id": "overview.monthly_betslips",
            "title": "Betslips by month",
            "grain": "betslip",
            "rows": monthly,
            "notes": [
                "Time-series anomaly detection is not supportable on this shape.",
            ],
        },
    }


def _build_quality(legs, load_report, tables, price_report) -> dict:
    report = tables.report
    placeholders = int(legs["Market"].astype(str).str.contains(r"\{", regex=True).sum())
    return {
        "dedup": {
            "id": "data_quality.dedup",
            "title": "Deduplication funnel",
            "rows_raw": load_report.rows_raw,
            "exact_dups_removed": load_report.exact_dups_removed,
            "cross_file_overlap": load_report.cross_file_overlap,
            "legs": load_report.rows_union,
            "notes": [
                "The two exports are partially disjoint slices, not copies: only "
                f"{load_report.cross_file_overlap} distinct rows appear in both, "
                "and the smaller file holds 84 fixtures the larger one lacks.",
            ],
        },
        "betslip_key": {
            "id": "data_quality.betslip_key",
            "title": "Betslip identity",
            "collision_legs": int(legs["had_key_collision"].sum()),
            "simple_with_multiple_legs": int(load_report.simple_with_multiple_legs),
            "notes": [
                "Uid plus a second-resolution timestamp collides when one "
                "customer places several single bets in the same second. Splitting "
                "the key on BetType resolves it (ADR-0003).",
            ],
        },
        "placeholders": {
            "id": "data_quality.placeholders",
            "title": "Unresolved market templates",
            "legs_with_placeholder": placeholders,
            "share": round(placeholders / len(legs), RATE_DECIMALS),
            "notes": [
                "`{COMPETITOR1}` and `{COMPETITOR2}` are whole market names, not "
                "slots: they are same-game bet builders. Stripping them naively "
                "would have dumped 10.6% of legs into an unnamed bucket.",
            ],
        },
        "currency_unresolved": {
            "id": "data_quality.currency_unresolved",
            "title": "Betslips without a currency",
            "betslips": report.currency_unresolved_betslips,
            "legs": report.currency_unresolved_legs,
            "turnover_units": report.currency_unresolved_turnover_units,
            "notes": [
                "These straddle both tracks (1,310 in ESTATAL, 119 in PERU), so "
                "region cannot resolve them either. Inferring a currency would "
                "invent a number.",
            ],
        },
        "player_resolution": {
            "id": "data_quality.player_resolution",
            "title": "Player name resolution",
            "player_centric_legs": report.player_centric_legs,
            "resolved_legs": report.player_resolved_legs,
            "coverage": round(report.player_coverage, RATE_DECIMALS),
            "distinct_players": report.distinct_players,
            "from_template": report.players_from_template,
            "from_option": report.players_from_option,
            "notes": [
                "The column named `Player` holds Spanish market labels, not "
                "people. Names come from the label's data-derived suffix or from "
                "`Option`, depending on the market family (ADR-0004).",
            ],
        },
        "inplay_bound": {
            "id": "data_quality.inplay_bound",
            "title": "In-play share",
            "share": round(float(legs["is_inplay"].mean()), RATE_DECIMALS),
            "notes": [
                "An upper bound, not a measurement: a late pre-match bet "
                "registered after the declared kick-off is indistinguishable "
                "from a true in-play bet on timestamps alone.",
            ],
        },
    }


def _build_prices(legs, movements, price_report) -> dict:
    steamers = movements[movements["is_sharp_move"] & (movements["direction"] == "steamer")]
    drifters = movements[movements["is_sharp_move"] & (movements["direction"] == "drifter")]
    columns = [
        "fixture",
        "market_normalised",
        "Player",
        "Option",
        "first_price",
        "last_price",
        "implied_prob_move",
        "legs",
        "distinct_uids",
        "turnover_within",
        "currency",
        "turnover_is_mixed_currency",
    ]

    def _shape(frame, direction):
        subset = frame.sort_values(
            ["implied_prob_move", "MatchId", "Option"],
            ascending=[direction == "drifter", True, True],
            kind="mergesort",
        ).head(MAX_MOVEMENT_ROWS_PER_DIRECTION)
        available = [column for column in columns if column in subset.columns]
        return _jsonify(subset[available].to_dict(orient="records"))

    return {
        "report": _jsonify(price_report.as_dict()),
        "movement": {
            "id": "prices.movement",
            "title": "Sharpest pre-match price moves",
            "grain": "leg",
            "steamers": _shape(steamers, "steamer"),
            "drifters": _shape(drifters, "drifter"),
            "truncation": {
                "total_rows": int(movements["is_sharp_move"].sum()),
                "shipped_rows": int(
                    min(len(steamers), MAX_MOVEMENT_ROWS_PER_DIRECTION)
                    + min(len(drifters), MAX_MOVEMENT_ROWS_PER_DIRECTION)
                ),
                "ranked_by": "implied_prob_move, MatchId asc, Option asc",
                "full_table": "outputs/tables/price_movement.csv",
            },
            "notes": [
                "Movement is measured in implied-probability terms so a short "
                "price and a long price move comparably.",
                "Requires 5+ pre-match legs and 2+ distinct Uids: a swing driven "
                "by one customer is that customer's activity, not a signal.",
                "Groups spanning more than one currency report no stake — "
                "summing across currencies is forbidden (ADR-0001).",
            ],
        },
        "value_histogram": _value_histogram(legs),
    }


def _build_anomalies(tables) -> dict:
    anomalies = tables.anomalies
    spikes = _table_to_dict(
        anomalies["turnover_spikes"], "anomalies.turnover_spikes", "Turnover spikes"
    )
    for row in spikes["rows"]:
        row["verify_ref"] = {
            "section": "timing.daily",
            "select": {"date": row.get("date")},
            "note": "The flagged day on the daily volume series.",
        }

    exposure = _table_to_dict(
        anomalies["abnormal_exposure"], "anomalies.abnormal_exposure", "Abnormal exposure"
    )
    for row in exposure["rows"]:
        row["verify_ref"] = {
            "section": "flow.by_fixture",
            "select": {"key": str(row.get("match_id"))},
            "note": "The fixture's overall volume, for comparison against the "
            "share this one selection carries.",
        }

    return {
        "turnover_spikes": spikes,
        "abnormal_exposure": exposure,
        "sharp_moves": _table_to_dict(
            anomalies["sharp_moves"], "anomalies.sharp_moves", "Sharp price moves"
        ),
        "repeat_backing": _truncate(
            anomalies["repeat_backing"],
            "anomalies.repeat_backing",
            "Repeated backing of one selection",
            MAX_REPEAT_BACKING_ROWS,
            ["betslips", "legs", "Uid"],
            [False, False, True],
            "outputs/tables/repeat_backing.csv",
            describe_column="betslips",
        ),
        "same_second_clusters": _truncate(
            anomalies["same_second_clusters"],
            "anomalies.same_second_clusters",
            "Same-second placement clusters",
            MAX_CLUSTER_ROWS,
            ["cluster_size", "Uid"],
            [False, True],
            "outputs/tables/same_second_clusters.csv",
            describe_column="cluster_size",
        ),
    }


def _build_sharp(scored: Table, flagged: Table, report) -> dict:
    slim = [
        "Uid",
        "uid_format",
        "priced_units",
        "beats",
        "beat_rate",
        "wilson_lb",
        "p_value",
        "fdr_pass",
        "flagged",
        "dominant_currency",
        "stake_weighted_price_value",
    ]
    available = [column for column in slim if column in scored.rows.columns]
    eligible = scored.rows[scored.rows["priced_units"] >= 20]

    flagged_rows = _table_to_dict(flagged, "sharp.flagged_windows", "Flagged windows")
    for row in flagged_rows["rows"]:
        row["verify_ref"] = {
            "section": "sharp.eligible_windows",
            "select": {"Uid": row.get("Uid")},
            "note": "The window among all tested windows, with the counts needed "
            "to recompute its binomial test.",
        }

    return {
        "report": _jsonify(report.as_dict()),
        "flagged_windows": flagged_rows,
        "eligible_windows": {
            "id": "sharp.eligible_windows",
            "title": "All windows eligible for flagging",
            "grain": "betslip",
            "rows": _jsonify(eligible[available].to_dict(orient="records")),
            "notes": [
                "Every window that met the evidence threshold, flagged or not. "
                "The scatter of these points is what shows a flag is not noise.",
            ],
            "truncation": None,
        },
    }


def _build_meta(payload: dict, raw_dir: Path) -> dict:
    registry = {}
    for artifact, content in payload.items():
        for key, section in content.items():
            if isinstance(section, dict) and "id" in section:
                registry[section["id"]] = {
                    "artifact": f"{artifact}.json",
                    "path": [artifact, key],
                    "grain": section.get("grain"),
                    "title": section.get("title"),
                }

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, allow_nan=False)
    payload_hash = hashlib.sha256(canonical.encode()).hexdigest()

    fingerprint = hashlib.sha256()
    for path in sorted(raw_dir.glob("*.xlsx")):
        fingerprint.update(path.name.encode())
        fingerprint.update(str(path.stat().st_size).encode())

    return {
        "artifact": "meta",
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_fingerprint": f"sha256:{fingerprint.hexdigest()[:16]}",
        "payload_hash": f"sha256:{payload_hash[:16]}",
        "environment": {
            "python": sys.version.split()[0],
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
        "sections": registry,
    }


# --------------------------------------------------------------------------
# Invariants
# --------------------------------------------------------------------------


def _walk(node, path="", parent=None):
    """Walk the payload yielding (path, key, value, containing object)."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield f"{path}.{key}", key, value, node
            yield from _walk(value, f"{path}.{key}", node)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _walk(item, f"{path}[{index}]", parent)


_CURRENCY_SIBLINGS = ("currency", "dominant_currency")


def check_invariants(payload: dict) -> list[str]:
    """Every check that must hold before artifacts are written."""
    failures: list[str] = []

    # Money is legal only as a per-currency block, or as a row-scoped number
    # whose own row declares which currency it is in.
    for path, key, value, parent in _walk(payload):
        if key in MONEY_KEYS and isinstance(value, (int, float)):
            scoped = any(sibling in parent for sibling in _CURRENCY_SIBLINGS)
            if ".by_currency" not in path and not scoped:
                failures.append(f"money-shape: unscoped money at {path}")
        if key == "by_currency" and isinstance(value, dict):
            unknown = set(value) - _ALLOWED_CURRENCIES
            if unknown:
                failures.append(f"money-shape: unknown currency {unknown} at {path}")

    # No non-finite values survive to the artifacts.
    canonical = json.dumps(payload, ensure_ascii=True, default=str)
    if "NaN" in canonical or "Infinity" in canonical:
        failures.append("no-nonfinite: NaN or Infinity present in payload")

    legs = payload["overview"]["universe"]["legs"]
    betslips = payload["overview"]["universe"]["betslips"]

    phase_legs = sum(row["legs"] for row in payload["timing"]["phases"]["rows"])
    if phase_legs != legs:
        failures.append(f"legs-conserved: phases sum to {phase_legs}, expected {legs}")

    for name in ("by_market", "by_competition", "by_fixture"):
        total = sum(row["legs"] for row in payload["flow"][name]["rows"])
        if total != legs:
            failures.append(f"legs-conserved: {name} sums to {total}, expected {legs}")

    for name in ("by_region", "by_bet_type"):
        total = sum(row["betslips"] for row in payload["flow"][name]["rows"])
        if total != betslips:
            failures.append(
                f"betslips-conserved: {name} sums to {total}, expected {betslips}"
            )

    sharp_report = payload["sharp"]["report"]
    flagged_rows = len(payload["sharp"]["flagged_windows"]["rows"])
    if sharp_report["flagged_windows"] != flagged_rows:
        failures.append(
            f"sharp-partition: report says {sharp_report['flagged_windows']} flags, "
            f"table holds {flagged_rows}"
        )
    for row in payload["sharp"]["flagged_windows"]["rows"]:
        if not row.get("fdr_pass") or not (row.get("stake_weighted_price_value") or 0) > 0:
            failures.append(f"sharp-partition: flagged window {row.get('Uid')} fails its own gate")

    price_beat = payload["prices"]["report"]["population_beat_rate"]
    sharp_beat = sharp_report["baseline_beat_rate_leg_grain"]
    if abs(price_beat - sharp_beat) > 1e-4:
        failures.append(
            f"beat-rate-consistency: prices says {price_beat}, sharp says {sharp_beat}"
        )

    # Truncation must account for every row it dropped.
    for path, key, value, _parent in _walk(payload):
        if key == "truncation" and isinstance(value, dict) and "omitted" in value:
            total = value.get("total_rows", 0)
            shipped = value.get("shipped_rows", 0)
            omitted = value.get("omitted", {}).get("rows", 0)
            if shipped + omitted != total:
                failures.append(
                    f"truncation-reconciles: {path} ships {shipped} + omits "
                    f"{omitted} != {total}"
                )

    # Every verify_ref must resolve to a section that actually shipped.
    registry = payload["meta"]["sections"] if "meta" in payload else {}
    for path, key, value, _parent in _walk(payload):
        if key == "verify_ref" and isinstance(value, dict):
            section = value.get("section")
            if registry and section not in registry:
                failures.append(f"verify-refs-resolve: unknown section {section} at {path}")

    return failures


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def write_artifacts(payload: dict, frames: dict, out_dir: Path, frontend: Path) -> dict:
    """Write JSON artifacts, full CSVs and the browser bundle. Atomic."""
    artifacts_dir = out_dir / "artifacts"
    tables_dir = out_dir / "tables"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    sizes = {}
    meta = payload["meta"]
    for name, content in payload.items():
        if name == "meta":
            continue
        document = {**{k: v for k, v in meta.items() if k != "sections"}, "artifact": name, "data": content}
        target = artifacts_dir / f"{name}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=True, allow_nan=False, indent=1)
        )
        temporary.replace(target)
        sizes[target.name] = target.stat().st_size

    meta_target = artifacts_dir / "meta.json"
    meta_target.write_text(json.dumps(meta, ensure_ascii=True, allow_nan=False, indent=1))
    sizes[meta_target.name] = meta_target.stat().st_size

    for name, frame in frames.items():
        if isinstance(frame, pd.DataFrame) and len(frame):
            frame.to_csv(tables_dir / f"{name}.csv", index=False)

    # The dashboard imports this JSON directly, so the bundler resolves it at
    # build time and the browser never fetches it. One payload, two encodings:
    # the per-section artifacts above are canonical for the notebook and the
    # audit trail; this is the same object in one file for the UI.
    frontend.parent.mkdir(parents=True, exist_ok=True)
    frontend.write_text(
        json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    )
    sizes[frontend.name] = frontend.stat().st_size
    return sizes


def load_artifacts(artifacts_dir: Path) -> dict:
    """Read the artifacts back into one payload — the notebook's entry point."""
    payload = {}
    for path in sorted(artifacts_dir.glob("*.json")):
        document = json.loads(path.read_text())
        payload[path.stem] = document.get("data", document)
    return payload


def resolve_ref(payload: dict, ref: dict) -> tuple[dict, list]:
    """Resolve a `verify_ref` to its section and the rows it points at."""
    registry = payload.get("meta", {}).get("sections", {})
    entry = registry.get(ref["section"])
    if entry is None:
        raise KeyError(f"unknown section {ref['section']}")
    section = payload
    for step in entry["path"]:
        section = section[step]
    rows = section.get("rows", [])
    select = ref.get("select") or {}
    matches = [
        row
        for row in rows
        if all(str(row.get(key)) == str(value) for key, value in select.items())
    ]
    return section, matches


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="Build Betflow artifacts.")
    parser.add_argument("--raw-dir", type=Path, default=root.parent / "data" / "raw")
    parser.add_argument("--out", type=Path, default=root / "outputs")
    parser.add_argument(
        "--frontend", type=Path, default=root / "dashboard" / "src" / "data" / "payload.json"
    )
    parser.add_argument("--check", action="store_true", help="verify without writing")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    started = time.time()
    if not args.raw_dir.exists():
        print(f"ERROR: raw directory not found: {args.raw_dir}", file=sys.stderr)
        return 2

    result = build_payload(args.raw_dir)
    payload = result.payload
    failures = check_invariants(payload)

    if not args.quiet:
        universe = payload["overview"]["universe"]
        sharp_report = payload["sharp"]["report"]
        price_report = payload["prices"]["report"]
        print(
            f"{universe['rows_raw_total']:,} raw rows -> {universe['legs']:,} legs "
            f"-> {universe['betslips']:,} betslips "
            f"-> {price_report['eligible_legs']:,} priced "
            f"-> {sharp_report['scored_windows']:,} scored "
            f"-> {sharp_report['flag_eligible_windows']:,} eligible "
            f"-> {sharp_report['flagged_windows']} flagged"
        )

    if failures:
        print(f"INVARIANTS FAILED ({len(failures)}):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    if args.check:
        existing = args.out / "artifacts" / "meta.json"
        if not existing.exists():
            print("ERROR: no artifacts on disk to check against", file=sys.stderr)
            return 1
        stored = json.loads(existing.read_text()).get("payload_hash")
        if stored != payload["meta"]["payload_hash"]:
            print(
                f"DRIFT: artifacts hash {stored}, rebuild hash "
                f"{payload['meta']['payload_hash']}",
                file=sys.stderr,
            )
            return 1
        print(f"CHECK CLEAN  {stored}")
        return 0

    sizes = write_artifacts(payload, result.frames, args.out, args.frontend)
    if not args.quiet:
        print(f"INVARIANTS PASS ({len(_INVARIANT_NAMES)} families)")
        for name, size in sorted(sizes.items()):
            print(f"  {name:28s} {size / 1024:8.1f} KB")
        print(f"payload {payload['meta']['payload_hash']}")
        print(f"done in {time.time() - started:.1f}s")
    return 0


_INVARIANT_NAMES = (
    "money-shape",
    "no-nonfinite",
    "legs-conserved",
    "betslips-conserved",
    "sharp-partition",
    "beat-rate-consistency",
    "truncation-reconciles",
    "verify-refs-resolve",
)


if __name__ == "__main__":
    raise SystemExit(main())
