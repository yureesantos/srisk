"""Betslip leg generation, with distributions calibrated against the real export.

Ported from `streaming/load/synthesise.sql`, which established the parameters by
fitting them to `data/raw/`. The SQL version generates server-side for bulk
loading; this one generates per-event for the producer. **They must agree in
shape**, which `check_shape.py` asserts rather than assumes — the two draw from
different RNGs (ClickHouse's cityHash64-derived uniforms against Python's
Mersenne Twister), so identical constants do not guarantee identical
distributions.

Why calibration matters at all: uniformly random values would make every
concentration metric meaningless. A uniform stake distribution gives a Gini near
0 against the 0.803 measured on EUR turnover per Uid, and no anomaly detector
would fire because there would be no anomalies to find. The generator has to
reproduce the *shape* of the data, not merely its column types.

Measured targets, from `data/raw/`:

    Gini (EUR turnover per Uid)     0.803
    legs per Uid                    median 4, max 2,238 (560x ratio)
    cardinalities                   competition 56 · fixture 453 · market 119
                                    player 2,714 · selection 6,014 · region 31
    currency mix                    EUR 88% · PEN 12% · USD <1%
    leg/betslip inflation           1.087x (EUR)
"""

from __future__ import annotations

import bisect
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Labels are drawn from the **real export's vocabulary at its measured
# frequencies**, not synthesised as "Market 47".
#
# This is not cosmetic. The pipeline reads meaning out of these strings:
# `normalise_market` collapses `{PLAYER}` and `{goalnr}` templates and names
# `{COMPETITOR1}`/`{COMPETITOR2}` as bet builders (10.6% of legs), and player
# resolution keys off market families like "goalscorer" and "to score"
# (ADR-0004). Generic labels match none of those paths, so the analysis runs
# against a book containing no player-centric markets at all — which surfaced as
# a ZeroDivisionError in `_player_breakdown` on the first refresh run, dividing
# by a count that was zero.
_VOCAB = json.loads(Path(__file__).with_name("vocabulary.json").read_text())

N_FIXTURES = 453


def _weighted(entries: list) -> tuple[list, list]:
    """[[label, weight], ...] -> (labels, cumulative distribution)."""
    labels = [e[0] for e in entries]
    cumulative, running = [], 0.0
    for _, weight in entries:
        running += weight
        cumulative.append(running)
    return labels, cumulative


MARKETS, MARKET_CDF = _weighted(_VOCAB["markets"])
COMPETITIONS, COMPETITION_CDF = _weighted(_VOCAB["competitions"])
REGIONS, REGION_CDF = _weighted(_VOCAB["regions"])
PLAYERS, PLAYER_CDF = _weighted(_VOCAB["players"])
SELECTIONS, SELECTION_CDF = _weighted(_VOCAB["selections"])

# The Uid pool is derived from the event count, not fixed. The export carries
# 113k legs over 10,405 Uids — **10.8 legs per Uid** — and that ratio, not the
# absolute pool size, is what the concentration metrics see. A fixed pool would
# make the shape depend on how long the producer ran, so a 5-minute run and an
# hour-long run would not be comparable.
#
# Calibrated together with UID_POWER and STAKE_SIGMA against the real export:
# these reproduce Gini 0.796 (0.803 measured) at a median of 6 legs per Uid
# (4 measured). Changing one without re-running check_shape.py invalidates all
# three.
LEGS_PER_UID = 10.0
UID_POWER = 2.6
MIN_UID_POOL = 1_000

# Log-normal parameters. sigma is the dominant control on concentration.
STAKE_MU, STAKE_SIGMA = 2.3, 2.4
STAKE_MIN, STAKE_MAX = 0.10, 500_000.0
PRICE_MU, PRICE_SIGMA = 0.85, 0.55
PRICE_MIN, PRICE_MAX = 1.01, 250.0

# Currency mix in per-mille, cumulative. EUR 88.0%, PEN 11.8%, USD 0.2%.
CURRENCY_CUTS = ((880, "EUR"), (998, "PEN"), (1000, "USD"))

# SIMPLE share, measured against the 1.087x leg/betslip inflation.
SIMPLE_SHARE_PCT = 78

# Share of settled legs the house wins. Derived from the export's GGR sign split.
HOUSE_WIN_PER_MILLE = 556

# The export is effectively a June book: 23 dense trading days carrying 99.8% of
# betslips (ADR-0007 context). 1,987,200 seconds is 23 days.
BOOK_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
BOOK_SECONDS = 1_987_200

# Kick-off sits within +/- 24h of placement, so both pre-match and in-play legs
# occur. `is_inplay` follows from the comparison, never from a separate draw.
KICKOFF_WINDOW_SECONDS = 172_800
KICKOFF_OFFSET_SECONDS = 86_400

EVENT_PLACEMENT = "placement"
EVENT_REVERSAL = "reversal"

SOURCE_A_SHARE_PCT = 70


@dataclass
class Leg:
    """One betslip leg, in the shape the consumer expects on the wire."""

    uid: str
    placed_at: str
    event_at: str
    bet_type: str
    match_id: int
    fixture: str
    competition: str
    market: str
    player: str
    selection: str
    region: str
    currency: str
    price: float
    turnover: float
    ggr: float
    net_revenue: float
    event_kind: str
    source: str
    is_inplay: int
    minutes_to_kickoff: float
    emitted_at: int

    def as_dict(self) -> dict:
        return self.__dict__


@dataclass
class Generator:
    """Draws legs from the calibrated distributions.

    Deterministic for a given seed: the same seed and count produce byte-identical
    output, which is what makes the consumer's replay tests meaningful.
    """

    seed: int = 42
    reversal_share: float = 0.0
    duplicate_share: float = 0.0
    # Expected total events, used only to size the Uid pool so the legs-per-Uid
    # ratio holds regardless of run length. An approximate value is fine — the
    # ratio moves slowly with it.
    expected_events: int = 300_000
    _rng: random.Random = field(init=False)
    _uid_pool: int = field(init=False)
    _pending_reversals: list = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._uid_pool = max(MIN_UID_POOL, int(self.expected_events / LEGS_PER_UID))

    def _lognormal(self, mu: float, sigma: float, lo: float, hi: float) -> float:
        return min(max(math.exp(mu + sigma * self._rng.gauss(0.0, 1.0)), lo), hi)

    def _uid(self) -> str:
        """Power-transformed uniform: a few windows absorb most of the activity.

        Raising u to UID_POWER crushes most draws toward 0, so low-numbered Uids
        are drawn far more often — reproducing the measured 560x ratio between
        the busiest Uid and the median.
        """
        u = self._rng.random()
        return str(int((u**UID_POWER) * self._uid_pool))

    def _currency(self) -> str:
        draw = self._rng.randrange(1000)
        for cut, code in CURRENCY_CUTS:
            if draw < cut:
                return code
        return "USD"

    def _pick(self, labels: list, cdf: list) -> str:
        """Draw a label at its measured frequency."""
        return labels[bisect.bisect_left(cdf, self._rng.random() * cdf[-1])]

    def leg(self, emitted_at: int) -> Leg:
        placed = BOOK_START + timedelta(seconds=self._rng.randrange(BOOK_SECONDS))
        event = placed + timedelta(
            seconds=self._rng.randrange(KICKOFF_WINDOW_SECONDS) - KICKOFF_OFFSET_SECONDS
        )

        price = round(self._lognormal(PRICE_MU, PRICE_SIGMA, PRICE_MIN, PRICE_MAX), 3)
        turnover = round(self._lognormal(STAKE_MU, STAKE_SIGMA, STAKE_MIN, STAKE_MAX), 2)

        # Settled outcome: the house keeps the stake, or pays out at the taken
        # price. GGR is negative when the customer won.
        if self._rng.randrange(1000) < HOUSE_WIN_PER_MILLE:
            ggr = turnover
        else:
            ggr = round(-turnover * (price - 1.0), 2)

        match_id = 30_000_000 + self._rng.randrange(N_FIXTURES)
        minutes = (placed - event).total_seconds() / 60.0

        return Leg(
            uid=self._uid(),
            placed_at=placed.isoformat(timespec="milliseconds"),
            event_at=event.isoformat(timespec="milliseconds"),
            bet_type="SIMPLE" if self._rng.randrange(100) < SIMPLE_SHARE_PCT else "COMBINED",
            match_id=match_id,
            fixture=f"Fixture {match_id - 30_000_000}",
            competition=self._pick(COMPETITIONS, COMPETITION_CDF),
            market=self._pick(MARKETS, MARKET_CDF),
            player=self._pick(PLAYERS, PLAYER_CDF),
            selection=self._pick(SELECTIONS, SELECTION_CDF),
            region=self._pick(REGIONS, REGION_CDF),
            currency=self._currency(),
            price=price,
            turnover=turnover,
            ggr=ggr,
            net_revenue=round(ggr * 0.08, 2),
            event_kind=EVENT_PLACEMENT,
            source="partner_a" if self._rng.randrange(100) < SOURCE_A_SHARE_PCT else "partner_b",
            is_inplay=int(placed > event),
            minutes_to_kickoff=round(minutes, 2),
            emitted_at=emitted_at,
        )

    def emit(self, emitted_at: int) -> list[Leg]:
        """One draw, expanded into the events that actually go on the wire.

        Returns a list because a single logical leg can produce several events:

        * a **duplicate** — the same event delivered twice, which is the regime
          the exports are already in (36,832 and 17,253 exact duplicates). This is
          what proves the consumer is idempotent rather than assuming it.
        * a **reversal** — a later settlement correction carrying the same
          identity, a higher `emitted_at`, and `ggr == turnover`, the signature
          measured on 14 of 14 revised rows in the real export (ADR-0007).

        Reversals are held and released later rather than emitted adjacently, so
        the consumer sees them out of order relative to their placement — which
        is the condition ADR-0007's version contract exists to survive.
        """
        events = [self.leg(emitted_at)]

        if self.duplicate_share and self._rng.random() < self.duplicate_share:
            events.append(events[0])

        if self.reversal_share and self._rng.random() < self.reversal_share:
            self._pending_reversals.append(events[0])

        # Release a held reversal roughly one in three emissions, so corrections
        # trail their placements by a variable gap.
        if self._pending_reversals and self._rng.randrange(3) == 0:
            original = self._pending_reversals.pop(0)
            reversed_leg = Leg(**{**original.as_dict()})
            reversed_leg.event_kind = EVENT_REVERSAL
            reversed_leg.ggr = original.turnover
            reversed_leg.net_revenue = round(original.turnover * 0.08, 2)
            # A higher version is what makes this supersede rather than duplicate.
            reversed_leg.emitted_at = emitted_at + 1
            events.append(reversed_leg)

        return events
