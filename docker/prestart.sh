#!/usr/bin/env sh
set -e

echo "=== Running database migrations ==="
nb orm upgrade
echo "=== Database migrations completed ==="
