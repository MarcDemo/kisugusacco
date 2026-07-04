import csv
from pathlib import Path

from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from groupcore.models import MemberProfile


class Command(BaseCommand):
    help = (
        "Safely update existing member usernames from a CSV mapping. "
        "Runs in dry-run mode unless --commit is supplied."
    )

    def add_arguments(self, parser):
        parser.add_argument('--file', required=True, help='CSV with old_username,new_username,email columns.')
        parser.add_argument('--report', help='Path for the update report CSV.')
        parser.add_argument('--commit', action='store_true', help='Write username updates to the database.')

    def handle(self, *args, **options):
        mapping_path = Path(options['file'])
        if not mapping_path.exists():
            raise CommandError(f'Username mapping file not found: {mapping_path}')

        report_path = Path(options['report'] or 'username_update_report.csv')
        rows = self._load_rows(mapping_path)
        report_rows, updates, errors = self._validate_rows(rows)

        if errors:
            self._write_report(report_path, report_rows)
            raise CommandError(
                f'Username update blocked: {len(errors)} row(s) need correction. Review {report_path}.'
            )

        if not options['commit']:
            self._write_report(report_path, report_rows)
            self.stdout.write(
                self.style.SUCCESS(
                    f'Dry run passed. No usernames changed. Review {report_path}, then rerun with --commit.'
                )
            )
            return

        with transaction.atomic():
            for report_index, user, new_username in updates:
                if user.username == new_username:
                    report_rows[report_index]['status'] = 'NO_CHANGE'
                    report_rows[report_index]['message'] = 'username already matches'
                    continue
                old_username = user.username
                user.username = new_username
                user.save(update_fields=['username'])
                report_rows[report_index]['status'] = 'UPDATED_USERNAME'
                report_rows[report_index]['message'] = f'{old_username} -> {new_username}'

        self._write_report(report_path, report_rows)
        self.stdout.write(self.style.SUCCESS(f'Username update completed. Review {report_path}.'))

    def _load_rows(self, mapping_path):
        with mapping_path.open(newline='', encoding='utf-8-sig') as handle:
            reader = csv.DictReader(handle)
            required = {'old_username', 'new_username'}
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise CommandError(f'Missing required columns: {", ".join(sorted(missing))}')
            rows = []
            for row_number, row in enumerate(reader, start=2):
                rows.append({
                    'row_number': row_number,
                    'old_username': (row.get('old_username') or '').strip(),
                    'new_username': (row.get('new_username') or '').strip(),
                    'email': (row.get('email') or '').strip().lower(),
                    'name': (row.get('name') or '').strip(),
                })
            return rows

    def _validate_rows(self, rows):
        validator = UnicodeUsernameValidator()
        report_rows = []
        updates = []
        errors = []
        seen_old = set()
        seen_new = set()

        for row in rows:
            row_errors = []
            old_username = row['old_username']
            new_username = row['new_username']
            old_key = old_username.lower()
            new_key = new_username.lower()

            if not old_username:
                row_errors.append('old_username is required')
            elif old_key in seen_old:
                row_errors.append(f'duplicate old_username in file: {old_username}')
            else:
                seen_old.add(old_key)

            if not new_username:
                row_errors.append('new_username is required')
            elif new_key in seen_new:
                row_errors.append(f'duplicate new_username in file: {new_username}')
            else:
                seen_new.add(new_key)

            if new_username:
                try:
                    validator(new_username)
                except ValidationError:
                    row_errors.append(f'new_username "{new_username}" contains invalid characters')
                if len(new_username) > 150:
                    row_errors.append(f'new_username "{new_username}" must be 150 characters or fewer')

            user = None
            if old_username:
                user = MemberProfile.objects.filter(username=old_username).first()
                if not user:
                    row_errors.append(f'user not found: {old_username}')
                elif row['email'] and (user.email or '').strip().lower() != row['email']:
                    row_errors.append(f'email mismatch for {old_username}')

            if user and new_username:
                conflict = (
                    MemberProfile.objects
                    .filter(username__iexact=new_username)
                    .exclude(pk=user.pk)
                    .first()
                )
                if conflict:
                    row_errors.append(f'new_username already belongs to another user: {new_username}')

            report_rows.append({
                'row': row['row_number'],
                'status': 'ERROR' if row_errors else 'VALID_UPDATE',
                'old_username': old_username,
                'new_username': new_username,
                'email': row['email'],
                'name': row['name'],
                'message': '; '.join(row_errors),
            })

            if row_errors:
                errors.extend(row_errors)
            else:
                updates.append((len(report_rows) - 1, user, new_username))

        return report_rows, updates, errors

    def _write_report(self, report_path, report_rows):
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open('w', newline='', encoding='utf-8') as handle:
            fieldnames = ['row', 'status', 'old_username', 'new_username', 'email', 'name', 'message']
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(report_rows)
