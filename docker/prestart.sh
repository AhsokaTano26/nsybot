#!/usr/bin/env sh
set -e

# Generate .env.prod from environment variables for NoneBot to read
echo "=== Generating .env.prod ==="
env | grep -v '^_' | grep -v '^PWD' | grep -v '^SHLVL' | grep -v '^PATH' | grep -v '^HOME' > /app/.env.prod
echo "ENVIRONMENT=prod" >> /app/.env.prod

echo "=== Running database migrations ==="
nb orm upgrade
echo "=== Database migrations completed ==="
