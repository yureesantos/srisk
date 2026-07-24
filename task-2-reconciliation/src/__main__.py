"""CLI entry point: `python -m src [alpha] [beta] [--out DIR]`."""

from __future__ import annotations

import argparse

from .pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile two provider match feeds.")
    parser.add_argument("alpha", nargs="?", default="feeds/provider_alpha.json")
    parser.add_argument("beta", nargs="?", default="feeds/provider_beta.json")
    parser.add_argument("--out", default="out", help="output directory (default: out/)")
    args = parser.parse_args()

    run(args.alpha, args.beta, args.out)


if __name__ == "__main__":
    main()
