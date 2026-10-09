"""Label spaces and the fixed category -> team table from the API contract.

The model bundle ships its own `labels.json`. `LabelSpace.from_file` checks it against the
contract so that a re-ordered or renamed label can never silently produce wrong categories.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Contract enum order (OpenAPI `Category`) and the fixed routing table.
CONTRACT_CATEGORIES = (
    "payment_refund",
    "ride_trip_issue",
    "lost_item",
    "order_missing_wrong",
    "delivery_delay",
    "food_quality",
    "account_promo",
    "safety_conduct",
    "app_technical",
    "general_inquiry",
    "spam_irrelevant",
)
CONTRACT_TEAM_MAP = {
    "payment_refund": "Payments & Refunds",
    "ride_trip_issue": "Ride Operations",
    "lost_item": "Lost & Found",
    "order_missing_wrong": "Food Operations",
    "delivery_delay": "Delivery Operations",
    "food_quality": "Restaurant Quality",
    "account_promo": "Account Services",
    "safety_conduct": "Trust & Safety",
    "app_technical": "Tech Support",
    "general_inquiry": "Front-line Support",
    "spam_irrelevant": "Auto-close / Spam Filter",
}
SPAM = "spam_irrelevant"


class LabelSpaceError(ValueError):
    """labels.json disagrees with the contract."""


@dataclass(frozen=True)
class LabelSpace:
    """Index <-> label mapping for the three model heads.

    Example:
        ls = LabelSpace.from_file(Path("models/winner/labels.json"))
        ls.categories[4]       -> "delivery_delay"
        ls.secondary[11]       -> "none"   (ls.none_idx == 11)
        ls.team("lost_item")   -> "Lost & Found"
    """

    categories: tuple[str, ...]
    secondary: tuple[str, ...]
    none_label: str

    @property
    def none_idx(self) -> int:
        return self.secondary.index(self.none_label)

    @property
    def spam_idx(self) -> int:
        return self.categories.index(SPAM)

    @staticmethod
    def team(category: str) -> str:
        # Always from the contract table, never from the bundle (the table is fixed by the organizers).
        return CONTRACT_TEAM_MAP[category]

    def validate(self) -> "LabelSpace":
        # Example failure: categories missing "spam_irrelevant" -> LabelSpaceError
        if set(self.categories) != set(CONTRACT_CATEGORIES) or len(self.categories) != len(CONTRACT_CATEGORIES):
            raise LabelSpaceError(f"category labels do not match the contract: {self.categories}")
        # The decoder masks the primary out of the secondary head *by index*, so the first 11
        # secondary labels must be exactly the category list, followed by the "none" label.
        if tuple(self.secondary[: len(self.categories)]) != self.categories or self.secondary[-1] != self.none_label:
            raise LabelSpaceError("secondary labels must be the category list followed by the 'none' label")
        return self

    @classmethod
    def from_file(cls, path: Path) -> "LabelSpace":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        bundle_teams = data.get("team_map")
        if bundle_teams is not None and bundle_teams != CONTRACT_TEAM_MAP:
            raise LabelSpaceError("labels.json team_map differs from the contract routing table")
        return cls(
            categories=tuple(data["category"]),
            secondary=tuple(data["secondary_category"]),
            none_label=data.get("none_label", "none"),
        ).validate()

    @classmethod
    def contract_default(cls) -> "LabelSpace":
        # Used by tests/fakes. Example: LabelSpace.contract_default().none_idx -> 11
        return cls(CONTRACT_CATEGORIES, CONTRACT_CATEGORIES + ("none",), "none").validate()
