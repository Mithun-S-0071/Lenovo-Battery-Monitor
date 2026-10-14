#!/usr/bin/env bash
# Delegation wrapper for root install.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/../install.sh" "$@"
