#!/usr/bin/env bash
#
# Container bootstrap — the safety net.
#
# railway.json also declares a preDeployCommand that runs the same two steps
# once per release, before traffic reaches the new version. That is the better
# place for them: it blocks the deploy if a migration fails, instead of letting
# a half-migrated app start serving.
#
# This runs them again anyway, because a platform hook that silently does not
# fire is indistinguishable from a broken app: the site comes up, the health
# check passes, and the only symptom is "username or password is not correct"
# on a sign-in page with no accounts behind it. Both steps are idempotent, so
# the cost of the belt-and-braces is two no-op commands and four log lines.
#
# Every line here is prefixed [boot] so it is obvious in the logs which of the
# two mechanisms actually did the work.
set -o errexit
set -o pipefail
set -o nounset

echo "[boot] ==> Applying database migrations"
python manage.py migrate --noinput

if [ -n "${OWNER_USERNAME:-}" ] && [ -n "${OWNER_PASSWORD:-}" ]; then
  echo "[boot] ==> Ensuring the first owner account exists"
  python manage.py create_owner --from-env --skip-if-exists
else
  echo "[boot] ==> OWNER_USERNAME / OWNER_PASSWORD not set; skipping owner creation."
  echo "[boot]     Set them and redeploy, or run: python manage.py create_owner"
fi

echo "[boot] ==> Handing over to the web server on port ${PORT:-8000}"
exec "$@"
