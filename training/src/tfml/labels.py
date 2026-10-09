"""Label spaces and the fixed category -> team table from the TensorForge API contract."""

CATEGORIES = [
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
]
NONE_LABEL = "none"
# Secondary head: the 11 categories + "none" (index 11).
SECONDARY_LABELS = CATEGORIES + [NONE_LABEL]
NONE_IDX = SECONDARY_LABELS.index(NONE_LABEL)
SPAM_IDX = CATEGORIES.index("spam_irrelevant")

CAT2ID = {c: i for i, c in enumerate(CATEGORIES)}
SEC2ID = {c: i for i, c in enumerate(SECONDARY_LABELS)}

# Only channel values allowed by the API (predict_request.schema.json).
CHANNELS = ["email", "chat", "call_transcript"]

CATEGORY_TEAM_MAP = {
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

LANGUAGES = ["en", "singlish", "si", "ta", "tanglish", "mixed"]


def label_maps() -> dict:
    """Serializable label mapping, exported next to the model."""
    return {
        "category": CATEGORIES,
        "secondary_category": SECONDARY_LABELS,
        "is_urgent": [False, True],
        "none_label": NONE_LABEL,
        "team_map": CATEGORY_TEAM_MAP,
    }
