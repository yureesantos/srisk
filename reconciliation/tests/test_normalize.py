"""Pure-function tests for normalization — the cheapest, highest-value TDD wins.

These pin two traps up front: the Ø character that survives NFKD decomposition,
and Python 3.10's `fromisoformat` rejecting the `Z` suffix. Both would otherwise
surface as subtle, hard-to-trace mismatches downstream.
"""

import pytest

from src import normalize as N


@pytest.mark.parametrize(
    "fractional,expected",
    [
        ("4/5", 1.80),
        ("1/1", 2.00),
        ("9/10", 1.90),
        ("6/4", 2.50),
        ("21/20", 2.05),
    ],
)
def test_fractional_to_decimal(fractional, expected):
    assert N.fractional_to_decimal(fractional) == pytest.approx(expected)


def test_fractional_to_decimal_rejects_malformed():
    with pytest.raises(ValueError):
        N.fractional_to_decimal("evens")


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Julián Álvarez", "julian alvarez"),
        ("Mateo Kovačić", "mateo kovacic"),
        ("Gabriel Magalhães", "gabriel magalhaes"),
        # The one that resists NFKD decomposition — must be special-cased.
        ("Martin Ødegaard", "martin odegaard"),
    ],
)
def test_norm_name_strips_diacritics(raw, expected):
    assert N.norm_name(raw) == expected


def test_norm_team_name_drops_suffixes():
    assert N.norm_team_name("Arsenal FC") == N.norm_team_name("Arsenal")
    assert N.norm_team_name("Manchester City") == "manchester city"


def test_kickoff_instants_equal_despite_different_strings():
    a = "2025-05-04T15:30:00Z"
    b = "2025-05-04T16:30:00+01:00"
    # The raw strings differ...
    assert a != b
    # ...but they denote the same instant. Comparing strings would be a bug.
    assert N.parse_instant(a) == N.parse_instant(b)


def test_parse_instant_normalizes_to_utc():
    dt = N.parse_instant("2025-05-04T16:30:00+01:00")
    assert N.to_iso_utc(dt) == "2025-05-04T15:30:00+00:00"


def test_parse_alpha_market_code_player():
    parsed = N.parse_alpha_market_code("PLAYER_SHOTS_ON@9001@1.5")
    assert parsed.market_type == "player_shots_on_target"
    assert parsed.player_source_id == "9001"
    assert parsed.line == 1.5


def test_parse_alpha_market_code_simple():
    parsed = N.parse_alpha_market_code("OU_TOTAL_GOALS@2.5")
    assert parsed.market_type == "total_goals"
    assert parsed.player_source_id is None
    assert parsed.line == 2.5


def test_parse_alpha_market_code_no_line():
    parsed = N.parse_alpha_market_code("BTTS")
    assert parsed.market_type == "btts"
    assert parsed.line is None
    assert parsed.player_source_id is None


def test_unknown_market_token_is_flagged_not_guessed():
    parsed = N.parse_alpha_market_code("SOME_NEW_MARKET@1.5")
    assert parsed.market_type == "unknown"
    # The raw token is preserved so a human can see what was not understood.
    assert parsed.raw == "SOME_NEW_MARKET@1.5"


def test_beta_market_type_maps_player_to_score_to_player_goals():
    # Semantic equivalence: a bookmaker "to score" market is a goals line at 0.5.
    assert N.canonical_market_type("player_to_score") == "player_goals"
    assert N.canonical_market_type("total_goals") == "total_goals"
    assert N.canonical_market_type("asian_handicap") == "asian_handicap"
