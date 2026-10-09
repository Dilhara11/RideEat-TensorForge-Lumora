"""Shrink an exported ONNX model without changing how it computes.

`fp16_storage` stores every large float32 weight as float16 and inserts a `Cast` back to float32
in front of it. ONNX Runtime folds those casts when the session is created, so inference still
runs in float32 (same kernels, same speed as FP32); only the file is ~2x smaller. The weights
are rounded to float16 (about 3 significant digits), which notebook 05 checks against FP32.

numpy + onnx only (no torch), so it also runs outside Colab.
"""

import hashlib
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fp16_storage(src: Path, dst: Path, min_elements: int = 1024) -> dict:
    """Write `dst` = `src` with float32 initializers stored as float16 (+ Cast to float32).

    Small tensors (< min_elements, e.g. LayerNorm epsilons, shape constants) and tensors whose
    values would overflow float16 stay float32. Returns conversion statistics.
    """
    model = onnx.load(str(src))
    graph = model.graph
    kept, casts = [], []
    n_conv = n_total = 0
    max_abs_err = max_rel_err = 0.0
    for init in graph.initializer:
        n = int(np.prod(init.dims)) if init.dims else 1
        if init.data_type == TensorProto.FLOAT:
            n_total += n
        if init.data_type != TensorProto.FLOAT or n < min_elements:
            kept.append(init)
            continue
        arr = numpy_helper.to_array(init)
        half = arr.astype(np.float16)
        if not np.isfinite(half).all():  # outside float16 range -> keep exact
            kept.append(init)
            continue
        err = np.abs(half.astype(np.float32) - arr)
        max_abs_err = max(max_abs_err, float(err.max()))
        nz = np.abs(arr) > 1e-3
        if nz.any():
            max_rel_err = max(max_rel_err, float((err[nz] / np.abs(arr[nz])).max()))
        name16 = f"{init.name}__fp16"
        kept.append(numpy_helper.from_array(half, name16))
        casts.append(helper.make_node("Cast", [name16], [init.name], to=TensorProto.FLOAT,
                                      name=f"fp16_storage_cast_{len(casts)}"))
        n_conv += n

    del graph.initializer[:]
    graph.initializer.extend(kept)
    nodes = list(graph.node)
    del graph.node[:]
    graph.node.extend(casts + nodes)  # casts first: their outputs feed the original consumers

    onnx.checker.check_model(model)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    onnx.save_model(model, str(dst))
    return {
        "converted_tensors": len(casts),
        "converted_fraction": n_conv / max(n_total, 1),
        "max_abs_weight_error": max_abs_err,
        "max_rel_weight_error": max_rel_err,
        "src_mb": Path(src).stat().st_size / 2**20,
        "dst_mb": Path(dst).stat().st_size / 2**20,
    }
