from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FeatureStatus = Literal["available", "unavailable", "partial", "unknown"]
ChangeType = Literal["new_availability", "regression", "status_change"]


class FeatureResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: FeatureStatus
    latency_ms: int | None = Field(default=None, ge=0)
    error_code: str | None = None
    message: str | None = None


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    regions: dict[str, dict[str, dict[str, FeatureResult]]]


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: str
    service: str
    feature: str
    previous: FeatureStatus | None
    current: FeatureStatus | None
    change_type: ChangeType


class Diff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    previous_timestamp: datetime
    current_timestamp: datetime
    changes: list[Change]
