"""Security-header branching: strict lockdown for /api, usable policy for the UI.

Single-server mode serves the built frontend from the API itself. A
blanket `default-src 'none'` breaks it (CSS/JS blocked -> unstyled dead
page), so the middleware branches by path. Guards both directions:
the API must never loosen, the UI must allow its own same-origin
assets plus the app's actual needs (fonts, data:/blob: images).
"""

from fastapi.testclient import TestClient


def _csp(response):
    return response.headers.get("content-security-policy", "")


def test_api_keeps_strict_csp():
    from backend.main import app

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert _csp(response) == "default-src 'none'; frame-ancestors 'none'"


def test_ui_allows_same_origin_assets():
    from backend.main import app

    client = TestClient(app, raise_server_exceptions=False)
    # Any non-/api path gets the UI policy (middleware applies even to
    # 404s, so no frontend/dist build is needed for this assertion).
    response = client.get("/assets/index-test.css")
    csp = _csp(response)
    assert "default-src 'none'" not in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_ui_permits_camera_only():
    from backend.main import app

    client = TestClient(app, raise_server_exceptions=False)
    api_policy = client.get("/api/health").headers.get("permissions-policy", "")
    ui_policy = client.get("/assets/index-test.css").headers.get("permissions-policy", "")
    assert "camera=()" in api_policy
    assert "camera=(self)" in ui_policy
    assert "microphone=()" in ui_policy
