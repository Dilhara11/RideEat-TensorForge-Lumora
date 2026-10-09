"""ONNX export, INT8 dynamic quantization and packaging of the winner model."""

import hashlib
import json
import shutil
from pathlib import Path

import torch
from torch import nn

RUNTIME_FILES = ["labels.py", "rules.py", "textproc.py", "onnx_runtime.py"]


class _ExportWrapper(nn.Module):
    """Eval-mode wrapper with plain positional inputs/outputs for the ONNX graph."""

    def __init__(self, model):
        super().__init__()
        self.model = model.eval()

    def forward(self, input_ids, attention_mask):
        return self.model(input_ids, attention_mask)


def export_onnx(model, tokenizer, out_path: Path, opset: int = 17) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model = model.to("cpu").eval()
    dummy = tokenizer(["chat"], ["dummy ticket text for export"], return_tensors="pt")
    args = (dummy["input_ids"], dummy["attention_mask"])
    kwargs = dict(
        input_names=["input_ids", "attention_mask"],
        output_names=["category_logits", "secondary_logits", "urgency_logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "category_logits": {0: "batch"},
            "secondary_logits": {0: "batch"},
            "urgency_logits": {0: "batch"},
        },
        opset_version=opset,
        do_constant_folding=True,
    )
    with torch.no_grad():
        try:
            # TorchScript-based exporter: mature and handles HF encoders with dynamic axes.
            torch.onnx.export(_ExportWrapper(model), args, str(out_path), dynamo=False, **kwargs)
        except TypeError:  # older torch without the `dynamo` kwarg
            torch.onnx.export(_ExportWrapper(model), args, str(out_path), **kwargs)
    # Large models may be written with external data; consolidate to one self-contained file.
    import onnx

    m = onnx.load(str(out_path), load_external_data=True)
    if m.ByteSize() < 2**31 - 1:
        for f in out_path.parent.glob(out_path.name + "*.data"):
            f.unlink()
        onnx.save_model(m, str(out_path), save_as_external_data=False)
    onnx.checker.check_model(str(out_path))
    return out_path


def quantize_int8(fp32_path: Path, int8_path: Path) -> Path:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    try:
        from onnxruntime.quantization.shape_inference import quant_pre_process

        pre = Path(fp32_path).with_suffix(".pre.onnx")
        quant_pre_process(str(fp32_path), str(pre), skip_symbolic_shape=True)
        src = pre
    except Exception as e:  # pre-processing is an optimisation, not a requirement
        print("quant_pre_process skipped:", e)
        src = fp32_path
    quantize_dynamic(str(src), str(int8_path), weight_type=QuantType.QInt8, per_channel=True)
    if src != fp32_path:
        Path(src).unlink(missing_ok=True)
    return Path(int8_path)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def package_winner(out_dir: Path, onnx_path: Path, tokenizer, inference_config: dict, metrics: dict, src_pkg: Path):
    """Write models/winner/: model.onnx, tokenizer/, labels.json, inference_config.json,
    metrics.json and a torch-free tfml_runtime/ package for the API server."""
    from .labels import label_maps

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "model.onnx"
    if Path(onnx_path).resolve() != dst.resolve():
        shutil.copy2(onnx_path, dst)
    tokenizer.save_pretrained(out_dir / "tokenizer")
    sha = file_sha256(dst)
    cfg = {**inference_config, "onnx_file": "model.onnx", "model_sha256": sha}
    cfg.setdefault("model_version", f"{cfg.get('version_prefix', 'v1.0')}-{sha[:12]}")
    (out_dir / "inference_config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    (out_dir / "labels.json").write_text(json.dumps(label_maps(), indent=2, ensure_ascii=False))
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False))
    rt = out_dir / "tfml_runtime"
    rt.mkdir(exist_ok=True)
    (rt / "__init__.py").write_text('"""Torch-free inference runtime exported with the winner model."""\n')
    for f in RUNTIME_FILES:
        shutil.copy2(Path(src_pkg) / f, rt / f)
    return cfg


def onnx_logits(onnx_path: Path, tokenizer, df, max_length: int, n_threads: int = 2, batch_size: int = 32) -> dict:
    """Run an ONNX model over a DataFrame with the training tokenization (for parity checks)."""
    import numpy as np
    import onnxruntime as ort

    from .data import make_collate, tokenize_frame

    so = ort.SessionOptions()
    so.intra_op_num_threads = n_threads
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    enc = tokenize_frame(tokenizer, df, max_length)
    collate = make_collate(tokenizer.pad_token_id)
    outs = {"category": [], "secondary": [], "urgency": []}
    for i in range(0, len(df), batch_size):
        items = [{"input_ids": a, "attention_mask": m}
                 for a, m in zip(enc["input_ids"][i : i + batch_size], enc["attention_mask"][i : i + batch_size])]
        b = collate(items)
        c, s, u = sess.run(None, {"input_ids": b["input_ids"].numpy(), "attention_mask": b["attention_mask"].numpy()})
        outs["category"].append(c)
        outs["secondary"].append(s)
        outs["urgency"].append(u)
    return {k: np.concatenate(v) for k, v in outs.items()}
