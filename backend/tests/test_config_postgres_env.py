from pathlib import Path

from app.core.config import _config_path_from_env, _postgres_url_from_env


def test_postgres_url_from_env_url_encodes_credentials(monkeypatch):
    monkeypatch.setenv("POSTGRES_HOST", "postgres")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("POSTGRES_DB", "sa helper")
    monkeypatch.setenv("POSTGRES_USER", "sa/helper")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss:word/with#chars")

    assert _postgres_url_from_env() == (
        "postgresql://sa%2Fhelper:p%40ss%3Aword%2Fwith%23chars@postgres:5432/sa%20helper"
    )


def test_app_config_path_does_not_treat_host_config_path_as_yaml(monkeypatch, tmp_path):
    host_config_root = tmp_path / "host-config"
    host_config_root.mkdir()
    monkeypatch.setenv("CONFIG_PATH", str(host_config_root))
    monkeypatch.delenv("APP_CONFIG_PATH", raising=False)

    assert _config_path_from_env(tmp_path) == (tmp_path / "backend" / "config" / "config.yaml").resolve()


def test_app_config_path_accepts_explicit_yaml_path(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIG_PATH", "/srv/ajaxhs/config")
    monkeypatch.setenv("APP_CONFIG_PATH", "/app/backend/config/config.yaml")

    assert _config_path_from_env(tmp_path) == Path("/app/backend/config/config.yaml")


def test_legacy_config_path_file_still_supported(monkeypatch, tmp_path):
    monkeypatch.delenv("APP_CONFIG_PATH", raising=False)
    monkeypatch.setenv("CONFIG_PATH", "custom/config.yml")

    assert _config_path_from_env(tmp_path) == (tmp_path / "custom" / "config.yml").resolve()
