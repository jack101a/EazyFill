from app.core.sqlite import DEFAULT_SQLITE_BUSY_TIMEOUT_MS, sqlite_busy_timeout_ms, sqlite_connect


def test_sqlite_busy_timeout_uses_safe_default_for_invalid_env(monkeypatch):
    monkeypatch.setenv("SQLITE_BUSY_TIMEOUT_MS", "not-a-number")

    assert sqlite_busy_timeout_ms() == DEFAULT_SQLITE_BUSY_TIMEOUT_MS


def test_sqlite_connect_applies_busy_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv("SQLITE_BUSY_TIMEOUT_MS", "2500")

    with sqlite_connect(tmp_path / "app.db") as conn:
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")

    assert busy_timeout == 2500
