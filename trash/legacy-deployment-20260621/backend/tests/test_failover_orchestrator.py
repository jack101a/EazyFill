import importlib.util
import subprocess
import sys
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "failover_orchestrator.py"
_SPEC = importlib.util.spec_from_file_location("failover_orchestrator", _SCRIPT_PATH)
failover_orchestrator = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules["failover_orchestrator"] = failover_orchestrator
_SPEC.loader.exec_module(failover_orchestrator)


class FakeRedisClient:
    def __init__(self, role="master"):
        self.commands = []
        self.role = role

    def execute_command(self, *args):
        self.commands.append(args)

    def info(self, section):
        assert section == "replication"
        return {"role": self.role}


def test_promote_redis_writes_marker_and_promotes(monkeypatch, tmp_path):
    fake_client = FakeRedisClient()

    class FakeRedisModule:
        class Redis:
            @staticmethod
            def from_url(*_args, **_kwargs):
                return fake_client

    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule)
    monkeypatch.setenv("EMERGENCY_REDIS_PASSWORD", "secret")
    marker = tmp_path / "redis" / "SA_HELPER_REDIS_PROMOTED"
    monkeypatch.setenv("EMERGENCY_REDIS_PROMOTED_MARKER", str(marker))

    result = failover_orchestrator.promote_redis()

    assert result.ok is True
    assert marker.exists()
    assert fake_client.commands == [("REPLICAOF", "NO", "ONE")]


def test_promote_redis_does_not_write_marker_when_role_stays_replica(monkeypatch, tmp_path):
    fake_client = FakeRedisClient(role="slave")

    class FakeRedisModule:
        class Redis:
            @staticmethod
            def from_url(*_args, **_kwargs):
                return fake_client

    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule)
    monkeypatch.setenv("EMERGENCY_REDIS_PASSWORD", "secret")
    marker = tmp_path / "redis" / "SA_HELPER_REDIS_PROMOTED"
    monkeypatch.setenv("EMERGENCY_REDIS_PROMOTED_MARKER", str(marker))

    result = failover_orchestrator.promote_redis()

    assert result.ok is False
    assert not marker.exists()
    assert fake_client.commands == [("REPLICAOF", "NO", "ONE")]


def test_run_cloudflare_uses_fixed_dns_switch_script(monkeypatch, tmp_path):
    calls = []
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "cloudflare_dns_switch.py").write_text("placeholder", encoding="utf-8")
    monkeypatch.setenv("FAILOVER_BOT_REPO_DIR", str(repo))

    def fake_runner(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="switched", stderr="")

    result = failover_orchestrator.run_cloudflare("failover", runner=fake_runner)

    assert result.ok is True
    assert calls[0][0][1] == str(scripts / "cloudflare_dns_switch.py")
    assert calls[0][0][2] == "failover"
