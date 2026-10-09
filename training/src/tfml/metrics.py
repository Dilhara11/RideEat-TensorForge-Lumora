"""Evaluation metrics for the three heads, per-language breakdown and calibration."""

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_recall_fscore_support

from .data import encode_labels
from .labels import CATEGORIES, NONE_IDX


def secondary_scores(y_true, y_pred) -> dict:
    """Secondary is ~90% "none", so plain accuracy is misleading.
    Report exact-match accuracy plus precision/recall/F1 on the *present* secondary labels:
    a TP is a predicted non-none secondary that equals the true one."""
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    pred_pos = y_pred != NONE_IDX
    true_pos = y_true != NONE_IDX
    tp = int(((y_pred == y_true) & true_pos).sum())
    p = tp / pred_pos.sum() if pred_pos.sum() else 0.0
    r = tp / true_pos.sum() if true_pos.sum() else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {
        "secondary_acc": float(accuracy_score(y_true, y_pred)),
        "secondary_precision": float(p),
        "secondary_recall": float(r),
        "secondary_f1": float(f1),
    }


def expected_calibration_error(confidence, correct, n_bins: int = 15) -> float:
    confidence, correct = np.asarray(confidence), np.asarray(correct, dtype=float)
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (confidence > lo) & (confidence <= hi)
        if m.any():
            ece += m.mean() * abs(correct[m].mean() - confidence[m].mean())
    return float(ece)


def compute_metrics(df: pd.DataFrame, decoded: dict) -> dict:
    """Headline metrics. `df` holds the gold labels, `decoded` comes from rules.decode_arrays."""
    y = encode_labels(df)
    cat_pred, sec_pred, urg_pred = decoded["category"], decoded["secondary"], decoded["is_urgent"].astype(int)
    up, ur, uf, _ = precision_recall_fscore_support(y["urgency"], urg_pred, average="binary", zero_division=0)
    correct = cat_pred == y["category"]
    m = {
        "n": int(len(df)),
        "category_acc": float(correct.mean()),
        "category_macro_f1": float(f1_score(y["category"], cat_pred, average="macro", labels=range(len(CATEGORIES)))),
        "category_weighted_f1": float(f1_score(y["category"], cat_pred, average="weighted")),
        **secondary_scores(y["secondary"], sec_pred),
        "urgency_acc": float((urg_pred == y["urgency"]).mean()),
        "urgency_precision": float(up),
        "urgency_recall": float(ur),
        "urgency_f1": float(uf),
        "exact_match": float((correct & (sec_pred == y["secondary"]) & (urg_pred == y["urgency"])).mean()),
        "ece": expected_calibration_error(decoded["confidence"], correct),
        "mean_confidence": float(np.mean(decoded["confidence"])),
    }
    return m


def per_language(df: pd.DataFrame, decoded: dict) -> pd.DataFrame:
    y = encode_labels(df)
    rows = []
    for lang, idx in df.groupby("language").indices.items():
        yt, yp = y["category"][idx], decoded["category"][idx]
        _, _, uf, _ = precision_recall_fscore_support(
            y["urgency"][idx], decoded["is_urgent"][idx].astype(int), average="binary", zero_division=0
        )
        rows.append(
            {
                "language": lang,
                "n": len(idx),
                "category_acc": float((yt == yp).mean()),
                "category_macro_f1": float(f1_score(yt, yp, average="macro")),
                "secondary_acc": float((y["secondary"][idx] == decoded["secondary"][idx]).mean()),
                "urgency_f1": float(uf),
            }
        )
    out = pd.DataFrame(rows).set_index("language").sort_values("n", ascending=False)
    if "en" in out.index:
        out["gap_vs_en"] = out["category_acc"] - out.loc["en", "category_acc"]
    return out


def category_report(df: pd.DataFrame, decoded: dict) -> pd.DataFrame:
    y = encode_labels(df)["category"]
    rep = classification_report(
        y, decoded["category"], labels=range(len(CATEGORIES)), target_names=CATEGORIES, output_dict=True, zero_division=0
    )
    return pd.DataFrame(rep).T


def category_confusion(df: pd.DataFrame, decoded: dict) -> pd.DataFrame:
    y = encode_labels(df)["category"]
    cm = confusion_matrix(y, decoded["category"], labels=range(len(CATEGORIES)))
    return pd.DataFrame(cm, index=CATEGORIES, columns=CATEGORIES)


def selection_score(m: dict) -> float:
    """Winner score (amended plan): correctness only, latency is a pass/fail gate."""
    return 0.5 * m["category_macro_f1"] + 0.25 * m["secondary_f1"] + 0.25 * m["urgency_f1"]
