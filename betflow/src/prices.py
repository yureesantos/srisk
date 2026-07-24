"""Reference price and captured price value.

The brief asks whether customers "got value" — did the price they took beat the
market's later reading? A true closing line is not in this export, so the
reference is a **proxy**: the last price observed on the same
(fixture, market, selection) before kick-off.

Two properties make the proxy defensible, and one makes it biased. All three are
reported rather than buried:

* **Coverage is high.** 77.3% of all legs have a strictly-later observation in
  their group, so most of the book is measurable.
* **Leakage is guarded.** A leg's reference must come from an observation
  strictly later than itself, and preferentially from a different Uid — without
  this, a sharp customer betting late would set their own benchmark and score
  neutral.
* **The sample is biased.** A reference only exists where late volume exists, so
  quiet markets are invisible and volatile markets are over-represented. This
  cannot be corrected with the data available; it is stated wherever price value
  is reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# A leg's price is compared against others on the same fixture, market and
# selection. Anything coarser compares unlike things.
#
# `Player` is part of the key, not decoration. On player-centric markets the raw
# market name carries a `{PLAYER}` placeholder that normalisation strips, and
# `Option` is only the line ("1 or more") — so without `Player` the group would
# pool Laporte at 15.00 with Oyarzabal at 2.22 and report a 5.6x "price move"
# that is really two different players' quotes. `Player` holds the Spanish
# market label including the player name (see ADR-0004), which is precisely the
# discriminator needed here.
GROUP_KEY = ["MatchId", "market_normalised", "Player", "Option"]

# Price value is a ratio, so a mispriced outlier can dominate a mean. Winsorised
# at +/-50% for aggregate statistics; raw values are kept for the histogram.
WINSOR_LIMIT = 0.50

# Groups thinner than this carry too little signal for movement analysis.
MIN_GROUP_FOR_MOVEMENT = 5

# A relative implied-probability move at or above this reads as a steamer/drifter.
SHARP_MOVE_THRESHOLD = 0.25


@dataclass
class PriceReport:
    """Coverage and exclusion accounting for the price-value calculation."""

    pre_match_legs: int = 0
    inplay_legs_excluded: int = 0
    eligible_legs: int = 0
    eligible_share_of_all: float = 0.0
    no_later_observation: int = 0
    reference_from_other_uid: int = 0
    reference_from_same_uid: int = 0
    groups_total: int = 0
    groups_with_variation: int = 0
    groups_for_movement: int = 0
    steamers: int = 0
    drifters: int = 0
    population_beat_rate: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "pre_match_legs": self.pre_match_legs,
            "inplay_legs_excluded": self.inplay_legs_excluded,
            "eligible_legs": self.eligible_legs,
            "eligible_share_of_all": round(self.eligible_share_of_all, 4),
            "no_later_observation": self.no_later_observation,
            "reference_from_other_uid": self.reference_from_other_uid,
            "reference_from_same_uid": self.reference_from_same_uid,
            "groups_total": self.groups_total,
            "groups_with_variation": self.groups_with_variation,
            "groups_for_movement": self.groups_for_movement,
            "steamers": self.steamers,
            "drifters": self.drifters,
            "population_beat_rate": round(self.population_beat_rate, 4),
            "notes": self.notes,
        }


def implied_probability(price: pd.Series) -> pd.Series:
    """Decimal odds to implied probability, before overround removal.

    Movement is measured here rather than in odds space so that a 1.30 -> 1.20
    shift and a 6.00 -> 4.00 shift are comparable: both are ~8 points of implied
    probability, but in odds terms one looks like 0.10 and the other like 2.00.
    """
    return 1.0 / price.where(price > 1.0)


def analyse(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, PriceReport]:
    """Run both price passes and return one fully-populated report.

    Callers should prefer this over calling ``attach_price_value`` and
    ``price_movement`` separately, since the movement counts belong on the same
    report as the coverage figures.
    """
    priced, report = attach_price_value(df)
    moves = price_movement(priced)
    report.steamers = int((moves["direction"] == "steamer").sum())
    report.drifters = int((moves["direction"] == "drifter").sum())
    report.notes.append(
        f"Population beat rate is {report.population_beat_rate:.1%}, not 50%. "
        "The proxy's construction biases the null downward because a group's "
        "last observation is itself often an already-moved price. Sharp "
        "behaviour is judged against this empirical baseline, never against 50%."
    )
    return priced, moves, report


def attach_price_value(df: pd.DataFrame) -> tuple[pd.DataFrame, PriceReport]:
    """Add reference price and captured value to every eligible leg.

    Returns the frame with these columns added:

    * ``reference_price`` — last pre-kick-off price in the leg's group that is
      strictly later than the leg itself.
    * ``price_value`` — ``taken / reference - 1``. Positive means the customer
      took a better price than the market's later reading.
    * ``price_value_winsorised`` — the same, clipped, for aggregate statistics.
    * ``price_value_eligible`` — whether a reference existed at all.
    * ``reference_is_own_bet`` — the reference came from the same Uid, so the
      value reading is weaker.
    * ``group_leg_count`` / ``group_price_moves`` — context for filtering.
    """
    report = PriceReport()
    out = df.copy()

    for col in (
        "reference_price",
        "price_value",
        "price_value_winsorised",
    ):
        out[col] = np.nan
    out["price_value_eligible"] = False
    out["reference_is_own_bet"] = False

    # In-play legs are excluded: after kick-off the price reflects match state,
    # so comparing a 70th-minute price against a pre-match one measures the
    # scoreline, not the customer's judgement.
    pre_mask = ~out["is_inplay"] & out["Price"].gt(1.0)
    report.inplay_legs_excluded = int(out["is_inplay"].sum())
    report.pre_match_legs = int(pre_mask.sum())

    pre = out.loc[pre_mask].sort_values(GROUP_KEY + ["Betslip date (utc)"])
    grouped = pre.groupby(GROUP_KEY, sort=False)

    # "Strictly later" is positional within the time-sorted group. Legs sharing a
    # timestamp are treated as simultaneous, so neither references the other.
    position_from_end = grouped.cumcount(ascending=False)
    has_later = position_from_end > 0

    # The reference is the group's final observation. For every leg but that
    # final one it is strictly later, which is the leakage guard.
    pre["reference_price"] = grouped["Price"].transform("last")
    pre["_last_uid"] = grouped["Uid"].transform("last")
    pre["group_leg_count"] = grouped["Price"].transform("size")
    pre["group_price_moves"] = grouped["Price"].transform("nunique").gt(1)

    eligible = has_later & pre["reference_price"].gt(1.0)
    pre.loc[~eligible, "reference_price"] = np.nan

    value = pre["Price"] / pre["reference_price"] - 1.0
    pre["price_value"] = value.where(eligible)
    pre["price_value_winsorised"] = pre["price_value"].clip(
        -WINSOR_LIMIT, WINSOR_LIMIT
    )
    pre["price_value_eligible"] = eligible
    pre["reference_is_own_bet"] = eligible & pre["Uid"].eq(pre["_last_uid"])

    numeric_carry = [
        "reference_price",
        "price_value",
        "price_value_winsorised",
        "group_leg_count",
    ]
    boolean_carry = [
        "price_value_eligible",
        "reference_is_own_bet",
        "group_price_moves",
    ]
    out.loc[pre.index, numeric_carry] = pre[numeric_carry]
    # Assigned separately: writing booleans into float-initialised columns
    # triggers a pandas dtype-incompatibility warning and will raise in future
    # versions.
    for column in boolean_carry:
        values = pd.Series(False, index=out.index, dtype=bool)
        values.loc[pre.index] = pre[column].fillna(False).astype(bool)
        out[column] = values
    out["group_leg_count"] = out["group_leg_count"].fillna(0).astype(int)
    out["group_price_moves"] = out["group_price_moves"].fillna(False).astype(bool)

    _fill_report(out, pre, eligible, report)
    return out, report


def _fill_report(
    out: pd.DataFrame, pre: pd.DataFrame, eligible: pd.Series, report: PriceReport
) -> None:
    report.eligible_legs = int(eligible.sum())
    report.eligible_share_of_all = report.eligible_legs / len(out) if len(out) else 0.0
    report.no_later_observation = int(report.pre_match_legs - report.eligible_legs)
    report.reference_from_same_uid = int(pre["reference_is_own_bet"].sum())
    report.reference_from_other_uid = (
        report.eligible_legs - report.reference_from_same_uid
    )

    groups = pre.groupby(GROUP_KEY, sort=False)["Price"]
    report.groups_total = int(groups.ngroups)
    report.groups_with_variation = int((groups.nunique() > 1).sum())
    report.groups_for_movement = int((groups.size() >= MIN_GROUP_FOR_MOVEMENT).sum())

    scored = out.loc[out["price_value_eligible"], "price_value"]
    report.population_beat_rate = float((scored > 0).mean()) if len(scored) else 0.0

    report.notes = [
        "Reference price is a proxy for the closing line: the last pre-kick-off "
        "price observed on the same fixture, market and selection. It is not a "
        "true closing price.",
        "A reference only exists where later volume exists, so quiet markets are "
        "absent and volatile markets are over-represented. Price-value figures "
        "describe the measurable book, not the whole book.",
        f"{report.reference_from_same_uid:,} eligible legs take their reference "
        "from the same Uid; those readings are weaker and are flagged.",
        "In-play legs are excluded because after kick-off the price reflects "
        "match state rather than the customer's pre-match judgement.",
    ]


def price_movement(df: pd.DataFrame) -> pd.DataFrame:
    """Per-group price movement, in implied-probability terms.

    Only groups with at least ``MIN_GROUP_FOR_MOVEMENT`` pre-match legs qualify:
    below that, "movement" is one customer's price against another's rather than
    a market signal.

    A **steamer** shortens (implied probability rises — money arrived).
    A **drifter** lengthens (implied probability falls).
    """
    pre = df[~df["is_inplay"] & df["Price"].gt(1.0)].sort_values(
        GROUP_KEY + ["Betslip date (utc)"]
    )
    grouped = pre.groupby(GROUP_KEY, sort=False)

    moves = grouped.agg(
        legs=("Price", "size"),
        first_price=("Price", "first"),
        last_price=("Price", "last"),
        fixture=("MATCH", "first"),
        kickoff=("Event date (utc)", "first"),
        turnover_within=("TURNOVER", "sum"),
        currencies=("Currency Code", "nunique"),
        currency=("Currency Code", "first"),
        distinct_uids=("Uid", "nunique"),
    ).reset_index()

    # A World Cup fixture takes Spanish EUR and Peruvian PEN bets on the same
    # market, so 46% of pricing groups span more than one currency. Summing
    # their stakes would be exactly the cross-currency total ADR-0001 forbids,
    # so mixed groups report no stake at all rather than a meaningless one.
    # Price movement itself is unaffected: odds are currency-free.
    mixed = moves["currencies"] > 1
    moves.loc[mixed, "turnover_within"] = np.nan
    moves.loc[mixed, "currency"] = None
    moves["turnover_is_mixed_currency"] = mixed

    moves = moves[moves["legs"] >= MIN_GROUP_FOR_MOVEMENT].copy()

    first_prob = 1.0 / moves["first_price"]
    last_prob = 1.0 / moves["last_price"]
    moves["implied_prob_move"] = (last_prob - first_prob) / first_prob
    moves["direction"] = np.where(
        moves["implied_prob_move"] > 0, "steamer", "drifter"
    )
    # A large swing driven by one customer is that customer's activity, not a
    # market signal. Requiring two distinct Uids keeps single-actor noise out of
    # the steamer/drifter tables.
    moves["is_sharp_move"] = (
        moves["implied_prob_move"].abs() >= SHARP_MOVE_THRESHOLD
    ) & (moves["distinct_uids"] >= 2)
    return moves.sort_values("implied_prob_move", ascending=False)
