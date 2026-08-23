# JCF Organic — Shop Manager

Inventory and sales management for a single-location organic shop.

The shopkeeper records sales from a laptop at the counter. The owner checks the
shop from a phone. Both use the same web app, and the app is the shop's source
of truth for what is on the shelf, what was sold, and why anything changed.

---

**Using the app day to day:** [`docs/SHOP-GUIDE.md`](docs/SHOP-GUIDE.md) — a
plain-language guide written for the shopkeeper and the owner, not for developers.

## Contents

- [What it does](#what-it-does)
- [Technology](#technology)
- [Local setup](#local-setup)
- [Running with Docker](#running-with-docker)
- [Environment variables](#environment-variables)
- [Creating the owner account](#creating-the-owner-account)
- [Sample data](#sample-data)
- [Running the tests](#running-the-tests)
- [Deploying to Railway](#deploying-to-railway)
- [Deploying to Render](#deploying-to-render)
- [Backup and restore](#backup-and-restore)
- [Key business rules](#key-business-rules)
- [How the code is arranged](#how-the-code-is-arranged)
- [Deviations from the original brief](#deviations-from-the-original-brief)
- [Known limitations](#known-limitations)
- [Future improvements](#future-improvements)

---

## What it does

**Selling**
- A fast till: search or scan, adjust quantities, take Cash / Mobile Money /
  Bank Transfer, see change due, print a receipt.
- Stock is reduced in the same database transaction as the sale, once.
- A dropped connection or a double-click can never record the same sale twice.

**Stock**
- Products, categories and suppliers.
- Receiving stock, with optional batch numbers and expiry dates.
- Damaged, expired, missing and returned stock, plus counting corrections.
- Every change is an immutable ledger entry that says who, when, how much and why.
- Products with expiry dates are sold first-expiry-first-out.

**Knowing where you stand**
- Role-specific dashboards: takings, items sold, restocking, expiry.
- Reports on sales, products, categories, payment methods, inventory value,
  expiry, adjustments and estimated gross profit — all exportable as CSV.
- An audit history the owner can read and nobody can edit.

---

## Technology

| Layer     | Choice                                                 |
| --------- | ------------------------------------------------------ |
| Framework | Django 5.2 LTS (a single monolith — no separate SPA)    |
| Database  | PostgreSQL 16+                                         |
| Templates | Django templates + Bootstrap 5.3 with a custom theme    |
| Visual style | Paces "SaaS" skin structure, mapped onto an organic palette |
| Interaction | HTMX for the till search; ~830 lines of vanilla JS total |
| Static    | WhiteNoise (no CDN — every asset is served locally)     |
| Server    | Gunicorn                                               |
| Tooling   | ruff (lint + format), Django's test runner             |

There is no Redis, no Celery, no message queue and no build step. A shop this
size does not need them, and each one would be another thing to keep running.

---

## Local setup

**Requirements:** Python 3.10+ and PostgreSQL 14+ running locally.

```bash
git clone <your-repository-url> jcforganic
cd jcforganic

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

createdb jcforganic

cp .env.example .env               # the defaults work for local development

python manage.py migrate
python manage.py create_owner      # asks for a username and password
python manage.py runserver
```

Open <http://localhost:8000/> and sign in.

> Python 3.10 is the floor (Django 5.2's own minimum). Docker and Render run
> 3.12; the test suite is verified on both.

---

## Running with Docker

Nothing needs to be installed but Docker itself.

```bash
docker compose up --build
```

Then, in a second terminal:

```bash
docker compose exec web python manage.py create_owner
docker compose exec web python manage.py seed_demo      # optional
```

The app is at <http://localhost:8000/>. PostgreSQL is published on host port
**5433** so it will not collide with a PostgreSQL you already run.

---

## Environment variables

Every setting is read from the environment. `.env.example` lists them all; the
ones that matter:

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | `postgres://localhost:5432/jcforganic` in debug | Standard PostgreSQL URL. |
| `DJANGO_SECRET_KEY` | in production | — | The app **refuses to start** without one when debug is off. Generate with `python manage.py generate_secret_key`. |
| `DJANGO_DEBUG` | no | `false` | Never `true` in production. |
| `DJANGO_ALLOWED_HOSTS` | in production | — | Comma-separated hostnames. Debug mode allows all hosts for local and device testing. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | behind a proxy | — | Comma-separated `https://` origins. Debug mode accepts all origins while still validating CSRF tokens. |
| `DB_SSL_REQUIRE` | on managed DBs | `false` | Set `true` on Render. |
| `DJANGO_TIME_ZONE` | no | `Africa/Accra` | |
| `CURRENCY_SYMBOL` | no | `GH₵` | |
| `SESSION_COOKIE_AGE` | no | `43200` (12 h) | Covers a full shop day. |
| `DJANGO_SECURE_SSL_REDIRECT` | no | `true` in production | |
| `OWNER_USERNAME` / `OWNER_EMAIL` / `OWNER_PASSWORD` | no | — | Only read by `create_owner --from-env`. |

Secrets are never committed: `.env` is git-ignored and `.env.example` holds no
real values.

---

## Creating the owner account

```bash
python manage.py create_owner
```

It prompts for a username, email and password, applies Django's password rules,
and creates (or promotes) an owner.

Non-interactively — for a deploy script:

```bash
OWNER_USERNAME=ama OWNER_PASSWORD='...' python manage.py create_owner --from-env --skip-if-exists
```

`--skip-if-exists` makes it safe to run on every deploy: it does nothing once an
owner exists.

Owners create everyone else from **Users** inside the app.

---

## Sample data

```bash
python manage.py seed_demo            # 45 days of a plausible shop
python manage.py seed_demo --days 90
```

It creates 18 products, 6 categories, 4 suppliers, opening stock, regular
deliveries, hundreds of sales and a scattering of breakages — plus two accounts:

| Username | Role | Password |
| --- | --- | --- |
| `ama` | Owner | `demo-pass-2026` |
| `kofi` | Shopkeeper | `demo-pass-2026` |

**Change these before the shop uses the app for anything real.**

`seed_demo` refuses to run on a database that already has sales, so it cannot
quietly pollute live figures. `--force` overrides that, and should only ever be
used on a throwaway database.

---

## Running the tests

```bash
python manage.py test              # 169 tests, about 3 seconds
python manage.py test apps.sales   # one app
pytest                             # pytest also works, via pytest-django
```

Tests run against a real PostgreSQL database, because the guarantees that matter
most — row locks, check constraints, concurrent sales — are database behaviour
and cannot be proved against SQLite.

They cover authentication, role permissions, product creation and duplicate
SKUs, opening stock, receiving, sale completion, multi-line sales,
insufficient-stock rejection, negative-stock prevention, **concurrent sales from
two tills**, adjustments, customer returns, sale reversal, completed-sale
immutability, cost and price snapshots, gross-profit maths, audit events, CSV
exports and every owner-only page.

Linting and formatting:

```bash
ruff check .
ruff format --check .
make lint          # both
make format        # fix both
```

Production readiness:

```bash
python manage.py check --deploy    # passes with zero warnings
```

Stock integrity, at any time:

```bash
python manage.py verify_stock          # report drift
python manage.py verify_stock --fix    # repair it
```

---

## Deploying to Railway

The repository carries `railway.json`, so Railway builds the `Dockerfile` and
knows how to migrate and how to health-check. The steps:

1. **New Project → Deploy from GitHub repo**, and pick this repository.
2. **Add a PostgreSQL database** to the same project (`New → Database → Postgres`).
3. On the **app service → Variables**, add:

   | Variable | Value |
   | --- | --- |
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` — a reference, not a literal |
   | `DJANGO_SECRET_KEY` | output of `python manage.py generate_secret_key` |
   | `DJANGO_DEBUG` | `false` |
   | `OWNER_USERNAME` | e.g. `ama` |
   | `OWNER_EMAIL` | optional |
   | `OWNER_PASSWORD` | a strong password, **deleted again after the first deploy** |

   `DJANGO_ALLOWED_HOSTS` is *not* required: the app reads Railway's own
   `RAILWAY_PUBLIC_DOMAIN` and trusts it for both host validation and CSRF. Set
   it only when you attach a custom domain.

4. **Deploy.** Migrations and the first owner run twice over, on purpose:

   * `railway.json` declares a `preDeployCommand`, which Railway runs once per
     release in a short-lived container **before** traffic reaches the new
     version. This is the right place for schema changes — if a migration
     fails, the deploy fails and the previous version keeps serving.
   * `docker-entrypoint.sh` runs the same two steps again at container start,
     prefixed `[boot]`, then hands over to gunicorn.

   Both steps are idempotent, so the second pass costs two no-op commands. The
   duplication is deliberate: a platform hook that silently does not fire is
   indistinguishable from a broken app — the site comes up, the health check
   passes, and the only symptom is "username or password is not correct" on a
   sign-in page with no accounts behind it.

   A healthy first deploy logs roughly:

   ```
   Owner "ama" created.                       <- preDeployCommand
   [boot] ==> Applying database migrations
     No migrations to apply.
   [boot] ==> Ensuring the first owner account exists
   An owner already exists — nothing to do.   <- entrypoint, work already done
   [boot] ==> Handing over to the web server on port 8080
   ```

   The `[boot]` prefix tells you which of the two actually did the work.

5. **Delete `OWNER_PASSWORD`** from the service variables. The account exists
   now, and later deploys no longer need it.

### Running a one-off command against the deployed app

```bash
railway link                       # once, to attach this directory to the service
railway ssh                        # a shell inside the running container
python manage.py create_owner      # interactive, if you skipped the OWNER_* route
python manage.py verify_stock
```

`railway run <cmd>` executes **locally** with Railway's variables injected — and
`DATABASE_URL` points at `*.railway.internal`, which does not resolve outside
Railway's network. For anything that touches the database from your own machine,
use `DATABASE_PUBLIC_URL` instead:

```bash
DATABASE_URL="$(railway variables --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["DATABASE_PUBLIC_URL"])')"   python manage.py migrate
```

### Notes

* **Static files are baked into the image** at build time, so no volume or
  post-deploy step is needed. Production uses WhiteNoise's manifest storage;
  without that build step every page raises `Missing staticfiles manifest entry`.
* **The container listens on `$PORT`**, which Railway injects. It defaults to
  8000 so `docker run` and Docker Compose keep working unchanged.
* **`/healthz/` is exempt from the HTTPS redirect**, because Railway probes it
  over the private network in plain HTTP. Every user-facing route stays
  HTTPS-only.
* **`ALLOWED_HOSTS` is deliberately stricter than Railway's own Django guide**,
  which suggests `["*"]`. This app reads `RAILWAY_PUBLIC_DOMAIN` instead, so a
  request arriving with an unexpected `Host` header is still rejected with 400.
* **`railway.json` validates against Railway's published JSON schema**
  (`https://backboard.railway.app/railway.schema.json`). Note that
  `preDeployCommand` accepts a string or a **single-element** array — the
  schema sets `maxItems: 1`, so chain multiple commands with `&&` rather than
  adding array entries.

## Deploying to Render

`render.yaml` is a complete blueprint. In the Render dashboard choose
**New → Blueprint** and point it at the repository. It creates the PostgreSQL
database and the web service, generates `DJANGO_SECRET_KEY`, and wires
`DATABASE_URL` in.

`build.sh` runs on every deploy and installs dependencies, collects static
files, applies migrations, and creates the first owner if `OWNER_USERNAME` and
`OWNER_PASSWORD` are set.

After the first successful deploy, **clear `OWNER_PASSWORD` from the Render
dashboard** so it is not left sitting in the environment.

Health checks hit `/healthz/`, which confirms the database is reachable.

Deploying anywhere else needs only: PostgreSQL, the variables above, `build.sh`,
and

```
gunicorn config.wsgi:application --workers 3 --threads 2 --timeout 60
```

---

## Backup and restore

The shop's data is small but irreplaceable. Back it up.

```bash
# Back up (locally, or against Render's external database URL)
pg_dump "$DATABASE_URL" --no-owner --no-privileges --format=custom > backup-$(date +%F).dump

# Restore into an empty database
pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL" backup-2026-08-23.dump

# Plain SQL alternative
make backup      # writes backup.sql
make restore     # reads backup.sql
```

Render's paid database plans take daily backups automatically; treat those as
the baseline and keep your own copy off-platform as well. Test a restore into a
scratch database at least once — an untested backup is a hope, not a backup.

---

## Key business rules

These are the rules the whole design protects. They are enforced in
`apps/inventory/services.py` and `apps/sales/services.py`, in the database, and
in the tests — not in the templates.

1. **Stock only changes through a movement.** Every single change writes an
   immutable `StockMovement` recording the product, the signed quantity, the
   quantity before and after, the reason, the user and the time. There is no
   form field anywhere that sets a quantity directly.
2. **Stock can never go negative.** Checked in the service, and again by a
   database `CHECK` constraint on both the product total and each batch.
3. **A sale is one transaction.** The sale, its lines and all stock reductions
   commit together or not at all. A sale that cannot be fully satisfied writes
   nothing.
4. **Simultaneous tills are safe.** Products are locked with `SELECT … FOR
   UPDATE` in a fixed order (by id, so two carts holding the same products in
   opposite order cannot deadlock). Two tills selling the last items queue;
   the loser gets a clear "not enough stock" message.
5. **A sale is never recorded twice.** Each submission carries an idempotency
   key. Re-submitting after a dropped connection returns the original sale
   instead of charging the customer again.
6. **Completed sales are immutable.** They cannot be edited or deleted — the
   model raises if you try, and no URL exists for it. A mistake is corrected by
   *reversing* the sale, which writes new movements and requires a reason. The
   original stays exactly as it was.
7. **Prices and costs are frozen at the moment of sale.** Each sale line stores
   the product name, SKU, unit, selling price and the actual cost of the goods
   sold. Editing a product tomorrow never changes what last month's report says.
8. **Cost is the real cost.** Profit uses the cost of the specific batches
   consumed, not today's price list. A line spanning two batches gets a blended
   cost.
9. **First expiry, first out.** Stock leaves from the batch expiring soonest;
   undated batches are used after dated ones.
10. **Nothing financial is ever deleted.** Products, categories, suppliers and
    users are deactivated, not removed. Sales, movements and audit events cannot
    be deleted at all.
11. **Sensitive actions are audited.** Sign-ins and failed sign-ins, product and
    stock changes, sales, reversals, user changes, settings changes and exports
    all write an `AuditEvent` that cannot be edited or deleted.
12. **Permissions are enforced on the server.** Owner-only views raise 403 for a
    shopkeeper even if they type the URL directly. Hidden nav links are a
    courtesy, never the rule.

### Roles

| | Owner | Shopkeeper |
| --- | :---: | :---: |
| Record sales, print receipts | ● | ● |
| Products, categories, suppliers | ● | ● |
| Receive stock; record damage, expiry, loss, returns | ● | ● |
| View sales and stock history | ● | ● |
| See cost prices and profit estimates | ● | |
| Reverse a completed sale | ● | |
| Manage users | ● | |
| Change shop settings | ● | |
| Read the audit history | ● | |

The shop can never be left without an active owner: an owner cannot switch off
their own account or change their own role, and the last active owner is
protected.

---

## How the code is arranged

```
config/            settings, URLs, WSGI
apps/
  core/            shop settings, audit trail, dashboard, permissions, shared utils
  accounts/        User model with a role, login, user management
  catalog/         Category, Supplier, Product
  inventory/       StockBatch, StockMovement + every stock-changing service
  sales/           Sale, SaleItem, the till, receipts, reversal
  reports/         read-only aggregations and CSV exports (no models)
templates/         one directory per app, plus shared partials/
static/
  css/theme.css    the design system
  js/app.js        connection banner, submit guards, small shared behaviour
  js/pos.js        the till
  vendor/          Bootstrap and HTMX, vendored — no CDN, no network at runtime
```

**Where the rules live.** Business logic is in `services.py`, not in views or
models. Views parse the request, call a service, and render. That is why the
same rule holds whether a sale arrives from the till, a management command or a
test.

**Design system.** `static/css/theme.css` is the single source of visual truth:
tokens, then components. It overrides Bootstrap's CSS custom properties rather
than fighting its stylesheet, so Bootstrap's grid and utilities still work.

The structure follows the **Paces "SaaS" skin**:

* a **floating shell** — sidebar and topbar inset from the viewport by a shared
  `--gutter` and rounded, sitting on a soft tinted canvas;
* a **light sidebar** with tinted active states rather than a dark rail;
* **Poppins** at a tight type scale (`--fs-xxs` 11px → `--fs-display`), with
  weights capped at 600 for the airy feel the skin depends on;
* **soft-tint status colours** — `rgba(hue, .13)` fills with darker
  `-emphasis` text, shown as pills;
* **metric cards** with a soft icon tile in the top-right corner;
* generous card padding (`1.5rem`) and a near-invisible shadow.

The **palette stays organic**. The template's `#0a74ff` would make a produce
shop look like a payments dashboard, so the SaaS token *structure* is mapped
onto deep leaf green, with status hues warmed and desaturated to match.

**Responsive approach.** The floating inset collapses to zero on phones — the
screen *is* the panel. Tables become genuine stacked cards below 768px (not a
squeezed grid), navigation becomes a bottom tab bar, metric cards go two-up so
the owner sees the whole picture without scrolling, and the till grows a pinned
running total so the shopkeeper is never adding items blind. Verified with no
horizontal overflow at 320, 375, 768, 1024 and 1440px.

---

## Deviations from the original brief

Each of these was a deliberate call. They are listed so a future maintainer
knows they were decisions, not oversights.

1. **`Product.stock_quantity` is a maintained cache, not a free-form number.**
   The ledger and the batches are authoritative. The cached total is updated
   inside the same transaction as every movement, is `editable=False`, appears
   in no form, and is guarded by a `CHECK (>= 0)` constraint. It exists so the
   product list and dashboard do not have to aggregate the whole ledger on every
   page load. `manage.py verify_stock` proves the three agree, and can repair
   them if a manual database edit ever breaks the invariant.

2. **Sale statuses are `completed` and `reversed` only.** The brief suggested
   also `draft` and `cancelled`. An unfinished cart is held in the browser's
   local storage, so no draft row is ever created; and since a sale is only
   written once it is complete, there is nothing to cancel. Fewer states means
   fewer ways for a report to be subtly wrong.

3. **Roles are checked directly, not through Django Groups and permissions.**
   Two roles with clear boundaries are better served by
   `OwnerRequiredMixin` / `@owner_required` than by a permission matrix an
   owner could accidentally misconfigure. Django's authentication, password
   hashing and sessions are used as-is.

4. **The till submits as an ordinary form POST, not as JSON over `fetch`.**
   If the server rejects the sale it re-renders the page with the cart intact
   and a plain message. That is far more robust on a flaky connection than
   client-side error handling, and it works even if JavaScript fails to load.

5. **Receiving stock and adjustments use a two-step review page**, not a modal.
   These change money and stock, and the confirmation screen shows the expected
   quantity afterwards. It works without JavaScript.

6. **The service worker is registered in production only.** In development a
   cache-first worker serves yesterday's CSS and JavaScript, which wastes a
   developer's afternoon. In production, static files are hashed, so cache-first
   is correct.

7. **PWA support is deliberately shallow.** The app is installable and shows a
   proper offline page, but sales are never queued offline — see below.

8. **`ruff` replaced `black`.** It lints and formats, so there is one tool and
   one configuration instead of two that can disagree.

9. **Two typefaces, both vendored locally.** The SaaS skin specifies Poppins,
   and Poppins carries the interface. But Poppins has *proportional* digits and
   no `tnum` feature — a "1" is 7.2px where a "4" is 13.2px — so a column of
   cedi amounts never lines up, and `font-variant-numeric: tabular-nums` is
   silently ignored. Every figure therefore renders in **Inter** (one variable
   file, 48KB) via `--font-num`, scoped to `.tnum`, metric values, cart totals
   and quantity inputs. Those elements contain only numbers, so the two faces
   never mix inside a phrase. Both are served from `static/fonts/` — the app
   makes **no network request at runtime**, which matters on a shop connection
   that drops.

10. **The base font size is one step up from the skin's.** Paces SaaS runs a
    13px body; this runs 14px. The brief asks for no unreadably small controls,
    and the people using it are standing at a counter, not studying a console.

---

## Known limitations

- **Sales cannot be made offline.** This is intentional. A sale is not a sale
  until the server has confirmed it; queueing sales in the browser would risk
  overselling stock that another till already sold. What the app does instead:
  shows a visible offline banner, keeps the unfinished cart on the device
  through refreshes and crashes, and makes retrying safe through idempotency
  keys. Genuinely offline selling needs a different architecture — see below.
- **No partial refunds.** A sale is reversed in full. A single returned item is
  recorded as a customer return through Stock adjustments, which puts the stock
  back and leaves a reason. The money side is handled at the till.
- **Gross profit is an estimate, and is labelled as one everywhere it appears.**
  It is revenue minus the cost of the goods sold. Rent, wages, transport,
  electricity and taxes are not included. This is not accounting software.
- **One shop, one location.** There is no concept of branches or stock transfers.
- **No supplier ordering.** The app tells you what needs restocking; placing the
  order is a phone call.
- **Reports are capped** (top 100 products, 100 recent adjustments) to keep pages
  fast. The CSV exports are complete and unbounded.
- **No password reset by email.** The owner sets a new password for a
  shopkeeper in person, which is recorded in the audit history. A single shop
  does not need mail infrastructure.
- **Deleting a user keeps their history.** Audit events and movements retain the
  person's name as text even after the account is removed. Deactivating is
  strongly preferred to deleting.

---

## Future improvements

Roughly in order of value to the shop:

1. **Barcode label printing**, so products without a manufacturer barcode can be
   scanned at the till.
2. **Purchase orders** — turn the low-stock list into an order to send a
   supplier, then receive against it in one step.
3. **Stock-take mode**: scan the shelf, see every discrepancy at once, and post
   the corrections as a single batch of adjustments.
4. **Partial refunds** with a proper credit record, if the shop starts needing
   them often.
5. **Offline selling**, if the connection genuinely becomes the limiting factor.
   This is a real architectural change, not a feature: it needs client-side
   sale numbering, a sync queue, and a documented policy for what happens when
   two tills sold the same last item while offline. Do not attempt it as an
   add-on to the current design.
6. **Daily figures by email** to the owner, if they want them pushed rather than
   pulled.
7. **Multi-currency or VAT**, only if the shop's obligations change.

---

## Licence

Private software for JCF Organic.
