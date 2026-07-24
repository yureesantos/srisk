"""Sharp-behaviour scoring over Uid activity windows.

This module answers the operational question behind the brief: *which activity
windows are taking prices the market later disagrees with, more often than the
book's own baseline explains?*

Three design decisions carry the module, and each replaced a weaker one:

**A flag is an absolute test, not a percentile.** Ranking windows and flagging
the top decile would flag exactly 10% of any population — including a population
with no sharp behaviour in it at all. A percentile is a relative statement and
cannot distinguish "this book has sharps" from "this book has a top decile".
Flagging here is a one-sided exact binomial test against the book's own beat
rate, with Benjamini-Hochberg control across every window tested.

**Legs are not independent observations.** Several legs by one Uid on the same
pricing group share a single reference price, so one favourable move turns all
of them into "beats". Scoring runs on **distinct priced selections** — one unit
per (Uid, fixture, market, player, selection) — which collapses that dependence.
Measured: 13.7% of units hold more than one leg.

**One scored quantity, not a composite.** An earlier design averaged three
percentile ranks (beat rate, mean price value, stake-weighted price value).
Those are not three measurements: beat rate and mean value are strongly
coupled, and the two value figures are the same numbers under different weights.
The composite measured roughly one and a half dimensions while presenting as
three, and every extra step was something to defend. Ranking here uses the
Wilson lower bound of the beat rate — the rate defensible at 95% confidence
given how few bets were seen — and value figures are displayed, never scored.

Empirical-Bayes shrinkage toward a fitted Beta prior would rank marginally
better, and was rejected: it adds a prior to justify, still needs a separate
test for flagging, and ranks near-identically at these sample sizes.

Everything here describes **activity windows, not customers** (ADR-0002): a
Uid's median activity span is 10 days inside an export that is effectively a
single tournament month. A flag routes a window to human review. It is never a
verdict and never an automatic limit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .betflow import Table, _money_by_currency
from .prices import GROUP_KEY

# ADR-0002: below this a window carries too little history to read.
MIN_BETSLIPS_TO_SCORE = 10

# Distinct priced selections needed before a window can be flagged. At n=20 an
# observed 65% beat rate is only just significant against a ~44% baseline, so
# this is the floor where the test can say anything at all.
MIN_UNITS_TO_FLAG = 20

# 95% confidence for the Wilson bound — a reporting convention, not a tuned dial.
WILSON_Z = 1.96

# Benjamini-Hochberg target: at most 10% of flags are expected false discoveries.
FDR_Q = 0.10

# Matches the "post-lineups proxy" phase boundary in betflow.PHASES.
LATE_WINDOW_MINUTES = 60


@dataclass
class SharpReport:
    """Population accounting, statistics and caveats for the scored set."""

    scored_windows: int = 0
    flag_eligible_windows: int = 0
    flagged_windows: int = 0
    windows_below_betslip_threshold: int = 0
    scoring_units_total: int = 0
    legs_in_scope: int = 0
    own_reference_legs_excluded: int = 0
    baseline_beat_rate_unit_grain: float = 0.0
    baseline_beat_rate_leg_grain: float = 0.0
    median_units_per_window: float = 0.0
    fdr_q: float = FDR_Q
    expected_false_discoveries: float = 0.0
    flags_under_raw_alpha: int = 0
    flags_under_top_decile: int = 0
    turnover_of_scored_windows: dict = field(default_factory=dict)
    multi_currency_windows: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scored_windows": self.scored_windows,
            "flag_eligible_windows": self.flag_eligible_windows,
            "flagged_windows": self.flagged_windows,
            "windows_below_betslip_threshold": self.windows_below_betslip_threshold,
            "scoring_units_total": self.scoring_units_total,
            "legs_in_scope": self.legs_in_scope,
            "own_reference_legs_excluded": self.own_reference_legs_excluded,
            "baseline_beat_rate_unit_grain": round(
                self.baseline_beat_rate_unit_grain, 4
            ),
            "baseline_beat_rate_leg_grain": round(self.baseline_beat_rate_leg_grain, 4),
            "median_units_per_window": round(self.median_units_per_window, 1),
            "fdr_q": self.fdr_q,
            "expected_false_discoveries": round(self.expected_false_discoveries, 1),
            "flags_under_raw_alpha": self.flags_under_raw_alpha,
            "flags_under_top_decile": self.flags_under_top_decile,
            "turnover_of_scored_windows": self.turnover_of_scored_windows,
            "multi_currency_windows": self.multi_currency_windows,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------
# Statistics (pure, dependency-free)
# --------------------------------------------------------------------------


def wilson_lower_bound(
    successes: np.ndarray, trials: np.ndarray, z: float = WILSON_Z
) -> np.ndarray:
    """Lower bound of the Wilson score interval for a binomial proportion.

    Folds sample size into the estimate: 14 beats from 20 reads as 70%, but its
    Wilson bound is 0.481 — barely above a 44% baseline. That discount is the
    whole point of ranking on it rather than on the raw rate.
    """
    k = np.asarray(successes, dtype=float)
    n = np.asarray(trials, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        phat = np.where(n > 0, k / n, 0.0)
        denominator = 1.0 + z * z / n
        centre = phat + z * z / (2 * n)
        margin = z * np.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
        bound = (centre - margin) / denominator
    return np.where(n > 0, np.clip(bound, 0.0, 1.0), 0.0)


def _log_binomial_coefficient(n: float, k: float) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def binomial_upper_tail(successes: int, trials: int, probability: float) -> float:
    """Exact P(X >= successes) for X ~ Binomial(trials, probability).

    Exact rather than normal-approximated: at n=20 the approximation is visibly
    wrong in the tail, which is exactly where every flag is decided.
    """
    if trials <= 0:
        return 1.0
    if successes <= 0:
        return 1.0
    if successes > trials:
        return 0.0
    log_p = math.log(probability)
    log_q = math.log1p(-probability)
    total = 0.0
    for k in range(int(successes), int(trials) + 1):
        total += math.exp(_log_binomial_coefficient(trials, k) + k * log_p + (trials - k) * log_q)
    return min(1.0, total)


def benjamini_hochberg(p_values: np.ndarray, q: float = FDR_Q) -> np.ndarray:
    """Boolean mask of hypotheses passing BH false-discovery-rate control.

    Testing ~700 windows at a raw 5% would manufacture ~35 chance flags. BH caps
    the *expected share* of flags that are false at `q` instead.
    """
    p = np.asarray(p_values, dtype=float)
    n = p.size
    if n == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p)
    ranked = p[order]
    thresholds = q * np.arange(1, n + 1) / n
    passing = ranked <= thresholds
    mask = np.zeros(n, dtype=bool)
    if passing.any():
        cutoff = np.max(np.where(passing)[0])
        mask[order[: cutoff + 1]] = True
    return mask


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def _scoring_units(legs: pd.DataFrame) -> pd.DataFrame:
    """Collapse eligible legs into distinct priced selections per Uid.

    Legs whose reference came from the same Uid are dropped: a window that set
    its own benchmark tells us nothing about beating the market.
    """
    scope = legs[legs["price_value_eligible"] & ~legs["reference_is_own_bet"]]
    units = scope.groupby(["Uid"] + GROUP_KEY, sort=False).agg(
        legs=("price_value_winsorised", "size"),
        mean_value=("price_value_winsorised", "mean"),
        stake=("TURNOVER", "sum"),
        currency=("Currency Code", "first"),
        placed_at=("Betslip date (utc)", "min"),
        match_id=("MatchId", "first"),
    )
    # Strict positivity matches how the population baseline is defined: the
    # median price value is exactly 0.00, so a large mass sits at zero and is
    # counted as "not a beat". Conservative, and consistent across both grains.
    units["beat"] = units["mean_value"] > 0
    return units.reset_index()


def _window_frame(units: pd.DataFrame, legs: pd.DataFrame) -> pd.DataFrame:
    """One row per Uid: statistics plus unscored behavioural context."""
    grouped = units.groupby("Uid", sort=False)
    windows = grouped.agg(
        priced_units=("beat", "size"),
        beats=("beat", "sum"),
        mean_price_value=("mean_value", "mean"),
        distinct_fixtures=("match_id", "nunique"),
    )

    # Stake-weighted value, computed inside the window's dominant currency so no
    # weight ever crosses a currency boundary (ADR-0001).
    weighted = []
    for uid, group in grouped:
        dominant = group["currency"].mode()
        code = dominant.iloc[0] if len(dominant) else None
        scoped = group[group["currency"] == code] if code is not None else group.iloc[0:0]
        stake = scoped["stake"].sum()
        value = (
            float((scoped["mean_value"] * scoped["stake"]).sum() / stake)
            if stake > 0
            else np.nan
        )
        weighted.append(
            {
                "Uid": uid,
                "dominant_currency": code,
                "stake_weighted_price_value": value,
                "multi_currency": group["currency"].nunique() > 1,
            }
        )
    windows = windows.join(pd.DataFrame(weighted).set_index("Uid"))

    context = legs.groupby("Uid", sort=False).agg(
        betslips=("betslip_id", "nunique"),
        legs=("betslip_id", "size"),
        first_seen=("Betslip date (utc)", "min"),
        last_seen=("Betslip date (utc)", "max"),
        region=("region", "first"),
        uid_format=("uid_format", "first"),
        distinct_markets=("market_normalised", "nunique"),
        has_same_second_clusters=("had_key_collision", "any"),
    )
    context["span_days"] = (
        context["last_seen"] - context["first_seen"]
    ).dt.total_seconds() / 86400.0

    late = legs[
        (legs["minutes_to_kickoff"] >= -LATE_WINDOW_MINUTES)
        & (legs["minutes_to_kickoff"] <= 0)
    ]
    context["late_share"] = (
        late.groupby("Uid").size().reindex(context.index).fillna(0) / context["legs"]
    )
    context["inplay_share"] = (
        legs[legs["is_inplay"]].groupby("Uid").size().reindex(context.index).fillna(0)
        / context["legs"]
    )
    context["simple_share"] = (
        legs[legs["BetType"] == "SIMPLE"]
        .groupby("Uid")
        .size()
        .reindex(context.index)
        .fillna(0)
        / context["legs"]
    )
    top_market = (
        legs.groupby(["Uid", "market_normalised"]).size().rename("n").reset_index()
    )
    top_market = top_market.sort_values("n", ascending=False).drop_duplicates("Uid")
    context["top_market"] = top_market.set_index("Uid")["market_normalised"]

    return windows.join(context, how="inner")


def analyse(legs: pd.DataFrame) -> tuple[Table, Table, SharpReport]:
    """Score every eligible Uid window. Expects the frame after `prices.analyse`.

    Returns `(all scored windows, flagged windows, report)`.
    """
    report = SharpReport()
    units = _scoring_units(legs)
    report.scoring_units_total = len(units)
    report.legs_in_scope = int(units["legs"].sum())
    report.own_reference_legs_excluded = int(legs["reference_is_own_bet"].sum())

    baseline = float(units["beat"].mean()) if len(units) else 0.0
    report.baseline_beat_rate_unit_grain = baseline
    eligible_legs = legs[legs["price_value_eligible"]]
    report.baseline_beat_rate_leg_grain = (
        float((eligible_legs["price_value_winsorised"] > 0).mean())
        if len(eligible_legs)
        else 0.0
    )

    windows = _window_frame(units, legs)
    below = windows["betslips"] < MIN_BETSLIPS_TO_SCORE
    report.windows_below_betslip_threshold = int(below.sum())
    windows = windows[~below].copy()
    report.scored_windows = len(windows)

    if not len(windows):
        empty = Table(grain="betslip", rows=pd.DataFrame(), notes=[])
        return empty, empty, report

    windows["beat_rate"] = windows["beats"] / windows["priced_units"]
    windows["wilson_lb"] = wilson_lower_bound(
        windows["beats"].to_numpy(), windows["priced_units"].to_numpy()
    )
    windows["score"] = (windows["wilson_lb"].rank(pct=True) * 100).round(1)

    flag_eligible = windows["priced_units"] >= MIN_UNITS_TO_FLAG
    report.flag_eligible_windows = int(flag_eligible.sum())

    windows["p_value"] = np.nan
    candidates = windows[flag_eligible]
    p_values = np.array(
        [
            binomial_upper_tail(int(row.beats), int(row.priced_units), baseline)
            for row in candidates.itertuples()
        ]
    )
    windows.loc[candidates.index, "p_value"] = p_values

    fdr_mask = benjamini_hochberg(p_values, FDR_Q)
    windows["fdr_pass"] = False
    windows.loc[candidates.index[fdr_mask], "fdr_pass"] = True

    # Money must agree with frequency: a window that beats the line marginally
    # but loses on stake-weighted value is not extracting value.
    windows["flagged"] = windows["fdr_pass"] & windows["stake_weighted_price_value"].gt(0)
    report.flagged_windows = int(windows["flagged"].sum())
    report.expected_false_discoveries = FDR_Q * report.flagged_windows
    report.flags_under_raw_alpha = int((p_values <= 0.05).sum())
    report.flags_under_top_decile = int(round(len(windows) * 0.10))
    report.median_units_per_window = float(windows["priced_units"].median())
    report.multi_currency_windows = int(windows["multi_currency"].sum())

    betslip_money = legs.groupby("betslip_id").agg(
        Uid=("Uid", "first"),
        turnover=("TURNOVER", "first"),
        currency=("Currency Code", "first"),
    )
    report.turnover_of_scored_windows = _money_by_currency(
        betslip_money[betslip_money["Uid"].isin(windows.index)], "turnover", "currency"
    )

    windows = windows.sort_values("score", ascending=False).reset_index()
    _fill_notes(report, baseline)

    columns = [
        "Uid",
        "uid_format",
        "region",
        "betslips",
        "legs",
        "span_days",
        "first_seen",
        "last_seen",
        "priced_units",
        "beats",
        "beat_rate",
        "wilson_lb",
        "p_value",
        "fdr_pass",
        "score",
        "flagged",
        "dominant_currency",
        "stake_weighted_price_value",
        "mean_price_value",
        "multi_currency",
        "distinct_fixtures",
        "distinct_markets",
        "top_market",
        "late_share",
        "inplay_share",
        "simple_share",
        "has_same_second_clusters",
    ]
    table_notes = [
        "Grain: one row per Uid activity window, never a customer (ADR-0002).",
        f"`priced_units` counts distinct priced selections, not legs — several "
        "legs on one selection share a reference price and are not independent.",
        f"Beat rate is judged against the book's own baseline of {baseline:.1%}, "
        "not 50%: the reference-price proxy biases the null downward.",
    ]
    scored = Table(grain="betslip", rows=windows[columns], notes=table_notes)
    flagged = Table(
        grain="betslip",
        rows=windows[windows["flagged"]][columns],
        notes=table_notes
        + [
            "A flag routes a window to human review. It is not a verdict and not "
            "an automatic limit.",
        ],
    )
    return scored, flagged, report


def _fill_notes(report: SharpReport, baseline: float) -> None:
    report.notes = [
        "Units are Uid activity windows, not customers. A Uid's median activity "
        "span is 10 days, and the export is effectively a single tournament "
        "month, so a flag means 'sharp pattern in this period' and carries no "
        "longitudinal claim (ADR-0002).",
        f"Flagging is an exact one-sided binomial test against the book's own "
        f"beat rate ({baseline:.1%}), FDR-controlled at q={FDR_Q}. "
        f"It flagged {report.flagged_windows} windows. A raw 5% threshold would "
        f"have flagged {report.flags_under_raw_alpha}; a top-decile cut would "
        f"have flagged {report.flags_under_top_decile} regardless of whether any "
        "signal existed at all.",
        f"At most {FDR_Q:.0%} of flags are expected to be false discoveries "
        f"(about {report.expected_false_discoveries:.0f} of "
        f"{report.flagged_windows}).",
        "Price value rests on a proxy closing line, so these figures describe "
        "the measurable book rather than the whole book (ADR-0005).",
        "A string-format Uid is a retail terminal, which aggregates many "
        "walk-in customers. Such a window can clear the test on volume alone; "
        "`uid_format` and `has_same_second_clusters` are on every row so an "
        "operational read comes before a risk read.",
        "A sharp actor spreading activity across several Uids is invisible here "
        "by construction — the stated detection gap of ADR-0002.",
    ]
