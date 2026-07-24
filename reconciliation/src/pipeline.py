"""Orchestration: load → normalize → match → reconcile → emit.

The one place the stages are wired together. It returns the canonical match and
the review list as plain dicts (also writing them to `out/`), and prints a
one-screen summary so a run is legible without opening the JSON.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import match as M
from . import reconcile as R
from .loaders import load_alpha, load_beta
from .models import Match, SourceIds
from .review import ReviewBuilder


def run(alpha_path: str | Path, beta_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    """Reconcile the two feeds. Writes canonical.json + review.json into out_dir
    and returns {"canonical": <match dict>, "review": [<items>]}."""
    alpha = load_alpha(alpha_path)
    beta = load_beta(beta_path)
    review = ReviewBuilder()

    # Match in dependency order: teams scope players, players scope player markets.
    teams = M.match_teams(alpha, beta, review)
    players = M.match_players(alpha, beta, teams, review)
    markets = M.match_markets(alpha, beta, players, review)

    # Reconcile fields (mutates players' stats and markets' selections in place).
    score = R.reconcile_score(alpha, beta, players, review)
    kickoff = R.reconcile_kickoff(alpha, beta, review)
    competition = R.reconcile_competition(alpha, beta)
    status = R.reconcile_status(alpha, beta)
    R.reconcile_player_stats(alpha, beta, players, review)
    R.reconcile_prices(markets, review)

    match = Match(
        source_ids=SourceIds(alpha.match_source_id, beta.match_source_id),
        competition=competition,
        kickoff_utc=kickoff,
        status=status,
        score=score,
        teams=teams.teams,
        players=players.players,
        markets=markets.markets,
    )

    canonical = match.to_dict()
    review_list = review.to_list()

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_json(out / "canonical.json", canonical)
    _write_json(out / "review.json", review_list)

    _print_summary(match, review_list)

    return {"canonical": canonical, "review": review_list}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _print_summary(match: Match, review_list: list[dict]) -> None:
    def count(status: str) -> int:
        return sum(1 for p in match.players if p.mapping.status == status)

    print("Two-feed reconciliation")
    print(f"  match: alpha {match.source_ids.alpha} ↔ beta {match.source_ids.beta}")
    print(
        f"  score: {match.score.value['home']}-{match.score.value['away']} "
        f"({'agreed' if match.score.agreement else 'RESOLVED from conflict'})"
    )
    print(
        f"  players: {count('matched')} matched · "
        f"{count('provisional')} provisional · {count('unmatched')} unmatched"
    )
    matched_markets = sum(1 for m in match.markets if m.mapping.status == "matched")
    print(f"  markets: {matched_markets} matched · {len(match.markets) - matched_markets} single-feed")
    print(f"  review items: {len(review_list)}")
    by_sev: dict[str, int] = {}
    for r in review_list:
        by_sev[r["severity"]] = by_sev.get(r["severity"], 0) + 1
    for sev in ("high", "medium", "low", "info"):
        if sev in by_sev:
            print(f"    {sev}: {by_sev[sev]}")
