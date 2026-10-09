"""Data loading, cleaning, splitting and tokenization.

Only `channel`, `subject` and `text` are model inputs, because the API sends nothing else.
`language` is used for stratification and per-language reporting only, never as a feature.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.model_selection import train_test_split
from torch.utils.data import Dataset

from .labels import CAT2ID, NONE_LABEL, SEC2ID
from .textproc import clean_text, prepare_input

def load_split(path: Path) -> pd.DataFrame:
    """Load a JSONL split (JSONL avoids CSV embedded-newline pitfalls)."""
    df = pd.read_json(path, lines=True, dtype={"ticket_id": str})
    df["subject"] = df["subject"].fillna("")
    df["secondary_category"] = df["secondary_category"].where(df["secondary_category"].notna(), None)
    df["is_urgent"] = df["is_urgent"].astype(bool)
    return df


def load_csv_split(path: Path) -> pd.DataFrame:
    """Load the CSV variant with a proper parser (quoted fields, embedded newlines)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8")
    df["secondary_category"] = df["secondary_category"].replace("", None)
    df["is_urgent"] = df["is_urgent"].str.lower().map({"true": True, "false": False})
    return df


def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["channel"] = out["channel"].map(clean_text)
    out["subject"] = out["subject"].map(clean_text)
    out["text"] = out["text"].map(clean_text)
    return out


def make_dev_split(train: pd.DataFrame, dev_frac: float = 0.1, seed: int = 42):
    """Hold out a dev set from train, stratified by category x language.

    Dev is used for epoch selection, threshold tuning and calibration, which keeps the
    official validation set untouched as an honest held-out test for model comparison.
    """
    strat = train["category"] + "|" + train["language"]
    # Merge tiny strata into their category so stratification never fails.
    counts = strat.value_counts()
    strat = strat.where(strat.map(counts) >= 2, train["category"])
    tr, dev = train_test_split(train, test_size=dev_frac, random_state=seed, stratify=strat)
    return tr.reset_index(drop=True), dev.reset_index(drop=True)


def encode_labels(df: pd.DataFrame) -> dict:
    sec = df["secondary_category"].fillna(NONE_LABEL)
    return {
        "category": df["category"].map(CAT2ID).to_numpy(),
        "secondary": sec.map(SEC2ID).to_numpy(),
        "urgency": df["is_urgent"].astype(int).to_numpy(),
    }


def tokenize_frame(tokenizer, df: pd.DataFrame, max_length: int) -> dict:
    sep = tokenizer.sep_token or "|"
    pairs = [prepare_input(c, s, t, sep) for c, s, t in zip(df["channel"], df["subject"], df["text"])]
    enc = tokenizer(
        [h for h, _ in pairs],
        [b for _, b in pairs],
        truncation="only_second",
        max_length=max_length,
        padding=False,
    )
    return {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"]}


class TicketDataset(Dataset):
    def __init__(self, tokenizer, df: pd.DataFrame, max_length: int, with_labels: bool = True):
        self.enc = tokenize_frame(tokenizer, df, max_length)
        self.labels = encode_labels(df) if with_labels else None

    def __len__(self):
        return len(self.enc["input_ids"])

    def __getitem__(self, i):
        item = {"input_ids": self.enc["input_ids"][i], "attention_mask": self.enc["attention_mask"][i]}
        if self.labels is not None:
            item["category_label"] = int(self.labels["category"][i])
            item["secondary_label"] = int(self.labels["secondary"][i])
            item["urgency_label"] = int(self.labels["urgency"][i])
        return item


def make_collate(pad_token_id: int):
    """Dynamic padding to the longest sequence in the batch."""

    def collate(batch):
        L = max(len(b["input_ids"]) for b in batch)
        ids = torch.full((len(batch), L), pad_token_id, dtype=torch.long)
        mask = torch.zeros((len(batch), L), dtype=torch.long)
        for i, b in enumerate(batch):
            n = len(b["input_ids"])
            ids[i, :n] = torch.tensor(b["input_ids"])
            mask[i, :n] = torch.tensor(b["attention_mask"])
        out = {"input_ids": ids, "attention_mask": mask}
        for k in ("category_label", "secondary_label", "urgency_label"):
            if k in batch[0]:
                out[k] = torch.tensor([b[k] for b in batch], dtype=torch.long)
        return out

    return collate


def save_jsonl(df: pd.DataFrame, path: Path):
    with open(path, "w", encoding="utf-8") as f:
        for rec in df.to_dict(orient="records"):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_processed(paths) -> dict[str, pd.DataFrame]:
    """Load the train/dev/val splits written by notebook 01."""
    return {s: load_split(paths.processed / f"{s}.jsonl") for s in ("train", "dev", "val")}
