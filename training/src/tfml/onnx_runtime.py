"""ONNX Runtime inference for the exported winner model.

Dependencies: numpy, onnxruntime, transformers (tokenizer only). No torch.
This file, labels.py, rules.py and textproc.py are copied into models/winner/tfml_runtime/
so the API server can `from tfml_runtime.onnx_runtime import OnnxTicketClassifier`.
"""

import json
import time
from pathlib import Path

import numpy as np

from .rules import decode_arrays, to_records
from .textproc import clean_text, prepare_input


class OnnxTicketClassifier:
    def __init__(self, model_dir, onnx_file: str | None = None, n_threads: int = 2):
        import onnxruntime as ort
        from transformers import AutoTokenizer

        self.dir = Path(model_dir)
        self.cfg = json.loads((self.dir / "inference_config.json").read_text())
        self.tokenizer = AutoTokenizer.from_pretrained(self.dir / "tokenizer")
        so = ort.SessionOptions()
        so.intra_op_num_threads = n_threads
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(self.dir / (onnx_file or self.cfg["onnx_file"])), so, providers=["CPUExecutionProvider"]
        )
        self.model_version = self.cfg["model_version"]

    def logits(self, tickets: list[dict], batch_size: int | None = None) -> dict:
        # Default 1: INT8 dynamic quantization computes activation scales over the whole batch
        # (padding included), so batching would make a ticket's prediction depend on its neighbours.
        batch_size = batch_size or self.cfg.get("inference_batch_size", 1)
        sep = self.tokenizer.sep_token or "|"
        outs = {"category": [], "secondary": [], "urgency": []}
        for i in range(0, len(tickets), batch_size):
            chunk = tickets[i : i + batch_size]
            pairs = [
                prepare_input(clean_text(t.get("channel")), clean_text(t.get("subject", "")), clean_text(t.get("text")), sep)
                for t in chunk
            ]
            enc = self.tokenizer(
                [h for h, _ in pairs], [b for _, b in pairs], truncation="only_second",
                max_length=self.cfg["max_length"], padding=True, return_tensors="np",
            )
            c, s, u = self.session.run(
                None, {"input_ids": enc["input_ids"].astype(np.int64), "attention_mask": enc["attention_mask"].astype(np.int64)}
            )
            outs["category"].append(c)
            outs["secondary"].append(s)
            outs["urgency"].append(u)
        return {k: np.concatenate(v) for k, v in outs.items()}

    def predict(self, tickets: list[dict], batch_size: int | None = None) -> list[dict]:
        lg = self.logits(tickets, batch_size)
        dec = decode_arrays(lg["category"], lg["secondary"], lg["urgency"], self.cfg["decode"])
        recs = to_records(dec, [t.get("ticket_id") for t in tickets])
        for r in recs:
            if r.get("ticket_id") is None:
                r.pop("ticket_id", None)
            r["model_version"] = self.model_version
        return recs


def benchmark(clf: OnnxTicketClassifier, tickets: list[dict], n_single: int = 100):
    clf.predict(tickets[:1])  # warm-up
    times = []
    for t in tickets[:n_single]:
        s = time.perf_counter()
        clf.predict([t])
        times.append(time.perf_counter() - s)
    s = time.perf_counter()
    clf.predict(tickets[:100])
    batch_s = time.perf_counter() - s
    a = np.asarray(times) * 1000
    return {"p50_ms": float(np.percentile(a, 50)), "p95_ms": float(np.percentile(a, 95)),
            "p99_ms": float(np.percentile(a, 99)), "mean_ms": float(a.mean()), "batch100_s": batch_s}
