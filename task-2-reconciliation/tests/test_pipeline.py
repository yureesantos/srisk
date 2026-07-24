"""End-to-end tests on the real feeds — the highest-value check.

Runs the whole pipeline and asserts the canonical output and the review list are
what a reviewer would expect, plus determinism (same input → byte-identical
output).
"""

import json

from src import pipeline as P


def _run(tmp_path):
    return P.run("feeds/provider_alpha.json", "feeds/provider_beta.json", tmp_path)


def test_match_level_fields(tmp_path):
    result = _run(tmp_path)
    match = result["canonical"]["match"] if "match" in result["canonical"] else result["canonical"]

    assert match["source_ids"] == {"alpha": "778211", "beta": "evt_2k5m9"}
    assert match["kickoff_utc"]["agreement"] is True
    assert match["score"]["value"] == {"home": 2, "away": 1}
    assert match["score"]["agreement"] is False


def test_market_via_player_dependency(tmp_path):
    result = _run(tmp_path)
    markets = result["canonical"]["markets"]

    shots = next(m for m in markets if m["market_type"] == "player_shots_on_target")
    assert shots["source_codes"]["alpha"] == "PLAYER_SHOTS_ON@9001@1.5"
    assert shots["source_codes"]["beta"] == "player_shots_on_target"
    assert shots["mapping"]["status"] == "matched"
    over = next(s for s in shots["selections"] if s["name"] == "over")
    assert over["prices"] == {"alpha": 1.90, "beta": 1.90}
    assert over["agreement"] is True

    # player_to_score (beta) mapped to player_goals (Saka) with the divergence.
    pg = next(m for m in markets if m["market_type"] == "player_goals")
    assert pg["mapping"]["status"] == "matched"
    pg_over = next(s for s in pg["selections"] if s["name"] == "over")
    assert pg_over["prices"] == {"alpha": 2.40, "beta": 2.50}
    assert pg_over["agreement"] is False


def test_unmatched_markets_present_not_crossmapped(tmp_path):
    result = _run(tmp_path)
    markets = result["canonical"]["markets"]

    btts = next(m for m in markets if m["market_type"] == "btts")
    assert btts["source_codes"] == {"alpha": "BTTS", "beta": None}
    assert btts["mapping"]["status"] == "unmatched"

    ah = next(m for m in markets if m["market_type"] == "asian_handicap")
    assert ah["source_codes"] == {"alpha": None, "beta": "asian_handicap"}
    assert ah["mapping"]["status"] == "unmatched"


def test_review_list_shape(tmp_path):
    result = _run(tmp_path)
    review = result["review"]

    categories = {r["category"] for r in review}
    assert "value_conflict" in categories  # score + stats
    assert "provisional_mapping" in categories  # Rodri
    assert "entity_unmatched" in categories  # single-feed players
    assert "market_unmatched" in categories  # BTTS, asian_handicap
    assert "data_quality" in categories  # p_x99
    assert "price_divergence" in categories  # 2.40 vs 2.50

    # Every id is unique and stably formatted.
    ids = [r["id"] for r in review]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))

    # A high-severity score conflict exists and carries all the numbers.
    score = next(r for r in review if r["entity_ref"] == "final score")
    assert score["severity"] == "high"
    assert score["competing_values"]["alpha_result"] == {"home": 2, "away": 1}
    assert score["competing_values"]["beta_result"] == {"home": 2, "away": 2}


def test_output_is_deterministic(tmp_path):
    r1 = _run(tmp_path)
    r2 = _run(tmp_path)
    assert json.dumps(r1, sort_keys=False) == json.dumps(r2, sort_keys=False)

    # And the files were written.
    assert (tmp_path / "canonical.json").exists()
    assert (tmp_path / "review.json").exists()
