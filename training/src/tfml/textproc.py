"""Text preprocessing shared by training and inference (no torch dependency)."""

import re
import unicodedata

_WS = re.compile(r"\s+")


def clean_text(s) -> str:
    """NFC-normalise (keeps Sinhala/Tamil combining marks) and collapse whitespace runs.

    No lowercasing, punctuation stripping or emoji removal: the tokenizer is cased,
    and noise is part of what the model must learn to handle.
    """
    if s is None or (isinstance(s, float) and s != s):
        return ""
    s = unicodedata.normalize("NFC", str(s))
    return _WS.sub(" ", s).strip()


def prepare_input(channel: str, subject: str, text: str, sep: str) -> tuple[str, str]:
    """Build the (header, body) pair fed to the encoder.

    The plan's `f"{channel} [SEP] {subject} [SEP] {text}"` is implemented as a sentence
    pair so the model's *real* separator token is used (`</s>` for XLM-R vocabularies)
    and truncation only ever cuts the body (`truncation="only_second"`), never the header.
    """
    header = f"{channel} {sep} {subject}" if subject else channel
    return header, text
