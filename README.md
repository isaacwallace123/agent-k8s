# homelab-ai

Personal local AI/coder-agent platform running on a two-node Proxmox/k3s homelab cluster.

**Philosophy**: Effective long context via retrieval, summarization, and session memory — not brute-force 500K+ token windows.

---

## Architecture

See [docs/architecture.md](docs/architecture.md) for full details.

**Summary**:
- `pve1` — Hot inference node: main LLM (Arc B580), Qdrant (NVMe), Postgres (NVMe), Redis
- `pve2` — Compute node: embeddings worker (Arc A380), summarizer, background processing

All workloads are pinned to the correct node via the `proxmox-host` label.

---

## Repository Structure

```
agent-k8s/
├── argocd/
│   └── application.yaml        # ArgoCD Application — point at your Git remote
├── charts/
│   └── homelab-ai/
│       ├── Chart.yaml
│       ├── values.yaml         # All config lives here — one chart, one values file
│       └── templates/
│           ├── _helpers.tpl
│           ├── namespace.yaml
│           ├── llm/            # Main Ollama instance (pve1)
│           ├── embeddings/     # Embeddings Ollama instance (pve2)
│           ├── summarizer/     # Summarizer Ollama instance (pve2)
│           ├── vectordb/       # Qdrant (pve1 NVMe)
│           ├── postgres/       # PostgreSQL (pve1 NVMe)
│           └── redis/          # Redis (pve1)
├── docs/
│   └── architecture.md
└── .gitignore
```

---

## Prerequisites

1. **k3s cluster** running across pve1 and pve2
2. **ArgoCD** installed in the `argocd` namespace
3. **Node labels** applied:
   ```bash
   kubectl label node <pve1-node-name> proxmox-host=pve1
   kubectl label node <pve2-node-name> proxmox-host=pve2
   ```
4. Git remote configured (GitHub, Gitea, etc.)

---

## Deploying with ArgoCD

### 1. Push this repo to Git

```bash
cd agent-k8s
git init
git remote add origin https://github.com/isaacwallace123/agent-k8s.git
git add .
git commit -m "initial scaffold"
git push -u origin main
```

### 2. Register the repo with ArgoCD (if private)

```bash
argocd repo add https://github.com/isaacwallace123/agent-k8s.git \
  --username isaacwallace123 \
  --password YOUR_TOKEN
```

### 3. Apply the Application manifest

The Application is already registered in the homelab-k8s repo at
`argocd/apps/applications.yaml`. Once you push this repo, ArgoCD will
auto-discover and sync it via the App-of-Apps root app.

Alternatively, apply it directly (bypassing homelab-k8s):

```bash
kubectl apply -f argocd/application.yaml -n argocd
```

ArgoCD will sync the chart and create all resources in the `homelab-ai` namespace.

### 4. Pull models into Ollama

After pods are Running, exec into each Ollama pod and pull models:

```bash
# Main LLM on pve1 (Arc B580 12GB — 14B fits fully in VRAM at ~8.5GB Q4_K_M)
kubectl exec -n homelab-ai deploy/llm -- ollama pull qwen2.5-coder:14b

# Optional: pull 32B for heavy tasks (will partially offload to CPU RAM — slow)
# kubectl exec -n homelab-ai deploy/llm -- ollama pull qwen2.5-coder:32b

# Embeddings on pve2
kubectl exec -n homelab-ai deploy/embeddings -- ollama pull nomic-embed-text

# Summarizer on pve2
kubectl exec -n homelab-ai deploy/summarizer -- ollama pull qwen2.5:7b
```

---

## Customizing Values

All configuration lives in `charts/homelab-ai/values.yaml`.

### Disable a component

```yaml
summarizer:
  enabled: false
```

### Change a model

```yaml
llm:
  defaultModel: "llama3.1:70b"
```

### Use a different storage class

```yaml
global:
  storageClass: longhorn

# Or per-component:
vectordb:
  storage:
    storageClass: local-path-nvme
```

### Override PVC sizes

```yaml
llm:
  storage:
    size: 500Gi

vectordb:
  storage:
    size: 200Gi
```

### Set Postgres password (never commit this)

Create a `values-secret.yaml` (already gitignored):

```yaml
# values-secret.yaml — DO NOT COMMIT
postgres:
  auth:
    password: "your-actual-password"
```

Then apply via Helm directly (not ArgoCD) if you want to keep it local, or use Sealed Secrets / External Secrets Operator for GitOps-safe secret management.

### Change node assignments

```yaml
global:
  pve1: pve1   # change to your actual node name
  pve2: pve2
```

---

## Storage Strategy

| PVC              | Size    | Node  | Device       | Purpose                    |
|------------------|---------|-------|--------------|----------------------------|
| llm-models       | 200Gi   | pve1  | SATA SSD     | Ollama model files         |
| embeddings-models| 20Gi    | pve2  | SATA SSD     | Embedding model files      |
| summarizer-models| 30Gi    | pve2  | SATA SSD     | Summarizer model files     |
| vectordb-storage | 100Gi   | pve1  | NVMe         | Qdrant collections         |
| postgres-data    | 50Gi    | pve1  | NVMe         | PostgreSQL data directory  |
| redis-data       | 10Gi    | pve1  | NVMe         | Redis AOF/RDB snapshots    |

> With `local-path` storage class, PVCs bind to the node where the pod first schedules. Node selectors ensure pods (and thus PVCs) always land on the correct node.

---

## Extending the Platform

To add a new component (e.g. a repo indexer):

1. Add a block to `values.yaml`:
   ```yaml
   indexer:
     enabled: false
     image:
       repository: your-registry/indexer
       tag: latest
     ...
   ```

2. Create `templates/indexer/deployment.yaml`, `service.yaml`, `pvc.yaml`

3. Use `{{- include "homelab-ai.nodeSelectorPve2" . | nindent 8 }}` in the deployment to pin it to pve2

4. Commit and push — ArgoCD deploys automatically

Planned future components: `reranker`, `ocr`, `stt`, `indexer`, `agent-api`, `webui`.
