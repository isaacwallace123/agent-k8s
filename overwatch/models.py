from __future__ import annotations
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel


class Anomaly(BaseModel):
    severity: str  # low, medium, high
    type: str      # crashloop, high_cpu, high_memory, pending_pod, node_pressure, other
    description: str
    affected: str


class Insight(BaseModel):
    id: Optional[int] = None
    collected_at: datetime
    status: str  # healthy, warning, critical, unknown
    summary: str
    anomalies: List[Anomaly]
    recommendations: List[str]
