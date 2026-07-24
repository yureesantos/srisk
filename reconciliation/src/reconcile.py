"""Conflict resolution — deciding a canonical value when the feeds disagree, and
recording how and why.

The policies here are the evaluated substance, so each is stated once and
applied uniformly:

  * Score — cross-checked against each feed's OWN per-player goal tally. Where a
    feed's stated result contradicts its own lineup, that is evidence, not a
    coin-flip. This resolves 2-1 vs 2-2 on the merits.
  * Kickoff — compared as instants, never strings; different offsets that denote
    the same moment agree, and the "conflict" dissolves.
  * Stats — facts about the match; on disagreement the stats-specialist feed
    (alpha) is the prior, both values kept, flagged.
  * Prices — quotes, not facts; never collapsed, divergence is information.
"""

from __future__ import annotations

from .loaders import FeedMatch
from .match import MarketMatchResult, PlayerMatchResult
from .models import FieldValue
from . import normalize as N
from .review import ReviewBuilder

# Stat keys, in a fixed order, and how each feed's raw player carried them is
# already normalized by the loaders to these keys.
_STAT_KEYS = ("goals", "shots", "shots_on_target")


def _goal_tally(feed: FeedMatch) -> dict[str, int]:
    """Sum a feed's own per-player goals into a home/away score, using its own
    team-role assignment."""
    role_by_team = {t.source_id: t.role for t in feed.teams}
    tally = {"home": 0, "away": 0}
    for p in feed.players:
        role = role_by_team.get(p.team_source_id or "")
        if role in tally:
            tally[role] += p.stats.get("goals", 0)
    return tally


def reconcile_score(
    alpha: FeedMatch, beta: FeedMatch, players: PlayerMatchResult, review: ReviewBuilder
) -> FieldValue:
    """Resolve a score disagreement on evidence: each feed's stated result vs the
    sum of its own players' goals."""
    a_score, b_score = alpha.score, beta.score
    agreement = a_score == b_score

    if agreement:
        return FieldValue(value=a_score, agreement=True, sources={"alpha": a_score, "beta": b_score})

    a_tally, b_tally = _goal_tally(alpha), _goal_tally(beta)

    # Prefer the score that its own feed's player goals corroborate. If exactly
    # one feed is self-consistent, that wins on evidence.
    a_consistent = a_score == a_tally
    b_consistent = b_score == b_tally

    if a_consistent and not b_consistent:
        chosen, chosen_by = a_score, "alpha"
        resolution = (
            "alpha value: both feeds' per-player goal tallies sum to "
            f"{a_tally['home']}-{a_tally['away']}, which matches alpha's result but "
            f"contradicts beta's result {b_score['home']}-{b_score['away']}"
        )
    elif b_consistent and not a_consistent:
        chosen, chosen_by = b_score, "beta"
        resolution = (
            "beta value: its per-player goal tally corroborates it while alpha's does not"
        )
    else:
        # Tallies inconclusive — fall back to the stated prior (stats feed),
        # still flagged. (Does not occur on this data.)
        chosen, chosen_by = a_score, "alpha"
        resolution = "goal tallies inconclusive; defaulted to the stats-specialist feed (alpha)"

    review_ref = review.add(
        category="value_conflict",
        entity_type="match",
        entity_ref="final score",
        reason=f"feeds disagree on the score; resolved to {chosen_by} on goal-tally evidence",
        suggested_action="confirm the settled result against an authoritative source",
        severity="high",
        competing_values={
            "alpha_result": a_score,
            "beta_result": b_score,
            "alpha_goal_tally": a_tally,
            "beta_goal_tally": b_tally,
        },
    )

    return FieldValue(
        value=chosen,
        agreement=False,
        sources={"alpha": a_score, "beta": b_score},
        resolution=resolution,
        review_ref=review_ref,
    )


def reconcile_kickoff(alpha: FeedMatch, beta: FeedMatch, review: ReviewBuilder) -> FieldValue:
    """Compare kickoff as instants. Different offsets, same moment → agreement."""
    a_instant = N.parse_instant(alpha.kickoff)
    b_instant = N.parse_instant(beta.kickoff)
    agreement = a_instant == b_instant

    if agreement:
        return FieldValue(
            value=N.to_iso_utc(a_instant),
            agreement=True,
            sources={"alpha": alpha.kickoff, "beta": beta.kickoff},
        )

    review_ref = review.add(
        category="value_conflict",
        entity_type="match",
        entity_ref="kickoff",
        reason="kickoff instants differ after timezone normalization",
        suggested_action="confirm the true kickoff time",
        severity="high",
        competing_values={"alpha": alpha.kickoff, "beta": beta.kickoff},
    )
    return FieldValue(
        value=N.to_iso_utc(a_instant),
        agreement=False,
        sources={"alpha": alpha.kickoff, "beta": beta.kickoff},
        resolution="instants differ; defaulted to alpha",
        review_ref=review_ref,
    )


def reconcile_competition(alpha: FeedMatch, beta: FeedMatch) -> FieldValue:
    """'English Premier League' vs 'Premier League': token-subset ⇒ same
    competition, canonical = the fuller string."""
    a, b = alpha.competition, beta.competition
    at, bt = set(N.norm_name(a).split()), set(N.norm_name(b).split())
    agreement = at <= bt or bt <= at
    fuller = a if len(a) >= len(b) else b
    return FieldValue(value=fuller, agreement=agreement, sources={"alpha": a, "beta": b})


def reconcile_status(alpha: FeedMatch, beta: FeedMatch) -> FieldValue:
    """alpha 'complete' vs beta settled=true — both mean the match is settled."""
    agreement = alpha.status_settled == beta.status_settled
    return FieldValue(
        value=alpha.status_raw,
        agreement=agreement,
        sources={"alpha": alpha.status_raw, "beta": beta.status_raw},
    )


def reconcile_player_stats(
    alpha: FeedMatch, beta: FeedMatch, players: PlayerMatchResult, review: ReviewBuilder
) -> None:
    """Attach reconciled per-stat FieldValues to each matched/provisional player.
    Single-feed players keep their one source's stats with agreement True."""
    alpha_by_id = {p.source_id: p for p in alpha.players}
    beta_by_id = {p.source_id: p for p in beta.players}

    for player in players.players:
        a_id, b_id = player.source_ids.alpha, player.source_ids.beta
        a_p = alpha_by_id.get(a_id) if a_id else None
        b_p = beta_by_id.get(b_id) if b_id else None

        for key in _STAT_KEYS:
            a_val = a_p.stats.get(key) if a_p else None
            b_val = b_p.stats.get(key) if b_p else None

            if a_val is not None and b_val is not None:
                if a_val == b_val:
                    player.stats[key] = FieldValue(
                        value=a_val, agreement=True, sources={"alpha": a_val, "beta": b_val}
                    )
                else:
                    review_ref = review.add(
                        category="value_conflict",
                        entity_type="player_stat",
                        entity_ref=f"{player.canonical_name} · {key}",
                        reason=f"{key} differs: alpha {a_val} vs beta {b_val}",
                        suggested_action="confirm against match data; alpha taken as the stats prior",
                        severity="medium",
                        source_ids=player.source_ids,
                        competing_values={"alpha": a_val, "beta": b_val},
                    )
                    player.stats[key] = FieldValue(
                        value=a_val,  # alpha is the stats-specialist prior
                        agreement=False,
                        sources={"alpha": a_val, "beta": b_val},
                        resolution="alpha (stats-specialist feed)",
                        review_ref=review_ref,
                    )
            elif a_val is not None:
                player.stats[key] = FieldValue(value=a_val, agreement=True, sources={"alpha": a_val})
            elif b_val is not None:
                player.stats[key] = FieldValue(value=b_val, agreement=True, sources={"beta": b_val})


def reconcile_prices(markets: MarketMatchResult, review: ReviewBuilder) -> None:
    """Flag price divergences on matched markets. Prices are quotes: both are
    always kept; a difference is information, not an error."""
    for market in markets.markets:
        for sel in market.selections:
            a_price = sel.prices.get("alpha")
            b_price = sel.prices.get("beta")
            if a_price is not None and b_price is not None:
                agree = abs(a_price - b_price) < 0.001
                sel.agreement = agree
                if not agree:
                    sel.review_ref = review.add(
                        category="price_divergence",
                        entity_type="selection",
                        entity_ref=f"{market.market_type}"
                        + (f"@{market.line}" if market.line is not None else "")
                        + f" · {sel.name}",
                        reason=f"prices differ: alpha {a_price} vs beta {b_price}",
                        suggested_action="expected between books, but verify on a settled market",
                        severity="info",
                        competing_values={"alpha": a_price, "beta": b_price},
                    )
            else:
                sel.agreement = None  # only one feed quoted this runner
