#!/usr/bin/env bash
set -euo pipefail

[[ -f "$1" ]] || exit 0

while IFS= read -r query || [[ -n "$query" ]]; do
    # skip empty lines and comments
    [[ -z "$query" || "$query" =~ ^[[:space:]]*# ]] && continue

    syncweb find -tf -- "$query" /
done < "$1"
