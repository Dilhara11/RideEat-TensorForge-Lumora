"""The engine's decoder must match the training decoder (`training/src/tfml/rules.py`) bit for bit."""

import sys

import numpy as np
import pytest

from conftest import REPO_ROOT
from tfengine.inference import DecodeConfig, LabelSpace, PredictionDecoder

TFML_SRC = REPO_ROOT / "training" / "src"


@pytest.fixture(scope="module")
def tfml_rules():
    if not (TFML_SRC / "tfml" / "rules.py").is_file():
        pytest.skip("training/src/tfml not available")
    sys.path.insert(0, str(TFML_SRC))
    from tfml import labels, rules  # numpy-only modules
    return rules, labels


@pytest.mark.parametrize("cfg", [
    {},
    {"temperature": 0.405, "urgency_threshold": 0.15, "secondary_threshold": 0.15, "review_threshold": 0.3},
    {"temperature": 2.0, "urgency_threshold": 0.9, "secondary_threshold": None, "review_threshold": 0.8},
])
def test_decode_matches_training(tfml_rules, cfg):
    rules, labels = tfml_rules
    rng = np.random.default_rng(0)
    cat, sec, urg = rng.normal(size=(500, 11)) * 3, rng.normal(size=(500, 12)) * 3, rng.normal(size=(500, 2)) * 2
    cat[:50, labels.SPAM_IDX] += 10  # make sure the spam branch is hit

    ref = rules.to_records(rules.decode_arrays(cat, sec, urg, cfg), [f"T{i}" for i in range(500)])
    ours = PredictionDecoder(LabelSpace.contract_default(), DecodeConfig.from_dict(cfg)).decode(
        cat, sec, urg, [f"T{i}" for i in range(500)], "v")
    for r, o in zip(ref, ours):
        o = {k: v for k, v in o.items() if k != "model_version"}
        assert r == o
    assert not rules.check_consistency(ours)


def test_label_order_matches_training(tfml_rules):
    _, labels = tfml_rules
    ls = LabelSpace.contract_default()
    assert list(ls.categories) == labels.CATEGORIES
    assert list(ls.secondary) == labels.SECONDARY_LABELS
    assert labels.CATEGORY_TEAM_MAP == {c: ls.team(c) for c in ls.categories}
