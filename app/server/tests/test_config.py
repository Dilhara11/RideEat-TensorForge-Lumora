"""Settings must load both from a repo checkout and from the shallow Docker layout (/app/tfengine)."""

from pathlib import Path

from tfengine.config import Settings, repo_root


def test_repo_root_in_checkout():
    assert repo_root(Path("/home/me/TensorForge/app/server/tfengine/config.py")) == Path("/home/me/TensorForge")


def test_repo_root_in_docker_image():
    # Regression: parents[3] raised IndexError here and the container crashed on startup.
    assert repo_root(Path("/app/tfengine/config.py")) == Path("/app")


def test_settings_from_env_docker_style(monkeypatch):
    monkeypatch.setenv("API_KEY", "secret-key-xyz")
    monkeypatch.setenv("MODEL_DIR", "/app/model")
    monkeypatch.setenv("DATA_DIR", "/app/data")
    monkeypatch.setenv("JOB_CHUNK_SIZE", "4")
    s = Settings.from_env()
    assert (s.model_dir, s.data_dir, s.job_chunk_size) == (Path("/app/model"), Path("/app/data"), 4)
    assert "secret-key-xyz" not in repr(s)  # the key never shows up in logs/reprs
