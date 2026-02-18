#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
RELEASE_NAME="${RELEASE_NAME:-efk-stack}"
NAMESPACE="${NAMESPACE:-default}"
FLUENTD_IMAGE="${FLUENTD_IMAGE:-fluentd:latest}"

echo -e "${GREEN}Deploying EFK Stack to Kubernetes${NC}"
echo "Release Name: ${RELEASE_NAME}"
echo "Namespace: ${NAMESPACE}"
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed or not in PATH${NC}"
    exit 1
fi

# Check if helm is available
if ! command -v helm &> /dev/null; then
    echo -e "${RED}Error: helm is not installed or not in PATH${NC}"
    exit 1
fi

# Check if we can connect to Kubernetes cluster
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to Kubernetes cluster${NC}"
    exit 1
fi

# Create namespace if it doesn't exist
if ! kubectl get namespace "${NAMESPACE}" &> /dev/null; then
    echo -e "${YELLOW}Creating namespace: ${NAMESPACE}${NC}"
    kubectl create namespace "${NAMESPACE}"
fi

# Build fluentd image if Docker is available
if command -v docker &> /dev/null && [ -f "./fluentd/Dockerfile" ]; then
    echo -e "${YELLOW}Building Fluentd image...${NC}"
    docker build -t "${FLUENTD_IMAGE}" ./fluentd
    
    # Try to load image into cluster (works for kind/minikube)
    if kubectl get nodes -o jsonpath='{.items[0].metadata.name}' &> /dev/null; then
        NODE_NAME=$(kubectl get nodes -o jsonpath='{.items[0].metadata.name}')
        if [[ "${NODE_NAME}" == *"kind"* ]] || [[ "${NODE_NAME}" == *"minikube"* ]]; then
            echo -e "${YELLOW}Loading image into cluster...${NC}"
            if command -v kind &> /dev/null && [[ "${NODE_NAME}" == *"kind"* ]]; then
                kind load docker-image "${FLUENTD_IMAGE}" || true
            elif command -v minikube &> /dev/null && [[ "${NODE_NAME}" == *"minikube"* ]]; then
                eval "$(minikube docker-env)" && docker build -t "${FLUENTD_IMAGE}" ./fluentd || true
            fi
        fi
    fi
    echo -e "${GREEN}Fluentd image built: ${FLUENTD_IMAGE}${NC}"
    echo -e "${YELLOW}Note: If using a remote cluster, push the image to a registry and update charts/fluentd/values.yaml${NC}"
else
    echo -e "${YELLOW}Skipping Fluentd image build (Docker not available or Dockerfile not found)${NC}"
    echo -e "${YELLOW}Using image from charts/fluentd/values.yaml${NC}"
fi

# Update fluentd image in values if we built it
if [ -n "${FLUENTD_IMAGE}" ] && [ "${FLUENTD_IMAGE}" != "fluentd:latest" ]; then
    # Extract image name and tag
    if [[ "${FLUENTD_IMAGE}" == *":"* ]]; then
        IMAGE_NAME="${FLUENTD_IMAGE%%:*}"
        IMAGE_TAG="${FLUENTD_IMAGE##*:}"
    else
        IMAGE_NAME="${FLUENTD_IMAGE}"
        IMAGE_TAG="latest"
    fi
fi

# Deploy Elasticsearch first (dependency for others)
echo -e "${GREEN}Deploying Elasticsearch...${NC}"
helm upgrade --install "${RELEASE_NAME}-elasticsearch" ./charts/elasticsearch \
    --namespace "${NAMESPACE}" \
    --wait \
    --timeout 5m

# Wait for Elasticsearch to be ready
echo -e "${YELLOW}Waiting for Elasticsearch to be ready...${NC}"
kubectl wait --for=condition=available \
    --timeout=300s \
    deployment/"${RELEASE_NAME}-elasticsearch" \
    -n "${NAMESPACE}" || true

# Deploy Fluentd
echo -e "${GREEN}Deploying Fluentd...${NC}"
ES_SERVICE_NAME="${RELEASE_NAME}-elasticsearch"
if [ -n "${FLUENTD_IMAGE}" ] && [[ "${FLUENTD_IMAGE}" == *":"* ]]; then
    IMAGE_NAME="${FLUENTD_IMAGE%%:*}"
    IMAGE_TAG="${FLUENTD_IMAGE##*:}"
    helm upgrade --install "${RELEASE_NAME}-fluentd" ./charts/fluentd \
        --namespace "${NAMESPACE}" \
        --set image.repository="${IMAGE_NAME}" \
        --set image.tag="${IMAGE_TAG}" \
        --set stackName="${RELEASE_NAME}" \
        --set elasticsearch.host="${ES_SERVICE_NAME}" \
        --wait \
        --timeout 5m
else
    helm upgrade --install "${RELEASE_NAME}-fluentd" ./charts/fluentd \
        --namespace "${NAMESPACE}" \
        --set stackName="${RELEASE_NAME}" \
        --set elasticsearch.host="${ES_SERVICE_NAME}" \
        --wait \
        --timeout 5m
fi

# Deploy Kibana
echo -e "${GREEN}Deploying Kibana...${NC}"
helm upgrade --install "${RELEASE_NAME}-kibana" ./charts/kibana \
    --namespace "${NAMESPACE}" \
    --set stackName="${RELEASE_NAME}" \
    --set elasticsearch.host="${ES_SERVICE_NAME}" \
    --wait \
    --timeout 5m

# Deploy HTTPD
echo -e "${GREEN}Deploying HTTPD...${NC}"
helm upgrade --install "${RELEASE_NAME}-httpd" ./charts/httpd \
    --namespace "${NAMESPACE}" \
    --set stackName="${RELEASE_NAME}" \
    --set logging.fluentdAddress="${RELEASE_NAME}-fluentd:24224" \
    --wait \
    --timeout 5m

# Deploy Log Generator (emits a log line every 5 seconds)
echo -e "${GREEN}Deploying Log Generator...${NC}"
helm upgrade --install "${RELEASE_NAME}-log-generator" ./charts/log-generator \
    --namespace "${NAMESPACE}" \
    --wait \
    --timeout 5m

# Deploy Ingress (Kibana at kibana.local)
echo -e "${GREEN}Deploying Ingress (kibana.local)...${NC}"
helm upgrade --install "${RELEASE_NAME}-ingress" ./charts/ingress \
    --namespace "${NAMESPACE}" \
    --set kibana.serviceName="${RELEASE_NAME}-kibana" \
    --set kibana.servicePort=5601 \
    --wait \
    --timeout 2m

# ---------------------------------------------------------------------------
# Health and readiness: wait for all workloads to be ready
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}Waiting for all workloads to be ready...${NC}"
kubectl wait --for=condition=available \
    --timeout=300s \
    deployment/"${RELEASE_NAME}-elasticsearch" \
    deployment/"${RELEASE_NAME}-kibana" \
    deployment/"${RELEASE_NAME}-httpd" \
    deployment/"${RELEASE_NAME}-log-generator" \
    -n "${NAMESPACE}" || true
kubectl wait --for=condition=ready \
    --timeout=300s \
    daemonset/"${RELEASE_NAME}-fluentd" \
    -n "${NAMESPACE}" || true

# ---------------------------------------------------------------------------
# Smoke tests: verify services respond
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}Running smoke tests...${NC}"
SMOKE_POD="smoke-test-$$"
ES_SVC="${RELEASE_NAME}-elasticsearch"
KB_SVC="${RELEASE_NAME}-kibana"
HTTPD_SVC="${RELEASE_NAME}-httpd"

kubectl run "${SMOKE_POD}" --restart=Never --image=curlimages/curl:latest \
    --namespace "${NAMESPACE}" -- sleep 120
trap "kubectl delete pod ${SMOKE_POD} -n ${NAMESPACE} --ignore-not-found=true --wait=false 2>/dev/null" EXIT

echo -n "  Waiting for smoke-test pod..."
for _ in $(seq 1 30); do
    if kubectl get pod "${SMOKE_POD}" -n "${NAMESPACE}" -o jsonpath='{.status.phase}' 2>/dev/null | grep -q Running; then
        echo " ready."
        break
    fi
    sleep 2
done
if ! kubectl get pod "${SMOKE_POD}" -n "${NAMESPACE}" &>/dev/null; then
    echo -e " ${RED}failed to start.${NC}"
    exit 1
fi

FAIL=0
if ! kubectl exec "${SMOKE_POD}" -n "${NAMESPACE}" -- curl -sf "http://${ES_SVC}:9200/_cluster/health" | grep -qE '"status":"(green|yellow)"'; then
    echo -e "  ${RED}Elasticsearch: FAIL${NC}"
    FAIL=1
else
    echo -e "  ${GREEN}Elasticsearch: OK${NC}"
fi
if ! kubectl exec "${SMOKE_POD}" -n "${NAMESPACE}" -- curl -sf "http://${KB_SVC}:5601/api/status" >/dev/null; then
    echo -e "  ${RED}Kibana: FAIL${NC}"
    FAIL=1
else
    echo -e "  ${GREEN}Kibana: OK${NC}"
fi
if ! kubectl exec "${SMOKE_POD}" -n "${NAMESPACE}" -- curl -sf "http://${HTTPD_SVC}:8888/" >/dev/null; then
    echo -e "  ${RED}HTTPD: FAIL${NC}"
    FAIL=1
else
    echo -e "  ${GREEN}HTTPD: OK${NC}"
fi

if [ "$FAIL" -ne 0 ]; then
    echo -e "${RED}Smoke test failed. Check pods and services:${NC}"
    echo "  kubectl get pods -n ${NAMESPACE}"
    echo "  kubectl get svc -n ${NAMESPACE}"
    exit 1
fi

echo ""
echo -e "${GREEN}Deployment complete!${NC}"
echo ""
echo "Services deployed:"
echo "  - Elasticsearch: ${RELEASE_NAME}-elasticsearch"
echo "  - Fluentd: ${RELEASE_NAME}-fluentd"
echo "  - Kibana: ${RELEASE_NAME}-kibana"
echo "  - HTTPD: ${RELEASE_NAME}-httpd"
echo "  - Log Generator: ${RELEASE_NAME}-log-generator"
echo "  - Ingress: ${RELEASE_NAME}-ingress (Kibana at http://kibana.local)"
echo ""
echo "To check status:"
echo "  kubectl get pods -n ${NAMESPACE}"
echo ""
echo "Access Kibana:"
echo "  http://kibana.local  (ensure /etc/hosts or DNS points kibana.local to ingress)"
echo ""
echo "Or use port-forward:"
echo "  kubectl port-forward -n ${NAMESPACE} svc/${RELEASE_NAME}-elasticsearch 9200:9200"
echo "  kubectl port-forward -n ${NAMESPACE} svc/${RELEASE_NAME}-kibana 5601:5601"
echo "  kubectl port-forward -n ${NAMESPACE} svc/${RELEASE_NAME}-httpd 8888:8888"
echo ""
echo "To setup Kibana dashboards:"
echo "  KIBANA_URL=http://kibana.local python3 setup-kibana.py"
echo "  (or use port-forward and default http://localhost:5601)"
