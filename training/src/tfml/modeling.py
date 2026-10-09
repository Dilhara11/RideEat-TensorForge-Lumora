"""Shared-backbone, three-head ticket classifier."""

import json
from pathlib import Path

import torch
from torch import nn
from transformers import AutoConfig, AutoModel, AutoTokenizer

from .labels import CATEGORIES, SECONDARY_LABELS, label_maps

# All three transformer candidates share the XLM-R SentencePiece vocabulary (250k tokens),
# which covers Sinhala and Tamil script.
MODEL_SPECS = {
    "xlmr-base": {
        "backbone": "FacebookAI/xlm-roberta-base",
        "tokenizer": "FacebookAI/xlm-roberta-base",
        "pooling": "cls",
    },
    "minilm": {
        "backbone": "microsoft/Multilingual-MiniLM-L12-H384",
        # Model card: use the XLM-R tokenizer with this checkpoint.
        "tokenizer": "FacebookAI/xlm-roberta-base",
        "pooling": "cls",
    },
    "me5-small": {
        "backbone": "intfloat/multilingual-e5-small",
        "tokenizer": "intfloat/multilingual-e5-small",
        # E5 was pre-trained with mean pooling.
        "pooling": "mean",
    },
}


def load_tokenizer(name: str):
    return AutoTokenizer.from_pretrained(name)


class MultiHeadClassifier(nn.Module):
    """Encoder -> pooled vector -> {category (11), secondary (12 incl. none), urgency (2)}."""

    def __init__(self, backbone_name: str, pooling: str = "cls", dropout: float = 0.1, pretrained: bool = True,
                 attn_implementation: str | None = None):
        super().__init__()
        kw = {"add_pooling_layer": False}
        if attn_implementation:
            kw["attn_implementation"] = attn_implementation
        if pretrained:
            self.backbone = AutoModel.from_pretrained(backbone_name, **kw)
        else:
            self.backbone = AutoModel.from_config(AutoConfig.from_pretrained(backbone_name), **kw)
        hidden = self.backbone.config.hidden_size
        self.pooling = pooling
        self.dropout = nn.Dropout(dropout)
        self.category_head = nn.Linear(hidden, len(CATEGORIES))
        self.secondary_head = nn.Linear(hidden, len(SECONDARY_LABELS))
        self.urgency_head = nn.Linear(hidden, 2)

    def pool(self, hidden_states, attention_mask):
        if self.pooling == "mean":
            m = attention_mask.unsqueeze(-1).to(hidden_states.dtype)
            return (hidden_states * m).sum(1) / m.sum(1).clamp(min=1e-6)
        return hidden_states[:, 0]

    def forward(self, input_ids, attention_mask):
        out = self.backbone(input_ids=input_ids, attention_mask=attention_mask)
        h = self.dropout(self.pool(out.last_hidden_state, attention_mask))
        return self.category_head(h), self.secondary_head(h), self.urgency_head(h)


def build_model(model_key: str, dropout: float = 0.1):
    spec = MODEL_SPECS[model_key]
    tokenizer = load_tokenizer(spec["tokenizer"])
    model = MultiHeadClassifier(spec["backbone"], spec["pooling"], dropout)
    return model, tokenizer


def save_checkpoint_dir(out_dir: Path, model, tokenizer, model_key: str, max_length: int, extra: dict | None = None):
    """Self-contained checkpoint: weights + tokenizer + metadata (no hub access needed to reload
    the tokenizer; the backbone *config* is also saved so reload works offline)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), out_dir / "model.pt")
    tokenizer.save_pretrained(out_dir / "tokenizer")
    model.backbone.config.save_pretrained(out_dir / "backbone_config")
    spec = MODEL_SPECS[model_key]
    meta = {
        "model_key": model_key,
        "backbone": spec["backbone"],
        "pooling": spec["pooling"],
        "max_length": max_length,
        "labels": label_maps(),
        **(extra or {}),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))


def load_checkpoint_dir(ckpt_dir: Path, device: str = "cpu", attn_implementation: str | None = None):
    """Reload a `best/` checkpoint offline. Use attn_implementation="eager" for ONNX export."""
    ckpt_dir = Path(ckpt_dir)
    meta = json.loads((ckpt_dir / "meta.json").read_text())
    tokenizer = AutoTokenizer.from_pretrained(ckpt_dir / "tokenizer")
    model = MultiHeadClassifier(str(ckpt_dir / "backbone_config"), meta["pooling"], pretrained=False,
                                attn_implementation=attn_implementation)
    state = torch.load(ckpt_dir / "model.pt", map_location=device)
    model.load_state_dict(state)
    model.to(device).eval()
    return model, tokenizer, meta
