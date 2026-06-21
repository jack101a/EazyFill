#!/usr/bin/env python3
"""Fixed Cloudflare DNS switch for EazyFill failover.

Actions are intentionally limited to status, plan, failover, and normal so this
script can be called safely from an external automation wrapper.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


API_BASE = "https://api.cloudflare.com/client/v4"


class ConfigError(RuntimeError):
    pass


class CloudflareError(RuntimeError):
    pass


@dataclass(frozen=True)
class DesiredRecord:
    mode: str
    record_type: str
    name: str
    content: str
    proxied: bool
    ttl: int

    def payload(self) -> dict[str, Any]:
        return {
            "type": self.record_type,
            "name": self.name,
            "content": self.content,
            "ttl": self.ttl,
            "proxied": self.proxied,
            "comment": f"EazyFill {self.mode} route managed by fixed failover script",
        }


def _env(name: str, *, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default if default is not None else "")
    value = str(value or "").strip()
    if required and not value:
        raise ConfigError(f"{name} is required")
    return value


def _bool_env(name: str, *, default: bool) -> bool:
    raw = _env(name, default="true" if default else "false").lower()
    return raw in {"1", "true", "yes", "on"}


def _ttl() -> int:
    raw = _env("CLOUDFLARE_DNS_TTL", default="1")
    try:
        ttl = int(raw)
    except ValueError as exc:
        raise ConfigError("CLOUDFLARE_DNS_TTL must be an integer") from exc
    if ttl != 1 and ttl < 60:
        raise ConfigError("CLOUDFLARE_DNS_TTL must be 1 for automatic TTL or >= 60")
    return ttl


def _desired(mode: str) -> DesiredRecord:
    if mode not in {"normal", "failover"}:
        raise ConfigError("mode must be normal or failover")
    prefix = "NORMAL" if mode == "normal" else "TUNNEL"
    return DesiredRecord(
        mode=mode,
        record_type=_env(f"CLOUDFLARE_{prefix}_DNS_TYPE", required=True).upper(),
        name=_env("CLOUDFLARE_DNS_NAME", required=True),
        content=_env(f"CLOUDFLARE_{prefix}_DNS_CONTENT", required=True),
        proxied=_bool_env(f"CLOUDFLARE_{prefix}_DNS_PROXIED", default=True),
        ttl=_ttl(),
    )


def _api(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _env("CLOUDFLARE_API_TOKEN", required=True)
    body = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            error_payload = {"errors": [{"message": str(exc)}]}
        raise CloudflareError(_format_errors(error_payload)) from exc
    except urllib.error.URLError as exc:
        raise CloudflareError(str(exc)) from exc

    if not data.get("success"):
        raise CloudflareError(_format_errors(data))
    return data


def _format_errors(payload: dict[str, Any]) -> str:
    errors = payload.get("errors") or []
    if not errors:
        return "Cloudflare API request failed"
    messages = []
    for item in errors:
        code = item.get("code")
        message = item.get("message") or item
        messages.append(f"{code}: {message}" if code else str(message))
    return "; ".join(messages)


def _zone_id() -> str:
    return _env("CLOUDFLARE_ZONE_ID", required=True)


def _list_records(name: str) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode({"name": name, "per_page": "100"})
    data = _api("GET", f"/zones/{_zone_id()}/dns_records?{query}")
    return list(data.get("result") or [])


def _record_summary(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record.get("id"),
        "type": record.get("type"),
        "name": record.get("name"),
        "content": record.get("content"),
        "proxied": record.get("proxied"),
        "ttl": record.get("ttl"),
    }


def _print_records(records: list[dict[str, Any]]) -> None:
    if not records:
        print("No DNS record found for configured name.")
        return
    for record in records:
        summary = _record_summary(record)
        print(
            f"{summary['type']} {summary['name']} -> {summary['content']} "
            f"proxied={summary['proxied']} ttl={summary['ttl']} id={summary['id']}"
        )


def _delete_record(record_id: str) -> None:
    _api("DELETE", f"/zones/{_zone_id()}/dns_records/{record_id}")


def _create_record(desired: DesiredRecord) -> dict[str, Any]:
    data = _api("POST", f"/zones/{_zone_id()}/dns_records", desired.payload())
    return dict(data.get("result") or {})


def _update_record(record_id: str, desired: DesiredRecord) -> dict[str, Any]:
    data = _api("PUT", f"/zones/{_zone_id()}/dns_records/{record_id}", desired.payload())
    return dict(data.get("result") or {})


def _matching(record: dict[str, Any], desired: DesiredRecord) -> bool:
    return (
        str(record.get("type") or "").upper() == desired.record_type
        and str(record.get("content") or "") == desired.content
        and bool(record.get("proxied")) == desired.proxied
    )


def _apply(desired: DesiredRecord, *, dry_run: bool = False) -> None:
    records = _list_records(desired.name)
    print(f"Current records for {desired.name}:")
    _print_records(records)
    print(
        f"Desired {desired.mode}: {desired.record_type} {desired.name} -> "
        f"{desired.content} proxied={desired.proxied} ttl={desired.ttl}"
    )

    if dry_run:
        print("Dry run only; no Cloudflare changes made.")
        return

    allow_delete = _bool_env("CLOUDFLARE_ALLOW_DELETE_CONFLICTS", default=False)
    recreate_on_failure = _bool_env("CLOUDFLARE_RECREATE_ON_UPDATE_FAILURE", default=False)

    if len(records) == 0:
        result = _create_record(desired)
        print(f"Created DNS record id={result.get('id')}")
        return

    if len(records) > 1:
        if not allow_delete:
            raise ConfigError(
                "Multiple DNS records exist for this name. Refusing to change them. "
                "Set CLOUDFLARE_ALLOW_DELETE_CONFLICTS=true only after verifying this hostname."
            )
        for record in records:
            _delete_record(str(record["id"]))
        result = _create_record(desired)
        print(f"Deleted {len(records)} conflicting records and created id={result.get('id')}")
        return

    current = records[0]
    if _matching(current, desired):
        print(f"Already in {desired.mode} mode; no change needed.")
        return

    try:
        result = _update_record(str(current["id"]), desired)
        print(f"Updated DNS record id={result.get('id')}")
    except CloudflareError:
        if not recreate_on_failure:
            raise
        _delete_record(str(current["id"]))
        result = _create_record(desired)
        print(f"Recreated DNS record id={result.get('id')}")


def _plan(mode: str) -> None:
    desired = _desired(mode)
    print(
        f"Would set {desired.name} to {desired.record_type} {desired.content} "
        f"proxied={desired.proxied} ttl={desired.ttl}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="EazyFill Cloudflare DNS failover switch")
    parser.add_argument("action", choices=["status", "plan", "failover", "normal"])
    parser.add_argument("--dry-run", action="store_true", help="show current/desired state without changing DNS")
    args = parser.parse_args(argv)

    try:
        if args.action == "status":
            _print_records(_list_records(_env("CLOUDFLARE_DNS_NAME", required=True)))
            return 0
        if args.action == "plan":
            _plan("failover")
            _plan("normal")
            return 0
        mode = "failover" if args.action == "failover" else "normal"
        _apply(_desired(mode), dry_run=args.dry_run)
        return 0
    except (ConfigError, CloudflareError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
