#!/usr/bin/env bash
set -euo pipefail

# ----------------------------------------------------------------------------
# run-minikube.sh
#
# Interactive Minikube runner for the ticketing system.
#
# What it does:
# - creates or reuses infra/k8s/secret.yaml
# - starts Minikube
# - builds the service images inside Minikube's Docker daemon
# - applies the Kubernetes manifests
# - optionally applies KEDA manifests
# - optionally starts a frontend port-forward
#
# Secret creation options:
# 1) enter values manually
# 2) read values from service .env files
# 3) copy an existing secret YAML file
# 4) reuse the existing infra/k8s/secret.yaml in this repo
# ----------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
K8S_DIR="$REPO_ROOT/infra/k8s"
SECRET_OUT="$K8S_DIR/secret.yaml"
SECRET_TEMPLATE="$K8S_DIR/secret.example.yaml"
AUTH_ENV="$REPO_ROOT/services/auth/.env"
DB_ENV="$REPO_ROOT/services/database/.env"
NOTIF_ENV="$REPO_ROOT/services/notification/.env"
PAYMENT_ENV="$REPO_ROOT/services/payment/razorpay/.env"
FRONTEND_PORT_FORWARD_PID=""

require_cmd() {
  # Fail fast when a required CLI is missing.
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: '$1' is required but not installed." >&2
    exit 1
  }
}

prompt() {
  # Prompt the user and return the typed value.
  local text=$1
  local default=${2:-}
  local value
  if [[ -n "$default" ]]; then
    read -r -p "$text [$default]: " value
    echo "${value:-$default}"
  else
    read -r -p "$text: " value
    echo "$value"
  fi
}

trim() {
  # Remove leading and trailing whitespace from a string.
  local value=$1
  value=${value#"${value%%[![:space:]]*}"}
  value=${value%"${value##*[![:space:]]}"}
  printf '%s' "$value"
}

load_env_file() {
  # Load a .env file into the current shell.
  local file=$1
  set -a
  # shellcheck disable=SC1090
  source "$file"
  set +a
}

normalize_secret_namespace() {
  # Keep reused secret manifests aligned with the app namespace migration.
  if grep -Eq '^[[:space:]]*namespace:' "$SECRET_OUT"; then
    sed -i 's/^[[:space:]]*namespace:.*/  namespace: app/' "$SECRET_OUT"
    return
  fi

  awk '
    BEGIN { inserted = 0 }
    /^metadata:$/ && inserted == 0 {
      print
      print "  namespace: app"
      inserted = 1
      next
    }
    { print }
    END {
      if (inserted == 0) {
        exit 1
      }
    }
  ' "$SECRET_OUT" > "${SECRET_OUT}.tmp"
  mv "${SECRET_OUT}.tmp" "$SECRET_OUT"
}

validate_secret_manifest() {
  # Fail early if a reused manifest does not match the keys expected by the deployments.
  local required_keys=(
    JWT_SECRET_KEY
    MYSQL_ROOT_PASSWORD
    MYSQL_PASSWORD
    SMTP_HOST
    SMTP_PORT
    SMTP_USER
    SMTP_PASSWORD
    DEFAULT_ADMIN_EMAIL
    DEFAULT_ADMIN_PASSWORD
    RAZORPAY_KEY_ID
    RAZORPAY_KEY_SECRET
    RAZORPAY_WEBHOOK_SECRET
  )
  local key
  local missing=()

  for key in "${required_keys[@]}"; do
    if ! grep -Eq "^[[:space:]]*${key}:" "$SECRET_OUT"; then
      missing+=("$key")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "ERROR: $SECRET_OUT is missing required keys: ${missing[*]}" >&2
    exit 1
  fi
}

write_secret_from_values() {
  # Write the Kubernetes Secret manifest using the provided values.
  local jwt_secret=$1
  local mysql_root_password=$2
  local mysql_password=$3
  local smtp_host=$4
  local smtp_port=$5
  local smtp_user=$6
  local smtp_password=$7
  local default_admin_email=$8
  local default_admin_password=$9
  local razorpay_key_id=${10}
  local razorpay_key_secret=${11}
  local razorpay_webhook_secret=${12}

  cat > "$SECRET_OUT" <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ticketing-system-credentials
  namespace: app
stringData:
  JWT_SECRET_KEY: "$jwt_secret"
  MYSQL_ROOT_PASSWORD: "$mysql_root_password"
  MYSQL_PASSWORD: "$mysql_password"
  SMTP_HOST: "$smtp_host"
  SMTP_PORT: "$smtp_port"
  SMTP_USER: "$smtp_user"
  SMTP_PASSWORD: "$smtp_password"
  DEFAULT_ADMIN_EMAIL: "$default_admin_email"
  DEFAULT_ADMIN_PASSWORD: "$default_admin_password"
  RAZORPAY_KEY_ID: "$razorpay_key_id"
  RAZORPAY_KEY_SECRET: "$razorpay_key_secret"
  RAZORPAY_WEBHOOK_SECRET: "$razorpay_webhook_secret"
EOF
}

write_secret_manually() {
  # Ask the user for each secret value explicitly.
  echo "Enter secret values one by one."
  local jwt_secret mysql_root_password mysql_password smtp_host smtp_port smtp_user smtp_password default_admin_email default_admin_password razorpay_key_id razorpay_key_secret razorpay_webhook_secret

  jwt_secret=$(prompt "JWT secret")
  mysql_root_password=$(prompt "MySQL root password")
  mysql_password=$(prompt "MySQL app password")
  smtp_host=$(prompt "SMTP host" "smtp.example.com")
  smtp_port=$(prompt "SMTP port" "2525")
  smtp_user=$(prompt "SMTP user")
  smtp_password=$(prompt "SMTP password")
  default_admin_email=$(prompt "Default admin email" "admin@example.com")
  default_admin_password=$(prompt "Default admin password")
  razorpay_key_id=$(prompt "Razorpay key ID")
  razorpay_key_secret=$(prompt "Razorpay key secret")
  razorpay_webhook_secret=$(prompt "Razorpay webhook secret")

  write_secret_from_values \
    "$(trim "$jwt_secret")" \
    "$(trim "$mysql_root_password")" \
    "$(trim "$mysql_password")" \
    "$(trim "$smtp_host")" \
    "$(trim "$smtp_port")" \
    "$(trim "$smtp_user")" \
    "$(trim "$smtp_password")" \
    "$(trim "$default_admin_email")" \
    "$(trim "$default_admin_password")" \
    "$(trim "$razorpay_key_id")" \
    "$(trim "$razorpay_key_secret")" \
    "$(trim "$razorpay_webhook_secret")"
}

write_secret_from_env_files() {
  # Read the secret values from the service .env files.
  [[ -f "$AUTH_ENV" ]] || { echo "ERROR: Missing $AUTH_ENV" >&2; exit 1; }
  [[ -f "$DB_ENV" ]] || { echo "ERROR: Missing $DB_ENV" >&2; exit 1; }
  [[ -f "$NOTIF_ENV" ]] || { echo "ERROR: Missing $NOTIF_ENV" >&2; exit 1; }
  [[ -f "$PAYMENT_ENV" ]] || { echo "ERROR: Missing $PAYMENT_ENV" >&2; exit 1; }

  # Load values into the current shell.
  # shellcheck disable=SC1090
  source "$AUTH_ENV"
  # shellcheck disable=SC1090
  source "$DB_ENV"
  # shellcheck disable=SC1090
  source "$NOTIF_ENV"
  # shellcheck disable=SC1090
  source "$PAYMENT_ENV"

  : "${JWT_SECRET_KEY:?Missing JWT_SECRET_KEY in services/auth/.env}"
  : "${MYSQL_ROOT_PASSWORD:?Missing MYSQL_ROOT_PASSWORD in services/database/.env}"
  : "${MYSQL_PASSWORD:?Missing MYSQL_PASSWORD in services/auth/.env or services/database/.env}"
  : "${SMTP_HOST:?Missing SMTP_HOST in services/notification/.env}"
  : "${SMTP_PORT:?Missing SMTP_PORT in services/notification/.env}"
  : "${SMTP_USER:?Missing SMTP_USER in services/notification/.env}"
  : "${SMTP_PASSWORD:?Missing SMTP_PASSWORD in services/notification/.env}"
  : "${DEFAULT_ADMIN_EMAIL:?Missing DEFAULT_ADMIN_EMAIL in services/auth/.env}"
  : "${DEFAULT_ADMIN_PASSWORD:?Missing DEFAULT_ADMIN_PASSWORD in services/auth/.env}"
  : "${RAZORPAY_KEY_ID:?Missing RAZORPAY_KEY_ID in services/payment/razorpay/.env}"
  : "${RAZORPAY_KEY_SECRET:?Missing RAZORPAY_KEY_SECRET in services/payment/razorpay/.env}"
  : "${RAZORPAY_WEBHOOK_SECRET:?Missing RAZORPAY_WEBHOOK_SECRET in services/payment/razorpay/.env}"

  write_secret_from_values \
    "$JWT_SECRET_KEY" \
    "$MYSQL_ROOT_PASSWORD" \
    "$MYSQL_PASSWORD" \
    "$SMTP_HOST" \
    "$SMTP_PORT" \
    "$SMTP_USER" \
    "$SMTP_PASSWORD" \
    "$DEFAULT_ADMIN_EMAIL" \
    "$DEFAULT_ADMIN_PASSWORD" \
    "$RAZORPAY_KEY_ID" \
    "$RAZORPAY_KEY_SECRET" \
    "$RAZORPAY_WEBHOOK_SECRET"
}

use_existing_secret_file() {
  # Copy a user-provided secret YAML file into infra/k8s/secret.yaml.
  local file_path
  file_path=$(prompt "Path to an existing secret yaml file" "$SECRET_OUT")
  file_path=$(trim "$file_path")

  [[ -f "$file_path" ]] || { echo "ERROR: File not found: $file_path" >&2; exit 1; }
  cp "$file_path" "$SECRET_OUT"
  echo "Copied secret file to $SECRET_OUT"
}

use_existing_repo_secret() {
  # Reuse the already-created infra/k8s/secret.yaml in this repo.
  if [[ ! -f "$SECRET_OUT" ]]; then
    echo "ERROR: $SECRET_OUT does not exist yet." >&2
    echo "Create it first using option 1, 2, or 3." >&2
    exit 1
  fi

  echo "Using existing $SECRET_OUT"
}

apply_observability_manifests() {
  # Deploy the observability stack (Prometheus, Loki, Grafana, Promtail) into the monitoring namespace.
  if [[ -d "$K8S_DIR/observability" ]]; then
    kubectl apply -f "$K8S_DIR/observability/"
    echo "Observability stack applied. Grafana will be available at http://$(minikube ip):32000 (admin/admin)"
  else
    echo "WARNING: $K8S_DIR/observability/ not found; skipping."
  fi
}

apply_keda_manifests() {
  # KEDA is optional; install CRDs/controller first (if needed) before applying ScaledObjects.
  local KEDA_VERSION=${KEDA_VERSION:-2.10.0}
  local KEDA_INSTALL_URL="https://github.com/kedacore/keda/releases/download/v${KEDA_VERSION}/keda-${KEDA_VERSION}.yaml"

  if ! kubectl get crd scaledobjects.keda.sh >/dev/null 2>&1; then
    echo "KEDA CRDs not found: installing KEDA $KEDA_VERSION..."
    kubectl apply -f "$KEDA_INSTALL_URL"

    echo "Waiting for KEDA operator to be ready..."
    kubectl -n keda rollout status deployment/keda-operator --timeout=180s || true
  else
    echo "KEDA CRDs already present; skipping KEDA controller install."
  fi

  if [[ -d "$K8S_DIR/keda" ]]; then
    kubectl apply -f "$K8S_DIR/keda/"
  fi
}

build_images() {
  # Build each service image inside Minikube's Docker daemon so the cluster can pull it locally.
  echo "Building images inside Minikube's Docker daemon..."
  # eval "$(minikube -p minikube docker-env)" is the recommended way to set the environment for 
  # Docker commands to use Minikube's Docker daemon. It works across different shells and platforms.
  eval "$(minikube docker-env)"
  docker build -t auth:latest "$REPO_ROOT/services/auth"
  docker build -t booking:latest "$REPO_ROOT/services/booking"
  docker build -t booking-status:latest "$REPO_ROOT/services/booking-status"
  docker build -t gateway:latest "$REPO_ROOT/services/gateway"
  docker build -t notification:latest "$REPO_ROOT/services/notification"
  docker build -t payment-mock:latest "$REPO_ROOT/services/payment/mock"
  docker build -t payment-razorpay:latest "$REPO_ROOT/services/payment/razorpay"
  docker build -t ticketing-system-mysql:latest "$REPO_ROOT/services/database"
  docker build -t frontend:latest "$REPO_ROOT/frontend/vue"
}

cleanup_stale_default_resources() {
  # Remove any old ticketing-system resources left behind in the default namespace.
  echo "Cleaning stale ticketing-system resources from the default namespace..."
  kubectl -n default get deployment,service,configmap,secret,pod,replicaset,statefulset -o name 2>/dev/null \
    | grep -E '(^deployment.apps/ticketing-system-|^service/ticketing-system-|^configmap/ticketing-system-|^secret/ticketing-system-|^pod/ticketing-system-|^replicaset.apps/ticketing-system-|^statefulset.apps/ticketing-system-)' \
    | xargs -r kubectl -n default delete --ignore-not-found=true >/dev/null 2>&1 || true
}

apply_manifests() {
  # Apply the core workload and service manifests in a safe order.
  kubectl create namespace app --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  kubectl apply -f "$K8S_DIR/namespace.yaml"
  kubectl apply -f "$K8S_DIR/secret.yaml"
  kubectl apply -f "$K8S_DIR/configmap.yaml"
  kubectl apply -f "$K8S_DIR/services/"
  kubectl apply -f "$K8S_DIR/deployments/"
  kubectl apply -f "$K8S_DIR/statefulsets/"
}

start_frontend_port_forward() {
  # Keep the frontend reachable at a stable local port while the script is running.
  local local_port=${1:-30090}
  local service_port=${2:-5173}

  echo "Starting frontend port-forward on http://127.0.0.1:${local_port} ..."
  kubectl port-forward -n app svc/ticketing-system-frontend "${local_port}:${service_port}" >/tmp/ticketing-frontend-port-forward.log 2>&1 &
  FRONTEND_PORT_FORWARD_PID=$!

  trap cleanup EXIT INT TERM
}

cleanup() {
  # Stop the background port-forward if the script exits.
  if [[ -n "${FRONTEND_PORT_FORWARD_PID}" ]] && kill -0 "${FRONTEND_PORT_FORWARD_PID}" >/dev/null 2>&1; then
    kill "${FRONTEND_PORT_FORWARD_PID}" >/dev/null 2>&1 || true
  fi
}

main() {
  # Check required tools before doing anything else.
  require_cmd kubectl
  require_cmd minikube
  require_cmd docker

  # Ask how the user wants to create or reuse the secret manifest.
  echo "Choose how to create infra/k8s/secret.yaml:"
  echo "  1) Enter values manually"
  echo "  2) Read values from service .env files"
  echo "  3) Copy an existing secret yaml file"
  echo "  4) Use the existing infra/k8s/secret.yaml in this repo"
  local choice
  choice=$(prompt "Select an option" "2")
  choice=$(trim "$choice")

  case "$choice" in
    1)
      write_secret_manually
      ;;
    2)
      write_secret_from_env_files
      ;;
    3)
      use_existing_secret_file
      ;;
    4)
      use_existing_repo_secret
      ;;
    *)
      echo "ERROR: Invalid option '$choice'" >&2
      exit 1
      ;;
  esac

  normalize_secret_namespace
  validate_secret_manifest

  # Make sure Minikube is running before we build images or apply resources.
  echo "Starting Minikube..."
  minikube start --driver=docker --wait=true --wait-timeout=5m --addons=default-storageclass --addons=metrics-server
  kubectl config use-context minikube >/dev/null

  # Wait for API readiness before doing further work to avoid addon race conditions.
  echo "Waiting for kube-apiserver readiness..."
  for i in {1..30}; do
    if kubectl get --raw /healthz >/dev/null 2>&1; then
      break
    fi
    sleep 2
  done

  # Build all service images inside the Minikube Docker environment.
  build_images

  # Remove stale resources from default namespace before applying the app manifests.
  cleanup_stale_default_resources

  # Apply the core Kubernetes resources in the correct order.
  apply_manifests

  # KEDA is optional, so let the user choose whether to include it.
  local apply_keda_choice
  apply_keda_choice=$(prompt "Apply KEDA manifests too? (y/N)" "N")
  apply_keda_choice=$(trim "$apply_keda_choice")
  if [[ "$apply_keda_choice" =~ ^[Yy]$ ]]; then
    apply_keda_manifests
  fi

  # Observability stack is optional but recommended for monitoring.
  local apply_obs_choice
  apply_obs_choice=$(prompt "Apply observability stack (Prometheus, Loki, Grafana)? (y/N)" "N")
  apply_obs_choice=$(trim "$apply_obs_choice")
  if [[ "$apply_obs_choice" =~ ^[Yy]$ ]]; then
    apply_observability_manifests
  fi

  # Port-forwarding is optional because some users may prefer to use the NodePort or skip the frontend.
  local port_forward_choice
  port_forward_choice=$(prompt "Start frontend port-forward automatically? (Y/n)" "Y")
  port_forward_choice=$(trim "$port_forward_choice")
  if [[ ! "$port_forward_choice" =~ ^[Nn]$ ]]; then
    start_frontend_port_forward
    echo "Frontend is being forwarded. Press Ctrl+C to stop the port-forward and exit."
    wait "$FRONTEND_PORT_FORWARD_PID"
  fi

  # Give the user the final connection hint when the script finishes.
  echo ""
  echo "Ticketing system deployed."
  echo "If you did not enable automatic port-forwarding, run: kubectl port-forward -n app svc/ticketing-system-frontend 30090:5173"
  echo "Then open: http://127.0.0.1:30090"
}

main "$@"
