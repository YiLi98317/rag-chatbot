# Deployment (local K8s) — v0

This repo ships K8s manifests for the **API** and documents installing **Milvus** via Helm (recommended).

## Prereqs

- A local cluster: **kind**, **k3d**, or **minikube**
- `kubectl`, `helm`
- Your Ollama endpoint reachable from the cluster (in-cluster Ollama is out of scope; you can run it separately)

## Install Milvus (Helm)

Milvus Helm charts live under the `zilliztech` repo.

```bash
helm repo add zilliztech https://zilliztech.github.io/milvus-helm/
helm repo update
helm install milvus zilliztech/milvus -f deploy/milvus-values.yaml
```

Wait for Milvus pods to be Ready:

```bash
kubectl get pods -w
```

## Deploy the API

1) Build/publish the API image so your cluster can pull it.

- **kind** example (load local image):

```bash
docker build -t chatbot-api:local .
kind load docker-image chatbot-api:local
```

2) Apply manifests:

```bash
kubectl apply -f k8s/api/
kubectl get pods -w
```

3) Port-forward for local testing:

```bash
kubectl port-forward svc/chatbot-api 8000:8000
curl http://localhost:8000/healthz
curl http://localhost:8000/readyz
```

## Notes

- `k8s/api/configmap.yaml` assumes Milvus is reachable at `http://milvus:19530`. If you installed the chart with a different service name/namespace, update `MILVUS_URI` accordingly.
- `OLLAMA_BASE_URL` must be reachable from inside the cluster; for local K8s you can expose Ollama via a `Service` or use your cluster’s host networking solutions.
