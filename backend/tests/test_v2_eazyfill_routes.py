import base64
import hashlib
import hmac
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v2_routes import router
from app.api.v2_routes import sync as sync_route
from app.api.v2_routes.deps import V2AuthContext, validate_v2_key


def _ctx() -> V2AuthContext:
    return V2AuthContext(
        api_key="fp_test",
        device_id="device-1",
        record={"id": 7, "user_id": 42, "name": "Main Key", "expires_at": None},
        key_kind="user",
        user=SimpleNamespace(id=42, full_name="Flow User", mobile_number="9999999999", email="flowuser@gmail.com"),
        subscription=SimpleNamespace(id=3),
        plan=SimpleNamespace(
            code="basic",
            name="Basic",
            monthly_limit=500,
            allowed_services={"captcha": True, "autofill": True, "userscripts": True, "sync": True},
        ),
    )


def _app(ctx: V2AuthContext | None = None, *, quota_allowed: bool = True) -> FastAPI:
    app = FastAPI()
    plan = SimpleNamespace(
        id=3,
        code="basic",
        name="Basic",
        description="Basic plan",
        price_amount=14900,
        currency="INR",
        duration_days=30,
        monthly_limit=500,
        max_devices=2,
        rate_limit_rpm=60,
        rate_limit_burst=10,
        show_in_checkout=True,
        allowed_services={
            "captcha": True,
            "autofill": True,
            "userscripts": True,
            "sync": True,
            "rules_limit": 50,
            "scripts_limit": 20,
            "script_storage_mb": 10,
        },
        is_active=True,
    )
    payment = SimpleNamespace(
        id=101,
        user_id=42,
        status="pending_payment",
        payment_provider="razorpay",
        provider_order_id="order_123",
        provider_payment_id=None,
        provider_status="created",
        currency="INR",
        to_dict=lambda: {
            "id": 101,
            "user_id": 42,
            "plan_id": 3,
            "status": "pending_payment",
            "amount": 14900,
            "currency": "INR",
            "payment_provider": "razorpay",
            "provider_order_id": "order_123",
        },
    )
    key = SimpleNamespace(
        id=7,
        user_id=42,
        key_prefix_display="fp_abc...",
        status="active",
        key_version=1,
        issued_at=datetime(2026, 6, 12),
        expires_at=None,
        last_used_at=None,
        usage_count=3,
        revoked_at=None,
    )
    device = SimpleNamespace(
        id=5,
        api_key_id=7,
        device_fingerprint="device-1",
        device_name="Chrome",
        user_agent="test-agent",
        status="active",
        first_seen_at=datetime(2026, 6, 12),
        last_seen_at=datetime(2026, 6, 12),
    )
    usage_cycle_service = MagicMock()
    usage_cycle_service.get_user_usage.return_value = {
        "has_subscription": True,
        "used": 13,
        "limit": 500,
        "remaining": 487,
        "cycle_end": "2026-06-13T00:00:00",
    }
    usage_cycle_service.get_usage_history.return_value = [{
        "cycle_id": 9,
        "cycle_start": "2026-06-01T00:00:00",
        "cycle_end": "2026-07-01T00:00:00",
        "captcha_used": 13,
        "captcha_limit": 500,
        "captcha_remaining": 487,
        "blocked": False,
    }]
    usage_cycle_service.increment_usage_atomic.return_value = {
        "allowed": quota_allowed,
        "used": 14 if quota_allowed else 500,
        "limit": 500,
        "cycle_id": 9,
    }
    usage_cycle_service.refund_usage_atomic.return_value = {"refunded": True}
    app.state.container = SimpleNamespace(
        db=SimpleNamespace(
            get_field_mapped_model=MagicMock(return_value={"ai_model_filename": "login_captcha.onnx"}),
            get_field_mapping_by_selectors=MagicMock(return_value=None),
            get_domain_field_mappings=MagicMock(return_value={
                "login_captcha": {
                    "task_type": "image",
                    "source_data_type": "image",
                    "source_selector": "#captcha-img",
                    "target_data_type": "text",
                    "target_selector": "#captcha-input",
                    "runtime": "onnx",
                    "model_filename": "login_captcha.onnx",
                    "lifecycle_state": "production",
                }
            }),
            propose_field_mapping=MagicMock(return_value={
                "id": 21,
                "domain": "example.com",
                "task_type": "image",
                "source_selector": "#captcha-img",
                "target_selector": "#captcha-input",
                "proposed_field_name": "login_captcha",
                "status": "pending",
            }),
            get_field_mapping_proposal_by_selectors=MagicMock(return_value=None),
            add_retrain_sample=MagicMock(return_value=31),
        ),
        usage_cycle_service=usage_cycle_service,
        solver_service=SimpleNamespace(
            submit_captcha=AsyncMock(return_value={"result": "X7K2", "processing_ms": 24, "model_used": "onnx"})
        ),
        usage_service=MagicMock(),
        sync_service=MagicMock(),
        subscription_service=MagicMock(),
        payment_service=MagicMock(),
        settings=SimpleNamespace(payment=SimpleNamespace(razorpay_key_id="rzp_test_key", razorpay_key_secret="test_secret")),
        user_key_service=MagicMock(),
    )
    app.state.container.subscription_service.list_plans.return_value = [plan]
    app.state.container.subscription_service.get_plan.return_value = plan
    app.state.container.subscription_service.get_plan_by_code.return_value = plan
    app.state.container.subscription_service.get_active_subscription.return_value = SimpleNamespace(
        id=3,
        to_dict=lambda: {"id": 3, "status": "active"},
    )
    app.state.container.subscription_service.cancel_subscription.return_value = SimpleNamespace(
        id=3,
        to_dict=lambda: {"id": 3, "status": "cancelled"},
    )
    app.state.container.payment_service.create_payment.return_value = payment
    app.state.container.payment_service.get_payment.return_value = payment
    app.state.container.payment_service.get_user_payments.return_value = [payment]
    app.state.container.payment_service.record_provider_payment.return_value = payment
    app.state.container.payment_service.activate_payment.return_value = {
        "payment": {**payment.to_dict(), "status": "approved"},
        "plan": {"code": "basic"},
        "plain_key": "fp_paid_key",
    }
    app.state.container.user_key_service.list_user_keys.return_value = [key]
    app.state.container.user_key_service.create_key.return_value = (key, "fp_new_key")
    app.state.container.user_key_service.rotate_key.return_value = (key, "fp_rotated_key")
    app.state.container.user_key_service.revoke_user_key.return_value = key
    app.state.container.user_key_service.get_user_devices.return_value = [device]
    app.state.container.user_key_service.bind_device.return_value = device
    app.state.container.user_key_service.remove_user_device.return_value = True
    app.state.container.sync_service.push_blob.return_value = {
        "device_id": "device-1",
        "sync_version": 2,
        "blob_hash": "sha256:test",
        "blob_size_bytes": 4,
        "created_at": "2026-06-12T00:00:00",
        "updated_at": "2026-06-12T00:00:00",
    }
    app.include_router(router)

    async def override_validate_v2_key():
        return ctx or _ctx()

    app.dependency_overrides[validate_v2_key] = override_validate_v2_key
    return app


def _install_auth_challenge_store(monkeypatch, auth_route, *, existing_identifiers: set[tuple[str, str]] | None = None):
    store = {}
    existing_identifiers = existing_identifiers or set()

    class FakeSession:
        def commit(self):
            return None

        def rollback(self):
            return None

        def close(self):
            return None

    def fake_user_for_identifier(_session, identifier_type, identifier):
        if (identifier_type, identifier) in existing_identifiers:
            return SimpleNamespace(id=42)
        return None

    def fake_purge(_session):
        now = auth_route._utcnow_naive()
        for challenge in store.values():
            if challenge.status == "pending" and challenge.expires_at <= now:
                challenge.status = "expired"

    def fake_drop(_session, identifier_type, identifier):
        for challenge in store.values():
            if (
                challenge.status == "pending"
                and challenge.identifier_type == identifier_type
                and challenge.identifier == identifier
            ):
                challenge.status = "replaced"

    def fake_create(_session, _request, *, identifier_type, identifier, name, plan_code, otp, account_mode):
        now = auth_route._utcnow_naive()
        challenge = SimpleNamespace(
            challenge_id=f"challenge-{len(store) + 1}",
            identifier_type=identifier_type,
            identifier=identifier,
            account_mode=account_mode,
            name=name,
            plan_code=plan_code,
            otp_hash=auth_route._otp_hash(otp),
            status="pending",
            attempts=0,
            expires_at=now + timedelta(seconds=auth_route.OTP_TTL_SECONDS),
            consumed_at=None,
            updated_at=now,
        )
        store[challenge.challenge_id] = challenge
        return challenge

    def fake_load(_session, challenge_id):
        challenge = store.get(challenge_id)
        if challenge and challenge.status == "pending":
            return challenge
        return None

    def fake_mark_status(challenge_id, status):
        if challenge_id in store:
            store[challenge_id].status = status

    monkeypatch.setattr(auth_route, "get_session", lambda: FakeSession())
    monkeypatch.setattr(auth_route, "_user_for_identifier", fake_user_for_identifier)
    monkeypatch.setattr(auth_route, "_purge_expired_challenges", fake_purge)
    monkeypatch.setattr(auth_route, "_drop_existing_identifier_challenges", fake_drop)
    monkeypatch.setattr(auth_route, "_create_auth_challenge", fake_create)
    monkeypatch.setattr(auth_route, "_load_pending_challenge", fake_load)
    monkeypatch.setattr(auth_route, "_mark_challenge_status", fake_mark_status)
    monkeypatch.setattr(
        auth_route,
        "_issue_user_session",
        lambda *_args, **_kwargs: (
            "efs_test_session",
            {
                "id": 11,
                "device_id": _kwargs.get("device_id", "device-1"),
                "status": "active",
                "issued_at": "2026-06-22T00:00:00",
                "expires_at": "2026-09-20T00:00:00",
                "last_seen_at": "2026-06-22T00:00:00",
            },
        ),
    )
    return store


def test_v2_verify_key_returns_eazyfill_contract(monkeypatch):
    from app.api.v2_routes import auth as auth_route

    async def fake_validate_v2_key(*_args, **_kwargs):
        return _ctx()

    app = _app()
    monkeypatch.setattr(auth_route, "validate_v2_key", fake_validate_v2_key)

    response = TestClient(app).post("/v2/auth/verify-key", json={"api_key": "fp_test"})

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["user_id"] == 42
    assert body["plan"]["code"] == "basic"
    assert body["credits"]["captcha"]["remaining"] == 487
    assert body["device"]["status"] == "active"


def test_v2_auth_register_and_verify_otp_issues_key(monkeypatch):
    from app.api.v2_routes import auth as auth_route

    created_key = SimpleNamespace(id=7)

    async def fake_validate_v2_key(*_args, **_kwargs):
        return _ctx()

    app = _app()
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=True),
        email=SimpleNamespace(otp_dev_otp_enabled=True),
    )
    app.state.container.user_key_service.create_key.return_value = (created_key, "fp_created")
    store = _install_auth_challenge_store(monkeypatch, auth_route)
    monkeypatch.setattr(auth_route, "_create_or_update_user", lambda _session, _challenge: SimpleNamespace(id=42))
    monkeypatch.setattr(auth_route, "_ensure_subscription", lambda *_args, **_kwargs: SimpleNamespace(id=3))
    monkeypatch.setattr(auth_route, "validate_v2_key", fake_validate_v2_key)

    client = TestClient(app)
    register = client.post("/v2/auth/register", json={"email": "user@gmail.com", "name": "Flow User"})

    assert register.status_code == 200
    challenge = register.json()
    assert challenge["challenge_id"]
    assert challenge["dev_otp"]

    verify = client.post(
        "/v2/auth/verify-otp",
        headers={"X-EazyFill-Device-Id": "device-1"},
        json={"challenge_id": challenge["challenge_id"], "otp": challenge["dev_otp"], "device_name": "Chrome"},
    )

    assert verify.status_code == 200
    body = verify.json()
    assert body["api_key"] == "fp_created"
    assert body["session_token"] == "efs_test_session"
    assert body["session"]["status"] == "active"
    assert body["valid"] is True
    assert store[challenge["challenge_id"]].status == "consumed"
    app.state.container.user_key_service.create_key.assert_called_once_with(42)
    app.state.container.user_key_service.bind_device.assert_called_once()


def test_v2_auth_register_sends_email_otp_without_dev_code(monkeypatch):
    from app.api.v2_routes import auth as auth_route

    app = _app()
    email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock(return_value=SimpleNamespace(message_id="msg-1")))
    app.state.container.email_service = email_service
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )
    _install_auth_challenge_store(monkeypatch, auth_route)

    response = TestClient(app).post("/v2/auth/register", json={"email": "user@gmail.com", "name": "Eazy User"})

    assert response.status_code == 200
    body = response.json()
    assert body["delivery"] == "email"
    assert body["challenge_id"]
    assert "dev_otp" not in body
    email_service.send_otp_email.assert_awaited_once()
    assert email_service.send_otp_email.await_args.kwargs["recipient"] == "user@gmail.com"


def test_v2_auth_register_allows_existing_user_login_without_name(monkeypatch):
    from app.api.v2_routes import auth as auth_route

    app = _app()
    email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock(return_value=SimpleNamespace(message_id="msg-1")))
    app.state.container.email_service = email_service
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )
    _install_auth_challenge_store(monkeypatch, auth_route, existing_identifiers={("email", "existing@gmail.com")})

    response = TestClient(app).post("/v2/auth/register", json={"email": "existing@gmail.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["account_mode"] == "login"
    assert body["challenge_id"]
    email_service.send_otp_email.assert_awaited_once()


def test_v2_auth_register_requires_name_for_new_account(monkeypatch):
    from app.api.v2_routes import auth as auth_route

    app = _app()
    email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock())
    app.state.container.email_service = email_service
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )
    _install_auth_challenge_store(monkeypatch, auth_route)

    response = TestClient(app).post("/v2/auth/register", json={"email": "newuser@gmail.com"})

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "name_required"
    email_service.send_otp_email.assert_not_called()


def test_v2_auth_register_rate_limits_repeated_otp_requests(monkeypatch):
    from app.api.v2_routes import auth as auth_route

    app = _app()
    email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock(return_value=SimpleNamespace(message_id="msg-1")))
    app.state.container.email_service = email_service
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )
    monkeypatch.setattr(auth_route, "OTP_REGISTER_MAX_PER_IDENTIFIER", 2)
    auth_route._OTP_REGISTER_EVENTS.clear()
    _install_auth_challenge_store(monkeypatch, auth_route)

    client = TestClient(app)
    payload = {"email": "limited@gmail.com", "name": "Eazy User"}
    assert client.post("/v2/auth/register", json=payload).status_code == 200
    assert client.post("/v2/auth/register", json=payload).status_code == 200

    response = client.post("/v2/auth/register", json=payload)

    assert response.status_code == 429
    assert response.json()["detail"]["error"] == "otp_rate_limited"


def test_v2_auth_register_uses_shared_rate_limiter_when_available(monkeypatch):
    from app.api.v2_routes import auth as auth_route

    app = _app()
    email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock(return_value=SimpleNamespace(message_id="msg-1")))
    app.state.container.email_service = email_service
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )
    app.state.container.rate_limiter = SimpleNamespace(check=AsyncMock(side_effect=[True, True]))
    _install_auth_challenge_store(monkeypatch, auth_route)

    response = TestClient(app).post("/v2/auth/register", json={"email": "shared@gmail.com", "name": "Eazy User"})

    assert response.status_code == 200
    assert app.state.container.rate_limiter.check.await_count == 2
    app.state.container.rate_limiter.check.assert_any_await("otp_register_client", "ip:testclient", 12, 300)
    app.state.container.rate_limiter.check.assert_any_await(
        "otp_register_identifier",
        "email:shared@gmail.com",
        3,
        300,
    )


def test_v2_auth_register_shared_rate_limiter_blocks_without_sending_email(monkeypatch):
    from app.api.v2_routes import auth as auth_route

    app = _app()
    email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock(return_value=SimpleNamespace(message_id="msg-1")))
    app.state.container.email_service = email_service
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )
    app.state.container.rate_limiter = SimpleNamespace(check=AsyncMock(side_effect=[True, False]))
    _install_auth_challenge_store(monkeypatch, auth_route)

    response = TestClient(app).post("/v2/auth/register", json={"email": "blocked@gmail.com", "name": "Eazy User"})

    assert response.status_code == 429
    assert response.json()["detail"]["error"] == "otp_rate_limited"
    email_service.send_otp_email.assert_not_awaited()


def test_v2_auth_register_keeps_only_latest_otp_challenge(monkeypatch):
    app = _app()
    email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock(return_value=SimpleNamespace(message_id="msg-1")))
    app.state.container.email_service = email_service
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )

    from app.api.v2_routes import auth as auth_route

    auth_route._OTP_REGISTER_EVENTS.clear()
    store = _install_auth_challenge_store(monkeypatch, auth_route)
    client = TestClient(app)

    first = client.post("/v2/auth/register", json={"email": "latest@gmail.com", "name": "Eazy User"}).json()
    second = client.post("/v2/auth/register", json={"email": "latest@gmail.com", "name": "Eazy User"}).json()

    assert first["challenge_id"] != second["challenge_id"]
    assert store[first["challenge_id"]].status == "replaced"
    assert store[second["challenge_id"]].status == "pending"


def test_v2_auth_register_rejects_unsupported_email_domain():
    app = _app()
    app.state.container.email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock())
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )

    response = TestClient(app).post("/v2/auth/register", json={"email": "user@example.com", "name": "Eazy User"})

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "unsupported_email_domain"
    app.state.container.email_service.send_otp_email.assert_not_called()


def test_v2_auth_register_rejects_temporary_email_domain():
    app = _app()
    app.state.container.email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock())
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )

    response = TestClient(app).post("/v2/auth/register", json={"email": "user@mailinator.com", "name": "Eazy User"})

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "temporary_email_not_allowed"
    app.state.container.email_service.send_otp_email.assert_not_called()


def test_v2_auth_register_rejects_mobile_until_sms_exists():
    app = _app()
    app.state.container.email_service = SimpleNamespace(enabled=True, send_otp_email=AsyncMock())
    app.state.container.settings = SimpleNamespace(
        server=SimpleNamespace(debug=False),
        email=SimpleNamespace(otp_dev_otp_enabled=False),
    )

    response = TestClient(app).post("/v2/auth/register", json={"mobile": "9999999999", "name": "Eazy User"})

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "email_required"
    app.state.container.email_service.send_otp_email.assert_not_called()


def test_v2_auth_refresh_revalidates_key(monkeypatch):
    from app.api.v2_routes import auth as auth_route

    async def fake_validate_v2_key(*_args, **_kwargs):
        return _ctx()

    app = _app()
    monkeypatch.setattr(auth_route, "validate_v2_key", fake_validate_v2_key)

    response = TestClient(app).post(
        "/v2/auth/refresh",
        headers={"X-Api-Key": "fp_test", "X-EazyFill-Device-Id": "device-1"},
        json={},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["user_id"] == 42
    assert body["key_info"]["key_kind"] == "user"


def test_v2_captcha_solve_reserves_quota_and_returns_credits():
    app = _app()

    response = TestClient(app).post(
        "/v2/captcha/solve",
        headers={"X-Api-Key": "fp_test"},
        json={
            "type": "image",
            "payload_base64": "QUJDRA==",
            "domain": "example.com",
            "field_name": "login_captcha",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "X7K2"
    assert body["credits_used"] == 1
    assert body["credits_remaining"] == 487
    assert body["model_used"] == "onnx"
    assert body["routing"] == {"domain": "example.com", "field_name": "login_captcha"}
    app.state.container.db.get_field_mapped_model.assert_called_once_with("example.com", "login_captcha", "image")
    app.state.container.usage_cycle_service.increment_usage_atomic.assert_called_once_with(42, amount=1)
    app.state.container.usage_cycle_service.refund_usage_atomic.assert_not_called()


def test_v2_captcha_solve_rejects_text_payload():
    app = _app()

    response = TestClient(app).post(
        "/v2/captcha/solve",
        headers={"X-Api-Key": "fp_test"},
        json={
            "type": "text",
            "payload_text": "A7K9",
            "domain": "example.com",
            "metadata": {"fieldName": "login_captcha"},
        },
    )

    assert response.status_code == 400
    app.state.container.solver_service.submit_captcha.assert_not_called()


def test_v2_captcha_solve_requires_exact_field_mapping_before_quota():
    app = _app()
    app.state.container.db.get_field_mapped_model.return_value = None

    response = TestClient(app).post(
        "/v2/captcha/solve",
        headers={"X-Api-Key": "fp_test"},
        json={
            "type": "image",
            "payload_base64": "QUJDRA==",
            "domain": "example.com",
            "field_name": "unknown_captcha",
        },
    )

    assert response.status_code == 404
    app.state.container.usage_cycle_service.increment_usage_atomic.assert_not_called()
    app.state.container.solver_service.submit_captcha.assert_not_called()


def test_v2_captcha_solve_rejects_when_quota_exceeded():
    app = _app(quota_allowed=False)

    response = TestClient(app).post(
        "/v2/captcha/solve",
        headers={"X-Api-Key": "fp_test"},
        json={
            "type": "image",
            "payload_base64": "QUJDRA==",
            "domain": "example.com",
            "field_name": "login_captcha",
        },
    )

    assert response.status_code == 429
    app.state.container.solver_service.submit_captcha.assert_not_called()


def test_v2_captcha_route_propose_auto_approves_preapproved_mapping():
    app = _app()
    app.state.container.db.get_field_mapping_by_selectors.return_value = {
        "id": 9,
        "domain": "example.com",
        "field_name": "login_captcha",
        "source_selector": "#captcha-img",
        "target_selector": "#captcha-input",
        "ai_model_id": 4,
        "ai_model_name": "Login OCR",
        "version": "v1",
        "lifecycle_state": "production",
    }

    response = TestClient(app).post(
        "/v2/captcha/routes/propose",
        headers={"X-Api-Key": "fp_test"},
        json={
            "domain": "www.example.com",
            "source_selector": "#captcha-img",
            "target_selector": "#captcha-input",
            "field_name": "login_captcha",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "approved"
    assert body["field_name"] == "login_captcha"
    app.state.container.db.propose_field_mapping.assert_not_called()


def test_v2_captcha_route_propose_creates_pending_proposal():
    app = _app()

    response = TestClient(app).post(
        "/v2/captcha/routes/propose",
        headers={"X-Api-Key": "fp_test"},
        json={
            "domain": "example.com",
            "source_selector": "#captcha-img",
            "target_selector": "#captcha-input",
            "field_name": "login_captcha",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["proposal_id"] == 21
    app.state.container.db.propose_field_mapping.assert_called_once()


def test_v2_captcha_route_propose_stores_learning_sample_with_consent(monkeypatch, tmp_path):
    from app.api.v2_routes import captcha as captcha_route

    monkeypatch.setattr(captcha_route, "_SAMPLES_DIR", tmp_path)
    app = _app()
    sample = base64.b64encode(b"sample-image").decode("ascii")

    response = TestClient(app).post(
        "/v2/captcha/routes/propose",
        headers={"X-Api-Key": "fp_test"},
        json={
            "domain": "example.com",
            "source_selector": "#captcha-img",
            "target_selector": "#captcha-input",
            "field_name": "login_captcha",
            "learning_consent": True,
            "sample_payload_base64": sample,
            "user_label": "X7K2",
        },
    )

    assert response.status_code == 200
    assert response.json()["sample_saved"] is True
    assert list(tmp_path.iterdir())
    app.state.container.db.add_retrain_sample.assert_called_once()


def test_v2_credits_history_returns_usage_cycles():
    app = _app()

    response = TestClient(app).get(
        "/v2/credits/history?limit=5",
        headers={"X-Api-Key": "fp_test"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["cycle_id"] == 9
    assert body["items"][0]["captcha_remaining"] == 487
    app.state.container.usage_cycle_service.get_usage_history.assert_called_once_with(42, limit=5)


def test_v2_sync_push_stores_encrypted_blob():
    app = _app()
    raw_blob = b"sync"
    encrypted_blob = base64.b64encode(raw_blob).decode("ascii")
    blob_hash = "sha256:" + hashlib.sha256(raw_blob).hexdigest()

    response = TestClient(app).post(
        "/v2/sync/push",
        headers={"X-Api-Key": "fp_test"},
        json={
            "sync_version": 2,
            "encrypted_blob": encrypted_blob,
            "blob_hash": blob_hash,
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    app.state.container.sync_service.push_blob.assert_called_once()


def test_v2_sync_requires_sync_entitlement():
    ctx = _ctx()
    ctx.plan.allowed_services = {"captcha": True, "sync": False}
    app = _app(ctx=ctx)

    response = TestClient(app).get("/v2/sync/status", headers={"X-Api-Key": "fp_test"})

    assert response.status_code == 403
    app.state.container.sync_service.status.assert_not_called()


def test_v2_sync_delete_requires_email_otp():
    app = _app()

    response = TestClient(app).delete("/v2/sync/delete", headers={"X-Api-Key": "fp_test"})

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "otp_required"
    app.state.container.sync_service.delete_blob.assert_not_called()


def test_v2_sync_delete_request_sends_email_otp(monkeypatch):
    app = _app()

    async def fake_send_challenge(_request, *, email, name, plan_code, account_mode):
        return {
            "ok": True,
            "challenge_id": "challenge-delete",
            "email": email,
            "account_mode": account_mode,
        }

    monkeypatch.setattr(sync_route.account_auth_service, "send_action_otp", fake_send_challenge)

    response = TestClient(app).post("/v2/sync/delete/request-otp", headers={"X-Api-Key": "fp_test"})

    assert response.status_code == 200
    body = response.json()
    assert body["challenge_id"] == "challenge-delete"
    assert body["email"] == "flowuser@gmail.com"
    assert body["account_mode"] == "sync_delete"


def test_v2_sync_delete_confirm_verifies_otp_before_delete(monkeypatch):
    app = _app()
    app.state.container.sync_service.delete_blob.return_value = {"deleted": True}
    verify_action_otp = MagicMock(return_value={"ok": True})
    monkeypatch.setattr(sync_route.account_auth_service, "verify_action_otp", verify_action_otp)
    monkeypatch.setattr(sync_route, "_sync_delete_challenge_belongs_to_user", lambda *_args, **_kwargs: True)

    response = TestClient(app).post(
        "/v2/sync/delete/confirm",
        headers={"X-Api-Key": "fp_test"},
        json={"challenge_id": "challenge-delete", "otp": "123456"},
    )

    assert response.status_code == 200
    assert response.json()["deleted"] is True
    verify_action_otp.assert_called_once_with(
        challenge_id="challenge-delete",
        otp="123456",
        account_mode="sync_delete",
        email="flowuser@gmail.com",
    )
    app.state.container.sync_service.delete_blob.assert_called_once_with(42)


def test_v2_plans_returns_catalog():
    app = _app()

    response = TestClient(app).get("/v2/plans")

    assert response.status_code == 200
    body = response.json()
    assert body["plans"][0]["code"] == "basic"
    assert body["plans"][0]["price"]["amount"] == 14900
    assert body["plans"][0]["features"]["cloud_sync"] is True
    assert body["plans"][0]["features"]["portable_pack"] is True
    assert body["plans"][0]["features"]["local_backup_export"] is True
    assert body["plans"][0]["features"]["local_backup_import"] is True
    assert body["payment_providers"][0]["code"] == "razorpay"
    assert body["payment_providers"][0]["available"] is True
    assert body["payment_providers"][0]["key_id"] == "rzp_test_key"


def test_v2_captcha_routes_returns_backend_approved_domain_mappings():
    app = _app()

    response = TestClient(app).get(
        "/v2/captcha/routes?domain=example.com",
        headers={"X-Api-Key": "fp_test"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["domain"] == "example.com"
    assert body["routes"][0]["field_name"] == "login_captcha"
    assert body["routes"][0]["sourceSelector"] == "#captcha-img"
    assert body["routes"][0]["targetSelector"] == "#captcha-input"
    assert body["routes"][0]["routeStatus"] == "approved"
    assert body["routes"][0]["serverManaged"] is True


def test_v2_plans_repairs_empty_checkout_catalog():
    app = _app()
    plan = app.state.container.subscription_service.get_plan_by_code.return_value
    app.state.container.subscription_service.list_plans.side_effect = [[], [plan]]

    response = TestClient(app).get("/v2/plans")

    assert response.status_code == 200
    assert response.json()["plans"][0]["code"] == "basic"
    app.state.container.subscription_service.ensure_default_checkout_plans.assert_called_once_with(
        only_when_empty=True,
    )


def test_v2_billing_create_order_uses_plan_price(monkeypatch):
    from app.api.v2_routes import billing as billing_route
    from fastapi.responses import JSONResponse

    async def fake_create_razorpay_order_for_user(_request, *, user_id, plan_id):
        return JSONResponse({
            "ok": True,
            "provider": "razorpay",
            "user_id": user_id,
            "plan_id": plan_id,
            "order": {"id": "order_123", "amount": 14900},
        })

    monkeypatch.setattr(billing_route, "create_razorpay_order_for_user", fake_create_razorpay_order_for_user)
    app = _app()

    response = TestClient(app).post(
        "/v2/billing/create-order",
        headers={"X-Api-Key": "fp_test"},
        json={"plan_code": "basic"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["order"]["amount"] == 14900
    app.state.container.payment_service.create_payment.assert_not_called()


def test_v2_billing_create_order_repairs_missing_default_plan(monkeypatch):
    from app.api.v2_routes import billing as billing_route
    from fastapi.responses import JSONResponse

    async def fake_create_razorpay_order_for_user(_request, *, user_id, plan_id):
        return JSONResponse({
            "ok": True,
            "provider": "razorpay",
            "user_id": user_id,
            "plan_id": plan_id,
            "order": {"id": "order_123", "amount": 14900},
        })

    monkeypatch.setattr(billing_route, "create_razorpay_order_for_user", fake_create_razorpay_order_for_user)
    app = _app()
    plan = app.state.container.subscription_service.get_plan_by_code.return_value
    app.state.container.subscription_service.get_plan_by_code.side_effect = [None, plan]

    response = TestClient(app).post(
        "/v2/billing/create-order",
        headers={"X-Api-Key": "fp_test"},
        json={"plan_code": "basic"},
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    app.state.container.subscription_service.ensure_default_checkout_plans.assert_called_once_with(
        codes={"basic"},
    )


def test_v2_billing_create_razorpay_order_delegates_to_provider(monkeypatch):
    from app.api.v2_routes import billing as billing_route
    from fastapi.responses import JSONResponse

    async def fake_create_razorpay_order_for_user(_request, *, user_id, plan_id):
        return JSONResponse({
            "ok": True,
            "provider": "razorpay",
            "user_id": user_id,
            "plan_id": plan_id,
            "order": {"id": "order_123"},
        })

    monkeypatch.setattr(billing_route, "create_razorpay_order_for_user", fake_create_razorpay_order_for_user)
    app = _app()

    response = TestClient(app).post(
        "/v2/billing/create-order",
        headers={"X-Api-Key": "fp_test"},
        json={"plan_code": "basic", "provider": "razorpay"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["order"]["id"] == "order_123"
    assert body["user_id"] == 42
    app.state.container.payment_service.create_payment.assert_not_called()


def test_v2_billing_verify_razorpay_signature_activates_payment():
    app = _app()
    payment_id = "pay_123"
    order_id = "order_123"
    signature = hmac.new(b"test_secret", f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256).hexdigest()

    response = TestClient(app).post(
        "/v2/billing/verify-payment",
        headers={"X-Api-Key": "fp_test"},
        json={
            "payment_id": 101,
            "provider": "razorpay",
            "provider_order_id": order_id,
            "provider_payment_id": payment_id,
            "provider_signature": signature,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["status"] == "approved"
    assert body["api_key"] == "fp_paid_key"
    app.state.container.payment_service.record_provider_payment.assert_called_once()
    app.state.container.payment_service.activate_payment.assert_called_once_with(101, triggered_by="razorpay_verify")


def test_v2_keys_create_returns_plain_key_once():
    app = _app()

    response = TestClient(app).post(
        "/v2/keys/create",
        headers={"X-Api-Key": "fp_test"},
        json={},
    )

    assert response.status_code == 200
    assert response.json()["api_key"] == "fp_new_key"
    app.state.container.user_key_service.create_key.assert_called_once()


def test_v2_devices_register_binds_current_key():
    app = _app()

    response = TestClient(app).post(
        "/v2/devices/register",
        headers={"X-Api-Key": "fp_test"},
        json={"device_name": "Chrome"},
    )

    assert response.status_code == 200
    assert response.json()["device"]["device_fingerprint"] == "device-1"
    app.state.container.user_key_service.bind_device.assert_called_once()
