#!/bin/sh
# Fixne ownership /workspace po bind-mountu (běží jako root),
# pak spustí aplikaci jako appuser.
set -e

chown appuser:appuser /workspace 2>/dev/null || true

exec runuser -u appuser -- "$@"
