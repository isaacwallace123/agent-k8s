# homelab-ai Architecture

## Overview

homelab-ai is a personal local AI/coder-agent platform deployed on a two-node Proxmox/k3s homelab cluster. It is designed for **effective long context** using retrieval, summaries, and session memory rather than brute-force 500K+ token windows.

## Node Roles

| Node  | Hardware                          | Role                                              |
|-------|-----------------------------------|---------------------------------------------------|
| pve1  | Intel Arc B580 12GB, 128GB DDR4   | Hot inference, vector DB, Postgres, Redis, cache  |
| pve2  | Intel Arc A380 6GB, 64GB DDR4     | Embeddings, summarizer, background workers        |

### pve1 Storage
| Device             | Use                                          |
|--------------------|----------------------------------------------|
| 1TB WD SN770 NVMe  | Vector DB, Postgres, Redis AOF               |
| 1TB Micron SATA    | Ollama model files (LLM)                     |
| 2TB Seagate HDD    | Backups, cold data snapshots                 |

### pve2 Storage
| Device             | Use                                          |
|--------------------|----------------------------------------------|
| 500GB SATA SSD     | Embeddings/summarizer model files            |
| 8TB Seagate HDD    | Cold archive, raw corpora staging            |

> pve2 has **no NVMe** — it is a compute/support node, not a hot-storage node.

## Services

```
┌─────────────────────────── pve1 ──────────────────────────────┐
│  llm          Ollama (qwen2.5-coder:32b)    :11434            │
│  vectordb     Qdrant                         :6333 :6334       │
│  postgres     PostgreSQL 16                  :5432             │
│  redis        Redis 7                        :6379             │
└────────────────────────────────────────────────────────────────┘
┌─────────────────────────── pve2 ──────────────────────────────┐
│  embeddings   Ollama (nomic-embed-text)      :11435            │
│  summarizer   Ollama (qwen2.5:7b)            :11436            │
└────────────────────────────────────────────────────────────────┘
```

### Service DNS names (within cluster)
All services use ClusterIP and are reachable by name within the `homelab-ai` namespace:

| Service    | DNS                                          | Port  |
|------------|----------------------------------------------|-------|
| llm        | `llm.homelab-ai.svc.cluster.local`           | 11434 |
| embeddings | `embeddings.homelab-ai.svc.cluster.local`    | 11435 |
| summarizer | `summarizer.homelab-ai.svc.cluster.local`    | 11436 |
| vectordb   | `vectordb.homelab-ai.svc.cluster.local`      | 6333  |
| postgres   | `postgres.homelab-ai.svc.cluster.local`      | 5432  |
| redis      | `redis.homelab-ai.svc.cluster.local`         | 6379  |

## Effective Long Context Strategy

Instead of a single 1M-token context window, the platform uses a layered memory architecture:

1. **Active session context** — Redis (fast ephemeral state, sliding window)
2. **Session summaries** — Summarizer compresses old turns into dense summaries stored in Postgres
3. **Semantic retrieval** — Embeddings + Qdrant enables retrieval of relevant past context chunks
4. **Repo memory** — Indexed repo state stored in Qdrant, refreshed by the embeddings worker

This keeps the main LLM's context window filled with *relevant* content, not stale scrollback.

## Future Extensions

The chart is designed to grow. Adding new components is a matter of:
1. Adding a new `enabled: true` block in `values.yaml`
2. Adding `templates/<component>/deployment.yaml + service.yaml + pvc.yaml`
3. Setting `nodeSelector` via the pve1/pve2 helpers

Planned future components:
- `reranker` — cross-encoder reranker (pve1 or pve2)
- `ocr` — Tesseract/PaddleOCR ingestion worker (pve2)
- `stt` — Whisper speech-to-text (pve2)
- `indexer` — repo crawler and chunker (pve2)
- `agent-api` — FastAPI orchestration layer (pve1)
- `webui` — Open WebUI or custom frontend (pve1)
