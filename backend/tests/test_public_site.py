from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.public_site import router


def test_public_site_serves_required_review_pages():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    for path in [
        "/",
        "/pricing",
        "/contact",
        "/privacy",
        "/privacy-policy.html",
        "/terms",
        "/terms-and-conditions",
        "/refunds",
        "/cancellation-refund-policy",
        "/delivery",
        "/shipping-delivery-policy",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert "EazyFill" in response.text
        assert "TBD" not in response.text


def test_public_site_unknown_page_404s():
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/not-a-real-page")
    assert response.status_code == 404


def test_pricing_page_loads_dynamic_plan_catalog():
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/pricing")

    assert response.status_code == 200
    assert "/public-assets/pricing.js" in response.text
    assert "INR 499.00" not in response.text
    assert "500 CAPTCHA credits per cycle" not in response.text


def test_home_page_links_to_browser_stores():
    app = FastAPI()
    app.include_router(router)

    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert "chromewebstore.google.com/detail/eazyfill/nafpeknhhfebaieljomikajfpkfgmmma" in response.text
    assert "addons.mozilla.org/en-US/firefox/addon/eazyfill/" in response.text
