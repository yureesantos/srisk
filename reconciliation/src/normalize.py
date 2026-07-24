"""Normalization primitives: names, odds, instants, market vocabulary.

Every function here is pure and unit-tested. They are the foundation the matcher
and reconciler stand on — a bug here (a diacritic that doesn't strip, a timezone
compared as a string) becomes a silent mismatch three modules downstream, so
they are pinned by tests first.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction

# Characters that do NOT decompose under NFKD (they have no combining-mark form),
# so the generic strip below can't reach them. Mapped explicitly.
_NON_DECOMPOSING = str.maketrans(
    {
        "Ø": "O",
        "ø": "o",
        "Đ": "D",
        "đ": "d",
        "Ł": "L",
        "ł": "l",
        "ð": "d",
        "Þ": "Th",
        "þ": "th",
        "ß": "ss",
    }
)

# Team-name suffix tokens dropped before comparison ("Arsenal FC" == "Arsenal").
_TEAM_SUFFIXES = {"fc", "afc", "cf", "sc"}


def strip_diacritics(text: str) -> str:
    """Fold accented characters to ASCII, including the NFKD-resistant ones."""
    pre = text.translate(_NON_DECOMPOSING)
    decomposed = unicodedata.normalize("NFKD", pre)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def norm_name(text: str) -> str:
    """Casefold + de-accent + collapse whitespace — the canonical name key."""
    folded = strip_diacritics(text).casefold()
    return " ".join(folded.split())


def norm_team_name(text: str) -> str:
    """`norm_name` with common club suffixes dropped, so 'Arsenal FC' == 'Arsenal'."""
    tokens = [t for t in norm_name(text).split() if t not in _TEAM_SUFFIXES]
    return " ".join(tokens)


def fractional_to_decimal(fractional: str) -> float:
    """UK fractional odds → decimal. '4/5' → 1.80, '1/1' → 2.00.

    Uses exact rational arithmetic, then rounds to 4dp for a stable float.
    """
    parts = fractional.split("/")
    if len(parts) != 2:
        raise ValueError(f"not fractional odds: {fractional!r}")
    num, den = parts
    dec = Fraction(int(num), int(den)) + 1
    return round(float(dec), 4)


def parse_instant(iso: str) -> datetime:
    """Parse an ISO-8601 timestamp to a timezone-aware UTC datetime.

    Python 3.10's `fromisoformat` rejects the 'Z' suffix, so it is rewritten to
    '+00:00' first. Everything is converted to UTC so two feeds that quote the
    same instant in different offsets compare equal.
    """
    normalized = iso.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized).astimezone(timezone.utc)


def to_iso_utc(dt: datetime) -> str:
    """Render an instant as a canonical UTC ISO string."""
    return dt.astimezone(timezone.utc).isoformat()


# --- Market vocabulary -----------------------------------------------------

# Both providers' market tokens mapped to one canonical vocabulary. The
# `player_to_score` ≡ `player_goals` (at line 0.5) equivalence is the one
# semantic (not merely lexical) mapping, and it is stated here on purpose.
_MARKET_VOCAB = {
    "ou_total_goals": "total_goals",
    "total_goals": "total_goals",
    "btts": "btts",
    "player_shots_on": "player_shots_on_target",
    "player_shots_on_target": "player_shots_on_target",
    "player_goals": "player_goals",
    "player_to_score": "player_goals",
    "asian_handicap": "asian_handicap",
}


def canonical_market_type(token: str) -> str:
    """Map a provider market token to the canonical vocabulary, or 'unknown'."""
    return _MARKET_VOCAB.get(token.strip().casefold(), "unknown")


@dataclass(frozen=True)
class ParsedMarketCode:
    """Alpha packs type, an optional player id and an optional line into one
    string like 'PLAYER_SHOTS_ON@9001@1.5'. This is the unpacked form."""

    market_type: str
    player_source_id: str | None
    line: float | None
    raw: str


def parse_alpha_market_code(code: str) -> ParsedMarketCode:
    """Unpack an alpha market code. Segments are '@'-separated: a type token,
    then optionally an embedded player id and/or a line. A player id looks
    numeric-with-no-dot beyond the type; a line contains a decimal point.

    Unknown type tokens are surfaced as 'unknown' (never guessed), with the raw
    code preserved for human inspection.
    """
    segments = code.split("@")
    type_token = segments[0]
    market_type = canonical_market_type(type_token)

    player_source_id: str | None = None
    line: float | None = None
    for seg in segments[1:]:
        if "." in seg:
            line = float(seg)
        else:
            # A bare integer segment after the type is an embedded player id.
            player_source_id = seg

    return ParsedMarketCode(
        market_type=market_type,
        player_source_id=player_source_id,
        line=line,
        raw=code,
    )
