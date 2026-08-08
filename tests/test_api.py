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


def test_diff_endpoint_returns_latest_diff(monkeypatch):
    # Ensure default diff exists
    client = TestClient(app)
    response = client.get("/api/diff")
    assert response.status_code == 200
    data = response.json()
    assert "changes" in data
    assert isinstance(data["changes"], list)

def test_diff_endpoint_missing_diff_returns_404(monkeypatch):
    # Simulate missing diff by pointing to invalid data directory
    monkeypatch.setenv("AZURE_REGION_MONITOR_DATA_DIR", "invalid_data_dir")
    client = TestClient(app)
    response = client.get("/api/diff")
    assert response.status_code == 404

def test_service_endpoint_returns_regions():
    client = TestClient(app)
    response = client.get("/api/services/aks")
    assert response.status_code == 200
    json = response.json()
    assert json["service"] == "aks"
    assert "regions" in json
    assert isinstance(json["regions"], dict)
    # Expect at least one known region
    assert any(region in json["regions"] for region in ("westeurope", "swedencentral"))

def test_unknown_service_returns_404():
    client = TestClient(app)
    response = client.get("/api/services/nonexistentservice")
    assert response.status_code == 404

def test_history_endpoint_returns_snapshot():
    client = TestClient(app)
    # Use known snapshot date
    response = client.get("/api/history/2026-05-07")
    assert response.status_code == 200
    data = response.json()
    assert "regions" in data
    assert "timestamp" in data

def test_history_endpoint_missing_snapshot_returns_404(monkeypatch):
    monkeypatch.setenv("AZURE_REGION_MONITOR_DATA_DIR", "invalid_data_dir")
    client = TestClient(app)
    response = client.get("/api/history/1900-01-01")
    assert response.status_code == 404

def test_subscribe_not_implemented():
    client = TestClient(app)
    payload = {"channel": "email", "target": "user@example.com"}
    response = client.post("/api/subscribe", json=payload)
    assert response.status_code == 501

def test_subscribe_invalid_request():
    client = TestClient(app)
    # Missing required field 'target'
    payload = {"channel": "email"}
    response = client.post("/api/subscribe", json=payload)
    assert response.status_code == 422
