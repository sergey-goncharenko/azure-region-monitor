from fastapi.testclient import TestClient

from azure_region_monitor.api import app


def test_latest_snapshot_returns_sample_data():
    client = TestClient(app)

    response = client.get("/api/latest")

    assert response.status_code == 200
    assert response.json()["regions"]["swedencentral"]["aks"]["extensions.gitops"]["status"] == "available"


def test_region_endpoint_filters_latest_snapshot():
    client = TestClient(app)

    response = client.get("/api/regions/westeurope")

    assert response.status_code == 200
    assert response.json()["region"] == "westeurope"
    assert set(response.json()["services"]) == {"aks"}


def test_unknown_region_returns_404():
    client = TestClient(app)

    response = client.get("/api/regions/antarcticadev")

    assert response.status_code == 404


def test_diff_endpoint_returns_latest_diff():
    client = TestClient(app)

    response = client.get("/api/diff")

    assert response.status_code == 200
    assert response.json()["changes"][0]["feature"] == "extensions.gitops"
    assert response.json()["previous_timestamp"].startswith("2026-05-07")
    assert response.json()["current_timestamp"].startswith("2026-05-08")


def test_diff_endpoint_missing_returns_404(tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_REGION_MONITOR_DATA_DIR", str(tmp_path))
    client = TestClient(app)

    response = client.get("/api/diff")

    assert response.status_code == 404
    assert response.json()["detail"] == "No diff is available yet"


def test_services_endpoint_returns_regions_for_service():
    client = TestClient(app)

    response = client.get("/api/services/aks")

    assert response.status_code == 200
    assert response.json()["service"] == "aks"
    assert "swedencentral" in response.json()["regions"]
    assert response.json()["regions"]["swedencentral"]["extensions.gitops"]["status"] == "available"


def test_services_endpoint_missing_service_returns_404():
    client = TestClient(app)

    response = client.get("/api/services/definitely-not-a-service")

    assert response.status_code == 404
    assert response.json()["detail"] == "Service not found"


def test_history_endpoint_returns_snapshot_for_date():
    client = TestClient(app)

    response = client.get("/api/history/2026-05-07")

    assert response.status_code == 200
    assert response.json()["timestamp"].startswith("2026-05-07")
    assert (
        response.json()["regions"]["swedencentral"]["aks"]["extensions.monitor"]["error_code"]
        == "ExtensionTypeNotFound"
    )


def test_history_endpoint_missing_date_returns_404():
    client = TestClient(app)

    response = client.get("/api/history/2099-01-01")

    assert response.status_code == 404
    assert response.json()["detail"] == "Snapshot not found"


def test_subscribe_valid_request_returns_501():
    client = TestClient(app)

    response = client.post("/api/subscribe", json={"channel": "email", "target": "example"})

    assert response.status_code == 501
    assert response.json()["detail"] == "Subscriptions are planned for v1; this starter implements read-only data endpoints."


def test_subscribe_invalid_channel_returns_422():
    client = TestClient(app)

    response = client.post("/api/subscribe", json={"channel": "sms", "target": "example"})

    assert response.status_code == 422


def test_subscribe_extra_field_returns_422():
    client = TestClient(app)

    response = client.post("/api/subscribe", json={"channel": "email", "target": "example", "unexpected": 1})

    assert response.status_code == 422
