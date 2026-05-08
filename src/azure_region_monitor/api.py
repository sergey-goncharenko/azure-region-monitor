from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, ConfigDict

from azure_region_monitor.storage import load_diff, load_snapshot

app = FastAPI(
    title="Azure Regional Feature Availability Monitor",
    version="0.1.0",
    description="Read-only API for synthetic Azure regional feature availability snapshots.",
)


class SubscriptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["email", "webhook", "slack", "teams"]
    target: str
    regions: list[str] = []
    services: list[str] = []


@app.get("/api/latest")
def latest_snapshot():
    return _load_latest_snapshot()


@app.get("/api/diff")
def latest_diff():
    path = _data_dir() / "diffs" / "latest.json"
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No diff is available yet")
    return load_diff(path)


@app.get("/api/regions/{region}")
def region_availability(region: str):
    snapshot = _load_latest_snapshot()
    if region not in snapshot.regions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Region not found")
    return {
        "timestamp": snapshot.timestamp,
        "region": region,
        "services": snapshot.regions[region],
    }


@app.get("/api/services/{service}")
def service_availability(service: str):
    snapshot = _load_latest_snapshot()
    regions = {
        region: services[service]
        for region, services in snapshot.regions.items()
        if service in services
    }
    if not regions:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Service not found")
    return {
        "timestamp": snapshot.timestamp,
        "service": service,
        "regions": regions,
    }


@app.get("/api/history/{date}")
def historical_snapshot(date: str):
    path = _data_dir() / "snapshots" / f"{date}.json"
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
    return load_snapshot(path)


@app.post("/api/subscribe", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def subscribe(_: SubscriptionRequest):
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Subscriptions are planned for v1; this starter implements read-only data endpoints.",
    )


def _load_latest_snapshot():
    path = _data_dir() / "snapshots" / "latest.json"
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No snapshot is available yet")
    return load_snapshot(path)


def _data_dir() -> Path:
    return Path(os.environ.get("AZURE_REGION_MONITOR_DATA_DIR", "data"))
