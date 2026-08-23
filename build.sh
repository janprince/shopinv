#!/usr/bin/env bash
# Render build step. Anything that must happen before the new version serves traffic.
set -o errexit
set -o pipefail
set -o nounset

pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput

# Create the first owner only if the shop has none yet. Safe to run on every deploy.
if [ -n "${OWNER_USERNAME:-}" ] && [ -n "${OWNER_PASSWORD:-}" ]; then
  python manage.py create_owner --from-env --skip-if-exists
fi
