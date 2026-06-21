import importlib.util
import sys
from pathlib import Path

import pytest


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "cloudflare_dns_switch.py"
_SPEC = importlib.util.spec_from_file_location("cloudflare_dns_switch", _SCRIPT_PATH)
cloudflare_dns_switch = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
sys.modules["cloudflare_dns_switch"] = cloudflare_dns_switch
_SPEC.loader.exec_module(cloudflare_dns_switch)


def _set_base_env(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "token")
    monkeypatch.setenv("CLOUDFLARE_ZONE_ID", "zone")
    monkeypatch.setenv("CLOUDFLARE_DNS_NAME", "api.example.com")
    monkeypatch.setenv("CLOUDFLARE_NORMAL_DNS_TYPE", "A")
    monkeypatch.setenv("CLOUDFLARE_NORMAL_DNS_CONTENT", "203.0.113.10")
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_DNS_TYPE", "CNAME")
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_DNS_CONTENT", "tunnel.cfargotunnel.com")


def test_desired_failover_record_uses_tunnel_cname(monkeypatch):
    _set_base_env(monkeypatch)

    desired = cloudflare_dns_switch._desired("failover")

    assert desired.record_type == "CNAME"
    assert desired.name == "api.example.com"
    assert desired.content == "tunnel.cfargotunnel.com"
    assert desired.proxied is True


def test_apply_refuses_multiple_records_without_delete_opt_in(monkeypatch):
    _set_base_env(monkeypatch)
    monkeypatch.setenv("CLOUDFLARE_ALLOW_DELETE_CONFLICTS", "false")
    monkeypatch.setattr(
        cloudflare_dns_switch,
        "_list_records",
        lambda _name: [
            {"id": "one", "type": "A", "content": "203.0.113.10", "proxied": True, "ttl": 1},
            {"id": "two", "type": "A", "content": "203.0.113.11", "proxied": True, "ttl": 1},
        ],
    )

    with pytest.raises(cloudflare_dns_switch.ConfigError):
        cloudflare_dns_switch._apply(cloudflare_dns_switch._desired("failover"))


def test_apply_noops_when_record_already_matches(monkeypatch):
    _set_base_env(monkeypatch)
    calls = []
    monkeypatch.setattr(
        cloudflare_dns_switch,
        "_list_records",
        lambda _name: [
            {"id": "one", "type": "CNAME", "content": "tunnel.cfargotunnel.com", "proxied": True, "ttl": 1},
        ],
    )
    monkeypatch.setattr(cloudflare_dns_switch, "_update_record", lambda *_args, **_kwargs: calls.append("update"))
    monkeypatch.setattr(cloudflare_dns_switch, "_create_record", lambda *_args, **_kwargs: calls.append("create"))

    cloudflare_dns_switch._apply(cloudflare_dns_switch._desired("failover"))

    assert calls == []
