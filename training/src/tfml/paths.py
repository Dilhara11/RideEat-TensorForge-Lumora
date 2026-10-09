"""Project paths that work both on Google Colab (Drive) and locally."""

import sys
from dataclasses import dataclass, field
from pathlib import Path

DRIVE_ROOT = Path("/content/drive/MyDrive/TensorForge")
DATASET_FILES = ["train.jsonl", "validation.jsonl"]


def in_colab() -> bool:
    return "google.colab" in sys.modules


@dataclass
class Paths:
    root: Path
    raw_data: Path = field(init=False)

    def __post_init__(self):
        self.root = Path(self.root).resolve()
        # Colab / Drive layout: <root>/data/train.jsonl.
        # Local fallback: the original dataset folder under Resources/.
        candidates = [
            self.root / "data",
            self.root.parent / "Resources" / "TensorForge 2.0 - MVP Resources DataSet",
        ]
        for c in candidates:
            if all((c / f).exists() for f in DATASET_FILES):
                self.raw_data = c
                break
        else:
            raise FileNotFoundError(
                f"Could not find {DATASET_FILES} in any of: {[str(c) for c in candidates]}"
            )
        for d in (self.processed, self.checkpoints, self.models, self.results, self.figures):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def processed(self) -> Path:
        return self.root / "data" / "processed"

    @property
    def checkpoints(self) -> Path:
        return self.root / "checkpoints"

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def winner(self) -> Path:
        return self.models / "winner"

    @property
    def results(self) -> Path:
        return self.root / "results"

    @property
    def figures(self) -> Path:
        return self.results / "figures"

    @property
    def data_config(self) -> Path:
        """Written by notebook 01 (max_length etc.), read by 02-04."""
        return self.results / "data_config.json"
