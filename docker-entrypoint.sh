#!/usr/bin/env bash
#
# Container bootstrap.
#
# Migrations and the first owner run here, at container start, rather than in a
# platform-specific hook. Railway's preDeployCommand, Render's buildCommand and
# Fly's release_command all do the same job in three different places, and a
# hook that silently does not fire looks exactly like a broken app: the site
# comes up, but nobody can sign in.
#
# Both steps are idempotent, so running them on every start is safe.
set -o errexit
set -o pipefail
set -o nounset

echo "==> Applying database migrations"
python manage.py migrate --noinput

# Only attempt the owner when the operator has supplied credentials. Without
# them this is a no-op, and the sign-in page explains what to do.
if [ -n "${OWNER_USERNAME:-}" ] && [ -n "${OWNER_PASSWORD:-}" ]; then
  echo "==> Ensuring the first owner account exists"
  python manage.py create_owner --from-env --skip-if-exists
else
  echo "==> OWNER_USERNAME / OWNER_PASSWORD not set; skipping owner creation."
  echo "    Set them and redeploy, or run: python manage.py create_owner"
fi

echo "==> Starting web server on port ${PORT:-8000}"
exec "$@"
