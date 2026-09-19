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

## Namecheap cPanel Python App

In cPanel, open **Setup Python App** and create the Django app with these values:

- Python version: 3.10 or 3.11
- Application root: `/home/cpaneluser/kisugu`
- Application URL: `kisugusacco.org`
- Application startup file: `passenger_wsgi.py`
- Application entry point: `application`

The `passenger_wsgi.py` file in the project root loads Django using `landgroup.settings`. After changing code or environment variables, restart the Python app from cPanel or touch `tmp/restart.txt`.

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

The deploy script installs `requirements-production.txt`, runs migrations, collects static files, and restarts the app by touching `tmp/restart.txt`. If your cPanel app needs a different restart command, set `DJANGO_RESTART_COMMAND` in `.env`.

## Send initial welcome credentials

Deploy the updated code through the existing Git deployment process. In cPanel
Terminal, activate the production Python app environment and change to the app's
project directory. Use the production MySQL database and existing SMTP settings.
Do not substitute the local SQLite database.

Apply the migration if the deployment has not already done so, then preview:

```bash
python manage.py migrate --noinput
python manage.py send_welcome_credentials --all-eligible --report logs/welcome-preview.csv
```

The preview sends nothing and changes no credentials or delivery timestamps.
Review the CSV recipient list, counts, and exclusion reasons. Eligible users must
be enabled, not superusers, and have no usable password, prior login, recorded
welcome email, or reserved welcome attempt. Their email must be valid and not
shared with any other user account, including deactivated accounts and superusers.
An account with an existing password is excluded even if it has never logged in.

Send and then verify with a fresh preview:

```bash
python manage.py send_welcome_credentials --all-eligible --send --report logs/welcome-results.csv
python manage.py send_welcome_credentials --all-eligible --report logs/welcome-after.csv
```

The send command checks current eligibility again; the preview is not a frozen
recipient list. Each email contains the existing username, a new temporary
password, `https://kisugusacco.org/login/`, and instructions to change the password.
`SENT` means the mail backend accepted the email, not that inbox delivery was
confirmed. Reports contain recipient information but never passwords or hashes;
keep them private in the ignored `logs/` directory.

The password hash and `welcome_email_attempted_at` are committed before SMTP is
contacted. `welcome_email_sent_at` is recorded only after confirmed acceptance.
An interruption, timeout, or failed success-record update can leave a reserved
attempt without confirmed delivery. `ALREADY_ATTEMPTED`, `ATTEMPTED`, and
`SEND_ERROR` need investigation using the member ID, attempt timestamp, and mail
provider delivery records. Do not clear timestamps or passwords merely to rerun
the command; investigate first and use the existing password-recovery process
when necessary. Rerunning automatically skips reserved attempts and sent emails.
If an error happened before reservation, no attempt is stored and the member can
still qualify. The command exits with an error if any delivery failed or is
uncertain, while continuing with other eligible members.

`--file path/to/names.txt` remains available instead of `--all-eligible` and uses
the same protections. Unmatched or ambiguous names block a named batch; other
ineligible accounts are reported and skipped. `--resend` is disabled. Sending
requires SMTP; the in-memory backend is allowed for tests, while console, file,
and dummy backends are rejected. Do not invoke sending inside an enclosing
database transaction because the attempt must be committed before email delivery.

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
- Server dependencies are installed with `python -m pip install -r requirements-production.txt`.
- Production MySQL database is empty before first real-data launch.
- `python manage.py migrate` succeeds on production.
- `python manage.py createsuperuser` has been run.
- Weekly database and media backup cron jobs have been created.
- A test backup restore has been tried at least once before relying on the backups.
