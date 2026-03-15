import os
import time
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from models import Insight, PodInsight
from collector import collect_cluster_snapshot
from analyzer import analyze
from pod_analyzer import analyze_pod, discover_apps
from database import init_db, save_insight, load_latest, load_history

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("overwatch")

INTERVAL = int(os.getenv("INTERVAL_SECONDS", "300"))
POD_SCAN_INTERVAL = int(os.getenv("POD_SCAN_INTERVAL_SECONDS", "600"))
POD_CACHE_TTL = 600  # seconds

# In-memory pod insight cache: "namespace/app" -> (PodInsight, timestamp)
_pod_cache: dict[str, tuple[PodInsight, float]] = {}

# In-memory cache — always holds the most recent insight
_latest: Insight | None = None


async def run_analysis():
    global _latest
    log.info("Starting analysis cycle...")
    try:
        snapshot = await asyncio.get_event_loop().run_in_executor(
            None, collect_cluster_snapshot
        )
        log.info("Snapshot collected (%d chars), calling LLM...", len(snapshot))
        insight = await asyncio.get_event_loop().run_in_executor(None, analyze, snapshot)
        _latest = insight
        await asyncio.get_event_loop().run_in_executor(None, save_insight, insight)
        log.info(
            "Analysis complete: status=%s anomalies=%d",
            insight.status,
            len(insight.anomalies),
        )
    except Exception as e:
        log.error("Analysis cycle failed: %s", e)


async def _scheduler():
    while True:
        await run_analysis()
        await asyncio.sleep(INTERVAL)


async def run_pod_scan():
    apps = await asyncio.get_event_loop().run_in_executor(None, discover_apps)
    log.info("Pod scan: discovered %d apps", len(apps))
    for ns, app in apps:
        cache_key = f"{ns}/{app}"
        cached = _pod_cache.get(cache_key)
        if cached:
            _, ts = cached
            if time.time() - ts < POD_CACHE_TTL:
                continue
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, analyze_pod, ns, app)
            _pod_cache[cache_key] = (result, time.time())
            log.info("Pod scan: %s/%s -> %s", ns, app, result.status)
        except Exception as e:
            log.error("Pod scan failed for %s/%s: %s", ns, app, e)


async def _pod_scheduler():
    await asyncio.sleep(60)  # let the cluster settle on startup
    while True:
        await run_pod_scan()
        await asyncio.sleep(POD_SCAN_INTERVAL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _latest
    # Init DB and restore last insight so the API is not empty on restart
    await asyncio.get_event_loop().run_in_executor(None, init_db)
    try:
        _latest = await asyncio.get_event_loop().run_in_executor(None, load_latest)
        if _latest:
            log.info("Restored last insight from DB (status=%s)", _latest.status)
    except Exception:
        pass
    task = asyncio.create_task(_scheduler())
    pod_task = asyncio.create_task(_pod_scheduler())
    yield
    task.cancel()
    pod_task.cancel()
    for t in (task, pod_task):
        try:
            await t
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Project Overwatch", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/insights")
def insights():
    if _latest is None:
        return {
            "status": "pending",
            "summary": "First analysis in progress, check back in a few minutes.",
            "anomalies": [],
            "recommendations": [],
            "collected_at": None,
        }
    return _latest


@app.get("/history")
def history(limit: int = 48):
    return load_history(min(limit, 200))


@app.get("/pod-insights/all")
def all_pod_insights():
    return [insight.model_dump() for insight, _ in _pod_cache.values()]


@app.get("/pod-insights")
async def pod_insights(namespace: str, app: str):
    if not namespace or not app:
        raise HTTPException(status_code=400, detail="namespace and app are required")
    cache_key = f"{namespace}/{app}"
    cached = _pod_cache.get(cache_key)
    if cached:
        insight, ts = cached
        if time.time() - ts < POD_CACHE_TTL:
            return insight
    result = await asyncio.get_event_loop().run_in_executor(None, analyze_pod, namespace, app)
    _pod_cache[cache_key] = (result, time.time())
    return result
