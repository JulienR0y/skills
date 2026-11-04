#!/usr/bin/env bash
# Run the Teams reader from this folder with the first `node` on the PATH.
set -euo pipefail
exec node "$(dirname "$0")/teams-read.js" "$@"
