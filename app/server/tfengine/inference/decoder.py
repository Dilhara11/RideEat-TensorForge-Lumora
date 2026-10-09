"""Head logits -> API predictions, with the contract's business rules enforced.

Mirrors `training/src/tfml/rules.py::decode_arrays` exactly (verified by
`tests/test_decoder_parity.py`) and then applies a defensive second pass so that a response
can never violate a consistency rule, whatever the thresholds are.
"""

from __future__ import annotations

import math

import numpy as np

from .bundle import DecodeConfig
from .labels import SPAM, LabelSpace


def softmax(x: np.ndarray) -> np.ndarray:
    # Numerically stable row-wise softmax. Example: [[0, 0]] -> [[0.5, 0.5]]
    x = x - x.max(axis=-1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=-1, keepdims=True)


class PredictionDecoder:
    """Example:
        dec = PredictionDecoder(LabelSpace.contract_default(), DecodeConfig(temperature=0.5))
        dec.decode(cat_logits[1x11], sec_logits[1x12], urg_logits[1x2], ["T1"], "v1.0-abc")
          -> [{"ticket_id": "T1", "category": "delivery_delay", "secondary_category": "payment_refund",
               "team": "Delivery Operations", "is_urgent": False, "confidence": 0.8123,
               "model_version": "v1.0-abc", "needs_human_review": False}]
    """

    def __init__(self, labels: LabelSpace, config: DecodeConfig):
        self.labels = labels
        self.cfg = config

    # --- vectorised decode (same math as training) ---------------------------------------
    def decode_arrays(self, cat_logits, sec_logits, urg_logits) -> dict[str, np.ndarray]:
        cfg, ls = self.cfg, self.labels
        cat_logits = np.asarray(cat_logits, dtype=np.float64)
        sec_logits = np.asarray(sec_logits, dtype=np.float64)
        urg_logits = np.asarray(urg_logits, dtype=np.float64)
        n = len(cat_logits)
        rows = np.arange(n)

        # Primary: temperature-scaled softmax; confidence = probability of the chosen class.
        # Example: T=0.405 sharpens [2.0, 1.0] logits before softmax.
        cat_probs = softmax(cat_logits / cfg.temperature)
        cat = cat_probs.argmax(1)
        confidence = cat_probs[rows, cat]

        # Secondary: mask the primary *before* choosing (secondary can never equal primary).
        # Example: primary=delivery_delay -> its column is zeroed, then argmax / threshold.
        sec_probs = softmax(sec_logits)
        sec_probs[rows, cat] = 0.0
        if cfg.secondary_threshold is None:
            sec = sec_probs.argmax(1)
        else:
            cand_probs = sec_probs[:, : ls.none_idx]
            cand = cand_probs.argmax(1)
            sec = np.where(cand_probs[rows, cand] >= cfg.secondary_threshold, cand, ls.none_idx)

        # Urgency: P(urgent) >= tuned threshold. Example: threshold 0.15, P=0.2 -> urgent.
        p_urgent = softmax(urg_logits)[:, 1]
        urgent = p_urgent >= cfg.urgency_threshold

        # Rule: spam is never urgent and has no secondary.
        spam = cat == ls.spam_idx
        urgent = np.where(spam, False, urgent)
        sec = np.where(spam, ls.none_idx, sec)

        review = (confidence < cfg.review_threshold) if cfg.review_threshold is not None else np.zeros(n, bool)
        return {"category": cat, "secondary": sec, "is_urgent": urgent, "confidence": confidence,
                "needs_human_review": review}

    # --- records + defensive business rules -----------------------------------------------
    @staticmethod
    def _safe_confidence(x: float) -> float:
        # Example: nan -> 0.0, 1.0000001 -> 1.0 (schema requires 0 <= confidence <= 1)
        if not math.isfinite(x):
            return 0.0
        return round(min(1.0, max(0.0, x)), 6)

    def to_records(self, decoded: dict, ticket_ids: list[str | None], model_version: str) -> list[dict]:
        ls = self.labels
        out = []
        for i, tid in enumerate(ticket_ids):
            category = ls.categories[int(decoded["category"][i])]
            sec_idx = int(decoded["secondary"][i])
            secondary = None if sec_idx == ls.none_idx else ls.secondary[sec_idx]
            is_urgent = bool(decoded["is_urgent"][i])
            # Second pass (never trust thresholds blindly):
            # Example: category=spam_irrelevant -> is_urgent=False, secondary=None
            if category == SPAM:
                is_urgent, secondary = False, None
            if secondary == category:
                secondary = None
            rec = {} if tid is None else {"ticket_id": tid}
            rec.update(
                category=category,
                secondary_category=secondary,  # key always present (null when none)
                team=ls.team(category),
                is_urgent=is_urgent,
                confidence=self._safe_confidence(float(decoded["confidence"][i])),
                model_version=model_version,
                needs_human_review=bool(decoded["needs_human_review"][i]),
            )
            out.append(rec)
        return out

    def decode(self, cat_logits, sec_logits, urg_logits, ticket_ids, model_version) -> list[dict]:
        return self.to_records(self.decode_arrays(cat_logits, sec_logits, urg_logits), ticket_ids, model_version)
