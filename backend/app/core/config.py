"""Configuration loader for the EazyFill backend."""

from __future__ import annotations

import os
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator, model_validator
from app.core.paths import get_project_root

DEFAULT_OTP_ALLOWED_EMAIL_DOMAINS = [
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "msn.com",
    "proton.me",
    "protonmail.com",
    "pm.me",
    "rediffmail.com",
    "rediff.com",
    "yahoo.com",
    "ymail.com",
    "rocketmail.com",
    "icloud.com",
    "me.com",
    "mac.com",
    "aol.com",
    "zoho.com",
    "zohomail.com",
    "fastmail.com",
    "hey.com",
    "mail.com",
    "gmx.com",
    "gmx.net",
    "tutanota.com",
    "tuta.io",
]

DEFAULT_OTP_BLOCKED_EMAIL_DOMAINS = [
    "10minutemail.com",
    "20minutemail.com",
    "anonaddy.com",
    "dispostable.com",
    "emailondeck.com",
    "fakeinbox.com",
    "getnada.com",
    "guerrillamail.com",
    "grr.la",
    "maildrop.cc",
    "mailinator.com",
    "mintemail.com",
    "moakt.com",
    "mytemp.email",
    "sharklasers.com",
    "temp-mail.org",
    "tempmail.com",
    "throwawaymail.com",
    "trashmail.com",
    "yopmail.com",
]

_DEFAULT_CONFIG: dict[str, Any] = {
    "app_name": "eazyfill",
    "server": {
        "host": "0.0.0.0",
        "port": 8080,
        "debug": False,
        "cors_origins": ["moz-extension://*", "chrome-extension://*"],
        "cors_origin_regex": "^(moz-extension|chrome-extension)://.*$",
    },
    "auth": {
        "key_prefix": "fp_",
        "key_length": 32,
        "default_expiry_days": 90,
        "hash_salt": "",
        "admin_token": "",
        "admin_username": "admin",
        "admin_password": "",
    },
    "rate_limit": {"requests_per_minute": 60, "burst": 10},
    "queue": {"workers": 4, "max_pending_jobs": 500, "cache_ttl_seconds": 300},
    "logging": {"level": "INFO", "debug": False, "json": True},
    "model": {
        "default": "onnx",
        "fallback": "onnx",
        "allow_future_model": False,
        "onnx_path": "data/models/model.onnx",
        "onnx_vocab": "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "onnx_height": 54,
        "onnx_width": 250,
    },
    "storage": {"sqlite_path": "backend/logs/app.db", "database_url": "", "db_type": "sqlite"},
    "redis": {"enabled": False, "url": "redis://localhost:6379/0", "prefix": "up:"},
    "retrain": {"worker_enabled": False},
    # Payments
    "payment": {
        "razorpay_key_id": "",
        "razorpay_key_secret": "",
        "razorpay_webhook_secret": "",
        "razorpay_order_token": "",
    },
    # Transactional email
    "email": {
        "otp_email_enabled": False,
        "otp_email_provider": "brevo",
        "brevo_api_key": "",
        "otp_email_from": "no-reply.eazyfill@002529.xyz",
        "otp_email_from_name": "EazyFill",
        "otp_email_reply_to": "support.eazyfill@002529.xyz",
        "otp_dev_otp_enabled": False,
        "otp_allowed_email_domains": DEFAULT_OTP_ALLOWED_EMAIL_DOMAINS,
        "otp_blocked_email_domains": DEFAULT_OTP_BLOCKED_EMAIL_DOMAINS,
    },
    "plans": {
        "auto_seed_on_empty": False,
        "bootstrap_plans": [],
    },
}


class ServerConfig(BaseModel):
    host: str
    port: int
    debug: bool = False
    cors_origins: list[str] = Field(default_factory=list)
    cors_origin_regex: str | None = None


class AuthConfig(BaseModel):
    hash_salt: str
    admin_token: str
    admin_username: str = ""
    admin_password: str = ""
    key_prefix: str = "fp_"
    key_length: int = 32
    default_expiry_days: int = 90



class RateLimitConfig(BaseModel):
    requests_per_minute: int = 60
    burst: int = 10


class QueueConfig(BaseModel):
    workers: int = 4
    max_pending_jobs: int = 500
    cache_ttl_seconds: int = 300


class LoggingConfig(BaseModel):
    model_config = {"populate_by_name": True}

    level: str = "INFO"
    debug: bool = False
    # The YAML key is "json"; we expose it as json_logs in Python code.
    json_logs: bool = Field(default=True, alias="json")


class ModelConfig(BaseModel):
    default: str = "onnx"
    fallback: str = "onnx"
    allow_future_model: bool = False
    onnx_path: str = ""
    onnx_vocab: str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    onnx_height: int = 54
    onnx_width: int = 250


class StorageConfig(BaseModel):
    sqlite_path: str
    # PostgreSQL support (used when DB_TYPE=postgresql)
    database_url: str = ""
    db_type: str = "sqlite"  # "sqlite" | "postgresql"

    @field_validator("db_type")
    @classmethod
    def validate_db_type(cls, v: str) -> str:
        if v not in ("sqlite", "postgresql"):
            raise ValueError(f"db_type must be 'sqlite' or 'postgresql', got '{v}'")
        return v


class RedisConfig(BaseModel):
    enabled: bool = False
    url: str = "redis://localhost:6379/0"
    prefix: str = "up:"  # key prefix for namespacing


class RetrainConfig(BaseModel):
    worker_enabled: bool = False


class PaymentConfig(BaseModel):
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_order_token: str = ""


class EmailConfig(BaseModel):
    otp_email_enabled: bool = False
    otp_email_provider: str = "brevo"
    brevo_api_key: str = ""
    otp_email_from: str = "no-reply.eazyfill@002529.xyz"
    otp_email_from_name: str = "EazyFill"
    otp_email_reply_to: str = "support.eazyfill@002529.xyz"
    otp_dev_otp_enabled: bool = False
    otp_allowed_email_domains: list[str] = Field(default_factory=lambda: list(DEFAULT_OTP_ALLOWED_EMAIL_DOMAINS))
    otp_blocked_email_domains: list[str] = Field(default_factory=lambda: list(DEFAULT_OTP_BLOCKED_EMAIL_DOMAINS))


class PlansConfig(BaseModel):
    auto_seed_on_empty: bool = False
    bootstrap_plans: list[dict[str, Any]] = Field(default_factory=list)


class Settings(BaseModel):
    app_name: str = "eazyfill"
    app_mode: str = "normal"
    server: ServerConfig
    auth: AuthConfig
    rate_limit: RateLimitConfig
    queue: QueueConfig
    logging: LoggingConfig
    model: ModelConfig
    storage: StorageConfig
    redis: RedisConfig = Field(default_factory=RedisConfig)
    retrain: RetrainConfig = Field(default_factory=RetrainConfig)
    payment: PaymentConfig = Field(default_factory=PaymentConfig)
    email: EmailConfig = Field(default_factory=EmailConfig)
    plans: PlansConfig = Field(default_factory=PlansConfig)

    @field_validator("app_mode")
    @classmethod
    def validate_app_mode(cls, value: str) -> str:
        normalized = str(value or "normal").strip().lower()
        if normalized not in {"normal", "primary", "standby", "remote_primary_db", "failover_readonly", "recovery", "emergency"}:
            raise ValueError(
                "app_mode must be one of: normal, primary, standby, remote_primary_db, "
                "failover_readonly, recovery, emergency"
            )
        return normalized


def _read_yaml_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(yaml.safe_dump(_DEFAULT_CONFIG, sort_keys=False), encoding="utf-8")
        except Exception as exc:
            # Log to stderr rather than swallowing silently
            import sys
            print(f"WARNING: could not write default config to {config_path}: {exc}", file=sys.stderr)
        return deepcopy(_DEFAULT_CONFIG)
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _resolve_path(raw_path: str) -> Path:
    return (get_project_root() / raw_path).resolve()


def _config_path_from_env(project_root: Path) -> Path:
    raw_config = os.getenv("APP_CONFIG_PATH", "").strip()
    if not raw_config:
        legacy_config = os.getenv("CONFIG_PATH", "").strip()
        if Path(legacy_config).suffix.lower() in {".yaml", ".yml"}:
            raw_config = legacy_config
    raw_config = raw_config or "backend/config/config.yaml"
    if Path(raw_config).is_absolute() or raw_config.startswith(("/", "\\")):
        return Path(raw_config)
    return (project_root / raw_config).resolve()


def _postgres_url_from_env() -> str:
    host = os.getenv("POSTGRES_HOST", "").strip()
    if not host:
        return ""
    port = os.getenv("POSTGRES_PORT", "").strip()
    database = os.getenv("POSTGRES_DB", "").strip()
    username = os.getenv("POSTGRES_USER", "").strip()
    password = os.getenv("POSTGRES_PASSWORD", "")
    if not port or not database or not username:
        return ""
    auth = quote(username, safe="")
    if password:
        auth = f"{auth}:{quote(password, safe='')}"
    return f"postgresql://{auth}@{host}:{port}/{quote(database, safe='')}"


def _csv_env(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return list(default)
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    project_root = get_project_root()
    load_dotenv(project_root / "config" / ".env")
    config_path = _config_path_from_env(project_root)
    config_dict = _deep_merge(_DEFAULT_CONFIG, _read_yaml_config(config_path))
    config_dict["app_mode"] = os.getenv("APP_MODE", config_dict.get("app_mode", "normal")).strip().lower()

    # Env overrides
    config_dict.setdefault("auth", {})
    config_dict["auth"]["hash_salt"]       = os.getenv("AUTH_HASH_SALT",   config_dict["auth"].get("hash_salt", ""))
    config_dict["auth"]["admin_token"]     = os.getenv("ADMIN_TOKEN",      config_dict["auth"].get("admin_token", ""))
    config_dict["auth"]["admin_username"]  = os.getenv("ADMIN_USERNAME",   config_dict["auth"].get("admin_username", ""))
    config_dict["auth"]["admin_password"]  = os.getenv("ADMIN_PASSWORD",   config_dict["auth"].get("admin_password", ""))

    config_dict.setdefault("storage", {})
    sqlite_raw = os.getenv("SQLITE_PATH", config_dict["storage"].get("sqlite_path", ""))
    config_dict["storage"]["sqlite_path"] = str(_resolve_path(sqlite_raw))
    config_dict["storage"]["db_type"] = os.getenv("DB_TYPE", config_dict["storage"].get("db_type", "sqlite")).lower()
    config_dict["storage"]["database_url"] = (
        os.getenv("DATABASE_URL", "").strip()
        or (_postgres_url_from_env() if config_dict["storage"]["db_type"] == "postgresql" else "")
        or config_dict["storage"].get("database_url", "")
    )

    config_dict.setdefault("redis", {})
    config_dict["redis"]["enabled"] = os.getenv("REDIS_ENABLED", str(config_dict["redis"].get("enabled", False))).lower() in ("1", "true", "yes")
    config_dict["redis"]["url"] = os.getenv("REDIS_URL", config_dict["redis"].get("url", "redis://localhost:6379/0"))
    config_dict["redis"]["prefix"] = os.getenv("REDIS_PREFIX", config_dict["redis"].get("prefix", "up:"))

    config_dict.setdefault("model", {})
    onnx_raw = os.getenv("ONNX_PATH", config_dict["model"].get("onnx_path", ""))
    if onnx_raw:
        config_dict["model"]["onnx_path"] = str(_resolve_path(onnx_raw))

    config_dict.setdefault("queue", {})
    config_dict["queue"]["workers"] = int(os.getenv("QUEUE_WORKERS", config_dict["queue"].get("workers", 4)))

    config_dict.setdefault("payment", {})
    config_dict["payment"]["razorpay_key_id"] = os.getenv("RAZORPAY_KEY_ID", config_dict["payment"].get("razorpay_key_id", ""))
    config_dict["payment"]["razorpay_key_secret"] = os.getenv("RAZORPAY_KEY_SECRET", config_dict["payment"].get("razorpay_key_secret", ""))
    config_dict["payment"]["razorpay_webhook_secret"] = os.getenv("RAZORPAY_WEBHOOK_SECRET", config_dict["payment"].get("razorpay_webhook_secret", ""))
    config_dict["payment"]["razorpay_order_token"] = os.getenv("RAZORPAY_ORDER_TOKEN", config_dict["payment"].get("razorpay_order_token", ""))

    config_dict.setdefault("email", {})
    config_dict["email"]["otp_email_enabled"] = os.getenv(
        "OTP_EMAIL_ENABLED", str(config_dict["email"].get("otp_email_enabled", False))
    ).lower() in {"1", "true", "yes", "on"}
    config_dict["email"]["otp_email_provider"] = os.getenv(
        "OTP_EMAIL_PROVIDER", config_dict["email"].get("otp_email_provider", "brevo")
    ).strip().lower()
    config_dict["email"]["brevo_api_key"] = os.getenv("BREVO_API_KEY", config_dict["email"].get("brevo_api_key", ""))
    config_dict["email"]["otp_email_from"] = os.getenv("OTP_EMAIL_FROM", config_dict["email"].get("otp_email_from", ""))
    config_dict["email"]["otp_email_from_name"] = os.getenv(
        "OTP_EMAIL_FROM_NAME", config_dict["email"].get("otp_email_from_name", "EazyFill")
    )
    config_dict["email"]["otp_email_reply_to"] = os.getenv(
        "OTP_EMAIL_REPLY_TO", config_dict["email"].get("otp_email_reply_to", "")
    )
    config_dict["email"]["otp_dev_otp_enabled"] = os.getenv(
        "OTP_DEV_OTP_ENABLED", str(config_dict["email"].get("otp_dev_otp_enabled", False))
    ).lower() in {"1", "true", "yes", "on"}
    config_dict["email"]["otp_allowed_email_domains"] = _csv_env(
        "OTP_ALLOWED_EMAIL_DOMAINS",
        config_dict["email"].get("otp_allowed_email_domains", DEFAULT_OTP_ALLOWED_EMAIL_DOMAINS),
    )
    config_dict["email"]["otp_blocked_email_domains"] = _csv_env(
        "OTP_BLOCKED_EMAIL_DOMAINS",
        config_dict["email"].get("otp_blocked_email_domains", DEFAULT_OTP_BLOCKED_EMAIL_DOMAINS),
    )

    config_dict.setdefault("plans", {})
    config_dict["plans"]["auto_seed_on_empty"] = os.getenv(
        "PLAN_AUTO_SEED_ON_EMPTY",
        str(config_dict["plans"].get("auto_seed_on_empty", False)),
    ).lower() in {"1", "true", "yes", "on"}
    bootstrap_plans_raw = (
        os.getenv("PLAN_BOOTSTRAP_JSON", "").strip()
        or os.getenv("EAZYFILL_PLAN_BOOTSTRAP_JSON", "").strip()
    )
    if bootstrap_plans_raw:
        import json
        config_dict["plans"]["bootstrap_plans"] = json.loads(bootstrap_plans_raw)

    config_dict.setdefault("server", {})
    config_dict["server"]["debug"] = os.getenv("DEBUG", str(config_dict["server"].get("debug", False))).lower() in {"1", "true", "yes"}

    config_dict.setdefault("retrain", {})
    config_dict["retrain"]["worker_enabled"] = os.getenv(
        "RETRAIN_WORKER_ENABLED", str(config_dict["retrain"].get("worker_enabled", False))
    ).lower() in {"1", "true", "yes"}

    config_dict.setdefault("logging", {})
    config_dict["logging"]["debug"] = config_dict["server"]["debug"]
    if config_dict["server"]["debug"]:
        config_dict["logging"]["level"] = "DEBUG"

    return Settings(**config_dict)


def require_runtime_auth(
    settings: Settings,
    *,
    require_hash_salt: bool = True,
    require_admin_token: bool = True,
) -> None:
    """Validate auth secrets for entrypoints that expose authenticated APIs.

    Background-only processes can load Settings without admin secrets. The API
    process must still fail fast when critical auth values are missing.
    """
    if require_hash_salt and not settings.auth.hash_salt.strip():
        raise ValueError(
            "AUTH_HASH_SALT must not be empty - set it in your .env file. "
            "An empty salt makes all API keys trivially equivalent."
        )
    if require_admin_token and not settings.auth.admin_token.strip():
        raise ValueError(
            "ADMIN_TOKEN must not be empty - set it in your .env file. "
            "An empty token allows unauthenticated admin access."
        )
