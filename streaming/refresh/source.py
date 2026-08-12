"""Read the collapsed table into the frame the batch pipeline already expects.

The decision that shapes this module: **the analysis is not reimplemented in
SQL.** ClickHouse does what it is good at — scan 20M rows, collapse versions,
project columns — and hands back a frame in exactly the shape `load.load()`
produces. Everything downstream (`prices.analyse`, `betflow.analyse`,
`sharp.analyse`) is then the code already validated in the batch pipeline,
unchanged.

Three reasons, in order of weight:

1. **The statistics are validated and that validation is worth more than the
   round trip.** ADR-0006 records that the sharp test was checked against a null:
   20 simulations of 701 random windows flagged 0 windows in 20 of 20 runs.
   Reimplementing an exact binomial test and Benjamini–Hochberg in SQL would
   discard that evidence and require rebuilding it.
2. **The oracle comparison becomes meaningful.** If both paths run the same
   aggregation code, a divergence points at the data or the adapter — not at two
   implementations of the same formula disagreeing in the tenth decimal.
3. **Grain is where this would go wrong.** Turnover is only valid at betslip
   grain (ADR-0003), and `_betslip_frame` reconstructs that grain in pandas.
   Rebuilding it in SQL was the likeliest source of divergence in the plan;
   reusing it removes the risk rather than managing it.

What ClickHouse does carry is the collapse (`FINAL`, ADR-0012) and the column
projection. What it does not carry is any statistic.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from io import StringIO

import pandas as pd

# Column aliases map the schema back onto the export's names, because that is
# what the batch pipeline's contract is written against. Renaming here keeps the
# adapter in one place instead of touching validated code.
SELECT_COLUMNS = """
    'Football'                          AS `Sport`,
    competition                         AS `Competition`,
    match_id                            AS `MatchId`,
    fixture                             AS `MATCH`,
    event_at                            AS `Event date (utc)`,
    market                              AS `Market`,
    bet_type                            AS `BetType`,
    player                              AS `Player`,
    selection                           AS `Option`,
    placed_at                           AS `Betslip date (utc)`,
    uid                                 AS `Uid`,
    region                              AS `Management unit`,
    price                               AS `Price`,
    turnover                            AS `TURNOVER`,
    ggr                                 AS `GGR`,
    net_revenue                         AS `Net Revenue`,
    currency                            AS `Currency Code`,
    source                              AS `source_file`
"""

# Every read collapses. ADR-0012: omitting FINAL does not merely inflate — it
# can invert the sign of GGR, and it is intermittent, because a background merge
# makes the wrong query start returning the right answer.
# The table is unqualified: the database comes from the connection, so a
# caller pointed at another one actually reads there. A qualified name
# silently ignores the parameter, which is how two workstreams ended up
# sharing one table.
BASE_QUERY = f"SELECT {SELECT_COLUMNS} FROM betslip_leg FINAL"

DEFAULT_URL = "http://localhost:18123"


def _run(url: str, query: str, user: str, password: str, database: str) -> str:
    params = urllib.parse.urlencode(
        {"user": user, "password": password, "database": database}
    )
    request = urllib.request.Request(
        f"{url}/?{params}", data=query.encode(), method="POST"
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read().decode()


def watermark(
    url: str = DEFAULT_URL,
    user: str = "srisk",
    password: str = "srisk",
    database: str = "srisk",
) -> dict:
    """Highest ingested version and row counts — the artifact's position in the stream.

    ADR-0009 replaced the batch artifact hash with "reproducible by replaying the
    stream to this watermark". This is that position: `max(version)` over the
    stored rows, plus the collapsed and uncollapsed counts, whose difference is
    how many supersedences are currently outstanding.
    """
    query = """
        SELECT max(version)      AS watermark,
               count()           AS rows_stored,
               uniqExact(row_key) AS identities
        FROM betslip_leg FORMAT TSV
    """
    line = _run(url, query, user, password, database).strip().split("\t")
    return {
        "watermark": int(line[0]) if line[0] else 0,
        "rows_stored": int(line[1]),
        "identities": int(line[2]),
    }


def read_legs(
    url: str = DEFAULT_URL,
    user: str = "srisk",
    password: str = "srisk",
    database: str = "srisk",
    where: str | None = None,
) -> pd.DataFrame:
    """The collapsed table, as the frame `load.load()` would have returned.

    `where` scopes a window (Class 3 metrics are window-bounded, ADR-0009);
    omitted, it reads everything.
    """
    # Row order is deterministic per read, but it is NOT the batch pipeline's
    # order and cannot be. The batch loader preserves the order rows appear in
    # the spreadsheet; a stream has no such order — events arrive when they
    # arrive, and ADR-0007 makes arrival order deliberately irrelevant.
    #
    # This matters because `_betslip_frame` reduces each betslip with `first()`.
    # Where a betslip's legs disagree on a field — a leg missing its currency, or
    # the differing stakes ADR-0003 documents — the surviving value depends on
    # which leg comes first. Measured against the oracle over identical rows:
    # 1,246 betslips resolve to a different currency and 1,059 to a different
    # turnover, moving per-region totals by up to 4.17 EUR on 400k.
    #
    # Ordering by the identity key is the honest choice: reproducible across
    # reads (so the artifact hash is stable), and independent of arrival.
    order = " ORDER BY row_key"
    query = BASE_QUERY + (f" WHERE {where}" if where else "") + order + " FORMAT TSVWithNames"
    payload = _run(url, query, user, password, database)

    frame = pd.read_csv(
        StringIO(payload),
        sep="\t",
        dtype={"Uid": str},
        parse_dates=["Event date (utc)", "Betslip date (utc)"],
    )

    # The batch pipeline's contract, restored: MatchId is an integer, money is
    # float, and Management unit carries the raw label that `_enrich` normalises
    # into `region`. Reading TSV gives strings for some of these.
    frame["MatchId"] = frame["MatchId"].astype("int64")
    for column in ("Price", "TURNOVER", "GGR", "Net Revenue"):
        frame[column] = frame[column].astype(float)

    return frame
