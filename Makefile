.PHONY: help install run test lint format migrate seed owner check backup restore

help:                ## Show this help
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:             ## Install development dependencies
	pip install -r requirements-dev.txt

run:                 ## Start the development server
	python manage.py runserver

test:                ## Run the whole test suite
	python manage.py test

lint:                ## Check formatting and linting
	ruff check .
	ruff format --check .

format:              ## Reformat and auto-fix
	ruff format .
	ruff check --fix .

migrate:             ## Apply database migrations
	python manage.py migrate

seed:                ## Load demo products, stock and sales
	python manage.py seed_demo

owner:               ## Create the first owner account
	python manage.py create_owner

check:               ## Django's production readiness checks
	python manage.py check --deploy

backup:              ## Dump the database to backup.sql
	pg_dump "$${DATABASE_URL:-postgres://localhost:5432/jcforganic}" > backup.sql
	@echo "Wrote backup.sql"

restore:             ## Restore the database from backup.sql
	psql "$${DATABASE_URL:-postgres://localhost:5432/jcforganic}" < backup.sql
