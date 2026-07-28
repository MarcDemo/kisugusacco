import csv
from html import escape
from pathlib import Path
import re
import secrets

from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import URLValidator, validate_email
from django.db import transaction
from django.utils import timezone

from groupcore.models import MemberProfile


GROUP_NAME = "St. Stephen's Kisugu Savings and Loans Association (SSLA)"
DEFAULT_LOGIN_URL = 'https://kisugusacco.org/login/'
MINIMUM_TEMPORARY_PASSWORD_LENGTH = 8
REPORT_FIELDS = (
    'requested_name',
    'status',
    'user_id',
    'username',
    'email',
    'welcome_sent_at',
    'message',
)


class Command(BaseCommand):
    help = (
        'Email temporary login credentials to an explicitly named set of existing members. '
        'The command is a dry run unless --send is supplied.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--file',
            required=True,
            help='UTF-8 text file containing one member name per line. Leading bullet markers are allowed.',
        )
        parser.add_argument(
            '--report',
            default='welcome_credentials_report.csv',
            help='CSV report path. Temporary passwords are never written to this report.',
        )
        parser.add_argument(
            '--login-url',
            default=DEFAULT_LOGIN_URL,
            help=f'Login link included in each email (default: {DEFAULT_LOGIN_URL}).',
        )
        parser.add_argument(
            '--password-length',
            type=int,
            default=10,
            help='Temporary password length. The minimum is 8 characters.',
        )
        parser.add_argument(
            '--send',
            action='store_true',
            help='Reset eligible passwords and send the welcome emails.',
        )
        parser.add_argument(
            '--resend',
            action='store_true',
            help='Also reset and resend credentials to members already marked as welcomed.',
        )

    def handle(self, *args, **options):
        names_path = Path(options['file'])
        report_path = Path(options['report'])
        login_url = options['login_url'].strip()
        password_length = options['password_length']
        should_send = options['send']
        resend = options['resend']

        if password_length < MINIMUM_TEMPORARY_PASSWORD_LENGTH:
            raise CommandError(
                f'Temporary passwords must be at least '
                f'{MINIMUM_TEMPORARY_PASSWORD_LENGTH} characters.'
            )
        try:
            URLValidator(schemes=['https', 'http'])(login_url)
        except ValidationError as exc:
            raise CommandError(f'Invalid login URL: {login_url}') from exc
        if not names_path.exists():
            raise CommandError(f'Member names file not found: {names_path}')

        names = self._load_names(names_path)
        report_rows, deliveries, blockers = self._preflight(names, resend=resend)
        self._write_report(report_path, report_rows)
        if blockers:
            raise CommandError(
                f'Welcome delivery blocked: {blockers} target(s) need correction. '
                f'No passwords were changed and no emails were sent. Review {report_path}.'
            )

        ready_count = len(deliveries)
        skipped_count = sum(row['status'] == 'ALREADY_SENT' for row in report_rows)
        if not should_send:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Dry run passed: {ready_count} member(s) ready, '
                    f'{skipped_count} already welcomed. No passwords were changed and '
                    f'no emails were sent. Review {report_path}, then rerun with --send.'
                )
            )
            return

        if (
            settings.EMAIL_BACKEND.endswith('smtp.EmailBackend')
            and (
                not getattr(settings, 'EMAIL_HOST_USER', '')
                or not getattr(settings, 'EMAIL_HOST_PASSWORD', '')
            )
        ):
            raise CommandError(
                'SMTP credentials are not configured. No passwords were changed and no emails were sent.'
            )

        report_by_name = {
            row['requested_name'].casefold(): row for row in report_rows
        }
        failures = 0
        delivered = 0
        for requested_name, user_id in deliveries:
            row = report_by_name[requested_name.casefold()]
            temporary_password = None
            try:
                with transaction.atomic():
                    member = MemberProfile.objects.select_for_update().get(pk=user_id)
                    if member.welcome_email_sent_at and not resend:
                        row['status'] = 'ALREADY_SENT'
                        row['message'] = 'Skipped because another process already sent the welcome email.'
                        continue
                    temporary_password = self._temporary_password(
                        password_length,
                        member=member,
                    )
                    member.set_password(temporary_password)
                    member.save(update_fields=['password'])
                    self._send_email(
                        member=member,
                        temporary_password=temporary_password,
                        login_url=login_url,
                    )
                    member.welcome_email_sent_at = timezone.now()
                    member.save(update_fields=['welcome_email_sent_at'])
                    row['status'] = 'SENT'
                    row['welcome_sent_at'] = member.welcome_email_sent_at.isoformat()
                    row['message'] = 'Welcome email sent and temporary password activated.'
                    delivered += 1
            except Exception as exc:
                failures += 1
                row['status'] = 'SEND_ERROR'
                row['message'] = f'{type(exc).__name__}: {exc}'
            finally:
                temporary_password = None

        self._write_report(report_path, report_rows)
        if failures:
            raise CommandError(
                f'Sent {delivered} welcome email(s); {failures} failed. '
                f'Successful members will be skipped on the next run. Review {report_path}.'
            )
        self.stdout.write(
            self.style.SUCCESS(
                f'Sent {delivered} welcome email(s). Temporary passwords were not logged. '
                f'Review {report_path}.'
            )
        )

    def _load_names(self, path):
        names = []
        seen = set()
        duplicate_names = []
        with path.open(encoding='utf-8-sig') as handle:
            for raw_line in handle:
                value = raw_line.strip()
                if not value or value.startswith('#'):
                    continue
                value = re.sub(r'^\s*[-*•]\s*', '', value).strip()
                if value.casefold() == 'name':
                    continue
                key = self._normalise(value)
                if not key:
                    continue
                if key in seen:
                    duplicate_names.append(value)
                    continue
                seen.add(key)
                names.append(value)
        if duplicate_names:
            raise CommandError(
                'Duplicate names in target file: ' + ', '.join(duplicate_names)
            )
        if not names:
            raise CommandError('The target file does not contain any member names.')
        return names

    def _preflight(self, names, resend=False):
        users = list(MemberProfile.objects.filter(is_superuser=False))
        report_rows = []
        deliveries = []
        blockers = 0
        email_targets = {}

        for requested_name in names:
            target_key = self._normalise(requested_name)
            matches = [
                user for user in users
                if target_key in self._identity_keys(user)
            ]
            row = {
                'requested_name': requested_name,
                'status': '',
                'user_id': '',
                'username': '',
                'email': '',
                'welcome_sent_at': '',
                'message': '',
            }
            if not matches:
                row['status'] = 'NO_MATCH'
                row['message'] = 'No existing member matched this exact normalised name or username.'
                blockers += 1
            elif len(matches) > 1:
                row['status'] = 'AMBIGUOUS'
                row['message'] = 'Matched multiple users: ' + ', '.join(
                    user.username for user in matches
                )
                blockers += 1
            else:
                user = matches[0]
                email = (user.email or '').strip().lower()
                row.update({
                    'user_id': user.id,
                    'username': user.username,
                    'email': email,
                    'welcome_sent_at': (
                        user.welcome_email_sent_at.isoformat()
                        if user.welcome_email_sent_at else ''
                    ),
                })
                if not user.is_active:
                    row['status'] = 'INACTIVE'
                    row['message'] = 'The matched member account is inactive.'
                    blockers += 1
                elif not email:
                    row['status'] = 'MISSING_EMAIL'
                    row['message'] = 'The matched member does not have an email address.'
                    blockers += 1
                elif not self._valid_email(email):
                    row['status'] = 'INVALID_EMAIL'
                    row['message'] = 'The matched member has an invalid email address.'
                    blockers += 1
                elif user.welcome_email_sent_at and not resend:
                    row['status'] = 'ALREADY_SENT'
                    row['message'] = 'Welcome credentials were already sent; use --resend to replace them.'
                else:
                    row['status'] = 'READY_RESEND' if user.welcome_email_sent_at else 'READY'
                    row['message'] = 'Ready to reset password and send welcome email.'
                    deliveries.append((requested_name, user.id))
                    email_targets.setdefault(email, []).append(row)
            report_rows.append(row)

        for email, rows in email_targets.items():
            if len(rows) < 2:
                continue
            blockers += len(rows)
            usernames = ', '.join(row['username'] for row in rows)
            for row in rows:
                row['status'] = 'DUPLICATE_EMAIL'
                row['message'] = (
                    f'This email belongs to multiple targeted accounts: {usernames}.'
                )
                deliveries = [
                    item for item in deliveries
                    if item[0].casefold() != row['requested_name'].casefold()
                ]
        return report_rows, deliveries, blockers

    @staticmethod
    def _normalise(value):
        return ''.join(character for character in value.casefold() if character.isalnum())

    def _identity_keys(self, user):
        full_name = user.get_full_name().strip()
        reverse_name = ' '.join(
            part for part in [user.last_name, user.first_name] if part
        )
        return {
            self._normalise(value)
            for value in (user.username, full_name, reverse_name)
            if value
        }

    @staticmethod
    def _valid_email(value):
        try:
            validate_email(value)
        except ValidationError:
            return False
        return True

    @staticmethod
    def _temporary_password(length, member):
        uppercase = 'ABCDEFGHJKLMNPQRSTUVWXYZ'
        lowercase = 'abcdefghijkmnopqrstuvwxyz'
        digits = '23456789'
        alphabet = uppercase + lowercase + digits
        for _ in range(100):
            characters = [
                secrets.choice(uppercase),
                secrets.choice(lowercase),
                secrets.choice(digits),
            ]
            characters.extend(
                secrets.choice(alphabet) for _ in range(length - len(characters))
            )
            secrets.SystemRandom().shuffle(characters)
            candidate = ''.join(characters)
            try:
                password_validation.validate_password(candidate, user=member)
            except ValidationError:
                continue
            return candidate
        raise CommandError('Could not generate a password accepted by Django validation.')

    @staticmethod
    def _send_email(member, temporary_password, login_url):
        member_name = member.get_full_name().strip() or member.username
        subject = f'Welcome to {GROUP_NAME}'
        text_body = (
            f'Dear {member_name},\n\n'
            f'Welcome to {GROUP_NAME}.\n\n'
            f'Login page: {login_url}\n'
            f'Username: {member.username}\n'
            f'Temporary password: {temporary_password}\n\n'
            'How to log in:\n'
            '1. Open the login page above.\n'
            '2. Enter your username and temporary password exactly as shown.\n'
            '3. After logging in, open My Profile and select Change Password.\n'
            '4. Choose a private password that you do not use on another website.\n\n'
            'Do not share your temporary password with anyone.\n\n'
            'Regards,\n'
            f'{GROUP_NAME}'
        )
        html_body = (
            f'<p>Dear {escape(member_name)},</p>'
            f'<p>Welcome to <strong>{escape(GROUP_NAME)}</strong>.</p>'
            '<div style="padding:16px;border:1px solid #d6eadb;border-radius:8px;background:#f4fbf6">'
            f'<p><strong>Login page:</strong> <a href="{escape(login_url)}">{escape(login_url)}</a></p>'
            f'<p><strong>Username:</strong> {escape(member.username)}<br>'
            f'<strong>Temporary password:</strong> {escape(temporary_password)}</p>'
            '</div>'
            '<h3>How to log in</h3>'
            '<ol>'
            '<li>Open the login page above.</li>'
            '<li>Enter your username and temporary password exactly as shown.</li>'
            '<li>After logging in, open <strong>My Profile</strong> and select <strong>Change Password</strong>.</li>'
            '<li>Choose a private password that you do not use on another website.</li>'
            '</ol>'
            '<p><strong>Do not share your temporary password with anyone.</strong></p>'
            f'<p>Regards,<br>{escape(GROUP_NAME)}</p>'
        )
        message = EmailMultiAlternatives(
            subject,
            text_body,
            settings.DEFAULT_FROM_EMAIL,
            [member.email],
        )
        message.attach_alternative(html_body, 'text/html')
        message.send(fail_silently=False)

    @staticmethod
    def _write_report(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
