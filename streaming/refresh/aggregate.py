"""Class 1 aggregation, executed inside ClickHouse.

This is the module that stops the refresh job from being a pandas pipeline with
a database attached. Every figure here is produced by a `GROUP BY` in the engine
and arrives already reduced — tens of rows, not tens of millions.

What that buys, measured at 20M rows: ~11s to transfer and parse the raw rows
into pandas before any aggregation, against 2.73s to aggregate them in SQL.

What it costs is that the batch pipeline's rules have to be restated in SQL
rather than inherited, and each one is a chance to get it wrong. They were
verified against the pandas path on the real export before this module was
wired in — every breakdown matches 16/16 rows, and betslip-grain totals match
exactly (55,299 = 55,299). The rules that had to be restated:

  * **Ranking is by count, never turnover** (ADR-0001) — turnover cannot be
    ordered across currencies.
  * **Money is nested under currency**, never summed across; rows with no
    currency are counted and not added to any total.
  * **A `__other__` row carries the tail**, so shares sum to 1.
  * **Betslip identity** (ADR-0003) is not `(uid, timestamp, bet_type)`: a
    customer placing several SIMPLE bets in one second has several betslips.
    Getting this wrong undercounts betslips by 5.9%.

Class 2 and 3 stay in pandas deliberately. The sharp test's validation against a
null (ADR-0006) is worth more than the round trip, and SQL reduces its input to
~700 rows first, so the statistics run on a table small enough that Python's
cost is irrelevant.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from io import StringIO

import pandas as pd

# Dimensions the caller may break down by, and the column each maps to. A fixed
# allow-list: `{dim:Identifier}` is bound from this, never from input.
LEG_DIMENSIONS = {
    "by_market": "market_normalised",
    "by_competition": "competition",
    "by_fixture": "fixture",
    "by_selection": "selection",
    "by_player": "player",
}

BETSLIP_DIMENSIONS = {
    "by_region": "region",
    "by_bet_type": "bet_type",
}

TOP_N = 15

# ADR-0003 betslip identity, as a GROUP BY clause. A SIMPLE leg is its own
# betslip; COMBINED legs group by (uid, timestamp). Measured: the naive key
# merges away 3,265 betslips from 1,662 same-second SIMPLE groups.
BETSLIP_KEY = "if(bet_type = 'SIMPLE', row_key, 0), uid, placed_at, bet_type"


def _run(url: str, sql: str, user: str, password: str, database: str) -> pd.DataFrame:
    params = urllib.parse.urlencode(
        {"user": user, "password": password, "database": database}
    )
    request = urllib.request.Request(
        f"{url}/?{params}", data=sql.encode(), method="POST"
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        payload = response.read().decode()
    if not payload.strip():
        return pd.DataFrame()
    return pd.read_csv(StringIO(payload), sep="\t")


def _is_currency(value) -> bool:
    """A real currency code, not an absent one.

    Reading TSV turns an empty ClickHouse string into the float NaN, which
    `str()` renders as the literal "nan" — and an unresolved currency then
    appears as a currency named "nan" holding real money. ADR-0001 requires
    those rows be counted and never summed into any total, so they are excluded
    here rather than allowed to invent a fourth currency.
    """
    text = str(value).strip()
    return bool(text) and text.lower() != "nan"


def _reduce(column: str) -> str:
    """How to collapse a column when reducing legs to betslips.

    A column that is already part of the betslip key — `bet_type`, `uid` — is
    constant within the group, so `any()` is both correct and cheap. Wrapping it
    in `argMin(col, placed_at) AS col` instead aliases an aggregate to the name
    of a GROUP BY column, and ClickHouse rejects that outright
    (ILLEGAL_AGGREGATION). Third time this trap appeared: the collapse view in
    ADR-0012 and the daily series hit the same wall.
    """
    if column in ("bet_type", "uid", "placed_at"):
        # Selected bare, not aggregated: the column is in GROUP BY, so it is
        # already one value per group. Any aggregate aliased back to its own
        # column name — `any(bet_type) AS bet_type` included — is rejected.
        return column
    return f"argMin({column}, placed_at)"


def _money(frame: pd.DataFrame, key: str) -> dict:
    """Per-currency money for one key, as the payload's nested shape.

    Never a single total: ADR-0001 makes a cross-currency sum unexpressible
    rather than merely discouraged.
    """
    rows = frame[frame["key"] == key]
    return {
        "by_currency": {
            str(r.currency): round(float(r.turnover), 2)
            for r in rows.itertuples()
            if _is_currency(r.currency)
        }
    }


class Aggregator:
    def __init__(
        self,
        url: str = "http://localhost:18123",
        user: str = "srisk",
        password: str = "srisk",
        database: str = "srisk",
    ) -> None:
        self.url, self.user, self.password, self.database = url, user, password, database

    def q(self, sql: str) -> pd.DataFrame:
        return _run(self.url, sql, self.user, self.password, self.database)

    def universe(self) -> dict:
        frame = self.q(
            f"""
            SELECT count()                          AS legs,
                   uniqExact(({BETSLIP_KEY}))       AS betslips,
                   uniqExact(uid)                   AS uids,
                   uniqExact(match_id)              AS fixtures,
                   uniqExact(competition)           AS competitions,
                   toString(toDate(min(placed_at))) AS date_min,
                   toString(toDate(max(placed_at))) AS date_max,
                   countIf(placed_at > event_at)    AS inplay_legs
            FROM betslip_leg FINAL FORMAT TSVWithNames
            """
        )
        return frame.iloc[0].to_dict() if len(frame) else {}

    def money_by_currency(self) -> dict:
        frame = self.q(
            f"""
            SELECT currency,
                   count()                 AS betslips,
                   round(sum(turnover), 2) AS turnover,
                   round(sum(ggr), 2)      AS ggr
            FROM (
                SELECT argMin(currency, placed_at) AS currency,
                       argMin(turnover, placed_at) AS turnover,
                       argMin(ggr, placed_at)      AS ggr
                FROM betslip_leg FINAL
                GROUP BY {BETSLIP_KEY}
            )
            GROUP BY currency ORDER BY turnover DESC FORMAT TSVWithNames
            """
        )
        mask = frame["currency"].map(_is_currency)
        known, unresolved = frame[mask], frame[~mask]
        return {
            "turnover": {
                "by_currency": {
                    str(r.currency): round(float(r.turnover), 2) for r in known.itertuples()
                },
                # Counted, never summed into a total (ADR-0001).
                "unresolved_rows": int(unresolved["betslips"].sum()) if len(unresolved) else 0,
            },
            "ggr": {
                "by_currency": {
                    str(r.currency): round(float(r.ggr), 2) for r in known.itertuples()
                },
                "unresolved_rows": int(unresolved["betslips"].sum()) if len(unresolved) else 0,
            },
        }

    def breakdown(self, dimension: str, grain: str) -> dict:
        """Top-N by count plus an `__other__` tail, with per-currency money."""
        column = (LEG_DIMENSIONS if grain == "leg" else BETSLIP_DIMENSIONS)[dimension]
        # Wrapped in a subquery even for leg grain: `betslip_leg FINAL AS s` is a
        # syntax error — the alias binds before FINAL — and a subquery sidesteps
        # the ordering rule instead of depending on it.
        source = (
            f"(SELECT {column}, currency, turnover, ggr FROM betslip_leg FINAL)"
            if grain == "leg"
            else f"""(
                SELECT {_reduce(column)}           AS {column},
                       argMin(currency, placed_at) AS currency,
                       argMin(turnover, placed_at) AS turnover,
                       argMin(ggr, placed_at)      AS ggr
                FROM betslip_leg FINAL GROUP BY {BETSLIP_KEY}
            )"""
        )
        count_name = "legs" if grain == "leg" else "betslips"

        counts = self.q(
            f"""
            WITH ranked AS (
                SELECT {column} AS key, count() AS n,
                       row_number() OVER (ORDER BY count() DESC, key ASC) AS rank
                FROM {source} GROUP BY key
            )
            SELECT if(rank <= {TOP_N}, key, '__other__') AS key,
                   sum(n)               AS n,
                   countDistinct(key)   AS members
            FROM ranked GROUP BY key ORDER BY n DESC FORMAT TSVWithNames
            """
        )
        money = self.q(
            f"""
            WITH ranked AS (
                SELECT {column} AS key,
                       row_number() OVER (ORDER BY count() DESC, key ASC) AS rank
                FROM {source} GROUP BY key
            )
            SELECT if(r.rank <= {TOP_N}, s.{column}, '__other__') AS key,
                   s.currency                                     AS currency,
                   round(sum(s.turnover), 2)                      AS turnover
            FROM {source} AS s
            INNER JOIN ranked AS r ON s.{column} = r.key
            WHERE s.currency != ''
            GROUP BY key, currency FORMAT TSVWithNames
            """
        )

        total = int(counts["n"].sum()) if len(counts) else 0
        rows = []
        for row in counts.itertuples():
            key = str(row.key)
            label = (
                f"Other ({int(row.members):,} more)" if key == "__other__" else key
            )
            rows.append(
                {
                    "key": key,
                    "label": label,
                    count_name: int(row.n),
                    "share": round(int(row.n) / total, 4) if total else 0.0,
                    "turnover": _money(money, key),
                }
            )
        return {"grain": grain, "rows": rows}

    def daily(self) -> dict:
        frame = self.q(
            f"""
            SELECT toString(toDate(placed_day)) AS day, currency,
                   count()                     AS betslips,
                   round(sum(turnover), 2)     AS turnover
            FROM (
                -- Aliased `placed_day`, not `placed_at`: aliasing an aggregate
                -- to the name of a column that appears in GROUP BY shadows it,
                -- and ClickHouse rejects the query outright
                -- (ILLEGAL_AGGREGATION). Same trap as the collapse view in
                -- ADR-0012.
                SELECT min(placed_at)              AS placed_day,
                       argMin(currency, placed_at) AS currency,
                       argMin(turnover, placed_at) AS turnover
                FROM betslip_leg FINAL GROUP BY {BETSLIP_KEY}
            )
            GROUP BY day, currency ORDER BY day FORMAT TSVWithNames
            """
        )
        rows = []
        for day, group in frame.groupby("day", sort=True):
            rows.append(
                {
                    "day": str(day),
                    "betslips": int(group["betslips"].sum()),
                    "turnover": {
                        "by_currency": {
                            str(r.currency): round(float(r.turnover), 2)
                            for r in group.itertuples()
                            if _is_currency(r.currency)
                        }
                    },
                }
            )
        return {"grain": "betslip", "rows": rows}

    def phases(self) -> dict:
        """Timing relative to kick-off.

        `minutes_to_kickoff` is derived here rather than read from its column:
        a stored derived value can be stale or wrong, as `is_inplay` was — the
        export adapter wrote 0 for every row, and it went unnoticed until the
        sharp test's denominator moved by 5.2%.
        """
        frame = self.q(
            """
            SELECT multiIf(
                       mtk < -10080, 'More than 7d before',
                       mtk < -1440,  '7d to 24h before',
                       mtk < -360,   '24h to 6h before',
                       mtk < -60,    '6h to 60m before',
                       mtk < -5,     '60m to 5m before (post-lineups proxy)',
                       mtk < 0,      '5m to kick-off',
                       mtk < 45,     'In-play: 0-45m',
                       mtk < 90,     'In-play: 45-90m',
                       mtk < 120,    'In-play: 90-120m (extra time)',
                                     'More than 120m after kick-off (residual)'
                   )                       AS phase,
                   currency,
                   count()                 AS legs,
                   round(sum(turnover), 2) AS turnover
            FROM (
                SELECT dateDiff('second', event_at, placed_at) / 60.0 AS mtk,
                       currency, turnover
                FROM betslip_leg FINAL
            )
            GROUP BY phase, currency FORMAT TSVWithNames
            """
        )
        order = [
            "More than 7d before", "7d to 24h before", "24h to 6h before",
            "6h to 60m before", "60m to 5m before (post-lineups proxy)",
            "5m to kick-off", "In-play: 0-45m", "In-play: 45-90m",
            "In-play: 90-120m (extra time)",
            "More than 120m after kick-off (residual)",
        ]
        total = int(frame["legs"].sum()) if len(frame) else 0
        rows = []
        for phase in order:
            group = frame[frame["phase"] == phase]
            if not len(group):
                continue
            legs = int(group["legs"].sum())
            rows.append(
                {
                    "phase": phase,
                    "legs": legs,
                    "share": round(legs / total, 4) if total else 0.0,
                    "turnover": {
                        "by_currency": {
                            str(r.currency): round(float(r.turnover), 2)
                            for r in group.itertuples()
                            if _is_currency(r.currency)
                        }
                    },
                }
            )
        return {"grain": "leg", "rows": rows}
