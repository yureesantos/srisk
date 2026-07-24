"""Entity matching across the two feeds, in dependency order.

Teams first (they scope player matching), then players (they scope player-market
matching), then markets. Every function returns the canonical entities with both
source ids and a `Mapping`; nothing is force-matched, and anything provisional or
unmatched is recorded in the review list.

Confidence is a small set of documented tiers, not a pseudo-continuous score
that would imply a precision we don't have:

    1.0  exact after normalization
    0.9  structural / initial-expansion ("E. Haaland" ↔ "Erling Haaland")
    0.6  nickname-prefix heuristic ("Rodri" ⊂ "Rodrigo Hernandez")
    <    no candidate

Thresholds: >= 0.8 matched · 0.5–0.8 provisional (merged, both ids kept, flagged)
· < 0.5 unmatched (kept with its single source id, never force-matched).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import normalize as N
from .loaders import FeedMatch, FeedPlayer
from .models import Mapping, Market, Player, Selection, SourceIds, Team
from .review import ReviewBuilder

MATCH_THRESHOLD = 0.8
PROVISIONAL_THRESHOLD = 0.5

# Labels a matcher must never treat as a real name.
_PLACEHOLDER_LABELS = {"unidentified player", "unknown player", "unknown"}


@dataclass
class TeamMatchResult:
    teams: list[Team]
    # role -> (alpha_source_id, beta_source_id) for downstream scoping.
    role_ids: dict[str, tuple[str | None, str | None]]


@dataclass
class PlayerMatchResult:
    players: list[Player]
    # alpha_source_id -> beta_source_id for player-market resolution.
    alpha_to_beta: dict[str, str]


@dataclass
class MarketMatchResult:
    markets: list[Market]


# --- teams -----------------------------------------------------------------


def _team_name_confidence(a_name: str, b_name: str) -> tuple[float, str]:
    an, bn = N.norm_team_name(a_name), N.norm_team_name(b_name)
    if an == bn:
        return 1.0, "exact_after_normalization"
    # Token-prefix check: "man city" vs "manchester city" — each shorter token
    # is a prefix of the aligned longer token.
    at, bt = an.split(), bn.split()
    if len(at) == len(bt) and all(
        s.startswith(t) or t.startswith(s) for s, t in zip(at, bt)
    ):
        return 0.9, "name_prefix"
    return 0.0, "no_name_match"


def match_teams(alpha: FeedMatch, beta: FeedMatch, review: ReviewBuilder | None = None) -> TeamMatchResult:
    """Teams are matched on the home/away role both feeds declare — a structural
    key — then verified by name. A role match that fails name verification is
    kept but flagged (defensive; does not trigger on this data)."""
    review = review or ReviewBuilder()
    teams: list[Team] = []
    role_ids: dict[str, tuple[str | None, str | None]] = {}

    for role in ("home", "away"):
        a = next(t for t in alpha.teams if t.role == role)
        b = next(t for t in beta.teams if t.role == role)
        conf, method = _team_name_confidence(a.name, b.name)

        review_ref = None
        if conf == 0.0:
            review_ref = review.add(
                category="value_conflict",
                entity_type="team",
                entity_ref=f"{role} team",
                reason=f"role-matched but names disagree: {a.name!r} vs {b.name!r}",
                suggested_action="confirm the feeds refer to the same club",
                severity="high",
                source_ids=SourceIds(a.source_id, b.source_id),
                competing_values={"alpha": a.name, "beta": b.name},
            )
            status, conf_out = "provisional", None
        else:
            status, conf_out = "matched", conf

        teams.append(
            Team(
                canonical_name=a.name,  # alpha's fuller form
                role=role,  # type: ignore[arg-type]
                source_ids=SourceIds(a.source_id, b.source_id),
                source_names={"alpha": a.name, "beta": b.name},
                mapping=Mapping(status=status, confidence=conf_out, method=method, review_ref=review_ref),  # type: ignore[arg-type]
            )
        )
        role_ids[role] = (a.source_id, b.source_id)

    return TeamMatchResult(teams=teams, role_ids=role_ids)


# --- players ---------------------------------------------------------------


def _player_pair_confidence(a: FeedPlayer, b: FeedPlayer) -> tuple[float, str]:
    """Score an alpha/beta player pair already known to share a team."""
    an, bn = N.norm_name(a.name), N.norm_name(b.name)
    if an == bn:
        return 1.0, "exact_after_normalization"

    a_tokens, b_tokens = an.split(), bn.split()

    # Initial-expansion: beta "X. Surname" vs alpha "Given Surname".
    # Same surname, and the abbreviated initial matches a full given name.
    if a_tokens and b_tokens and a_tokens[-1] == b_tokens[-1]:
        b_first = b_tokens[0].rstrip(".")
        if len(b_first) == 1 and any(g.startswith(b_first) for g in a_tokens[:-1]):
            return 0.9, "initial_expansion"
        a_first = a_tokens[0].rstrip(".")
        if len(a_first) == 1 and any(g.startswith(a_first) for g in b_tokens[:-1]):
            return 0.9, "initial_expansion"

    # Nickname-prefix heuristic: a single-token name that is a prefix of the
    # other's first token, same team ("rodri" ⊂ "rodrigo hernandez"). Low
    # confidence on purpose — a lexical hint, not proof.
    if len(a_tokens) == 1 and b_tokens and b_tokens[0].startswith(a_tokens[0]):
        return 0.6, "nickname_prefix"
    if len(b_tokens) == 1 and a_tokens and a_tokens[0].startswith(b_tokens[0]):
        return 0.6, "nickname_prefix"

    return 0.0, "no_candidate"


def _stat_field(a_val, b_val):
    # Placeholder — real reconciliation of stats lives in reconcile.py, which the
    # pipeline calls. Here we only need the merged entity to exist.
    return None


def match_players(
    alpha: FeedMatch, beta: FeedMatch, teams: TeamMatchResult, review: ReviewBuilder | None = None
) -> PlayerMatchResult:
    """Greedy one-to-one matching within each mapped team, highest score first,
    deterministic tie-break by alpha source id. Placeholder-labelled or
    null-team beta players are routed to review before matching."""
    review = review or ReviewBuilder()

    # Map beta team ids to roles so a beta player can be scoped to a role.
    beta_team_role = {b_id: role for role, (_, b_id) in teams.role_ids.items()}
    alpha_team_role = {a_id: role for role, (a_id, _) in teams.role_ids.items()}

    used_beta: set[str] = set()
    players: list[Player] = []
    alpha_to_beta: dict[str, str] = {}

    # Beta players that can never be matched: no team, or a placeholder label.
    unmatchable_beta: list[FeedPlayer] = []
    matchable_beta: list[FeedPlayer] = []
    for p in beta.players:
        if p.team_source_id is None or N.norm_name(p.name) in _PLACEHOLDER_LABELS:
            unmatchable_beta.append(p)
        else:
            matchable_beta.append(p)

    # Score every valid alpha/beta pair within the same team.
    candidates: list[tuple[float, str, FeedPlayer, FeedPlayer, str]] = []
    for a in alpha.players:
        a_role = alpha_team_role.get(a.team_source_id or "")
        for b in matchable_beta:
            if beta_team_role.get(b.team_source_id or "") != a_role:
                continue
            conf, method = _player_pair_confidence(a, b)
            if conf >= PROVISIONAL_THRESHOLD:
                candidates.append((conf, method, a, b, a.source_id))

    # Greedy assignment: highest confidence first, tie-break by alpha id.
    candidates.sort(key=lambda c: (-c[0], c[4]))
    matched_alpha: dict[str, tuple[float, str, FeedPlayer]] = {}
    for conf, method, a, b, _ in candidates:
        if a.source_id in matched_alpha or b.source_id in used_beta:
            continue
        matched_alpha[a.source_id] = (conf, method, b)
        used_beta.add(b.source_id)

    # Emit matched / provisional players (alpha-driven).
    for a in alpha.players:
        role = alpha_team_role.get(a.team_source_id or "")
        if a.source_id in matched_alpha:
            conf, method, b = matched_alpha[a.source_id]
            alpha_to_beta[a.source_id] = b.source_id
            if conf >= MATCH_THRESHOLD:
                status, review_ref = "matched", None
            else:
                status = "provisional"
                review_ref = review.add(
                    category="provisional_mapping",
                    entity_type="player",
                    entity_ref=a.name,
                    reason=(
                        f"low-confidence name match: {a.name!r} ↔ {b.name!r} "
                        f"({method}); same team, but lexically weak"
                    ),
                    suggested_action="confirm the two ids are the same player; add an alias if so",
                    severity="medium",
                    source_ids=SourceIds(a.source_id, b.source_id),
                    competing_values={"alpha": a.name, "beta": b.name},
                )
            players.append(
                Player(
                    canonical_name=a.name,
                    team_role=role,
                    position=a.position,
                    source_ids=SourceIds(a.source_id, b.source_id),
                    source_names={"alpha": a.name, "beta": b.name},
                    mapping=Mapping(status=status, confidence=conf, method=method, review_ref=review_ref),  # type: ignore[arg-type]
                )
            )
        else:
            # Alpha-only player.
            review_ref = review.add(
                category="entity_unmatched",
                entity_type="player",
                entity_ref=a.name,
                reason="present in alpha only; no beta counterpart",
                suggested_action="confirm the player featured / add mapping if a beta id exists",
                severity="low",
                source_ids=SourceIds(a.source_id, None),
            )
            players.append(
                Player(
                    canonical_name=a.name,
                    team_role=role,
                    position=a.position,
                    source_ids=SourceIds(a.source_id, None),
                    source_names={"alpha": a.name, "beta": None},
                    mapping=Mapping(status="unmatched", confidence=None, method="no_candidate", review_ref=review_ref),
                )
            )

    # Beta-only matchable players.
    for b in matchable_beta:
        if b.source_id in used_beta:
            continue
        role = beta_team_role.get(b.team_source_id or "")
        review_ref = review.add(
            category="entity_unmatched",
            entity_type="player",
            entity_ref=b.name,
            reason="present in beta only; no alpha counterpart",
            suggested_action="confirm the player featured / add mapping if an alpha id exists",
            severity="low",
            source_ids=SourceIds(None, b.source_id),
        )
        players.append(
            Player(
                canonical_name=b.name,
                team_role=role,
                position=None,
                source_ids=SourceIds(None, b.source_id),
                source_names={"alpha": None, "beta": b.name},
                mapping=Mapping(status="unmatched", confidence=None, method="no_candidate", review_ref=review_ref),
            )
        )

    # Unmatchable beta players (null team / placeholder) — data-quality flags.
    for b in unmatchable_beta:
        review_ref = review.add(
            category="data_quality",
            entity_type="player",
            entity_ref=b.name,
            reason="cannot be matched: no team and/or a placeholder label",
            suggested_action="identify the player in the source feed, or drop the record",
            severity="medium",
            source_ids=SourceIds(None, b.source_id),
        )
        players.append(
            Player(
                canonical_name=b.name,
                team_role=None,
                position=None,
                source_ids=SourceIds(None, b.source_id),
                source_names={"alpha": None, "beta": b.name},
                mapping=Mapping(status="unmatched", confidence=None, method="placeholder", review_ref=review_ref),
            )
        )

    return PlayerMatchResult(players=players, alpha_to_beta=alpha_to_beta)


# --- markets ---------------------------------------------------------------


def _market_key(market_type: str, line, player_canonical: str | None):
    return (market_type, line, player_canonical)


def match_markets(
    alpha: FeedMatch, beta: FeedMatch, players: PlayerMatchResult, review: ReviewBuilder | None = None
) -> MarketMatchResult:
    """Markets are keyed by (type, line, canonical player). A player market is
    only mappable once its player mapped — so provider player ids are resolved
    through the player mapping before keying."""
    review = review or ReviewBuilder()

    # Resolve a provider player id to a stable canonical key (alpha id if the
    # player mapped, else the provider id prefixed so the two namespaces can't
    # collide).
    beta_to_alpha = {v: k for k, v in players.alpha_to_beta.items()}

    def alpha_player_key(pid: str | None) -> str | None:
        return f"a:{pid}" if pid else None

    def beta_player_key(pid: str | None) -> str | None:
        if pid is None:
            return None
        if pid in beta_to_alpha:
            return f"a:{beta_to_alpha[pid]}"
        return f"b:{pid}"

    markets: dict[tuple, Market] = {}

    for m in alpha.markets:
        key = _market_key(m.market_type, m.line, alpha_player_key(m.player_source_id))
        markets[key] = Market(
            market_type=m.market_type,
            line=m.line,
            player_ref=alpha_player_key(m.player_source_id),
            source_codes={"alpha": m.source_code, "beta": None},
            mapping=Mapping(status="unmatched", confidence=None, method="alpha_only"),
            selections=[Selection(s.name, {"alpha": s.price, "beta": None}) for s in m.selections],
        )

    for m in beta.markets:
        key = _market_key(m.market_type, m.line, beta_player_key(m.player_source_id))
        existing = markets.get(key)
        if existing is None:
            markets[key] = Market(
                market_type=m.market_type,
                line=m.line,
                player_ref=beta_player_key(m.player_source_id),
                source_codes={"alpha": None, "beta": m.source_code},
                mapping=Mapping(status="unmatched", confidence=None, method="beta_only"),
                selections=[Selection(s.name, {"alpha": None, "beta": s.price}) for s in m.selections],
            )
        else:
            # Merge beta prices into the alpha market — it maps.
            existing.source_codes["beta"] = m.source_code
            existing.mapping = Mapping(status="matched", confidence=1.0, method="key_match")
            beta_by_name = {s.name: s.price for s in m.selections}
            for sel in existing.selections:
                if sel.name in beta_by_name:
                    sel.prices["beta"] = beta_by_name[sel.name]
            # Beta selections with no alpha counterpart (shouldn't happen here).
            existing_names = {s.name for s in existing.selections}
            for s in m.selections:
                if s.name not in existing_names:
                    existing.selections.append(Selection(s.name, {"alpha": None, "beta": s.price}))

    # Flag the unmatched markets.
    for market in markets.values():
        if market.mapping.status == "unmatched":
            only = "alpha" if market.source_codes["alpha"] else "beta"
            review_ref = review.add(
                category="market_unmatched",
                entity_type="market",
                entity_ref=f"{market.market_type}"
                + (f"@{market.line}" if market.line is not None else ""),
                reason=f"present in {only} only; no counterpart in the other feed",
                suggested_action="confirm the market was not offered by the other provider",
                severity="low",
                competing_values={"source_codes": market.source_codes},
            )
            market.mapping.review_ref = review_ref

    return MarketMatchResult(markets=list(markets.values()))
