from __future__ import annotations
from typing import List, Optional, Union
from datetime import datetime
from pydantic import BaseModel, field_validator


class Anomaly(BaseModel):
    severity: str  # low, medium, high
    type: str      # crashloop, high_cpu, high_memory, pending_pod, node_pressure, other
    description: str
    affected: str

    @field_validator('affected', mode='before')
    @classmethod
    def coerce_affected(cls, v: object) -> str:
        if isinstance(v, list):
            return ', '.join(str(x) for x in v)
        return str(v) if v is not None else ''


class Insight(BaseModel):
    id: Optional[int] = None
    collected_at: datetime
    status: str  # healthy, warning, critical, unknown
    summary: str
    anomalies: List[Anomaly]
    recommendations: List[str]


class PodInsight(BaseModel):
    namespace: str
    app: str
    analyzed_at: datetime
    status: str  # healthy, warning, critical, unknown
    diagnosis: str
    root_cause: str
    suggestions: List[str]
