"""Text cleaning + tokenization, identical to training (`training/src/tfml/textproc.py`).

Uses the Rust `tokenizers` library directly (no `transformers`) to keep the image small. The
model input is the sentence pair (header, body):

    header = f"{channel} {sep} {subject}"  (or just channel when subject is empty)
    body   = text

and only the body is truncated (`only_second`), so the channel/subject are never cut.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path

import numpy as np
from tokenizers import Tokenizer

log = logging.getLogger("tfengine.preprocessing")


class TextPreprocessor:
    """NFC-normalise (keeps Sinhala/Tamil combining marks) and collapse whitespace runs.

    Example:
        TextPreprocessor.clean("  bro\\n\\n order  eka late ")  -> "bro order eka late"
        TextPreprocessor.clean(None)                             -> ""
        TextPreprocessor.build_pair("email", "Re: Order #4", "Late!", "</s>")
          -> ("email </s> Re: Order #4", "Late!")
        TextPreprocessor.build_pair("chat", "", "hi", "</s>")     -> ("chat", "hi")
    """

    _WS = re.compile(r"\s+")

    @classmethod
    def clean(cls, s) -> str:
        if s is None:
            return ""
        return cls._WS.sub(" ", unicodedata.normalize("NFC", str(s))).strip()

    @staticmethod
    def build_pair(channel: str, subject: str, text: str, sep: str) -> tuple[str, str]:
        header = f"{channel} {sep} {subject}" if subject else channel
        return header, text


class TicketEncoder:
    """Turns one ticket into ONNX inputs (`input_ids`, `attention_mask`, int64, shape [1, seq]).

    Example:
        enc = TicketEncoder(Path("models/winner/tokenizer"), max_length=192)
        ids, mask = enc.encode("chat", "", "my food never arrived")
        ids.shape -> (1, n) with n <= 192
    """

    def __init__(self, tokenizer_dir: Path, max_length: int):
        tokenizer_dir = Path(tokenizer_dir)
        self.max_length = max_length
        self.sep = self._read_sep_token(tokenizer_dir)

        # Primary tokenizer: truncate only the ticket body (training behaviour).
        self._primary = Tokenizer.from_file(str(tokenizer_dir / "tokenizer.json"))
        self._primary.no_padding()
        self._primary.enable_truncation(max_length=max_length, strategy="only_second")

        # Fallback: a long subject (valid up to 500 chars) can make the header alone longer than
        # max_length; `only_second` then raises. `longest_first` always fits, so a valid request
        # never turns into a 5xx. Example: 500-char Sinhala subject -> fallback path.
        self._fallback = Tokenizer.from_str(self._primary.to_str())
        self._fallback.no_padding()
        self._fallback.enable_truncation(max_length=max_length, strategy="longest_first")

    @staticmethod
    def _read_sep_token(tokenizer_dir: Path) -> str:
        # Example: tokenizer_config.json {"sep_token": "</s>"} -> "</s>" (XLM-R / E5 vocabularies)
        cfg_path = tokenizer_dir / "tokenizer_config.json"
        if cfg_path.is_file():
            sep = json.loads(cfg_path.read_text(encoding="utf-8")).get("sep_token")
            if isinstance(sep, dict):  # serialized AddedToken
                sep = sep.get("content")
            if sep:
                return sep
        return "</s>"

    def encode(self, channel: str, subject: str, text: str) -> tuple[np.ndarray, np.ndarray]:
        header, body = TextPreprocessor.build_pair(
            TextPreprocessor.clean(channel), TextPreprocessor.clean(subject), TextPreprocessor.clean(text), self.sep
        )
        try:
            enc = self._primary.encode(header, body)
        except Exception:  # tokenizers raises a plain Exception for impossible truncation
            log.debug("only_second truncation impossible (long header); using longest_first")
            enc = self._fallback.encode(header, body)
        ids = np.asarray([enc.ids], dtype=np.int64)
        mask = np.asarray([enc.attention_mask], dtype=np.int64)
        return ids, mask
