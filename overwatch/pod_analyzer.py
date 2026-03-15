"""On-demand per-pod AI analysis."""
import os
import json
import logging
import requests
from datetime import datetime, timezone
from kubernetes import client, config
from models import PodInsight

log = logging.getLogger("overwatch.pod_analyzer")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus.monitoring:9090")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://llm:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")

_PROMPT = """You are a Kubernetes SRE. Analyze the pod data below and respond ONLY with valid JSON — no markdown, no explanation.

POD: {namespace}/{app}
DATA:
{data}

Respond with exactly this structure:
{{
  "status": "healthy" or "warning" or "critical",
  "diagnosis": "1-2 sentences describing what is currently happening with this pod",
  "root_cause": "1 sentence on the likely root cause, or 'None detected' if healthy",
  "suggestions": ["specific actionable suggestion 1", "specific actionable suggestion 2"]
}}"""


def _prom(q: str) -> list:
    try:
        r = requests.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": q}, timeout=8)
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])
    except Exception:
        return []


def collect_pod_data(namespace: str, app: str) -> str:
    lines: list[str] = []

    try:
        config.load_incluster_config()
        v1 = client.CoreV1()

        all_pods = v1.list_namespaced_pod(namespace).items
        app_pods = [
            p for p in all_pods
            if (p.metadata.labels or {}).get("app", "") == app
            or (p.metadata.labels or {}).get("app.kubernetes.io/name", "") == app
            or p.metadata.name.startswith(app + "-")
            or p.metadata.name == app
        ]

        if not app_pods:
            lines.append(f"NO PODS FOUND matching app={app} in namespace={namespace}")
        else:
            for pod in app_pods:
                phase = pod.status.phase or "Unknown"
                restarts = sum(cs.restart_count for cs in (pod.status.container_statuses or []))
                waiting = [
                    cs.state.waiting.reason
                    for cs in (pod.status.container_statuses or [])
                    if cs.state and cs.state.waiting and cs.state.waiting.reason
                ]
                lines.append(
                    f"POD {pod.metadata.name}: phase={phase} restarts={restarts}"
                    + (f" waiting={waiting}" if waiting else "")
                )

            # Recent events for the first matching pod
            try:
                first = app_pods[0].metadata.name
                events = v1.list_namespaced_event(
                    namespace,
                    field_selector=f"involvedObject.name={first}",
                )
                if events.items:
                    lines.append("RECENT_EVENTS:")
                    for evt in events.items[:8]:
                        msg = (evt.message or "")[:100]
                        lines.append(f"  [{evt.reason}] {msg}")
            except Exception:
                pass

    except Exception as e:
        lines.append(f"K8s error: {e}")

    # Prometheus: CPU and memory for this app
    cpu_results = _prom(
        f'sum(rate(container_cpu_usage_seconds_total{{pod=~".*{app}.*",namespace="{namespace}",container!=""}}[5m]))'
    )
    if cpu_results:
        millis = float(cpu_results[0]["value"][1]) * 1000
        lines.append(f"CPU: {millis:.1f}m")

    mem_results = _prom(
        f'sum(container_memory_working_set_bytes{{pod=~".*{app}.*",namespace="{namespace}",container!=""}})'
    )
    if mem_results:
        mb = float(mem_results[0]["value"][1]) / 1024 / 1024
        lines.append(f"Memory: {mb:.1f}MB")

    return "\n".join(lines)


def analyze_pod(namespace: str, app: str) -> PodInsight:
    data = collect_pod_data(namespace, app)
    prompt = _PROMPT.format(namespace=namespace, app=app, data=data)

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_ctx": 2048, "temperature": 0.1},
            },
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json().get("response", "")
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("No JSON in response")
        d = json.loads(raw[start:end])
        return PodInsight(
            namespace=namespace,
            app=app,
            analyzed_at=datetime.now(timezone.utc),
            status=d.get("status", "unknown"),
            diagnosis=d.get("diagnosis", ""),
            root_cause=d.get("root_cause", ""),
            suggestions=d.get("suggestions", []),
        )
    except Exception as e:
        log.error("Pod analysis failed for %s/%s: %s", namespace, app, e)
        return PodInsight(
            namespace=namespace,
            app=app,
            analyzed_at=datetime.now(timezone.utc),
            status="unknown",
            diagnosis=f"Analysis failed: {e}",
            root_cause="",
            suggestions=[],
        )
