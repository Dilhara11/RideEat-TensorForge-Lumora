"""Classifier interface + the ONNX Runtime implementation.

`TicketClassifier` is the seam the rest of the engine depends on; tests plug in a fake, the
container uses `OnnxTicketClassifier`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Sequence

import numpy as np

from ..validation import Ticket
from .bundle import ModelBundle
from .decoder import PredictionDecoder
from .preprocessing import TicketEncoder

log = logging.getLogger("tfengine.classifier")


class TicketClassifier(ABC):
    """Anything that turns tickets into contract-shaped prediction dicts.

    Example:
        clf.predict([Ticket(ticket_id="T1", channel="chat", text="food never came")])
          -> [{"ticket_id": "T1", "category": "delivery_delay", ..., "model_version": clf.model_version}]
    """

    model_version: str

    @abstractmethod
    def predict(self, tickets: Sequence[Ticket]) -> list[dict]: ...


class OnnxTicketClassifier(TicketClassifier):
    """CPU ONNX Runtime session over the exported three-head encoder.

    Example:
        clf = OnnxTicketClassifier(ModelBundle.open(Path("training/models/winner")), n_threads=2)
        clf.model_version -> "v1.0-1a8163c34f54"
    """

    OUTPUTS = ("category_logits", "secondary_logits", "urgency_logits")

    def __init__(self, bundle: ModelBundle, n_threads: int = 2):
        import onnxruntime as ort

        self.bundle = bundle
        self.model_version = bundle.model_version
        self.encoder = TicketEncoder(bundle.tokenizer_dir, bundle.max_length)
        self.decoder = PredictionDecoder(bundle.labels, bundle.decode)

        # Session options: 2 intra-op threads (2 vCPU box), fully optimised graph, CPU only.
        so = ort.SessionOptions()
        so.intra_op_num_threads = n_threads
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(bundle.onnx_path), so, providers=["CPUExecutionProvider"])
        self._check_io()

    def _check_io(self) -> None:
        # Fail fast at load time (not on the first request) if the graph is not the expected one.
        # Example: an export with outputs ["logits"] -> RuntimeError naming the expected outputs.
        inputs = {i.name for i in self.session.get_inputs()}
        outputs = [o.name for o in self.session.get_outputs()]
        if not {"input_ids", "attention_mask"} <= inputs or any(o not in outputs for o in self.OUTPUTS):
            raise RuntimeError(f"unexpected ONNX signature: inputs={sorted(inputs)} outputs={outputs}")
        self._input_names = inputs

    def _forward_one(self, t: Ticket) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        # One ticket per forward pass -> the prediction never depends on its batch neighbours.
        ids, mask = self.encoder.encode(t.channel, t.subject, t.text)
        feeds = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self._input_names:  # BERT-style exports
            feeds["token_type_ids"] = np.zeros_like(ids)
        cat, sec, urg = self.session.run(list(self.OUTPUTS), feeds)
        return cat[0], sec[0], urg[0]

    def predict(self, tickets: Sequence[Ticket]) -> list[dict]:
        # Example: 3 tickets -> 3 forward passes -> stacked logits [3x11], [3x12], [3x2] -> 3 records
        if not tickets:
            return []
        rows = [self._forward_one(t) for t in tickets]
        cat = np.stack([r[0] for r in rows])
        sec = np.stack([r[1] for r in rows])
        urg = np.stack([r[2] for r in rows])
        return self.decoder.decode(cat, sec, urg, [t.ticket_id for t in tickets], self.model_version)
