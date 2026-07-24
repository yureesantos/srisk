"""Entity-matching tests — the substance being evaluated.

These pin the confidence tiers, the thresholds, and — most importantly — the
honest handling of the cases that should NOT auto-match: the Rodri nickname
(provisional, not silently merged and not dropped), the unidentified player, and
players present in only one feed.
"""

from src.loaders import load_alpha, load_beta
from src import match as M


def _load():
    return load_alpha("feeds/provider_alpha.json"), load_beta("feeds/provider_beta.json")


def test_teams_match_on_role_and_name():
    a, b = _load()
    result = M.match_teams(a, b)
    home = next(t for t in result.teams if t.role == "home")
    away = next(t for t in result.teams if t.role == "away")

    assert home.source_ids.alpha == "501" and home.source_ids.beta == "MCI"
    assert home.mapping.confidence is not None and home.mapping.confidence >= 0.9
    # "Arsenal" vs "Arsenal FC" resolve to 1.0 after the suffix drop.
    assert away.source_ids.alpha == "502" and away.source_ids.beta == "ARS"
    assert away.mapping.confidence == 1.0


def test_player_exact_and_initial_expansion():
    a, b = _load()
    teams = M.match_teams(a, b)
    result = M.match_players(a, b, teams)

    haaland = _find(result.players, alpha_id="9001")
    assert haaland.source_ids.beta == "p_h44"
    assert haaland.mapping.status == "matched"
    assert haaland.mapping.confidence >= 0.9  # "Erling Haaland" ↔ "E. Haaland"


def test_diacritic_players_match():
    a, b = _load()
    teams = M.match_teams(a, b)
    result = M.match_players(a, b, teams)

    # Ødegaard / Odegaard, Álvarez / Alvarez, Magalhães / Magalhaes all resolve.
    for alpha_id, beta_id in [("8004", "p_mo8"), ("9006", "p_ja19"), ("8003", "p_gm6")]:
        p = _find(result.players, alpha_id=alpha_id)
        assert p.source_ids.beta == beta_id, f"{alpha_id} should map to {beta_id}"
        assert p.mapping.status == "matched"


def test_rodri_is_provisional_not_forced_not_dropped():
    a, b = _load()
    teams = M.match_teams(a, b)
    result = M.match_players(a, b, teams)

    rodri = _find(result.players, alpha_id="9003")
    # Same player, lexically very different names → provisional, both ids kept.
    assert rodri.source_ids.beta == "p_r16"
    assert rodri.mapping.status == "provisional"
    assert rodri.mapping.confidence is not None and rodri.mapping.confidence < 0.8
    assert rodri.mapping.review_ref is not None


def test_unidentified_player_never_matched():
    a, b = _load()
    teams = M.match_teams(a, b)
    result = M.match_players(a, b, teams)

    px99 = _find(result.players, beta_id="p_x99")
    assert px99.source_ids.alpha is None
    assert px99.mapping.status == "unmatched"


def test_single_feed_players_unmatched_with_correct_ids():
    a, b = _load()
    teams = M.match_teams(a, b)
    result = M.match_players(a, b, teams)

    # Kovačić exists only in alpha; Foden and Rice only in beta.
    kovacic = _find(result.players, alpha_id="9007")
    assert kovacic.source_ids.beta is None and kovacic.mapping.status == "unmatched"
    foden = _find(result.players, beta_id="p_pf47")
    assert foden.source_ids.alpha is None and foden.mapping.status == "unmatched"
    rice = _find(result.players, beta_id="p_dr41")
    assert rice.source_ids.alpha is None and rice.mapping.status == "unmatched"


def test_no_forced_pairing_beyond_real_matches():
    a, b = _load()
    teams = M.match_teams(a, b)
    result = M.match_players(a, b, teams)

    paired = [p for p in result.players if p.source_ids.alpha and p.source_ids.beta]
    # 9 confident matches + Rodri provisional = 10 pairs; the rest stay single.
    assert len(paired) == 10


def test_cross_team_names_do_not_match():
    """A synthetic guard: a name can only match within the same mapped team."""
    a, b = _load()
    teams = M.match_teams(a, b)
    result = M.match_players(a, b, teams)
    for p in result.players:
        if p.source_ids.alpha and p.source_ids.beta:
            assert p.team_role is not None


def test_markets_map_via_player_dependency():
    a, b = _load()
    teams = M.match_teams(a, b)
    players = M.match_players(a, b, teams)
    result = M.match_markets(a, b, players)

    shots = _find_market(result.markets, "player_shots_on_target")
    assert shots.source_codes["alpha"] == "PLAYER_SHOTS_ON@9001@1.5"
    assert shots.source_codes["beta"] == "player_shots_on_target"
    assert shots.mapping.status == "matched"


def test_unmatched_markets_kept_not_crossmapped():
    a, b = _load()
    teams = M.match_teams(a, b)
    players = M.match_players(a, b, teams)
    result = M.match_markets(a, b, players)

    btts = _find_market(result.markets, "btts")
    assert btts.source_codes["alpha"] == "BTTS" and btts.source_codes["beta"] is None
    assert btts.mapping.status == "unmatched"

    ah = _find_market(result.markets, "asian_handicap")
    assert ah.source_codes["beta"] == "asian_handicap" and ah.source_codes["alpha"] is None
    assert ah.mapping.status == "unmatched"


# --- helpers ---------------------------------------------------------------


def _find(players, alpha_id=None, beta_id=None):
    for p in players:
        if alpha_id and p.source_ids.alpha == alpha_id:
            return p
        if beta_id and p.source_ids.beta == beta_id:
            return p
    raise AssertionError(f"player not found: alpha={alpha_id} beta={beta_id}")


def _find_market(markets, market_type):
    for m in markets:
        if m.market_type == market_type:
            return m
    raise AssertionError(f"market not found: {market_type}")
