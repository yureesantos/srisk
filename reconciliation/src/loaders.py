"""Feed loaders — the only modules that know each provider's schema.

Each `load_*` turns a provider's idiosyncratic JSON into a uniform intermediate
(`FeedMatch`) so every module downstream works against one shape. All the schema
divergence — beta's `perf.g/sh/sot` vs alpha's `stats.goals/shots/...`, alpha's
packed market codes vs beta's nested price objects, int ids vs string ids — is
absorbed here and nowhere else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import normalize as N


@dataclass
class FeedTeam:
    source_id: str
    role: str  # "home" | "away"
    name: str


@dataclass
class FeedPlayer:
    source_id: str
    team_source_id: str | None
    name: str
    position: str | None
    stats: dict[str, int]  # canonical keys: goals, shots, shots_on_target


@dataclass
class FeedSelection:
    name: str  # normalized: over/under/yes/no/home/away
    price: float  # decimal


@dataclass
class FeedMarket:
    market_type: str
    line: float | None
    player_source_id: str | None
    source_code: str
    selections: list[FeedSelection] = field(default_factory=list)


@dataclass
class FeedMatch:
    provider: str
    match_source_id: str
    competition: str
    kickoff: str  # raw ISO string; normalized later
    status_settled: bool
    status_raw: str
    score: dict[str, int]  # {"home": int, "away": int}
    teams: list[FeedTeam]
    players: list[FeedPlayer]
    markets: list[FeedMarket]


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _norm_selection_name(name: str) -> str:
    return name.strip().casefold()


def load_alpha(path: str | Path) -> FeedMatch:
    """Parse the stats-style feed: int ids (stringified), decimal prices, market
    metadata packed into '@'-delimited codes."""
    raw = _read_json(path)
    fx = raw["fixture"]

    teams = [
        FeedTeam(str(fx["home_team"]["team_id"]), "home", fx["home_team"]["name"]),
        FeedTeam(str(fx["away_team"]["team_id"]), "away", fx["away_team"]["name"]),
    ]

    players = [
        FeedPlayer(
            source_id=str(p["player_id"]),
            team_source_id=str(p["team_id"]),
            name=p["name"],
            position=p.get("position"),
            stats={
                "goals": p["stats"]["goals"],
                "shots": p["stats"]["shots"],
                "shots_on_target": p["stats"]["shots_on_target"],
            },
        )
        for p in raw["players"]
    ]

    # Group the flat (code, selection, price) rows into markets keyed by code.
    by_code: dict[str, FeedMarket] = {}
    for row in raw["markets"]:
        parsed = N.parse_alpha_market_code(row["code"])
        market = by_code.get(row["code"])
        if market is None:
            market = FeedMarket(
                market_type=parsed.market_type,
                line=parsed.line,
                player_source_id=parsed.player_source_id,
                source_code=row["code"],
            )
            by_code[row["code"]] = market
        market.selections.append(
            FeedSelection(_norm_selection_name(row["selection"]), float(row["price"]))
        )

    return FeedMatch(
        provider=raw["provider"],
        match_source_id=str(fx["fixture_id"]),
        competition=fx["competition"],
        kickoff=fx["kickoff_utc"],
        status_settled=fx["status"] == "complete",
        status_raw=fx["status"],
        score={"home": fx["final_score"]["home"], "away": fx["final_score"]["away"]},
        teams=teams,
        players=players,
        markets=list(by_code.values()),
    )


def load_beta(path: str | Path) -> FeedMatch:
    """Parse the bookmaker-style feed: own string ids, abbreviated names,
    fractional odds, nested market objects, `perf` stat keys."""
    raw = _read_json(path)
    ev = raw["event"]

    teams = [
        FeedTeam(ev["teams"]["home"]["id"], "home", ev["teams"]["home"]["short"]),
        FeedTeam(ev["teams"]["away"]["id"], "away", ev["teams"]["away"]["short"]),
    ]

    players = [
        FeedPlayer(
            source_id=p["id"],
            team_source_id=p.get("team"),  # may be null (unidentified player)
            name=p["label"],
            position=None,  # beta carries no position
            stats={
                "goals": p["perf"]["g"],
                "shots": p["perf"]["sh"],
                "shots_on_target": p["perf"]["sot"],
            },
        )
        for p in raw["lineup"]
    ]

    # Group nested price objects into markets keyed by (market, line, player).
    by_key: dict[tuple, FeedMarket] = {}
    for row in raw["prices"]:
        market_type = N.canonical_market_type(row["market"])
        line = row.get("line")
        player_source_id = row.get("player")
        key = (row["market"], line, player_source_id)
        market = by_key.get(key)
        if market is None:
            market = FeedMarket(
                market_type=market_type,
                line=line,
                player_source_id=player_source_id,
                source_code=row["market"],
            )
            by_key[key] = market
        market.selections.append(
            FeedSelection(
                _norm_selection_name(row["runner"]),
                N.fractional_to_decimal(row["odds"]),
            )
        )

    return FeedMatch(
        provider=raw["provider"],
        match_source_id=ev["event_ref"],
        competition=ev["league"],
        kickoff=ev["start"],
        status_settled=bool(ev["settled"]),
        status_raw="settled" if ev["settled"] else "unsettled",
        score={"home": ev["result"]["home_goals"], "away": ev["result"]["away_goals"]},
        teams=teams,
        players=players,
        markets=list(by_key.values()),
    )
