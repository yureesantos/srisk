"""Conflict-resolution tests — the defensibility of the decisions.

The headline case: the two feeds disagree on the score (2-1 vs 2-2), and the
resolution is evidence-based — both feeds' own per-player goal tallies sum to
2-1, so beta's result contradicts beta's own lineup. That is stronger than an
arbitrary "prefer provider X", and these tests pin it.
"""

from src.loaders import load_alpha, load_beta
from src import match as M
from src import reconcile as R
from src.review import ReviewBuilder


def _prep():
    a, b = load_alpha("feeds/provider_alpha.json"), load_beta("feeds/provider_beta.json")
    rb = ReviewBuilder()
    teams = M.match_teams(a, b, rb)
    players = M.match_players(a, b, teams, rb)
    return a, b, teams, players, rb


def test_score_resolves_to_2_1_by_goal_tally_evidence():
    a, b, teams, players, rb = _prep()
    fv = R.reconcile_score(a, b, players, rb)

    assert fv.value == {"home": 2, "away": 1}
    assert fv.agreement is False
    assert fv.sources == {"alpha": {"home": 2, "away": 1}, "beta": {"home": 2, "away": 2}}
    # The resolution must cite the goal-tally evidence, not just "prefer alpha".
    assert "tall" in fv.resolution.lower()
    assert fv.review_ref is not None


def test_score_conflict_creates_high_severity_review():
    a, b, teams, players, rb = _prep()
    R.reconcile_score(a, b, players, rb)
    score_items = [i for i in rb.items if i.category == "value_conflict" and i.entity_type == "match"]
    assert len(score_items) == 1
    assert score_items[0].severity == "high"


def test_kickoff_agrees_after_instant_normalization():
    a, b, teams, players, rb = _prep()
    fv = R.reconcile_kickoff(a, b, rb)

    assert fv.agreement is True
    assert fv.value == "2025-05-04T15:30:00+00:00"
    # The two raw strings are preserved as provenance...
    assert fv.sources["alpha"] == "2025-05-04T15:30:00Z"
    assert fv.sources["beta"] == "2025-05-04T16:30:00+01:00"
    # ...and no review item is raised: normalization dissolved the apparent gap.
    assert fv.review_ref is None


def test_player_stats_conflict_keeps_both_and_flags():
    a, b, teams, players, rb = _prep()
    R.reconcile_player_stats(a, b, players, rb)

    haaland = next(p for p in players.players if p.source_ids.alpha == "9001")
    shots = haaland.stats["shots"]
    assert shots.agreement is False
    assert shots.sources == {"alpha": 5, "beta": 4}
    assert shots.value == 5  # alpha, the stats-specialist feed
    assert shots.review_ref is not None

    sot = haaland.stats["shots_on_target"]
    assert sot.agreement is True  # 3 == 3
    assert sot.review_ref is None


def test_price_divergence_is_info_not_error():
    a, b, teams, players, rb = _prep()
    markets = M.match_markets(a, b, players, rb)
    R.reconcile_prices(markets, rb)

    # player_goals over: alpha 2.40 vs beta 2.50 → divergence flagged as info.
    pg = next(m for m in markets.markets if m.market_type == "player_goals")
    over = next(s for s in pg.selections if s.name == "over")
    assert over.agreement is False
    assert over.prices == {"alpha": 2.40, "beta": 2.50}
    assert over.review_ref is not None

    # total_goals over: 1.80 both → agreement, no flag.
    tg = next(m for m in markets.markets if m.market_type == "total_goals")
    tg_over = next(s for s in tg.selections if s.name == "over")
    assert tg_over.agreement is True
    assert tg_over.review_ref is None
