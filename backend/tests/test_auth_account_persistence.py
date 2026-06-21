from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.v2_routes import auth as auth_route
from app.core.db import Base
from app.core.models import AuthChallenge, UserSession


def _session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _request():
    return SimpleNamespace(headers={"user-agent": "pytest-agent"}, client=SimpleNamespace(host="127.0.0.1"))


def test_auth_challenge_replaces_previous_pending_for_identifier():
    Session = _session_factory()
    session = Session()

    first = auth_route._create_auth_challenge(
        session,
        _request(),
        identifier_type="email",
        identifier="user@gmail.com",
        name="Test User",
        plan_code="free",
        otp="111111",
        account_mode="signup",
    )
    session.commit()

    auth_route._drop_existing_identifier_challenges(session, "email", "user@gmail.com")
    second = auth_route._create_auth_challenge(
        session,
        _request(),
        identifier_type="email",
        identifier="user@gmail.com",
        name="Test User",
        plan_code="free",
        otp="222222",
        account_mode="signup",
    )
    session.commit()

    assert session.query(AuthChallenge).filter_by(challenge_id=first.challenge_id).one().status == "replaced"
    assert auth_route._load_pending_challenge(session, first.challenge_id) is None
    assert auth_route._load_pending_challenge(session, second.challenge_id).challenge_id == second.challenge_id


def test_issue_user_session_replaces_existing_device_session(monkeypatch):
    Session = _session_factory()
    monkeypatch.setattr(auth_route, "get_session", Session)

    first_token, first_session = auth_route._issue_user_session(
        _request(),
        user_id=42,
        api_key_id=7,
        device_id="device-1",
        device_name="Chrome",
    )
    second_token, second_session = auth_route._issue_user_session(
        _request(),
        user_id=42,
        api_key_id=8,
        device_id="device-1",
        device_name="Chrome",
    )

    session = Session()
    records = session.query(UserSession).order_by(UserSession.id.asc()).all()

    assert first_token.startswith("efs_")
    assert second_token.startswith("efs_")
    assert first_token != second_token
    assert first_session["status"] == "active"
    assert second_session["status"] == "active"
    assert [record.status for record in records] == ["replaced", "active"]
