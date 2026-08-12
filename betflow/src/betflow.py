"""Descriptive Betflow aggregates: flow, timing, concentration, anomalies.

This module owns every descriptive table the report and the dashboard render.
It computes nothing about price value — that belongs to `prices.py`, whose
output this module consumes.

Three rules run through the whole module:

* **Money never crosses a currency.** `_money_by_currency` is the only function
  allowed to sum turnover, and it nests results under a currency key, so a
  cross-currency total is unexpressible rather than merely discouraged
  (ADR-0001). Betslips with no currency are counted, never summed.
* **Every table declares its grain.** Turnover is real only at betslip grain;
  leg-grain money is valid *within* a breakdown but is inflated 1.07x against
  the betslip figure (ADR-0003), so `Table.grain` carries the label and
  `_breakdown` attaches the caveat automatically.
* **A group key is valid only if everything inside the group is a quote on the
  same real-world thing.** Learned the hard way in `prices.py`, where
  `(MatchId, market, Option)` pooled Laporte at 15.00 with Oyarzabal at 2.22 and
  reported a 5.6x "price move" that did not exist. Every key here that touches a
  player-centric market carries `Player` for that reason.

Expected call order: `load.load` -> `prices.analyse` -> `betflow.analyse`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TOP_N = 15
TOP_MARKETS_FOR_SELECTIONS = 5

# Daily turnover spike threshold. The multiplier is an empirical operating dial,
# not a normality argument, so MAD is left unscaled (no 1.4826 constant).
SPIKE_MAD_MULTIPLIER = 5
# A day counts as part of the operating period if it carries at least this share
# of the busiest day's betslips. Separates the dense June book from the residual
# March-to-May tail without hardcoding a cut-off date.
OPERATING_DAY_MIN_SHARE = 0.01
# Below this many operating days, a spike baseline is not meaningful.
MIN_DAYS_FOR_SPIKES = 10

REPEAT_BACKING_MIN_BETSLIPS = 3

# Abnormal exposure: a fixture in the top decile of turnover where one selection
# holds at least half of it. The minimum-legs floor stops a thin fixture from
# triggering on structure alone.
EXPOSURE_FIXTURE_QUANTILE = 0.90
EXPOSURE_SELECTION_SHARE = 0.50
EXPOSURE_MIN_FIXTURE_LEGS = 50
EXPOSURE_MIN_SELECTION_LEGS = 20

# `1` and `2` are the home/away outcomes of a 1X2 market. Legible in a betting
# system, meaningless in a report, so they are spelled out on display.
SELECTION_DISPLAY_ALIASES = {
    "1": "Home win (1)",
    "2": "Away win (2)",
    "X": "Draw (X)",
}

LORENZ_POINTS = 101

# Selection identity on player-centric markets. `Player` is the discriminator:
# without it, "the same selection" pools different players' lines.
SELECTION_KEY = ["market_normalised", "Player", "Option"]

# Bet builders carry free-text combination strings in `Option` (1,615 distinct
# values across 9,467 legs), so a "top selections" table over them is a tail of
# n=1 rows. They are excluded from the selection pool and reported by count.
BET_BUILDER_MARKETS = (
    "Home-side combo (bet builder)",
    "Away-side combo (bet builder)",
)

# Ordered time phases on `minutes_to_kickoff` (negative = pre-match).
# The 60-minute boundary stands in for "after team news"; the export carries no
# lineup timestamp, so it is a proxy and is labelled as one everywhere.
# In-play bins are wall-clock minutes after the *declared* kick-off, not match
# minutes, so half-time falls inside the 45-90m bucket.
PHASES: tuple[tuple[str, float, float], ...] = (
    ("More than 7d before", -np.inf, -10080),
    ("7d to 24h before", -10080, -1440),
    ("24h to 6h before", -1440, -360),
    ("6h to 60m before", -360, -60),
    ("60m to 5m before (post-lineups proxy)", -60, -5),
    ("5m to kick-off", -5, 0),
    ("In-play: 0-45m", 0, 45),
    ("In-play: 45-90m", 45, 90),
    ("In-play: 90-120m (extra time)", 90, 120),
    ("More than 120m after kick-off (residual)", 120, np.inf),
)

_DIGIT_RE = re.compile(r"\d")
_LINE_WORDS_RE = re.compile(r"\b(?:or more|or fewer|or less|over|under)\b", re.I)
_STAR_SUFFIX_RE = re.compile(
    r"\s*\((?:Suplente Estrella|Jugador Estrella|Star Substitute)\)\s*$", re.I
)
_TEMPLATE_RE = re.compile(r"\{PLAYER\}", re.I)

# Market families whose player name lives in `Option` rather than in `Player`.
_NAME_IN_OPTION_RE = re.compile(
    r"goal ?scorer|to score|to be carded|hat trick|most passes|assist", re.I
)
# Team- and match-centric markets that survive the pattern above but are not
# about an individual.
_NOT_PLAYER_PREFIX_RE = re.compile(r"^(?:team|match)\b", re.I)

MAX_PLAYER_NAME_LEN = 60


@dataclass
class Table:
    """A rendered table plus the context a reader needs to trust it."""

    grain: str  # "betslip" or "leg"
    rows: pd.DataFrame
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "grain": self.grain,
            "rows": self.rows.to_dict(orient="records"),
            "notes": self.notes,
        }


@dataclass
class BetflowReport:
    """Coverage, reconciliation and caveats for the descriptive layer."""

    betslips: int = 0
    legs: int = 0
    player_centric_legs: int = 0
    player_resolved_legs: int = 0
    player_coverage: float = 0.0
    distinct_players: int = 0
    players_from_template: int = 0
    players_from_option: int = 0
    phase_residual_legs: int = 0
    currency_unresolved_betslips: int = 0
    currency_unresolved_legs: int = 0
    currency_unresolved_turnover_units: float = 0.0
    finding_counts: dict[str, int] = field(default_factory=dict)
    gini_summary: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "betslips": self.betslips,
            "legs": self.legs,
            "player_centric_legs": self.player_centric_legs,
            "player_resolved_legs": self.player_resolved_legs,
            "player_coverage": round(self.player_coverage, 4),
            "distinct_players": self.distinct_players,
            "players_from_template": self.players_from_template,
            "players_from_option": self.players_from_option,
            "phase_residual_legs": self.phase_residual_legs,
            "currency_unresolved_betslips": self.currency_unresolved_betslips,
            "currency_unresolved_legs": self.currency_unresolved_legs,
            "currency_unresolved_turnover_units": round(
                self.currency_unresolved_turnover_units, 2
            ),
            "finding_counts": self.finding_counts,
            "gini_summary": {k: round(v, 4) for k, v in self.gini_summary.items()},
            "notes": self.notes,
        }


@dataclass
class BetflowTables:
    """Everything the artifacts need, one field per report section."""

    by_market: Table
    by_competition: Table
    by_fixture: Table
    by_region: Table
    by_bet_type: Table
    by_selection: Table
    by_player: Table
    phases: Table
    concentration: dict
    anomalies: dict[str, Table]
    report: BetflowReport


# --------------------------------------------------------------------------
# Player resolution (ADR-0004, as amended)
# --------------------------------------------------------------------------


def _template_prefix(labels: pd.Series) -> str:
    """Longest common prefix of a market's Spanish labels.

    On `{PLAYER}` markets the label reads "Remates a puerta Arda Guler": a
    constant Spanish market prefix followed by the player's name. Deriving the
    prefix from the data avoids hardcoding a Spanish dictionary, so the resolver
    survives markets and competitions that are not in this export.
    """
    unique = labels.dropna().unique()
    if len(unique) == 0:
        return ""
    prefix = unique[0]
    for label in unique[1:]:
        limit = min(len(prefix), len(label))
        index = 0
        while index < limit and prefix[index] == label[index]:
            index += 1
        prefix = prefix[:index]
        if not prefix:
            break
    return prefix.rstrip()


def _looks_like_name(value: object) -> bool:
    """Reject line expressions and combination text; accept everything else."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or len(text) > MAX_PLAYER_NAME_LEN:
        return False
    if _DIGIT_RE.search(text) or _LINE_WORDS_RE.search(text):
        return False
    if text.lower() in {"yes", "no"} or text.lower().startswith("no "):
        return False
    return True


def resolve_players(legs: pd.DataFrame) -> pd.DataFrame:
    """Resolve a player name per leg, where the market is about one player.

    Returns a frame aligned to `legs.index` with `player_family` and
    `player_name`.

    Stage order matters: `Assists {PLAYER}` and `To score or assist` both match
    an "assist" keyword, and only the template test separates them, so templates
    are classified first.
    """
    market_raw = legs["Market"].astype(str)
    market_norm = legs["market_normalised"].astype(str)

    is_template = market_raw.str.contains(_TEMPLATE_RE, na=False)
    is_option = (
        ~is_template
        & market_norm.str.contains(_NAME_IN_OPTION_RE, na=False)
        & ~market_norm.str.contains(_NOT_PLAYER_PREFIX_RE, na=False)
    )

    family = pd.Series("not_player_centric", index=legs.index, dtype=object)
    family[is_template] = "template_player"
    family[is_option] = "name_in_option"

    name = pd.Series(pd.NA, index=legs.index, dtype=object)

    # Stage 1: strip the derived Spanish prefix off the `Player` label.
    if is_template.any():
        labels = (
            legs.loc[is_template, "Player"]
            .astype(str)
            .str.replace(_STAR_SUFFIX_RE, "", regex=True)
            .str.strip()
        )
        markets = market_raw[is_template]
        for market, positions in labels.groupby(markets).groups.items():
            prefix = _template_prefix(labels.loc[positions])
            stripped = labels.loc[positions]
            if prefix:
                stripped = stripped.str.slice(len(prefix)).str.strip()
            name.loc[positions] = stripped.where(stripped.map(_looks_like_name))

    # Stage 2: the name sits in `Option`.
    if is_option.any():
        options = legs.loc[is_option, "Option"].astype(str).str.strip()
        name.loc[is_option] = options.where(options.map(_looks_like_name))

    return pd.DataFrame({"player_family": family, "player_name": name})


# --------------------------------------------------------------------------
# Concentration
# --------------------------------------------------------------------------


def gini_lorenz(values: np.ndarray, points: int = LORENZ_POINTS) -> dict:
    """Sample Gini coefficient, Lorenz curve points and top-share cuts.

    Plain sample coefficient, no small-sample correction: with populations in
    the thousands the correction is noise, and an unadjusted figure is the one a
    reader can reproduce.
    """
    array = np.asarray([v for v in values if np.isfinite(v)], dtype=float)
    array = array[array >= 0]
    n = array.size
    total = array.sum()
    if n < 2 or total <= 0:
        return {
            "gini": None,
            "lorenz": [],
            "top_shares": {},
            "n_units": int(n),
            "note": "population too small or zero-valued for a Gini coefficient",
        }

    ordered = np.sort(array)
    ranks = np.arange(1, n + 1)
    gini = (2.0 * np.sum(ranks * ordered)) / (n * total) - (n + 1) / n

    cumulative = np.concatenate([[0.0], np.cumsum(ordered) / total])
    population = np.concatenate([[0.0], ranks / n])
    grid = np.linspace(0.0, 1.0, points)
    lorenz = [
        [round(float(p), 4), round(float(v), 6)]
        for p, v in zip(grid, np.interp(grid, population, cumulative))
    ]

    descending = ordered[::-1]
    top_shares = {}
    for label, fraction in (("top_1pct", 0.01), ("top_5pct", 0.05), ("top_10pct", 0.10)):
        count = max(1, int(round(n * fraction)))
        top_shares[label] = round(float(descending[:count].sum() / total), 4)
    top_shares["top_10_units"] = round(float(descending[: min(10, n)].sum() / total), 4)

    return {
        "gini": round(float(gini), 4),
        "lorenz": lorenz,
        "top_shares": top_shares,
        "n_units": int(n),
    }


# --------------------------------------------------------------------------
# Grain helpers
# --------------------------------------------------------------------------


def _betslip_frame(legs: pd.DataFrame) -> pd.DataFrame:
    """One row per betslip — the universe every money aggregate uses.

    Currency, region and BetType are constant within a betslip (verified: zero
    mixed-currency betslips; ADR-0003 established BetType constancy), so taking
    the first value is safe rather than lossy.
    """
    return legs.groupby("betslip_id", sort=False).agg(
        Uid=("Uid", "first"),
        placed_at=("Betslip date (utc)", "first"),
        bet_type=("BetType", "first"),
        region=("region", "first"),
        currency=("Currency Code", "first"),
        turnover=("TURNOVER", "first"),
        ggr=("GGR", "first"),
        legs=("TURNOVER", "size"),
        uid_format=("uid_format", "first"),
        had_key_collision=("had_key_collision", "any"),
    )


def _money_by_currency(
    frame: pd.DataFrame, value_col: str, currency_col: str = "currency"
) -> dict:
    """Sum a money column, nested under currency. The only place money is summed.

    Rows with no currency are counted, never added to a total: 1,366 betslips
    carry no currency and cannot be assigned by region either, so folding them
    into either track would invent a number (ADR-0001).
    """
    currency = frame[currency_col]
    known = frame[currency.notna()]
    totals = {
        str(code): round(float(group[value_col].sum()), 2)
        for code, group in known.groupby(currency, sort=False)
    }
    return {
        "by_currency": totals,
        "unresolved_rows": int(currency.isna().sum()),
        "unresolved_units": round(float(frame.loc[currency.isna(), value_col].sum()), 2),
    }


_LEG_MONEY_CAVEAT = (
    "Turnover shown at leg grain: valid for comparison within this breakdown "
    "only. A combined betslip repeats its stake on every leg, so the leg-grain "
    "total runs 1.07x above the true betslip-grain figure."
)


def _breakdown(
    frame: pd.DataFrame,
    key: str,
    grain: str,
    label_col: str | None = None,
    top_n: int = TOP_N,
    count_name: str = "legs",
    money_col: str = "TURNOVER",
    currency_col: str = "Currency Code",
) -> Table:
    """Top-N rows by count, plus an "Other" rollup carrying the remainder.

    Ranking is always by **count**, never by turnover: turnover cannot be
    ordered across currencies (ADR-0001), so a turnover ranking would be
    meaningless the moment two currencies appear in one table.
    """
    grouped = frame.groupby(key, sort=False)
    counts = grouped.size().sort_values(ascending=False)
    total = int(counts.sum())

    head = counts.head(top_n)
    rows = []
    for value, count in head.items():
        subset = frame[frame[key] == value]
        label = value
        if label_col is not None:
            label = subset[label_col].iloc[0]
        rows.append(
            {
                "key": str(value),
                "label": str(label),
                count_name: int(count),
                "share": round(count / total, 4) if total else 0.0,
                "betslips": int(subset["betslip_id"].nunique())
                if "betslip_id" in subset
                else int(count),
                "turnover": _money_by_currency(subset, money_col, currency_col),
            }
        )

    tail_keys = counts.index[top_n:]
    if len(tail_keys):
        tail = frame[frame[key].isin(tail_keys)]
        tail_count = int(counts.iloc[top_n:].sum())
        rows.append(
            {
                "key": "__other__",
                "label": f"Other ({len(tail_keys):,} more)",
                count_name: tail_count,
                "share": round(tail_count / total, 4) if total else 0.0,
                "betslips": int(tail["betslip_id"].nunique())
                if "betslip_id" in tail
                else tail_count,
                "turnover": _money_by_currency(tail, money_col, currency_col),
            }
        )

    notes = [f"Ranked by {count_name}; totals cover all {len(counts):,} values."]
    if grain == "leg":
        notes.append(_LEG_MONEY_CAVEAT)
    return Table(grain=grain, rows=pd.DataFrame(rows), notes=notes)


def _selection_breakdown(legs: pd.DataFrame) -> Table:
    """Top selections within the busiest markets.

    Selection identity is `(market, Player, Option)`, not `Option` alone. On
    player-centric markets `Option` is only the line ("2 or more"), so keying on
    it would pool every player's line into one row — the same defect that
    produced a fictitious 5.6x price move in `prices.py`.

    Bet builders are excluded: their `Option` is free-text combination copy with
    1,615 distinct values, so a top-selections table over them is a tail of
    single-occurrence rows. Their combination count is reported instead.
    """
    pool = legs[~legs["market_normalised"].isin(BET_BUILDER_MARKETS)]
    top_markets = (
        pool["market_normalised"].value_counts().head(TOP_MARKETS_FOR_SELECTIONS).index
    )
    scoped = pool[pool["market_normalised"].isin(top_markets)].copy()

    # Compose the display label from Player only where the market actually
    # spans several players; otherwise the Spanish label is noise.
    players_per_market = scoped.groupby("market_normalised")["Player"].transform(
        "nunique"
    )
    option_display = (
        scoped["Option"].astype(str).replace(SELECTION_DISPLAY_ALIASES)
    )
    scoped["selection_label"] = np.where(
        players_per_market > 1,
        scoped["Player"].astype(str) + " - " + option_display,
        option_display,
    )
    scoped["selection_key"] = (
        scoped["market_normalised"].astype(str)
        + "|"
        + scoped["Player"].astype(str)
        + "|"
        + scoped["Option"].astype(str)
    )

    table = _breakdown(
        scoped, key="selection_key", grain="leg", label_col="selection_label"
    )
    builders = legs[legs["market_normalised"].isin(BET_BUILDER_MARKETS)]
    table.notes.insert(
        0,
        f"Scoped to the {TOP_MARKETS_FOR_SELECTIONS} busiest markets. Selection "
        "identity includes the player, so different players' lines never share "
        "a row.",
    )
    if len(builders):
        table.notes.append(
            f"Bet builders excluded: {len(builders):,} legs across "
            f"{builders['Option'].nunique():,} distinct combinations — free-text "
            "selections that do not aggregate meaningfully."
        )
    return table


def _player_breakdown(legs: pd.DataFrame, resolved: pd.DataFrame) -> Table:
    """Top players by leg count, over the markets that name a player."""
    scoped = legs.join(resolved)
    named = scoped[scoped["player_name"].notna()].copy()
    table = _breakdown(named, key="player_name", grain="leg")

    centric = int(resolved["player_family"].ne("not_player_centric").sum())
    got = int(resolved["player_name"].notna().sum())
    table.notes.insert(
        0,
        f"Resolved {got:,} of {centric:,} player-centric legs "
        f"({got / centric:.1%}) into {named['player_name'].nunique():,} names.",
    )
    table.notes.append(
        "Names are not entity-resolved: 'Mbappe' and 'Kylian Mbappe' would "
        "occupy separate rows. Cross-feed identity is the reconciliation service's problem."
    )
    return table


def _phase_table(legs: pd.DataFrame) -> Table:
    """Leg counts and leg-grain turnover per time phase.

    Betslip-grain turnover is deliberately absent: a combined betslip spans
    fixtures with different kick-offs, so it has no single minutes-to-kick-off.
    Picking one (the earliest, say) would be a silent judgment call.
    """
    minutes = legs["minutes_to_kickoff"]
    labels = pd.Series(pd.NA, index=legs.index, dtype=object)
    for name, lower, upper in PHASES:
        if lower == -np.inf:
            mask = minutes < upper
        elif upper == np.inf:
            mask = minutes > lower
        elif upper == 0:
            # A bet placed in the exact second of kick-off is pre-match, matching
            # `is_inplay = minutes > 0` in load.py. Without the closed upper edge
            # it falls between the pre-match and in-play bins and is lost.
            mask = (minutes >= lower) & (minutes <= upper)
        elif lower < 0:
            mask = (minutes >= lower) & (minutes < upper)
        else:
            mask = (minutes > lower) & (minutes <= upper)
        labels[mask & labels.isna()] = name

    scoped = legs.assign(phase=labels)
    total = len(scoped)
    rows = []
    for name, _, _ in PHASES:
        subset = scoped[scoped["phase"] == name]
        rows.append(
            {
                "phase": name,
                "is_pre_match": not name.startswith(("In-play", "More than 120m")),
                "legs": len(subset),
                "share": round(len(subset) / total, 4) if total else 0.0,
                "betslips": int(subset["betslip_id"].nunique()),
                "turnover": _money_by_currency(subset, "TURNOVER", "Currency Code"),
            }
        )

    return Table(
        grain="leg",
        rows=pd.DataFrame(rows),
        notes=[
            "The 60-minute boundary stands in for 'after team news'. The export "
            "carries no lineup timestamp, so this is a proxy, not a measurement.",
            "In-play bins count wall-clock minutes after the declared kick-off, "
            "not match minutes, so half-time falls inside the 45-90m bucket.",
            "In-play share is an upper bound: a late pre-match bet registered "
            "after kick-off is indistinguishable from a true in-play bet.",
            _LEG_MONEY_CAVEAT,
        ],
    )


def _concentration(betslips: pd.DataFrame, legs: pd.DataFrame) -> dict:
    """Concentration across Uid windows and across fixtures.

    The unit is always labelled a 'Uid window', never a customer: a Uid's median
    activity span is 10 days inside a 3.5-month export, so it does not identify
    a person (ADR-0002).
    """
    result: dict = {"uid_windows": {}, "fixtures": {}}

    per_currency: dict[str, dict] = {}
    for code, group in betslips[betslips["currency"].notna()].groupby("currency"):
        if len(group) < 100:  # too thin for a curve; counted elsewhere
            continue
        totals = group.groupby("Uid")["turnover"].sum().to_numpy()
        per_currency[str(code)] = gini_lorenz(totals)
    result["uid_windows"]["turnover"] = per_currency
    result["uid_windows"]["betslip_count"] = gini_lorenz(
        betslips.groupby("Uid").size().to_numpy()
    )

    result["fixtures"]["leg_count"] = gini_lorenz(
        legs.groupby("MatchId").size().to_numpy()
    )
    fixture_money: dict[str, dict] = {}
    known = legs[legs["Currency Code"].notna()]
    for code, group in known.groupby("Currency Code"):
        if group["MatchId"].nunique() < 20:
            continue
        fixture_money[str(code)] = gini_lorenz(
            group.groupby("MatchId")["TURNOVER"].sum().to_numpy()
        )
    result["fixtures"]["turnover_leg_grain"] = fixture_money
    result["notes"] = [
        "Units are Uid windows, not customers: a Uid's median activity span is "
        "10 days inside a 3.5-month export (ADR-0002).",
        "Fixture turnover is leg grain — a combined betslip spans fixtures, so "
        "its stake cannot be attributed to one of them at betslip grain.",
    ]
    return result


# --------------------------------------------------------------------------
# Anomaly detectors
# --------------------------------------------------------------------------


def daily_series(betslips: pd.DataFrame) -> Table:
    """Betslip counts and per-currency turnover per calendar day.

    Days are annotated with `in_operating_period` using the same rule the spike
    detector applies, so a chart can show the residual March-to-May tail without
    letting it distort the baseline it is judged against.
    """
    frame = betslips.reset_index() if betslips.index.name else betslips
    rows = []
    for date, group in frame.groupby(frame["placed_at"].dt.date, sort=True):
        rows.append(
            {
                "date": date.isoformat(),
                "betslips": len(group),
                "legs": int(group["legs"].sum()),
                "turnover": _money_by_currency(group, "turnover", "currency"),
            }
        )
    table = pd.DataFrame(rows)
    if len(table):
        busiest = float(table["betslips"].max())
        table["in_operating_period"] = table["betslips"] >= busiest * OPERATING_DAY_MIN_SHARE
    return Table(
        grain="betslip",
        rows=table,
        notes=[
            "A day is inside the operating period when it carries at least "
            f"{OPERATING_DAY_MIN_SHARE:.0%} of the busiest day's betslips. The "
            "March-to-May tail falls outside it: 132 betslips across 38 days "
            "against 77,300 in June.",
        ],
    )


def _detect_turnover_spikes(betslips: pd.DataFrame) -> Table:
    """Days whose turnover breaks out of the operating period's own range.

    **This detector is deliberately weak, and the reason is the data.** The
    export is effectively a June book: March holds 4 betslips, April 11, May
    117, and June 77,300 — 99.8% of the total. The March-to-May tail is residual
    early betting on June fixtures, not a period of quiet trading.

    That leaves ~23 active trading days. A trailing-window baseline needs more
    history than that, and a whole-period baseline would compare June against
    March and flag every single June day. So the baseline is restricted to the
    dense operating period itself, and days outside it are reported as context
    rather than scored.

    A real deployment would carry months of history and use a seasonal baseline.
    Saying so is more useful than shipping a detector that fires on everything.
    """
    rows = []
    for code, group in betslips[betslips["currency"].notna()].groupby("currency"):
        daily = (
            group.set_index("placed_at")
            .resample("D")
            .agg(turnover=("turnover", "sum"), betslips=("turnover", "size"))
            .fillna(0.0)
        )
        # Days with no betting are days this client sent no data, not quiet
        # trading days.
        daily = daily[daily["betslips"] > 0]

        # Restrict the baseline to the operating period: days carrying at least
        # 1% of the busiest day's volume. This drops the residual tail without
        # hardcoding a date.
        busiest = float(daily["betslips"].max())
        operating = daily[daily["betslips"] >= busiest * OPERATING_DAY_MIN_SHARE]
        if len(operating) < MIN_DAYS_FOR_SPIKES:
            continue

        median = float(operating["turnover"].median())
        mad = float((operating["turnover"] - median).abs().median())
        if mad <= 0:
            continue
        threshold = median + SPIKE_MAD_MULTIPLIER * mad

        flagged = operating[operating["turnover"] > threshold]
        for date, row in flagged.iterrows():
            rows.append(
                {
                    "date": date.date().isoformat(),
                    "currency": str(code),
                    "turnover": round(float(row["turnover"]), 2),
                    "betslips": int(row["betslips"]),
                    "median": round(median, 2),
                    "mad": round(mad, 2),
                    "threshold": round(threshold, 2),
                    "excess_ratio": round(float(row["turnover"]) / threshold, 3),
                }
            )

    return Table(
        grain="betslip",
        rows=pd.DataFrame(rows).sort_values("excess_ratio", ascending=False)
        if rows
        else pd.DataFrame(),
        notes=[
            f"A day is flagged above median + {SPIKE_MAD_MULTIPLIER}x MAD of "
            "the operating period in its own currency. MAD is unscaled — the "
            "multiplier is an operating dial, not a normality argument.",
            "The baseline covers only the dense operating period. The export is "
            "effectively a June book (4 betslips in March, 11 in April, 117 in "
            "May, 77,300 in June), so ~23 real trading days is too little "
            "history for a seasonal or trailing baseline.",
            "Low confidence by construction. A deployment with months of history "
            "would use a seasonal baseline; this is the honest version of the "
            "detector given what the export contains.",
        ],
    )


def _detect_repeat_backing(legs: pd.DataFrame) -> Table:
    """One Uid window backing the same selection across several betslips.

    `Player` belongs in the key: without it, three bets on three different
    players' shots-on-target lines would read as one selection backed three
    times.
    """
    key = ["Uid", "MatchId", "market_normalised", "Player", "Option"]
    grouped = legs.groupby(key, sort=False)
    summary = grouped.agg(
        betslips=("betslip_id", "nunique"),
        legs=("betslip_id", "size"),
        fixture=("MATCH", "first"),
        currency=("Currency Code", "first"),
        first_price=("Price", "first"),
        last_price=("Price", "last"),
        first_seen=("Betslip date (utc)", "min"),
        last_seen=("Betslip date (utc)", "max"),
        includes_key_collision=("had_key_collision", "any"),
        uid_format=("uid_format", "first"),
    ).reset_index()

    flagged = summary[summary["betslips"] >= REPEAT_BACKING_MIN_BETSLIPS].copy()
    if len(flagged):
        # Stake counts once per betslip, never once per leg: a combined bet
        # repeats its stake on every leg. Deduplicating (key + betslip) before
        # summing is the vectorised form of "first stake per betslip, then sum",
        # and avoids a per-group Python call on ~89k groups.
        stakes = (
            legs.drop_duplicates(subset=key + ["betslip_id"])
            .groupby(key, sort=False)["TURNOVER"]
            .sum()
            .rename("stake")
            .reset_index()
        )
        flagged = flagged.merge(stakes, on=key, how="left")
        if "price_value_winsorised" in legs.columns:
            value = (
                legs.groupby(key, sort=False)["price_value_winsorised"]
                .mean()
                .rename("mean_price_value")
                .reset_index()
            )
            flagged = flagged.merge(value, on=key, how="left")
        flagged["span_minutes"] = (
            flagged["last_seen"] - flagged["first_seen"]
        ).dt.total_seconds() / 60.0
        flagged = flagged.sort_values("betslips", ascending=False)

    return Table(
        grain="betslip",
        rows=flagged,
        notes=[
            f"Flagged at {REPEAT_BACKING_MIN_BETSLIPS}+ betslips on one selection "
            "by one Uid window.",
            "Selection identity includes the player, so distinct players' lines "
            "never merge into one finding.",
            "`includes_key_collision` marks overlap with the same-second cluster "
            "detector, so one behaviour is not reported as two alarms.",
        ],
    )


def _detect_abnormal_exposure(legs: pd.DataFrame) -> Table:
    """A busy fixture where one selection carries most of the money.

    Two guards keep this honest: the fixture needs real depth, and a share
    driven by a single Uid is that customer's behaviour rather than market-wide
    exposure — it is flagged as such instead of being presented as exposure.
    """
    rows = []
    known = legs[legs["Currency Code"].notna()]
    for code, group in known.groupby("Currency Code"):
        per_fixture = group.groupby("MatchId")["TURNOVER"].sum()
        legs_per_fixture = group.groupby("MatchId").size()
        eligible = per_fixture[legs_per_fixture >= EXPOSURE_MIN_FIXTURE_LEGS]
        if len(eligible) < 10:
            continue
        cutoff = eligible.quantile(EXPOSURE_FIXTURE_QUANTILE)
        for match_id in eligible[eligible >= cutoff].index:
            fixture = group[group["MatchId"] == match_id]
            total = float(fixture["TURNOVER"].sum())
            if total <= 0:
                continue
            by_selection = fixture.groupby(SELECTION_KEY, sort=False).agg(
                turnover=("TURNOVER", "sum"),
                legs=("TURNOVER", "size"),
                distinct_uids=("Uid", "nunique"),
            )
            top = by_selection.sort_values("turnover", ascending=False).head(1)
            share = float(top["turnover"].iloc[0]) / total
            if share < EXPOSURE_SELECTION_SHARE:
                continue
            # A dominant share carried by two or three bets is a thin fixture,
            # not concentrated exposure. The selection needs its own depth.
            if int(top["legs"].iloc[0]) < EXPOSURE_MIN_SELECTION_LEGS:
                continue
            market, player, option = top.index[0]
            rows.append(
                {
                    "match_id": int(match_id),
                    "fixture": str(fixture["MATCH"].iloc[0]),
                    "currency": str(code),
                    "fixture_turnover": round(total, 2),
                    "market": str(market),
                    "selection": str(option),
                    "player_label": str(player),
                    "selection_turnover": round(float(top["turnover"].iloc[0]), 2),
                    "share": round(share, 4),
                    "legs": int(top["legs"].iloc[0]),
                    "distinct_uids": int(top["distinct_uids"].iloc[0]),
                    "single_actor": bool(top["distinct_uids"].iloc[0] < 2),
                }
            )

    return Table(
        grain="leg",
        rows=pd.DataFrame(rows).sort_values("share", ascending=False)
        if rows
        else pd.DataFrame(),
        notes=[
            f"Fixtures at or above the {EXPOSURE_FIXTURE_QUANTILE:.0%} turnover "
            f"percentile with at least {EXPOSURE_MIN_FIXTURE_LEGS} legs, where one "
            f"selection holds {EXPOSURE_SELECTION_SHARE:.0%}+ of the fixture.",
            "`single_actor` marks a share driven by one Uid window — individual "
            "behaviour, not market-wide exposure.",
            _LEG_MONEY_CAVEAT,
        ],
    )


def _collision_clusters(legs: pd.DataFrame) -> Table:
    """Several distinct single bets registered under one Uid in one second.

    ADR-0003 established these are genuinely separate bets, so this is an
    operational signature — terminal or automated placement — not a fraud
    verdict.
    """
    collided = legs[legs["had_key_collision"]]
    if not len(collided):
        return Table(grain="leg", rows=pd.DataFrame(), notes=[])

    clusters = (
        collided.groupby(["Uid", "Betslip date (utc)"], sort=False)
        .agg(
            cluster_size=("betslip_id", "nunique"),
            legs=("betslip_id", "size"),
            fixtures=("MatchId", "nunique"),
            markets=("market_normalised", "nunique"),
            region=("region", "first"),
            currency=("Currency Code", "first"),
            uid_format=("uid_format", "first"),
            stake=("TURNOVER", "sum"),
        )
        .reset_index()
        .sort_values("cluster_size", ascending=False)
    )
    clusters["placed_at"] = clusters["Betslip date (utc)"].astype(str)
    clusters = clusters.drop(columns=["Betslip date (utc)"])

    single_fixture = float((clusters["fixtures"] == 1).mean())
    return Table(
        grain="leg",
        rows=clusters,
        notes=[
            f"{len(clusters):,} clusters covering {len(collided):,} legs. "
            f"{single_fixture:.1%} sit on a single fixture.",
            "An operational signature (terminal or automated placement), not a "
            "fraud finding. ADR-0003 established these are separate bets.",
        ],
    )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def analyse(
    legs: pd.DataFrame, price_moves: pd.DataFrame | None = None
) -> BetflowTables:
    """Build every descriptive table. Expects the frame after `prices.analyse`."""
    betslips = _betslip_frame(legs)
    resolved = resolve_players(legs)
    report = BetflowReport(betslips=len(betslips), legs=len(legs))

    if price_moves is not None and len(price_moves):
        sharp = price_moves[price_moves["is_sharp_move"]].copy()
        sharp_table = Table(
            grain="leg",
            rows=sharp,
            notes=[
                "Consumed from `prices.price_movement`; not recomputed here.",
                "Requires 5+ pre-match legs and 2+ distinct Uids in the group.",
            ],
        )
    else:
        sharp_table = Table(
            grain="leg",
            rows=pd.DataFrame(),
            notes=["Price movement unavailable: `prices.analyse` output not supplied."],
        )

    anomalies = {
        "turnover_spikes": _detect_turnover_spikes(betslips.reset_index()),
        "repeat_backing": _detect_repeat_backing(legs),
        "sharp_moves": sharp_table,
        "abnormal_exposure": _detect_abnormal_exposure(legs),
        "same_second_clusters": _collision_clusters(legs),
    }

    tables = BetflowTables(
        by_market=_breakdown(legs, "market_normalised", "leg"),
        by_competition=_breakdown(legs, "Competition", "leg"),
        by_fixture=_breakdown(legs, "MatchId", "leg", label_col="MATCH"),
        by_region=_breakdown(
            betslips.reset_index(),
            "region",
            "betslip",
            count_name="betslips",
            money_col="turnover",
            currency_col="currency",
        ),
        by_bet_type=_breakdown(
            betslips.reset_index(),
            "bet_type",
            "betslip",
            count_name="betslips",
            money_col="turnover",
            currency_col="currency",
        ),
        by_selection=_selection_breakdown(legs),
        by_player=_player_breakdown(legs, resolved),
        phases=_phase_table(legs),
        concentration=_concentration(betslips, legs),
        anomalies=anomalies,
        report=report,
    )
    _fill_report(legs, betslips, resolved, tables, report)
    return tables


def _fill_report(
    legs: pd.DataFrame,
    betslips: pd.DataFrame,
    resolved: pd.DataFrame,
    tables: BetflowTables,
    report: BetflowReport,
) -> None:
    centric = resolved["player_family"].ne("not_player_centric")
    report.player_centric_legs = int(centric.sum())
    report.player_resolved_legs = int(resolved["player_name"].notna().sum())
    report.player_coverage = (
        report.player_resolved_legs / report.player_centric_legs
        if report.player_centric_legs
        else 0.0
    )
    report.distinct_players = int(resolved["player_name"].nunique())
    report.players_from_template = int(
        (resolved["player_family"].eq("template_player") & resolved["player_name"].notna()).sum()
    )
    report.players_from_option = int(
        (resolved["player_family"].eq("name_in_option") & resolved["player_name"].notna()).sum()
    )

    report.phase_residual_legs = int((legs["minutes_to_kickoff"] > 120).sum())

    no_currency = betslips["currency"].isna()
    report.currency_unresolved_betslips = int(no_currency.sum())
    report.currency_unresolved_legs = int(legs["Currency Code"].isna().sum())
    report.currency_unresolved_turnover_units = float(
        betslips.loc[no_currency, "turnover"].sum()
    )

    report.finding_counts = {
        name: int(len(table.rows)) for name, table in tables.anomalies.items()
    }

    summary = {}
    counts = tables.concentration["uid_windows"]["betslip_count"]
    if counts.get("gini") is not None:
        summary["uid_windows_betslip_count"] = counts["gini"]
    fixtures = tables.concentration["fixtures"]["leg_count"]
    if fixtures.get("gini") is not None:
        summary["fixtures_leg_count"] = fixtures["gini"]
    report.gini_summary = summary

    # Reconciliation guard: every betslip belongs to exactly one currency track
    # or to the unresolved bucket. If this breaks, a money figure has drifted.
    tracked = int(betslips["currency"].notna().sum())
    assert tracked + report.currency_unresolved_betslips == len(betslips)

    report.notes = [
        "Money never crosses a currency: totals nest under a currency key and "
        f"{report.currency_unresolved_betslips:,} betslips with no currency are "
        "counted but never summed (ADR-0001).",
        "Breakdowns are ranked by count, never by turnover — turnover cannot be "
        "ordered across currencies.",
        f"Player names resolved for {report.player_coverage:.1%} of "
        "player-centric legs (ADR-0004, as amended).",
    ]
