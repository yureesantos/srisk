"""Loading and normalisation of the betslip exports.

Encapsulates every data-quality decision documented in docs/DATA-FINDINGS.md.
None of them is silent: each one records a fact on `LoadReport` so the report
and the dashboard can surface it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# The header sits on Excel row 5 (index 4); data occupies columns B:R.
SHEET = "Sample1"
HEADER_ROW = 4
USECOLS = "B:R"

DATE_COLS = ["Event date (utc)", "Betslip date (utc)"]
DATE_FMT = "%d/%m/%Y %H:%M:%S"

# Uid alone does NOT identify a betslip (only 38.5% carry a single turnover).
# Uid + timestamp yields 98% constant turnover and 100% constant BetType.
BETSLIP_KEY = ["Uid", "Betslip date (utc)"]

_PLACEHOLDER_RE = re.compile(r"\{[^}]*\}")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class LoadReport:
    """Auditable trace of what the load step did to the data."""

    rows_raw: dict[str, int] = field(default_factory=dict)
    rows_after_exact_dedup: dict[str, int] = field(default_factory=dict)
    exact_dups_removed: dict[str, int] = field(default_factory=dict)
    cross_file_overlap: int = 0
    rows_union: int = 0
    betslips: int = 0
    legs: int = 0
    inflation_factor: float = 0.0
    inflation_by_currency: dict[str, float] = field(default_factory=dict)
    currencies: dict[str, int] = field(default_factory=dict)
    inplay_share: float = 0.0
    unparsed_dates: int = 0
    simple_with_multiple_legs: int = 0

    def as_dict(self) -> dict:
        return {
            "rows_raw": self.rows_raw,
            "rows_after_exact_dedup": self.rows_after_exact_dedup,
            "exact_dups_removed": self.exact_dups_removed,
            "cross_file_overlap": self.cross_file_overlap,
            "rows_union": self.rows_union,
            "betslips": self.betslips,
            "legs": self.legs,
            "inflation_factor": round(self.inflation_factor, 4),
            "inflation_by_currency": self.inflation_by_currency,
            "currencies": self.currencies,
            "inplay_share": round(self.inplay_share, 4),
            "unparsed_dates": self.unparsed_dates,
            "simple_with_multiple_legs": self.simple_with_multiple_legs,
        }


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn"
    )


def normalise_management_unit(value: object) -> str:
    """`RETABET EUSKADI` and `EUSKADI` are the same region on different systems.

    Returns the canonical region, accent-free and stripped of the brand prefix.
    The original value is preserved on a separate column so the origin channel
    is not lost.
    """
    if not isinstance(value, str):
        return "UNKNOWN"
    cleaned = _strip_accents(value).upper().strip()
    for prefix in ("RETABET ", "RETA "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    # `CATALUNYA RETA` carries the brand as a suffix instead of a prefix.
    if cleaned.endswith(" RETA"):
        cleaned = cleaned[: -len(" RETA")]
    aliases = {"C. LA MANCHA": "CASTILLA LA MANCHA"}
    return aliases.get(cleaned, cleaned) or "UNKNOWN"


def normalise_market(name: object) -> str:
    """Collapse unresolved template placeholders into a stable label.

    The feed ships `Saves {PLAYER}`, `{goalnr}{ordinal} goal scorer` and similar.
    Without this, one logical market fragments across several distinct labels.

    Two placeholders are the *entire* market name rather than a slot inside it:
    `{COMPETITOR1}` and `{COMPETITOR2}`. Stripping them would erase 10.6% of all
    legs into a meaningless bucket, so they are named explicitly. Inspecting the
    rows shows they are same-game combos anchored on the home / away side
    (`Option` reads "France win y Over 2.5 goals"), not plain 1X2.
    """
    if not isinstance(name, str):
        return "UNKNOWN"

    explicit = {
        "{COMPETITOR1}": "Home-side combo (bet builder)",
        "{COMPETITOR2}": "Away-side combo (bet builder)",
    }
    stripped = name.strip()
    if stripped in explicit:
        return explicit[stripped]

    cleaned = _PLACEHOLDER_RE.sub("", name)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" -:")
    return cleaned or "UNKNOWN"


def read_export(path: Path) -> pd.DataFrame:
    """Read one export, parsing dates with an explicit format.

    Without `format=`, pandas keeps the dates as text and sorts them
    alphabetically, producing bogus ranges (01/06 -> 31/05).
    See docs/DATA-FINDINGS.md section 4.

    Parsing .xlsx costs ~10s per file because openpyxl walks the sheet XML cell
    by cell, so the parsed frame is cached beside the export. The source file's
    size and mtime are part of the *cache filename*, so touching or replacing an
    export simply misses the cache rather than reading a stale one. The cache
    holds the frame exactly as parsed — every normalisation still runs on every
    load, so this can never mask a change in the pipeline's own logic.
    """
    stamp = path.stat()
    cache = path.with_suffix(f".{stamp.st_size}-{int(stamp.st_mtime)}.cache.pkl")

    if cache.exists():
        try:
            return pd.read_pickle(cache)
        except Exception:
            # A corrupt or unreadable cache is never fatal: fall through and
            # reparse the authoritative .xlsx.
            pass

    df = pd.read_excel(
        path, sheet_name=SHEET, header=HEADER_ROW, usecols=USECOLS, dtype={"Uid": str}
    )
    for col in DATE_COLS:
        df[col] = pd.to_datetime(df[col], format=DATE_FMT, errors="coerce")
    df["source_file"] = path.name

    try:
        for stale in path.parent.glob(f"{path.stem}.*.cache.pkl"):
            stale.unlink()
        df.to_pickle(cache)
    except Exception:
        # Caching is an optimisation, never a requirement.
        pass
    return df


def load(raw_dir: Path) -> tuple[pd.DataFrame, LoadReport]:
    """Load every export, deduplicate, and return the unified universe.

    The two exports are partially disjoint slices rather than copies: the
    smaller one holds 84 fixtures and 4 competitions the larger one lacks.
    Using only one would drop real data, so the universe is the deduplicated
    union.
    """
    report = LoadReport()
    paths = sorted(raw_dir.glob("*.xlsx"))
    if not paths:
        raise FileNotFoundError(f"No .xlsx found under {raw_dir}")

    frames = []
    for path in paths:
        df = read_export(path)
        report.rows_raw[path.name] = len(df)

        # Exact duplicates inside one file are an export artefact. Genuine legs
        # of a combined betslip differ on at least one column.
        value_cols = [c for c in df.columns if c != "source_file"]
        before = len(df)
        df = df.drop_duplicates(subset=value_cols)
        report.exact_dups_removed[path.name] = before - len(df)
        report.rows_after_exact_dedup[path.name] = len(df)
        frames.append(df)

    combined = pd.concat(frames, ignore_index=True)
    value_cols = [c for c in combined.columns if c != "source_file"]

    dup_mask = combined.duplicated(subset=value_cols, keep=False)
    report.cross_file_overlap = int(
        combined[dup_mask].groupby(value_cols, dropna=False).ngroups
    )

    combined = combined.drop_duplicates(subset=value_cols).reset_index(drop=True)
    report.rows_union = len(combined)

    combined = _enrich(combined)
    _fill_report(combined, report)
    return combined, report


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add the derived columns the analysis depends on."""
    df = df.copy()

    df["region"] = df["Management unit"].map(normalise_management_unit)
    df["is_retabet_brand"] = (
        df["Management unit"].astype(str).str.upper().str.contains("RETA")
    )
    # Numeric and string Uids come from distinct source systems.
    df["uid_format"] = (
        df["Uid"]
        .astype(str)
        .str.fullmatch(r"\d+")
        .map({True: "numeric", False: "string"})
    )

    # Minutes between the bet and kick-off. Negative means pre-match.
    delta = df["Betslip date (utc)"] - df["Event date (utc)"]
    df["minutes_to_kickoff"] = delta.dt.total_seconds() / 60.0
    df["is_inplay"] = df["minutes_to_kickoff"] > 0

    # Betslip identity. See docs/DATA-FINDINGS.md section 3 and ADR-0003.
    #
    # Uid + second-resolution timestamp is *almost* the betslip grain, but it
    # collides when one customer places several simple bets within the same
    # second: 2,213 groups come back as SIMPLE yet hold multiple legs, 87% of
    # them on the same fixture and 100% within one region.
    #
    # Those are genuinely separate single bets, so BetType splits them apart —
    # a SIMPLE betslip is one leg by definition, while COMBINED legs legitimately
    # share one stake.
    base_id = (
        df["Uid"].astype(str)
        + "|"
        + df["Betslip date (utc)"].dt.strftime("%Y%m%d%H%M%S").fillna("NaT")
    )
    is_simple = df["BetType"].eq("SIMPLE")
    # Give each SIMPLE leg its own identity; keep COMBINED legs grouped.
    simple_seq = df.groupby([base_id, is_simple]).cumcount().astype(str)
    df["betslip_id"] = base_id.where(~is_simple, base_id + "#" + simple_seq)

    # Flag the collisions so the data-quality section can report them.
    df["had_key_collision"] = is_simple & base_id.duplicated(keep=False)

    df["leg_count"] = df.groupby("betslip_id")["betslip_id"].transform("size")
    df["market_normalised"] = df["Market"].map(normalise_market)
    return df


def _fill_report(df: pd.DataFrame, report: LoadReport) -> None:
    report.legs = len(df)
    report.betslips = int(df["betslip_id"].nunique())

    # The leg-vs-betslip inflation factor is computed per currency and then
    # taken over the largest track. A single absolute turnover total is
    # deliberately NOT reported here: summing EUR, PEN and USD into one figure
    # is the cross-currency total ADR-0001 forbids. Per-currency money lives in
    # `betflow._money_by_currency`, which is the only place money is summed.
    by_currency: dict[str, float] = {}
    for code, group in df[df["Currency Code"].notna()].groupby("Currency Code"):
        betslip_total = group.groupby("betslip_id")["TURNOVER"].first().sum()
        if betslip_total > 0:
            by_currency[str(code)] = float(group["TURNOVER"].sum() / betslip_total)
    report.inflation_by_currency = {k: round(v, 4) for k, v in by_currency.items()}
    if by_currency:
        largest = df["Currency Code"].value_counts().idxmax()
        report.inflation_factor = by_currency.get(str(largest), 0.0)
    report.currencies = df["Currency Code"].value_counts().to_dict()
    report.inplay_share = float(df["is_inplay"].mean())
    report.unparsed_dates = int(df["Betslip date (utc)"].isna().sum())

    simple = df[df["BetType"] == "SIMPLE"]
    report.simple_with_multiple_legs = int(
        (simple.groupby("betslip_id").size() > 1).sum()
    )
