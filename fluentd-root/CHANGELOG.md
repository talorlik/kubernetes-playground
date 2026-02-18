# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added

- Converted Docker Compose stack to Kubernetes Helm Charts
- Created separate Helm charts for each service:
  - `charts/elasticsearch/` - Elasticsearch service chart
  - `charts/fluentd/` - Fluentd log aggregator chart (DaemonSet)
  - `charts/httpd/` - Apache HTTP server chart
  - `charts/kibana/` - Kibana visualization chart
  - `charts/log-generator/` - Log generator service (emits a log every 5
    seconds)
  - `charts/ingress/` - Ingress chart (Kibana at kibana.local)
- Added `deploy.sh` script for automated Kubernetes deployment
- Added `docker-compose-k8s.yaml` for Kubernetes conversion (excludes
  portainer)
- Each chart includes:
  - `Chart.yaml` - Chart metadata
  - `values.yaml` - Default configuration values
  - `templates/` - Kubernetes manifest templates
  - `templates/_helpers.tpl` - Helm template helpers
- Comprehensive log collection in Fluentd:
  - Container/pod logs: tails `/var/log/containers/*.log` on each node
  - Node (host) logs: tails `/var/log/syslog` and `/var/log/messages`
  - Systemd journal: reads from `/var/log/journal` and `/run/log/journal`
    (kubelet, runtime, control-plane components)
  - Forward protocol: continues to accept logs on port 24224
- Fluentd Dockerfile enhancements:
  - Added `libsystemd-dev` for systemd journal support
  - Added `fluent-plugin-systemd` gem (v1.0.3)
- Kibana setup script (`setup-kibana.py`) improvements:
  - Predefined common index patterns via `COMMON_INDEX_PATTERNS` list
  - Automatically sets default index pattern when supported
  - Supports `KIBANA_URL` environment variable for remote/port-forward
    access
- Ingress support:
  - Kibana accessible at `http://kibana.local` via Ingress
  - Configurable ingress class (default: nginx)
  - Optional TLS and annotations support
- Elasticsearch persistence and log rotation:
  - PersistentVolumeClaim (default 150Mi) for Elasticsearch data
  - CronJob deletes oldest `fluentd-*` indices when total size exceeds
    configured limit (default 140MB), so logs persist within the cap and
    old data is overridden when the limit is reached
- Added `destroy.sh` script to tear down the stack and delete PVCs (uses
  same `RELEASE_NAME` and `NAMESPACE` as `deploy.sh`)
- Health and readiness probes on all workloads:
  - Kibana: httpGet `/api/status` (liveness and readiness)
  - HTTPD: httpGet `/` (liveness and readiness)
  - Fluentd: tcpSocket port 24224 (liveness and readiness)
  - Log-generator: exec liveness (process check)
  - Elasticsearch: existing exec cluster-health probes unchanged
- Deploy script smoke tests: after deployment, runs a temporary curl pod
  to verify Elasticsearch cluster health, Kibana `/api/status`, and HTTPD
  respond; script exits with error if any check fails

### Changed

- Fluentd changed from Deployment to DaemonSet (runs on every node for
  complete log collection)
- Fluentd configuration now uses ConfigMap instead of volume mount
- Fluentd DaemonSet runs as root (UID 0) to access node logs and journal
- Service dependencies handled through Kubernetes service discovery
- Health checks converted to Kubernetes liveness/readiness probes
- Elasticsearch chart: added `persistence` (enabled, size 150Mi) and
  `rotation` (CronJob schedule, maxSizeBytes, indexPattern)
- Fluentd chart values:
  - Added `containerLogs.enabled`, `containerLogs.path`,
    `containerLogs.posFile`
  - Added `nodeLogs.enabled`, `nodeLogs.paths`, `nodeLogs.posFile`
  - Added `journal.enabled`, `journal.path`, `journal.pathRun`, `journal.tag`
- Deployment script (`deploy.sh`):
  - Deploys log-generator chart automatically
  - Deploys ingress chart automatically
  - Sets Kibana service name/port for ingress configuration
  - Waits for all deployments and DaemonSet to be ready before smoke tests
  - Runs smoke tests (Elasticsearch, Kibana, HTTPD) and fails deploy if any
    check fails
  - Updated completion messages with ingress access instructions
- Chart values: added `healthcheck` blocks (enable/disable, delays,
  thresholds) to Kibana, HTTPD, Fluentd, and log-generator charts

### Removed

- Portainer service excluded from Kubernetes deployment (Docker-specific
  tool)
- Fluentd chart `replicas` value (not applicable to DaemonSet)

### Technical Details

- Helm charts follow Helm 3 best practices
- Services use ClusterIP by default (use port-forward or Ingress for
  external access)
- Fluentd image needs to be built separately or pushed to a container
  registry
- Deployment script handles image building for local clusters (kind,
  minikube)
- Fluentd collects all log types: container/pod logs, node logs, and
  systemd journal (cluster-wide via DaemonSet)
- All logs forwarded to Elasticsearch under `fluentd-*` index pattern
- Ingress requires an ingress controller (e.g. ingress-nginx) installed in
  the cluster
- For `kibana.local` access: configure DNS or `/etc/hosts` to point to the
  ingress controller's address
- Probes can be disabled per chart via `healthcheck.enabled: false` in
  values
- Smoke tests require cluster-internal DNS and a runnable curl image
  (curlimages/curl)

## [Previous Versions]

### Docker Compose Version

- Initial Docker Compose stack with EFK (Elasticsearch, Fluentd, Kibana)
- Portainer included for container management
- Local volume mounts for Fluentd configuration and logs
