"""Training / inference loops, checkpointing, calibration and latency benchmarking."""

import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader
from transformers import get_linear_schedule_with_warmup

from .data import TicketDataset, make_collate
from .metrics import compute_metrics
from .modeling import build_model, save_checkpoint_dir
from .rules import decode_arrays


@dataclass
class TrainConfig:
    model_key: str
    learning_rate: float = 2e-5
    batch_size: int = 16
    max_length: int = 256
    epochs: int = 5
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01
    loss_weights: tuple = (1.0, 0.5, 0.3)  # category, secondary, urgency
    dropout: float = 0.1
    grad_clip: float = 1.0
    fp16: bool = True  # T4 has no bf16 -> fp16 autocast + GradScaler
    seed: int = 42
    eval_batch_size: int = 64


def set_seed(seed: int = 42):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)


def device() -> str:
    return "cuda" if torch.cuda.is_available() else "cpu"


def make_loader(ds, batch_size, pad_id, shuffle, seed=42):
    g = torch.Generator()
    g.manual_seed(seed)
    return DataLoader(ds, batch_size=batch_size, shuffle=shuffle, collate_fn=make_collate(pad_id), generator=g)


@torch.no_grad()
def predict_logits(model, loader, dev: str | None = None, fp16: bool = False) -> dict:
    dev = dev or next(model.parameters()).device.type
    model.eval()
    outs = {"category": [], "secondary": [], "urgency": []}
    for b in loader:
        with torch.autocast(device_type=dev, dtype=torch.float16, enabled=fp16 and dev == "cuda"):
            c, s, u = model(b["input_ids"].to(dev), b["attention_mask"].to(dev))
        outs["category"].append(c.float().cpu().numpy())
        outs["secondary"].append(s.float().cpu().numpy())
        outs["urgency"].append(u.float().cpu().numpy())
    return {k: np.concatenate(v) for k, v in outs.items()}


def evaluate(model, loader, df, decode_cfg=None, fp16=False):
    logits = predict_logits(model, loader, fp16=fp16)
    decoded = decode_arrays(logits["category"], logits["secondary"], logits["urgency"], decode_cfg)
    return compute_metrics(df, decoded), logits, decoded


def _save_resume_state(path: Path, model, optimizer, scheduler, scaler, epoch, best, history):
    tmp = path.with_suffix(".tmp")
    torch.save(
        {
            "model": model.state_dict(),
            "optimizer": optimizer.state_dict(),
            "scheduler": scheduler.state_dict(),
            "scaler": scaler.state_dict(),
            "epoch": epoch,
            "best": best,
            "history": history,
            "rng_cpu": torch.get_rng_state(),
        },
        tmp,
    )
    os.replace(tmp, path)  # atomic: a Colab disconnect mid-write never corrupts last.pt


def train_model(cfg: TrainConfig, splits: dict, ckpt_root: Path, resume: bool = True) -> dict:
    """Fine-tune one backbone. Selects the best epoch on **dev** (category macro-F1), saves
    `<ckpt_root>/<model_key>/best/` and a resumable `last.pt` after every epoch, then scores
    the best checkpoint once on the held-out validation set."""
    set_seed(cfg.seed)
    dev = device()
    out_dir = Path(ckpt_root) / cfg.model_key
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "train_config.json").write_text(json.dumps(asdict(cfg), indent=2))

    model, tok = build_model(cfg.model_key, cfg.dropout)
    model.to(dev)
    pad = tok.pad_token_id
    ds = {s: TicketDataset(tok, splits[s], cfg.max_length) for s in ("train", "dev", "val")}
    train_dl = make_loader(ds["train"], cfg.batch_size, pad, shuffle=True, seed=cfg.seed)
    dev_dl = make_loader(ds["dev"], cfg.eval_batch_size, pad, shuffle=False)
    val_dl = make_loader(ds["val"], cfg.eval_batch_size, pad, shuffle=False)

    no_decay = ("bias", "LayerNorm.weight", "layer_norm.weight")
    params = [
        {"params": [p for n, p in model.named_parameters() if not any(k in n for k in no_decay)], "weight_decay": cfg.weight_decay},
        {"params": [p for n, p in model.named_parameters() if any(k in n for k in no_decay)], "weight_decay": 0.0},
    ]
    optimizer = torch.optim.AdamW(params, lr=cfg.learning_rate)
    total_steps = len(train_dl) * cfg.epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, int(cfg.warmup_ratio * total_steps), total_steps)
    use_amp = cfg.fp16 and dev == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    ce = nn.CrossEntropyLoss()
    w_cat, w_sec, w_urg = cfg.loss_weights

    start_epoch, best, history = 0, {"score": -1.0, "epoch": None}, []
    last_path = out_dir / "last.pt"
    if resume and last_path.exists():
        st = torch.load(last_path, map_location=dev, weights_only=False)
        model.load_state_dict(st["model"])
        optimizer.load_state_dict(st["optimizer"])
        scheduler.load_state_dict(st["scheduler"])
        scaler.load_state_dict(st["scaler"])
        start_epoch, best, history = st["epoch"] + 1, st["best"], st["history"]
        print(f"Resumed from epoch {st['epoch'] + 1}/{cfg.epochs} (best so far: {best})")

    for epoch in range(start_epoch, cfg.epochs):
        # Re-seed per epoch so a resumed run sees the same shuffling as an uninterrupted one.
        train_dl.generator.manual_seed(cfg.seed + epoch)
        model.train()
        t0, run_loss = time.time(), 0.0
        for step, b in enumerate(train_dl):
            b = {k: v.to(dev) for k, v in b.items()}
            with torch.autocast(device_type=dev, dtype=torch.float16, enabled=use_amp):
                c, s, u = model(b["input_ids"], b["attention_mask"])
            loss = (
                w_cat * ce(c.float(), b["category_label"])
                + w_sec * ce(s.float(), b["secondary_label"])
                + w_urg * ce(u.float(), b["urgency_label"])
            )
            optimizer.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.grad_clip)
            scaler.step(optimizer)
            scaler.update()
            scheduler.step()
            run_loss += loss.item()
            if (step + 1) % 50 == 0:
                print(f"  epoch {epoch + 1} step {step + 1}/{len(train_dl)} loss {run_loss / (step + 1):.4f}")

        dev_m, _, _ = evaluate(model, dev_dl, splits["dev"], fp16=use_amp)
        rec = {"epoch": epoch + 1, "train_loss": run_loss / len(train_dl), "secs": round(time.time() - t0, 1),
               **{f"dev_{k}": v for k, v in dev_m.items()}}
        history.append(rec)
        print(
            f"epoch {epoch + 1}: loss {rec['train_loss']:.4f} | dev cat acc {dev_m['category_acc']:.4f} "
            f"macroF1 {dev_m['category_macro_f1']:.4f} | sec F1 {dev_m['secondary_f1']:.4f} | "
            f"urg F1 {dev_m['urgency_f1']:.4f} | {rec['secs']}s"
        )
        if dev_m["category_macro_f1"] > best["score"]:
            best = {"score": dev_m["category_macro_f1"], "epoch": epoch + 1}
            save_checkpoint_dir(out_dir / "best", model, tok, cfg.model_key, cfg.max_length,
                                extra={"best_epoch": epoch + 1, "dev_metrics": dev_m})
            print(f"  -> new best, saved to {out_dir / 'best'}")
        _save_resume_state(last_path, model, optimizer, scheduler, scaler, epoch, best, history)

    # Final scoring of the best checkpoint (dev logits are kept for calibration in notebook 04).
    state = torch.load(out_dir / "best" / "model.pt", map_location=dev)
    model.load_state_dict(state)
    dev_m, dev_logits, _ = evaluate(model, dev_dl, splits["dev"])
    val_m, val_logits, val_dec = evaluate(model, val_dl, splits["val"])
    np.savez(out_dir / "best" / "logits.npz",
             **{f"dev_{k}": v for k, v in dev_logits.items()}, **{f"val_{k}": v for k, v in val_logits.items()})
    del optimizer, scheduler
    return {"history": history, "best": best, "dev": dev_m, "val": val_m, "val_decoded": val_dec,
            "model": model, "tokenizer": tok, "out_dir": out_dir}


# ---------------------------------------------------------------- calibration / thresholds

def fit_temperature(logits: np.ndarray, labels: np.ndarray) -> float:
    """Temperature scaling (Guo et al. 2017) fitted by NLL on dev."""
    lg = torch.tensor(logits, dtype=torch.float64)
    y = torch.tensor(labels, dtype=torch.long)
    log_t = torch.zeros(1, dtype=torch.float64, requires_grad=True)
    opt = torch.optim.LBFGS([log_t], lr=0.1, max_iter=200)

    def closure():
        opt.zero_grad()
        loss = nn.functional.cross_entropy(lg / log_t.exp(), y)
        loss.backward()
        return loss

    opt.step(closure)
    return float(log_t.exp().item())


def tune_threshold(scores: np.ndarray, positives: np.ndarray, grid=None) -> tuple[float, float]:
    """Pick the threshold maximising binary F1 of (scores >= t) vs positives."""
    from sklearn.metrics import f1_score

    grid = np.round(np.arange(0.05, 0.951, 0.025), 3) if grid is None else grid
    best_t, best_f = 0.5, -1.0
    for t in grid:
        f = f1_score(positives, scores >= t, zero_division=0)
        if f > best_f + 1e-9:
            best_t, best_f = float(t), float(f)
    return best_t, best_f


def risk_coverage(confidence: np.ndarray, correct: np.ndarray, thresholds=None):
    import pandas as pd

    thresholds = np.round(np.arange(0.3, 0.991, 0.05), 2) if thresholds is None else thresholds
    rows = []
    for t in thresholds:
        keep = confidence >= t
        rows.append({"threshold": float(t), "coverage": float(keep.mean()),
                     "auto_routed_acc": float(correct[keep].mean()) if keep.any() else math.nan,
                     "review_rate": float(1 - keep.mean())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- latency

def percentile_ms(times_s):
    a = np.asarray(times_s) * 1000
    return {"p50_ms": float(np.percentile(a, 50)), "p95_ms": float(np.percentile(a, 95)),
            "p99_ms": float(np.percentile(a, 99)), "mean_ms": float(a.mean())}


@torch.no_grad()
def benchmark_torch_cpu(model, tokenizer, df, max_length, n_single=100, batch_size=100, n_threads=2, seed=0):
    """Simulate the 2-vCPU deployment box: single-ticket latency (tokenize + forward) and
    one 100-ticket batch, PyTorch fp32 on CPU."""
    from .data import tokenize_frame

    torch.set_num_threads(n_threads)
    model = model.to("cpu").eval()
    sample = df.sample(n=min(n_single, len(df)), random_state=seed)
    collate = make_collate(tokenizer.pad_token_id)

    def run(frame):
        enc = tokenize_frame(tokenizer, frame, max_length)
        items = [{"input_ids": i, "attention_mask": m} for i, m in zip(enc["input_ids"], enc["attention_mask"])]
        b = collate(items)
        return model(b["input_ids"], b["attention_mask"])

    run(sample.iloc[:1])  # warm-up
    times = []
    for i in range(len(sample)):
        t = time.perf_counter()
        run(sample.iloc[i : i + 1])
        times.append(time.perf_counter() - t)
    batch = df.sample(n=min(batch_size, len(df)), random_state=seed + 1)
    t = time.perf_counter()
    for i in range(0, len(batch), 16):
        run(batch.iloc[i : i + 16])
    batch_s = time.perf_counter() - t
    return {**percentile_ms(times), "batch100_s": batch_s}


def dir_size_mb(path: Path) -> float:
    path = Path(path)
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    return sum(p.stat().st_size for p in files) / 2**20
