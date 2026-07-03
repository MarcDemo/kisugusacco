# Production Deployment Guide

This project should deploy code through Git while keeping production data on the server. Do not upload or commit `db.sqlite3`, `.env`, media uploads, logs, or backups.

## Production Database

Use MySQL on cPanel production and keep SQLite for local development/testing only.

1. Create a fresh MySQL database and user in cPanel.
2. Copy `.env.example` to `.env` on the server.
3. Fill in the production values:
   - `DJANGO_DEBUG=False`
   - `DJANGO_SECRET_KEY`
   - `DJANGO_ALLOWED_HOSTS`
   - `DB_ENGINE=mysql`
   - `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
   - email credentials
   - `DJANGO_MEDIA_ROOT` and `DJANGO_STATIC_ROOT`
   - quote secrets/passwords with single quotes when they contain special characters
4. Run migrations against the empty production database.
5. Create the first admin user with `python manage.py createsuperuser`.

Do not copy the local SQLite database to production. Once real data exists, never reset, flush, drop, or overwrite the production database as part of deployment.

## GitHub Actions Secrets

Add these repository secrets in GitHub:

- `CPANEL_HOST`
- `CPANEL_USER`
- `CPANEL_SSH_KEY`
- `CPANEL_SSH_PORT`, optional, defaults to `22`
- `CPANEL_APP_DIR`, for example `/home/cpaneluser/kisugu`

The server should already have a Git clone of the project in `CPANEL_APP_DIR`. The workflow runs tests first, then SSHes into cPanel and runs:

```bash
git pull --ff-only
bash scripts/deploy_cpanel.sh
```

The deploy script installs dependencies, runs migrations, collects static files, and restarts the app by touching `tmp/restart.txt`. If your cPanel app needs a different restart command, set `DJANGO_RESTART_COMMAND` in `.env`.

## Weekly Backups

Create a cPanel cron job for the MySQL backup:

```bash
bash /home/cpaneluser/kisugu/scripts/backup_mysql.sh
```

Create a separate cron job for uploaded files:

```bash
bash /home/cpaneluser/kisugu/scripts/backup_media.sh
```

Recommended schedule:

- Database: weekly, during low-traffic hours.
- Media uploads: weekly, after the database backup.
- Retention: `BACKUP_RETENTION_DAYS=84`, keeping roughly 12 weeks.

Backups should be stored outside the public web directory, such as `/home/cpaneluser/backups/kisugu`. Download or sync backups to another location periodically so a server failure does not remove both the live data and the backups.

## Pre-Deploy Backups

Set this on the production server if you want every deployment to make a database backup before migrations:

```bash
RUN_PRE_DEPLOY_BACKUP=1
```

For the first deployment, leave it as `0` until the MySQL database exists and `.env` has the final credentials.

## Go-Live Checklist

- `.env` exists on the server and is not committed to Git.
- `db.sqlite3` is not committed and is not copied to the server.
- Production MySQL database is empty before first real-data launch.
- `python manage.py migrate` succeeds on production.
- `python manage.py createsuperuser` has been run.
- Weekly database and media backup cron jobs have been created.
- A test backup restore has been tried at least once before relying on the backups.
