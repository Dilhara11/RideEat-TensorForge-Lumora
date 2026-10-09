"""The exported model package (`training/models/winner/`) as one validated object.

Expected layout (written by `training/src/tfml/export.py::package_winner`):

    model.onnx              three outputs: category_logits, secondary_logits, urgency_logits
    tokenizer/tokenizer.json (+ tokenizer_config.json)
    inference_config.json   max_length, decode thresholds, model_sha256, model_version
    labels.json             label orders + team map
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .labels import LabelSpace

log = logging.getLogger("tfengine.bundle")


class BundleError(RuntimeError):
    """The model directory is incomplete or inconsistent."""


@dataclass(frozen=True)
class DecodeConfig:
    """Thresholds tuned in notebook 04 (missing keys fall back to plain argmax decoding).

    Example: DecodeConfig.from_dict({"temperature": 0.405, "urgency_threshold": 0.15})
             -> DecodeConfig(temperature=0.405, urgency_threshold=0.15, secondary_threshold=None, review_threshold=None)
    """

    temperature: float = 1.0
    urgency_threshold: float = 0.5
    secondary_threshold: float | None = None
    review_threshold: float | None = None

    @classmethod
    def from_dict(cls, d: dict | None) -> "DecodeConfig":
        d = d or {}
        cfg = cls(
            temperature=float(d.get("temperature", 1.0)),
            urgency_threshold=float(d.get("urgency_threshold", 0.5)),
            secondary_threshold=None if d.get("secondary_threshold") is None else float(d["secondary_threshold"]),
            review_threshold=None if d.get("review_threshold") is None else float(d["review_threshold"]),
        )
        if cfg.temperature <= 0:
            raise BundleError(f"decode.temperature must be > 0, got {cfg.temperature}")
        return cfg


@dataclass(frozen=True)
class ModelBundle:
    """Validated view of a model directory.

    Example:
        b = ModelBundle.open(Path("training/models/winner"))
        b.model_version   -> "v1.0-1a8163c34f54"
        b.onnx_path       -> .../model.onnx
        b.verify_hash()   -> raises BundleError if model.onnx bytes != inference_config.model_sha256
    """

    root: Path
    config: dict
    labels: LabelSpace
    decode: DecodeConfig = field(default_factory=DecodeConfig)

    REQUIRED = ("inference_config.json", "labels.json", "tokenizer/tokenizer.json")

    @property
    def onnx_path(self) -> Path:
        return self.root / self.config.get("onnx_file", "model.onnx")

    @property
    def tokenizer_dir(self) -> Path:
        return self.root / "tokenizer"

    @property
    def model_version(self) -> str:
        return self.config["model_version"]

    @property
    def max_length(self) -> int:
        return int(self.config["max_length"])

    @property
    def inference_batch_size(self) -> int:
        # INT8 dynamic quantization is only batch-invariant at batch size 1 (see plan amendment C4).
        return max(1, int(self.config.get("inference_batch_size", 1)))

    @classmethod
    def open(cls, root: Path) -> "ModelBundle":
        """Cheap: reads the JSON files and checks presence. Does *not* load ONNX."""
        root = Path(root)
        # List every missing file at once. Example: "missing: tokenizer/tokenizer.json, inference_config.json"
        missing = [rel for rel in cls.REQUIRED if not (root / rel).is_file()]
        if missing:
            raise BundleError(f"model bundle {root} is incomplete; missing: {', '.join(missing)}")
        config = json.loads((root / "inference_config.json").read_text(encoding="utf-8"))
        for key in ("model_version", "max_length"):
            if not config.get(key):
                raise BundleError(f"inference_config.json has no '{key}'")
        bundle = cls(root=root, config=config, labels=LabelSpace.from_file(root / "labels.json"),
                     decode=DecodeConfig.from_dict(config.get("decode")))
        if not bundle.onnx_path.is_file():
            raise BundleError(f"model bundle {root} is incomplete; missing: {bundle.onnx_path.name}")
        return bundle

    def verify_hash(self) -> None:
        """Tie `model_version` to the artifact: sha256(model.onnx) must equal the exported hash."""
        expected = self.config.get("model_sha256")
        if not expected:
            log.warning("inference_config.json has no model_sha256; skipping artifact hash check")
            return
        h = hashlib.sha256()
        with open(self.onnx_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != expected:
            raise BundleError(
                f"{self.onnx_path.name} sha256 {h.hexdigest()[:12]} does not match inference_config "
                f"model_sha256 {expected[:12]} (model_version {self.model_version})"
            )
