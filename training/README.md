# TensorForge 2.0: Model Training

Implementation of the team's model training plan, including its review and amendments (v1.1, v1.1b and v1.2
are described in the notebook headers and below). It fine-tunes a multilingual encoder with three heads
(category / secondary / urgency), compares it against challengers, calibrates the winner and exports it
to ONNX for the CPU-only API container.

## Layout

```
training/
├── notebooks/
│   ├── 01_eda_preprocessing.ipynb     EDA, token lengths → max_length, train/dev/val splits      (CPU ok)
│   ├── 02_baseline_xlmr.ipynb         XLM-RoBERTa-base, 3 heads                                  (T4 GPU)
│   ├── 03_challengers.ipynb           MiniLM, multilingual-e5-small, TF-IDF + LogReg             (T4 GPU)
│   ├── 04_comparison_export.ipynb     compare, latency, winner, ONNX, INT8, calibration, export  (CPU runtime)
│   └── 05_fp16_compression.ipynb      FP16-storage compression of the winner + score check     (CPU runtime)
├── src/tfml/                          shared library used by all notebooks
│   ├── labels.py      label spaces, category → team table
│   ├── textproc.py    clean_text, prepare_input (shared by training + inference)
│   ├── data.py        loading, dev split, tokenization, Dataset/collate
│   ├── modeling.py    MultiHeadClassifier, MODEL_SPECS, checkpoint save/load
│   ├── engine.py      train loop (fp16, resumable), predict, temperature/threshold tuning, CPU benchmark
│   ├── rules.py       logits → API-shaped predictions + business rules (numpy only)
│   ├── metrics.py     category/secondary/urgency metrics, per-language, ECE, selection score
│   ├── export.py      ONNX export, INT8 quantization, packaging of models/winner/
│   ├── compress.py    FP16-storage compression (float16 weights, float32 compute)
│   └── onnx_runtime.py  torch-free OnnxTicketClassifier (copied into models/winner/tfml_runtime/)
├── data/processed/    train/dev/val jsonl (written by NB01)
├── checkpoints/       <model>/best/ + resumable last.pt   (git-ignored, large)
├── models/winner/     final packaged model                (commit with Git LFS)
├── results/           metrics json/csv, figures
├── requirements-colab.txt   extras on top of the Colab image
└── requirements.txt         full env for running outside Colab
```

## Running on Google Colab

1. Upload this `training/` folder to Google Drive as **`MyDrive/TensorForge/training/`**, so that
   `MyDrive/TensorForge/training/src/tfml/` and `MyDrive/TensorForge/training/notebooks/` exist.
2. Copy the competition dataset files (`train.jsonl`, `validation.jsonl` from the organizers' resource pack) into
   **`MyDrive/TensorForge/training/data/`**. The dataset is not stored in this repository.
3. Open the notebooks from Drive in Colab and run them **in order**:

| Notebook | Runtime | Approx. time on T4 |
|---|---|---|
| 01 | CPU (or GPU) | ~3 min |
| 02 | **T4 GPU** | ~15–30 min (5 epochs) |
| 03 | **T4 GPU** | ~15–25 min (two small models + TF-IDF) |
| 04 | **CPU** (matches the deployment box) | ~15–45 min |
| 05 | CPU | ~5–10 min |

The first cell of each notebook mounts Drive, installs `requirements-colab.txt` and imports `src/tfml`.
torch and transformers come from the Colab image and aren't reinstalled.

**Disconnects:** NB02/NB03 write `checkpoints/<model>/last.pt` (model + optimizer + scheduler) after
every epoch. Re-running the training cell resumes from the last finished epoch. To retrain from scratch,
delete `checkpoints/<model>/`.

## Running locally

```bash
cd training
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd notebooks && jupyter lab
```

Locally, put `train.jsonl` and `validation.jsonl` from the organizers' resource pack into `training/data/`. The dataset
is not stored in this repository.

## Notebook 05: FP16-storage compression (v1.2)

NB04 v1.1 picked **xlmr-base**. INT8 lost 10.3 pt of val macro-F1, so it shipped **FP32 (1.06 GB)**. NB05 stores
the float32 weights as float16 and adds a `Cast` back to float32. ONNX Runtime folds the casts at load time, so inference
still runs in float32 and the file is ~2× smaller. NB05 runs both models on the same val_cal/val_test split as NB04 and
replaces `models/winner/model.onnx` **only if** category agreement ≥ 99.5% and every |Δ| (macro-F1, secondary F1,
urgency F1, ECE) ≤ 0.005. The untouched FP32 export stays in `models/staging/winner_fp32.onnx`, and
`inference_config.json → compression` records its version and hash. Version becomes `v1.2-<sha256[:12]>`.

## Key design decisions

- **Inputs:** `channel`, `subject` and `text` only, because the API never sends `language`.
  Input = sentence pair `(channel </s> subject, text)`, truncating only the body.
- **Splits:** 10% of train → **dev** (stratified category × language) for epoch selection, thresholds
  and calibration. The official **validation** set is a held-out test, scored once per model.
- **Loss:** `CE_cat + 0.5·CE_sec + 0.3·CE_urg`. The secondary head has 12 classes (11 + `none`).
- **Decoding** (`rules.decode_arrays`): the primary is masked out of the secondary head, then spam →
  not urgent, no secondary, and team comes from the fixed table. Thresholds come from `inference_config.json`.
- **Winner score (dev):** `0.5·F1_cat(macro) + 0.25·F1_sec + 0.25·F1_urg`. Latency/size are gates.
- **Calibration:** temperature scaling on dev. `needs_human_review = confidence < τ`, where τ is the smallest
  threshold whose auto-routed dev accuracy is ≥ 97%.

## Output contract for the API phase

`models/winner/`:

| File | Purpose |
|---|---|
| `model.onnx` | Three-output graph: `category_logits`, `secondary_logits`, `urgency_logits`. NB04 ships INT8, or FP32 if INT8 lost > 1 pt. NB05 then stores FP32 weights as FP16 (computed in FP32) if no score drops |
| `tokenizer/` | tokenizer files (offline) |
| `inference_config.json` | `max_length`, decode thresholds, `model_version` (`v1.0-<sha256[:12]>`) |
| `labels.json` | label orders + team map |
| `metrics.json` | final validation metrics, per-language results, latency, success criteria |
| `tfml_runtime/` | torch-free runtime |

```python
import sys; sys.path.insert(0, "models/winner")
from tfml_runtime.onnx_runtime import OnnxTicketClassifier
clf = OnnxTicketClassifier("models/winner", n_threads=2)
clf.predict([{"ticket_id": "T1", "channel": "chat", "subject": "", "text": "My food never arrived"}])
# -> [{"ticket_id": "T1", "category": ..., "secondary_category": ..., "is_urgent": ..., "confidence": ...,
#      "needs_human_review": ..., "team": ..., "model_version": "v1.0-..."}]
```

Runtime dependencies: `numpy`, `onnxruntime`, `transformers` (tokenizer only), `sentencepiece`.
`model.onnx` is larger than GitHub's 100 MB limit, so track it with Git LFS (`git lfs track "*.onnx"`).
