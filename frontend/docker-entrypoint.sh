#!/bin/sh
set -eu

API_BASE_URL="${API_BASE_URL:-/api/v1}"
TARGET_DIR="/usr/share/nginx/html"
OLD_BASE_URL="http://localhost:8000/api/v1"
DEFAULT_BASE_URL="/api/v1"

echo "Rewriting frontend API base URL to: ${API_BASE_URL}"

find "${TARGET_DIR}" -type f \( -name "*.js" -o -name "*.html" \) -print0 \
  | xargs -0 sed -i \
      -e "s|${OLD_BASE_URL}|${API_BASE_URL}|g" \
      -e "s|${DEFAULT_BASE_URL}|${API_BASE_URL}|g"
