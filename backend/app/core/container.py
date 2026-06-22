"""Dependency container for EazyFill."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.database import Database
from app.core.db import init_db as init_sqlalchemy_db, get_session
from app.services.admin_notification_service import AdminNotificationService
from app.services.audit_service import AuditService
from app.services.cache_service import CacheService
from app.services.credit_service import CreditService
from app.services.key_service import KeyService
from app.services.model_router import ModelRouter
from app.services.payment_service import PaymentService
from app.services.solver_service import SolverService
from app.services.subscription_service import SubscriptionService
from app.services.sync_service import SyncService
from app.services.usage_service import UsageService
from app.services.user_service import UserService
from app.services.usage_cycle_service import UsageCycleService
from app.services.rate_limiter import RateLimiter
from app.services.backup_service import BackupService
from app.services.user_key_service import UserKeyService
from app.services.email_service import EmailService



@dataclass
class Container:
    """Holds all initialized app services."""

    settings: Settings
    db: Database

    # ── Platform Module ────────────────────────────────────────────────
    key_service: KeyService
    usage_service: UsageService

    # ── Captcha Module ─────────────────────────────────────────────────
    solver_service: SolverService     # text captcha ONNX

    # New scalable services (SQLAlchemy-based)
    # ── User Module ────────────────────────────────────────────────────
    user_service: UserService = field(default=None)
    subscription_service: SubscriptionService = field(default=None)
    payment_service: PaymentService = field(default=None)

    # ── Platform Module ────────────────────────────────────────────────
    audit_service: AuditService = field(default=None)
    admin_notification_service: AdminNotificationService = field(default=None)
    usage_cycle_service: UsageCycleService = field(default=None)
    rate_limiter: RateLimiter = field(default=None)
    backup_service: BackupService = field(default=None)
    credit_service: CreditService = field(default=None)
    sync_service: SyncService = field(default=None)

    # ── User Module ────────────────────────────────────────────────────
    user_key_service: UserKeyService = field(default=None)
    email_service: EmailService = field(default=None)



def build_container(settings: Settings) -> Container:
    """Initialize and wire all services."""

    # Legacy raw-SQL database (existing api_keys, usage_events, etc.)
    db = Database(settings=settings)
    db.init()

    # New SQLAlchemy-based database (users, subscriptions, payments, etc.)
    init_sqlalchemy_db(settings)
    # Import models to register them with Base.metadata before creating tables
    import app.core.models  # noqa: F401
    # Create ORM tables (dev only — production uses Alembic migrations)
    if settings.server.debug:
        from app.core.db import create_all_tables
        create_all_tables()

    # Captcha solver (existing ONNX pipeline)
    model_router = ModelRouter(settings=settings, db=db)
    cache = CacheService(ttl_seconds=settings.queue.cache_ttl_seconds)
    solver = SolverService(
        workers=settings.queue.workers,
        max_pending_jobs=settings.queue.max_pending_jobs,
        model_router=model_router,
        cache=cache,
    )

    key_service   = KeyService(db=db, settings=settings)
    usage_service = UsageService(db=db)

    # New scalable services (SQLAlchemy-based)
    user_service = UserService(session_factory=get_session)
    subscription_service = SubscriptionService(session_factory=get_session, settings=settings)
    payment_service = PaymentService(session_factory=get_session, settings=settings)
    audit_service = AuditService(session_factory=get_session)
    admin_notification_service = AdminNotificationService(session_factory=get_session)
    usage_cycle_service = UsageCycleService(session_factory=get_session)
    rate_limiter = RateLimiter(settings=settings)
    backup_service = BackupService(settings=settings)
    credit_service = CreditService(usage_cycle_service=usage_cycle_service, session_factory=get_session)
    sync_service = SyncService(session_factory=get_session)
    user_key_service = UserKeyService(session_factory=get_session, settings=settings)
    email_service = EmailService(settings=settings)

    return Container(
        settings=settings,
        db=db,
        key_service=key_service,
        usage_service=usage_service,
        solver_service=solver,
        user_service=user_service,
        subscription_service=subscription_service,
        payment_service=payment_service,
        audit_service=audit_service,
        admin_notification_service=admin_notification_service,
        usage_cycle_service=usage_cycle_service,
        rate_limiter=rate_limiter,
        backup_service=backup_service,
        credit_service=credit_service,
        sync_service=sync_service,
        user_key_service=user_key_service,
        email_service=email_service,
    )
