#!/usr/bin/env bash
# Checks the machine before running the Docker stack (make doctor).
# FAIL lines block `make up`/`make monitoring`; WARN lines may only slow things down.
set -u

failures=0
warnings=0
ok() { printf '  \033[32mok\033[0m    %s\n' "$1"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$1"; warnings=$((warnings + 1)); }
fail() { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; failures=$((failures + 1)); }

echo "Docker"
# Under WSL, Docker comes from Docker Desktop on Windows, not from apt.
if grep -qi microsoft /proc/version 2>/dev/null; then
    desktop_hint="start Docker Desktop and enable Settings > Resources > WSL integration > Ubuntu"
else
    desktop_hint=""
fi
if ! command -v docker >/dev/null 2>&1; then
    fail "docker not installed (${desktop_hint:-Ubuntu: sudo apt install -y docker.io docker-compose-v2})"
elif docker info >/dev/null 2>&1; then
    ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), daemon reachable"
elif [ -n "$desktop_hint" ]; then
    fail "daemon not reachable: $desktop_hint"
elif [ -S /var/run/docker.sock ] && ! id -nG | grep -qw docker; then
    fail "not in the docker group: sudo usermod -aG docker \$USER, then log out and in again"
elif id -nG | grep -qw docker; then
    fail "daemon not reachable: sudo systemctl start docker"
else
    fail "daemon not reachable and not in the docker group (see docs/SETUP.md)"
fi
if command -v docker >/dev/null 2>&1; then
    if docker compose version >/dev/null 2>&1; then
        ok "compose $(docker compose version --short 2>/dev/null)"
    else
        fail "Compose v2 missing (${desktop_hint:-Ubuntu: sudo apt install -y docker-compose-v2})"
    fi
fi

echo "Resources"
if [ -r /proc/meminfo ]; then
    avail_mb=$(awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo)
    if [ "$avail_mb" -lt 1500 ]; then
        warn "${avail_mb} MB RAM available: make up needs ~1.5 GB, make monitoring ~2.5 GB"
    elif [ "$avail_mb" -lt 2500 ]; then
        warn "${avail_mb} MB RAM available: enough for make up, tight for make monitoring (~2.5 GB)"
    else
        ok "${avail_mb} MB RAM available"
    fi
fi
disk_gb=$(df -Pk . | awk 'NR == 2 {print int($4 / 1048576)}')
if [ "$disk_gb" -lt 5 ]; then
    fail "${disk_gb} GB disk free here: images, models and venvs need ~5 GB"
else
    ok "${disk_gb} GB disk free"
fi

echo "Ports"
running=""
if docker info >/dev/null 2>&1; then
    running=$(docker compose --profile app --profile monitoring ps --format '{{.Ports}}' 2>/dev/null)
fi
listening() {
    if command -v ss >/dev/null 2>&1; then
        ss -Hltn "sport = :$1" 2>/dev/null | grep -q .
    else
        lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
    fi
}
for entry in 5000:app 8501:tfserving 27017:mongo 5432:postgres 9090:prometheus 3000:grafana; do
    port=${entry%%:*}
    name=${entry#*:}
    if ! listening "$port"; then
        ok "$port free ($name)"
    elif printf '%s' "$running" | grep -q ":$port->"; then
        ok "$port used by this compose stack ($name)"
    else
        warn "$port in use by another process ($name can't start; for 5000: stop make run-prod/run before make monitoring)"
    fi
done

echo "Project"
[ -x .venv/bin/python ] && ok ".venv" || fail ".venv missing: make setup"
[ -x .venv-models/bin/python ] && ok ".venv-models" || warn ".venv-models missing: make setup-models (needed for make models)"
if [ ! -f tmp/model/models.lock.json ]; then
    fail "no pulled models (tmp/model/models.lock.json): make setup-models && make models"
elif [ ! -f tmp/model/model_config.config ] || [ ! -f tmp/model/candidates.lock.json ]; then
    fail "tmp/model is from an older pull (TF Serving exits 255): make pull-models"
else
    ok "models pulled: $(tr -d '\n ' < tmp/model/models.lock.json)"
fi
[ -d tmp/baselines ] && ok "tmp/baselines" || warn "tmp/baselines missing: make pull-models (Docker would create it as root)"

echo
if [ "$failures" -gt 0 ]; then
    echo "$failures problem(s), $warnings warning(s)"
    exit 1
fi
echo "Ready ($warnings warning(s))"
