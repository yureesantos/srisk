"""The canonical model — one match assembled from two feeds.

Design stance on two kinds of value:
  * Facts about the world (score, a player's shots, the kickoff instant) get a
    single resolved `value` plus provenance: where it came from, whether the
    feeds agreed, and the rule applied when they didn't.
  * Quotes (odds) are NOT facts — two bookmakers legitimately price differently,
    so prices are always kept per-source and never collapsed to one number; a
    divergence is information for a human, not an error to resolve.

Every mapped entity carries BOTH source ids (either may be null for a
one-feed-only entity) and a mapping with a confidence and the method used.
Nothing is ever force-matched or silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MappingStatus = Literal["matched", "provisional", "unmatched"]
ReviewCategory = Literal[
    "value_conflict",
    "provisional_mapping",
    "entity_unmatched",
    "market_unmatched",
    "data_quality",
    "price_divergence",
]
Severity = Literal["high", "medium", "low", "info"]


@dataclass(frozen=True)
class SourceIds:
    """The identifiers this entity had in each feed. Both are kept so a consumer
    can join back to either provider; either may be null."""

    alpha: str | None = None
    beta: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"alpha": self.alpha, "beta": self.beta}


@dataclass
class Mapping:
    """How an entity was matched across feeds (or why it wasn't)."""

    status: MappingStatus
    confidence: float | None = None
    method: str | None = None
    review_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence": self.confidence,
            "method": self.method,
            "review_ref": self.review_ref,
        }


@dataclass
class FieldValue:
    """A single reconciled field: the chosen value, whether the feeds agreed,
    each feed's raw value, and — when they disagreed — the rule applied."""

    value: Any
    agreement: bool
    sources: dict[str, Any]
    resolution: str | None = None
    review_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "value": self.value,
            "agreement": self.agreement,
            "sources": self.sources,
        }
        if self.resolution is not None:
            out["resolution"] = self.resolution
        if self.review_ref is not None:
            out["review_ref"] = self.review_ref
        return out


@dataclass
class Team:
    canonical_name: str
    role: Literal["home", "away"]
    source_ids: SourceIds
    source_names: dict[str, str | None]
    mapping: Mapping

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "role": self.role,
            "source_ids": self.source_ids.to_dict(),
            "source_names": self.source_names,
            "mapping": self.mapping.to_dict(),
        }


@dataclass
class Player:
    canonical_name: str
    team_role: str | None
    position: str | None
    source_ids: SourceIds
    source_names: dict[str, str | None]
    mapping: Mapping
    stats: dict[str, FieldValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "team_role": self.team_role,
            "position": self.position,
            "source_ids": self.source_ids.to_dict(),
            "source_names": self.source_names,
            "mapping": self.mapping.to_dict(),
            "stats": {k: v.to_dict() for k, v in self.stats.items()},
        }


@dataclass
class Selection:
    """One runner of a market, with each feed's decimal-normalized price kept
    separately (odds are quotes, not facts)."""

    name: str
    prices: dict[str, float | None]
    agreement: bool | None = None
    review_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "name": self.name,
            "prices": self.prices,
            "agreement": self.agreement,
        }
        if self.review_ref is not None:
            out["review_ref"] = self.review_ref
        return out


@dataclass
class Market:
    market_type: str
    line: float | None
    player_ref: str | None
    source_codes: dict[str, str | None]
    mapping: Mapping
    selections: list[Selection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_type": self.market_type,
            "line": self.line,
            "player_ref": self.player_ref,
            "source_codes": self.source_codes,
            "mapping": self.mapping.to_dict(),
            "selections": [s.to_dict() for s in self.selections],
        }


@dataclass
class ReviewItem:
    """One thing a human should look at: an unmatched entity, an unresolved or
    resolved-but-notable conflict, or a data-quality flag."""

    id: str
    category: ReviewCategory
    entity_type: str
    entity_ref: str
    reason: str
    suggested_action: str
    severity: Severity
    source_ids: SourceIds | None = None
    competing_values: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "category": self.category,
            "entity_type": self.entity_type,
            "entity_ref": self.entity_ref,
            "severity": self.severity,
            "reason": self.reason,
            "suggested_action": self.suggested_action,
        }
        if self.source_ids is not None:
            out["source_ids"] = self.source_ids.to_dict()
        if self.competing_values is not None:
            out["competing_values"] = self.competing_values
        return out


@dataclass
class Match:
    source_ids: SourceIds
    competition: FieldValue
    kickoff_utc: FieldValue
    status: FieldValue
    score: FieldValue
    teams: list[Team] = field(default_factory=list)
    players: list[Player] = field(default_factory=list)
    markets: list[Market] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_ids": self.source_ids.to_dict(),
            "competition": self.competition.to_dict(),
            "kickoff_utc": self.kickoff_utc.to_dict(),
            "status": self.status.to_dict(),
            "score": self.score.to_dict(),
            "teams": [t.to_dict() for t in self.teams],
            "players": [p.to_dict() for p in self.players],
            "markets": [m.to_dict() for m in self.markets],
        }
