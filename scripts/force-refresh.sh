#!/bin/bash
# Force an immediate cookie refresh on running AIStudioBuildWS instance(s).
#
# Usage inside container:
#   ./scripts/force-refresh.sh              # triggers ALL instances
#   ./scripts/force-refresh.sh account2.json # triggers one instance
#
# From host via docker compose exec:
#   docker compose exec aistudio-websocket-app ./scripts/force-refresh.sh
#
# Then watch logs:
#   docker compose logs -f

LABEL="${1:-}"
TRIGGER="/tmp/force_refresh${LABEL:+_$LABEL}"
touch "$TRIGGER"
echo "Force-refresh triggered: $TRIGGER"
echo "Watch logs: docker compose logs -f"
