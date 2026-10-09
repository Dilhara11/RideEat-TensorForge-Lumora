"""Turn raw head logits into API-shaped predictions and enforce business rules.

numpy-only so the exact same decoding runs for PyTorch, ONNX and the API server.
"""

import numpy as np

from .labels import CATEGORIES, CATEGORY_TEAM_MAP, NONE_IDX, SECONDARY_LABELS, SPAM_IDX


def softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=axis, keepdims=True)


DEFAULT_DECODE = {
    "temperature": 1.0,        # category temperature (fitted in notebook 04)
    "urgency_threshold": 0.5,  # P(urgent) >= t -> urgent (tuned in notebook 04)
    "secondary_threshold": None,  # None = argmax incl. "none"; float = P(best non-primary) >= t
    "review_threshold": None,  # confidence < t -> needs_human_review (chosen in notebook 04)
}


def decode_arrays(cat_logits, sec_logits, urg_logits, cfg: dict | None = None) -> dict:
    """Vectorised decode. Returns integer/boolean arrays plus confidence."""
    cfg = {**DEFAULT_DECODE, **(cfg or {})}
    cat_logits = np.asarray(cat_logits, dtype=np.float64)
    sec_logits = np.asarray(sec_logits, dtype=np.float64)
    urg_logits = np.asarray(urg_logits, dtype=np.float64)
    n = len(cat_logits)

    cat_probs = softmax(cat_logits / cfg["temperature"])
    cat = cat_probs.argmax(1)
    confidence = cat_probs[np.arange(n), cat]

    # Secondary: the primary category can never be the secondary, so mask it *before*
    # choosing (better than predicting it and then nulling it afterwards).
    sec_probs = softmax(sec_logits)
    sec_probs[np.arange(n), cat] = 0.0
    if cfg["secondary_threshold"] is None:
        sec = sec_probs.argmax(1)
    else:
        cand_probs = sec_probs[:, :NONE_IDX]
        cand = cand_probs.argmax(1)
        sec = np.where(cand_probs[np.arange(n), cand] >= cfg["secondary_threshold"], cand, NONE_IDX)

    p_urgent = softmax(urg_logits)[:, 1]
    urgent = p_urgent >= cfg["urgency_threshold"]

    # Rule 1: spam is never urgent and has no secondary.
    spam = cat == SPAM_IDX
    urgent = np.where(spam, False, urgent)
    sec = np.where(spam, NONE_IDX, sec)

    review = (
        confidence < cfg["review_threshold"] if cfg["review_threshold"] is not None else np.zeros(n, bool)
    )
    return {
        "category": cat,
        "secondary": sec,
        "is_urgent": urgent,
        "confidence": confidence,
        "p_urgent": p_urgent,
        "needs_human_review": review,
    }


def apply_business_rules(prediction: dict) -> dict:
    """Rule set from the plan, applied to a single prediction dict (defensive second pass)."""
    if prediction["category"] == "spam_irrelevant":
        prediction["is_urgent"] = False
        prediction["secondary_category"] = None
    if prediction["secondary_category"] == prediction["category"]:
        prediction["secondary_category"] = None
    prediction["team"] = CATEGORY_TEAM_MAP[prediction["category"]]
    return prediction


def to_records(decoded: dict, ticket_ids=None) -> list[dict]:
    """Convert decode_arrays() output into API-shaped dicts."""
    recs = []
    for i in range(len(decoded["category"])):
        sec_idx = int(decoded["secondary"][i])
        rec = {
            "category": CATEGORIES[int(decoded["category"][i])],
            "secondary_category": None if sec_idx == NONE_IDX else SECONDARY_LABELS[sec_idx],
            "is_urgent": bool(decoded["is_urgent"][i]),
            "confidence": round(float(decoded["confidence"][i]), 6),
            "needs_human_review": bool(decoded["needs_human_review"][i]),
        }
        if ticket_ids is not None:
            rec = {"ticket_id": ticket_ids[i], **rec}
        recs.append(apply_business_rules(rec))
    return recs


def check_consistency(records: list[dict]) -> list[str]:
    """Return violations of the API consistency rules (empty list = all good)."""
    errs = []
    for r in records:
        if r["secondary_category"] is not None and r["secondary_category"] == r["category"]:
            errs.append(f"{r.get('ticket_id')}: secondary == category")
        if r["category"] == "spam_irrelevant" and (r["is_urgent"] or r["secondary_category"] is not None):
            errs.append(f"{r.get('ticket_id')}: spam rule violated")
        if r["team"] != CATEGORY_TEAM_MAP[r["category"]]:
            errs.append(f"{r.get('ticket_id')}: wrong team")
        if not 0.0 <= r["confidence"] <= 1.0:
            errs.append(f"{r.get('ticket_id')}: confidence out of range")
    return errs
