from app.services.credit_service import CreditService


class _UsageCycles:
    def __init__(self):
        self.reserved = []
        self.refunded = []

    def get_user_usage(self, user_id):
        return {
            "cycle_id": 11,
            "used": 7,
            "limit": 100,
            "remaining": 93,
            "cycle_end": "2026-06-13T00:00:00",
        }

    def increment_usage_atomic(self, user_id, amount=1):
        self.reserved.append((user_id, amount))
        return {"allowed": True, "used": 8, "limit": 100, "cycle_id": 11}

    def refund_usage_atomic(self, user_id, amount=1, cycle_id=None):
        self.refunded.append((user_id, amount, cycle_id))
        return {"refunded": True, "used": 7, "limit": 100, "cycle_id": cycle_id}


def test_credit_service_returns_eazyfill_balance_shape():
    service = CreditService(_UsageCycles())

    balance = service.get_balance(42, cloud_sync_enabled=True, rules_count=3, scripts_count=2)

    assert balance["captcha"]["used_today"] == 7
    assert balance["captcha"]["daily_limit"] == 100
    assert balance["captcha"]["remaining"] == 93
    assert balance["autofill"]["rules_count"] == 3
    assert balance["scripts"]["count"] == 2
    assert balance["sync"]["enabled"] is True


def test_credit_service_reserves_and_refunds_captcha():
    usage_cycles = _UsageCycles()
    service = CreditService(usage_cycles)

    reserve = service.reserve_captcha(42, amount=2)
    refund = service.refund_captcha(42, amount=2, cycle_id=11)

    assert reserve["allowed"] is True
    assert refund["refunded"] is True
    assert usage_cycles.reserved == [(42, 2)]
    assert usage_cycles.refunded == [(42, 2, 11)]
