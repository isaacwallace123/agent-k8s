import os
import logging
import requests
from kubernetes import client, config

log = logging.getLogger("overwatch.collector")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus.monitoring:9090")

SYSTEM_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}


def _prom_query(q: str) -> list:
    try:
        r = requests.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": q},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])
    except Exception as e:
        log.warning("Prometheus query failed (%s): %s", q[:60], e)
        return []


def collect_cluster_snapshot() -> str:
    lines: list[str] = []

    # --- Kubernetes data ---
    try:
        config.load_incluster_config()
        v1 = client.CoreV1()

        # Nodes
        nodes = v1.list_node()
        node_lines = []
        for node in nodes.items:
            ready = next(
                (c.status for c in node.status.conditions if c.type == "Ready"),
                "Unknown",
            )
            pressure = [
                c.type
                for c in node.status.conditions
                if c.type != "Ready" and c.status == "True"
            ]
            pressure_str = f" PRESSURE={','.join(pressure)}" if pressure else ""
            node_lines.append(f"  {node.metadata.name}: Ready={ready}{pressure_str}")
        lines.append(f"NODES ({len(node_lines)}):")
        lines.extend(node_lines)

        # Pods — only flag non-healthy ones to keep context short
        pods = v1.list_pod_for_all_namespaces()
        issues = []
        total_running = 0
        for pod in pods.items:
            if pod.metadata.namespace in SYSTEM_NAMESPACES:
                continue
            ns = pod.metadata.namespace
            name = pod.metadata.name
            phase = (pod.status.phase or "Unknown")

            if phase == "Running":
                total_running += 1

            restarts = sum(
                cs.restart_count for cs in (pod.status.container_statuses or [])
            )
            waiting_reasons = [
                cs.state.waiting.reason
                for cs in (pod.status.container_statuses or [])
                if cs.state and cs.state.waiting and cs.state.waiting.reason
            ]

            if phase not in ("Running", "Succeeded") or restarts > 3 or waiting_reasons:
                reason = ", ".join(waiting_reasons) if waiting_reasons else phase
                issues.append(f"  {ns}/{name}: {reason} restarts={restarts}")

        lines.append(f"RUNNING_PODS: {total_running}")
        if issues:
            lines.append(f"POD_ISSUES ({len(issues)}):")
            lines.extend(issues[:25])
        else:
            lines.append("POD_ISSUES: none")

        # Recent warning events
        try:
            events = v1.list_event_for_all_namespaces(
                field_selector="type=Warning", limit=15
            )
            if events.items:
                lines.append(f"RECENT_WARNINGS ({len(events.items)}):")
                for evt in events.items[:15]:
                    obj = evt.involved_object
                    msg = (evt.message or "")[:120]
                    lines.append(f"  {obj.namespace}/{obj.name} [{evt.reason}]: {msg}")
        except Exception as e:
            log.warning("Failed to fetch events: %s", e)

    except Exception as e:
        log.error("K8s collection error: %s", e)
        lines.append(f"K8S_ERROR: {e}")

    # --- Prometheus data ---
    # Node CPU usage
    cpu_results = _prom_query(
        '100 - (avg by (node) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)'
    )
    if cpu_results:
        lines.append("NODE_CPU_PERCENT:")
        for r in cpu_results:
            node = r["metric"].get("node", r["metric"].get("instance", "?"))
            val = float(r["value"][1])
            lines.append(f"  {node}: {val:.1f}%")

    # Node memory usage
    mem_results = _prom_query(
        "(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100"
    )
    if mem_results:
        lines.append("NODE_MEMORY_PERCENT:")
        for r in mem_results:
            instance = r["metric"].get("node", r["metric"].get("instance", "?"))
            val = float(r["value"][1])
            lines.append(f"  {instance}: {val:.1f}%")

    return "\n".join(lines)
