#!/usr/bin/env bash
# =============================================================================
# create-k8s-secret.sh
#
# Generates infra/k8s/secret.yaml from local service .env files.
# Run this once after cloning, whenever .env files change.
#
# Usage:
#   ./scripts/create-k8s-secret.sh
#
# Requirements:
#   - Each service .env file must exist (copy from .env.example and fill values)
#     services/auth/.env
#     services/database/.env
#     services/notification/.env
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

AUTH_ENV="$REPO_ROOT/services/auth/.env"
DB_ENV="$REPO_ROOT/services/database/.env"
NOTIF_ENV="$REPO_ROOT/services/notification/.env"
OUT="$REPO_ROOT/infra/k8s/secret.yaml"

# --- Validate .env files exist -----------------------------------------------
missing=()
[[ -f "$AUTH_ENV" ]]  || missing+=("$AUTH_ENV")
[[ -f "$DB_ENV" ]]    || missing+=("$DB_ENV")
[[ -f "$NOTIF_ENV" ]] || missing+=("$NOTIF_ENV")

if [[ ${#missing[@]} -gt 0 ]]; then
  echo "ERROR: Missing .env files. Copy from .env.example and fill in values:"
  for f in "${missing[@]}"; do
    echo "  cp ${f}.example ${f}"
  done
  exit 1
fi

# --- Helper: read a key from an env file -------------------------------------
get_env() {
  local file=$1
  local key=$2
  local value
  value=$(grep -E "^${key}=" "$file" 2>/dev/null | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs)
  if [[ -z "$value" ]]; then
    echo "ERROR: Key '${key}' not found or empty in ${file}" >&2
    exit 1
  fi
  echo "$value"
}

# --- Read values from .env files ---------------------------------------------
JWT_SECRET_KEY=$(get_env "$AUTH_ENV" JWT_SECRET_KEY)
MYSQL_ROOT_PASSWORD=$(get_env "$DB_ENV" MYSQL_ROOT_PASSWORD)
MYSQL_PASSWORD=$(get_env "$AUTH_ENV" MYSQL_PASSWORD)
SMTP_HOST=$(get_env "$NOTIF_ENV" SMTP_HOST)
SMTP_PORT=$(get_env "$NOTIF_ENV" SMTP_PORT)
SMTP_USER=$(get_env "$NOTIF_ENV" SMTP_USER)
SMTP_PASSWORD=$(get_env "$NOTIF_ENV" SMTP_PASSWORD)
DEFAULT_ADMIN_EMAIL=$(get_env "$AUTH_ENV" DEFAULT_ADMIN_EMAIL)
DEFAULT_ADMIN_PASSWORD=$(get_env "$AUTH_ENV" DEFAULT_ADMIN_PASSWORD)

# --- Write secret.yaml -------------------------------------------------------
cat > "$OUT" <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ticketing-system-credentials
stringData:
  JWT_SECRET_KEY: "${JWT_SECRET_KEY}"
  MYSQL_ROOT_PASSWORD: "${MYSQL_ROOT_PASSWORD}"
  MYSQL_PASSWORD: "${MYSQL_PASSWORD}"
  SMTP_HOST: "${SMTP_HOST}"
  SMTP_PORT: "${SMTP_PORT}"
  SMTP_USER: "${SMTP_USER}"
  SMTP_PASSWORD: "${SMTP_PASSWORD}"
  DEFAULT_ADMIN_EMAIL: "${DEFAULT_ADMIN_EMAIL}"
  DEFAULT_ADMIN_PASSWORD: "${DEFAULT_ADMIN_PASSWORD}"
EOF

echo "✅  Generated $OUT"
echo ""
echo "Apply to your cluster with:"
echo "  kubectl apply -f infra/k8s/secret.yaml"
