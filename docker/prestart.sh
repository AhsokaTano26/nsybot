#!/usr/bin/env sh
set -e

# Generate .env.prod from environment variables for NoneBot to read
echo "=== Generating .env.prod ==="
if [ -z "${QQ_BOTS:-}" ] && [ -n "${QQ_APP_ID:-}" ]; then
  export QQ_BOTS="$(python -c 'from nsy.qq_bootstrap import build_qq_bots; print(build_qq_bots())')"
fi
env | grep -v '^_' | grep -v '^PWD' | grep -v '^SHLVL' | grep -v '^PATH' | grep -v '^HOME' > /app/.env.prod
echo "ENVIRONMENT=prod" >> /app/.env.prod

echo "=== Running database migrations ==="
nb orm upgrade
echo "=== Database migrations completed ==="
