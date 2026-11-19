# Kubernetes Deployment & Horizontal Pod Autoscaler (HPA) Guide

This document explains the 3-node KIND cluster architecture, resource management (`requests` vs. `limits`), Metrics Server configuration, and verified Horizontal Pod Autoscaling (HPA) results for the **AI Ops Platform**.

---

## 1. Cluster Topology (`k8s/kind-config.yaml`)

- **Cluster tool**: KIND (`kind v0.33.0`, node image `kindest/node:v1.37.0`)
- **Nodes**: `1 control-plane` (`ai-ops-control-plane`) + `2 workers` (`ai-ops-worker`, `ai-ops-worker2`)
- **Networking**: KIND uses `NodePort` services (`30081` → `8001`, `30082` → `8002`, `30083` → `8003`) mapped via `extraPortMappings` on `ai-ops-control-plane` instead of `LoadBalancer`, because KIND does not provision external LoadBalancer IPs out of the box. Internal microservice calls use Kubernetes `ClusterIP` DNS (`http://usage-service:8000`, `http://cost-service:8000`, `postgres-db:5432`).

---

## 2. Architecture & Data Isolation

- **3 Microservices**: `agent-service`, `usage-service`, `cost-service` (stateless pods scaled independently by HPA).
- **1 Infrastructure Database**: `postgres-db` (`replicas: 1`, `Recreate` strategy, `1Gi` PVC, no HPA) hosting `agentdb`, `usagedb`, and `costdb`.
- **Execution flow**: `Client → agent-service → usage-service → cost-service → Response`.

---

## 3. Requests vs. Limits (and Why Capacity Calibration Matters)

In Kubernetes:
- **Resource Requests** (`resources.requests`): The guaranteed minimum CPU and memory reserved for scheduling a pod onto a node.
  - **Crucial for HPA**: Kubernetes HPA calculates CPU utilization using **`(Actual Pod CPU Usage / pod.spec.containers[].resources.requests.cpu) × 100`**, *not* `limits.cpu`. If `requests.cpu` is omitted, HPA reports `<unknown>`.
- **Resource Limits** (`resources.limits`): The hard ceiling enforced by the Linux kernel cgroup.
  - Exceeding **CPU limit** results in **CPU throttling** (slower responses, no pod kill).
  - Exceeding **Memory limit** triggers an **`OOMKilled` (exit code 137)** container termination.

### Capacity Check on This Host (16 GB RAM / `7.642 GiB` Docker Desktop VM)
- Assigning `500m` CPU / `512Mi` memory requests to 14 max-HPA app pods plus `500m` / `1Gi` for Postgres would total **`7,500m` CPU and `8,192 MiB` (`8.0 GiB`) memory requests**, exceeding Docker Desktop's `7.642 GiB` Linux VM RAM (and leaving zero room for `kube-system` / KIND control plane pods), causing `Pending` pods under scale-up.
- **Calibrated allocation deployed in [`k8s/`](../k8s/)**:

| Component | Min / Max Replicas | CPU Request / Limit | Memory Request / Limit | Max Total Requests |
|---|---:|---|---|---|
| `agent-service` | 1 / 5 | `250m` / `2000m` | `256Mi` / `1Gi` | `1,250m` CPU, `1,280Mi` RAM |
| `usage-service` | 1 / 5 | `250m` / `2000m` | `256Mi` / `1Gi` | `1,250m` CPU, `1,280Mi` RAM |
| `cost-service` | 1 / 4 | `250m` / `1500m` | `256Mi` / `1Gi` | `1,000m` CPU, `1,024Mi` RAM |
| `postgres-db` | 1 / 1 (no HPA) | `500m` / `2000m` | `1Gi` / `2Gi` | `500m` CPU, `1,024Mi` RAM |
| **Max Cluster Total (15 pods)** | **15** | — | — | **`4,000m` CPU, `4.5 GiB` RAM** |

This preserves ~3 GiB inside the Docker VM for KIND system pods and host stability while giving every microservice 4×–15× its measured baseline memory (`~64–70 MiB` per app pod, `~113–216 MiB` for Postgres).

---

## 4. HPA & Metrics Server Configuration

- **Metrics Server**: Installed in `kube-system` ([`k8s/00-metrics-server.yaml`](../k8s/00-metrics-server.yaml)) with `--kubelet-insecure-tls`, `--kubelet-preferred-address-types=InternalIP,ExternalIP,Hostname`, and `--metric-resolution=15s`.
- **HPA (`autoscaling/v2`)** ([`k8s/06-hpa.yaml`](../k8s/06-hpa.yaml)):
  - Target: `averageUtilization: 50` (`125m` per `250m`-request pod)
  - Scale-up: `stabilizationWindowSeconds: 0` (`100%` or `+2` pods per `15s`)
  - Scale-down: `stabilizationWindowSeconds: 60` (`-2` pods per `15s`) for observable live scale-down during viva demonstrations.

---

## 5. Measured Live HPA Results

1. **Baseline (1 replica each)**:
   - `agent-service`: `0–2%` (`2m` CPU, `64–69Mi` RAM)
   - `usage-service`: `0–4%` (`2m` CPU, `63–67Mi` RAM)
   - `cost-service`: `0–3%` (`2m` CPU, `60–63Mi` RAM)
   - `postgres-db`: `7–10m` CPU, `59–61Mi` RAM
2. **Scale-Up Under Real `POST /agents/{id}/run` Load (`concurrency=48`, 75.4s, 5,796 requests, 0 errors)**:
   - At `T+45s`: `agent-service` `163%/50%` (`408m`) → `3`, `usage-service` `108%/50%` (`272m`) → `3`, `cost-service` `84%/50%` (`211m`) → `2`
   - At `T+60s`: `agent-service` `240%/50%` (`601m`), `usage-service` `284%/50%` (`711m`), `cost-service` `212%/50%` (`530m`)
   - At `T+75s`: Reached max replicas **`5 / 5 / 4`** across `ai-ops-worker` and `ai-ops-worker2` (`15` total pods `Running`, `0` restarts, `0` `Pending`, `0` `OOMKilled`).
   - Node host RAM usage at max scale: `control-plane 939.3MiB`, `worker 952MiB`, `worker2 987.3MiB` (`~2.88 GiB / 7.642 GiB`).
   - Second 60s latency window run (`concurrency=48`, 4,258 requests, 0 errors): window `avg_ms` dropped from **`808.6 ms`** (`t=36s`, during scale-up) to **`431.6 ms`** (`t=51s`, `111.1 rps`) as new pods joined rotation.
3. **Automatic Scale-Down**:
   - At `T+60s` after stopping load: `5 → 3`, `5 → 3`, `4 → 2`.
   - At `T+100s` after stopping load: all three returned cleanly to **`1 / 1 / 1`** replicas (`0–1%` CPU), and post-scale-down `POST /agents/1/run` succeeded (`status=success`).
