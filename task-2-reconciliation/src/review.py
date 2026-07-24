"""The human-review list.

Everything the pipeline can't resolve with confidence — an unmatched entity, a
provisional mapping, a value conflict, a data-quality flag, a price divergence —
is recorded here with the competing values and a suggested action. Ids are
assigned in creation order (`R01`, `R02`, …) so a given input always yields the
same list, byte for byte.
"""

from __future__ import annotations

from .models import ReviewCategory, ReviewItem, Severity, SourceIds


class ReviewBuilder:
    """Collects review items and hands back stable ids as they are created."""

    def __init__(self) -> None:
        self._items: list[ReviewItem] = []

    def add(
        self,
        *,
        category: ReviewCategory,
        entity_type: str,
        entity_ref: str,
        reason: str,
        suggested_action: str,
        severity: Severity,
        source_ids: SourceIds | None = None,
        competing_values: dict | None = None,
    ) -> str:
        review_id = f"R{len(self._items) + 1:02d}"
        self._items.append(
            ReviewItem(
                id=review_id,
                category=category,
                entity_type=entity_type,
                entity_ref=entity_ref,
                reason=reason,
                suggested_action=suggested_action,
                severity=severity,
                source_ids=source_ids,
                competing_values=competing_values,
            )
        )
        return review_id

    @property
    def items(self) -> list[ReviewItem]:
        return list(self._items)

    def to_list(self) -> list[dict]:
        return [item.to_dict() for item in self._items]
