import os
import json
import logging
import requests
from datetime import datetime, timezone
from models import Insight, Anomaly

log = logging.getLogger("overwatch.analyzer")

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://llm:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")

_PROMPT_TEMPLATE = """You are a Kubernetes cluster monitoring AI. Analyze the snapshot below and respond ONLY with valid JSON — no explanation, no markdown, just the JSON object.

CLUSTER SNAPSHOT:
{snapshot}

Respond with exactly this structure:
{{
  "status": "healthy" or "warning" or "critical",
  "summary": "1-2 sentence plain-English cluster health summary",
  "anomalies": [
    {{
      "severity": "low" or "medium" or "high",
      "type": "crashloop" or "high_cpu" or "high_memory" or "pending_pod" or "node_pressure" or "other",
      "description": "specific, actionable description",
      "affected": "namespace/pod-name or node-name"
    }}
  ],
  "recommendations": ["concrete recommendation 1", "concrete recommendation 2"]
}}

Rules:
- anomalies array must be empty [] if everything looks healthy
- status is "warning" if any anomaly severity >= medium, "critical" if any severity == high
- keep summary under 200 characters
- keep each recommendation under 150 characters"""


def analyze(snapshot: str) -> Insight:
    prompt = _PROMPT_TEMPLATE.format(snapshot=snapshot)
    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_ctx": 4096,
                    "temperature": 0.1,
                    "top_p": 0.9,
                },
            },
            timeout=180,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")

        # Extract JSON block from response
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError(f"No JSON object found in LLM response: {raw[:200]}")

        data = json.loads(raw[start:end])
        anomalies = [Anomaly(**a) for a in data.get("anomalies", [])]

        return Insight(
            collected_at=datetime.now(timezone.utc),
            status=data.get("status", "unknown"),
            summary=data.get("summary", ""),
            anomalies=anomalies,
            recommendations=data.get("recommendations", []),
        )

    except Exception as e:
        log.error("LLM analysis failed: %s", e)
        return Insight(
            collected_at=datetime.now(timezone.utc),
            status="unknown",
            summary=f"Analysis failed: {e}",
            anomalies=[],
            recommendations=[],
        )
