#!/usr/bin/env bash
# Prints every URL to try (make urls): localhost on your machine, the forwarded
# https addresses inside a GitHub codespace.
set -u

if [ -n "${CODESPACE_NAME:-}" ]; then
    domain=${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-app.github.dev}
    base() { printf 'https://%s-%s.%s' "$CODESPACE_NAME" "$1" "$domain"; }
    echo "Codespace $CODESPACE_NAME. Ports are private (your GitHub login) unless set to Public"
    echo "in the Ports tab: right-click the port > Port Visibility > Public."
else
    base() { printf 'http://localhost:%s' "$1"; }
    echo "Local machine."
fi

app=$(base 5000)
grafana=$(base 3000)
prometheus=$(base 9090)
mlflow=$(base 5001)
tfserving=$(base 8501)

row() { printf '  %s\n      %s\n' "$2" "$1"; }

echo
echo "API (make start or make monitoring)"
row "$app/docs/" "Swagger UI: try every endpoint, upload an image"
row "$app/health/ready" "readiness: database and both models"
row "$app/models" "served models and versions"
row "$app/object-counts" "running totals per class"
row "$app/openapi.yaml" "the API contract"
row "$app/metrics" "Prometheus metrics of the app"
echo
echo "Dashboards (make monitoring)"
row "$grafana/d/object-counter" "Grafana dashboard 'Object Counter'"
row "$prometheus/targets" "Prometheus: scraped targets (both UP)"
row "$prometheus/alerts" "Prometheus: the 5 alert rules"
echo
echo "Models"
row "$tfserving/v1/models/ssd_mobilenet_v2" "TF Serving: default model status"
row "$tfserving/v1/models/acme_shelf_detector" "TF Serving: second model status"
row "$mlflow" "MLflow registry (run make mlflow-ui first)"
