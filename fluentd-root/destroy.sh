#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

RELEASE_NAME="${RELEASE_NAME:-efk-stack}"
NAMESPACE="${NAMESPACE:-default}"

echo -e "${YELLOW}Destroying EFK Stack and all resources (including PVCs)${NC}"
echo "Release Name: ${RELEASE_NAME}"
echo "Namespace: ${NAMESPACE}"
echo ""

if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed or not in PATH${NC}"
    exit 1
fi

if ! command -v helm &> /dev/null; then
    echo -e "${RED}Error: helm is not installed or not in PATH${NC}"
    exit 1
fi

RELEASES=(
    "${RELEASE_NAME}-ingress"
    "${RELEASE_NAME}-log-generator"
    "${RELEASE_NAME}-httpd"
    "${RELEASE_NAME}-kibana"
    "${RELEASE_NAME}-fluentd"
    "${RELEASE_NAME}-elasticsearch"
)

echo -e "${GREEN}Uninstalling Helm releases...${NC}"
for rel in "${RELEASES[@]}"; do
    if helm status "$rel" --namespace "$NAMESPACE" &> /dev/null; then
        echo "  Uninstalling $rel"
        helm uninstall "$rel" --namespace "$NAMESPACE" --wait --timeout 2m || true
    else
        echo "  Skip $rel (not found)"
    fi
done

echo ""
echo -e "${GREEN}Deleting PVCs...${NC}"
ES_PVC="${RELEASE_NAME}-elasticsearch-data"
if kubectl get pvc "$ES_PVC" --namespace "$NAMESPACE" &> /dev/null; then
    echo "  Deleting PVC $ES_PVC"
    kubectl delete pvc "$ES_PVC" --namespace "$NAMESPACE" --ignore-not-found=true --wait=true
else
    echo "  PVC $ES_PVC not found (already deleted or never created)"
fi

# Delete any other PVCs that might match our release (e.g. if more are added later)
while IFS= read -r pvc; do
    [ -z "$pvc" ] && continue
    echo "  Deleting $pvc"
    kubectl delete "$pvc" --namespace "$NAMESPACE" --ignore-not-found=true --wait=true
done < <(kubectl get pvc --namespace "$NAMESPACE" -o name 2>/dev/null | grep -E "${RELEASE_NAME}-" || true)

echo ""
echo -e "${GREEN}Destroy complete.${NC}"
echo "All releases and the Elasticsearch data PVC have been removed from namespace ${NAMESPACE}."
