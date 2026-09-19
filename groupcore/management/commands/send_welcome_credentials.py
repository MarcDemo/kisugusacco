import csv
from collections import Counter
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
from django.db import connection, transaction
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
    'welcome_attempted_at',
    'message',
)


class Command(BaseCommand):
    help = (
        'Email initial login credentials to members who have never had login access. '
        'The command is a dry run unless --send is supplied.'
    )

    def add_arguments(self, parser):
        selection = parser.add_mutually_exclusive_group(required=True)
        selection.add_argument(
            '--all-eligible',
            action='store_true',
            help='Check every user and send only to eligible members.',
        )
        selection.add_argument(
            '--file',
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
            help='Create initial passwords and send the welcome emails.',
        )
        parser.add_argument(
            '--resend',
            action='store_true',
            help='Disabled: existing credentials and previous deliveries must never be replaced.',
        )

    def handle(self, *args, **options):
        report_path = Path(options['report'])
        login_url = options['login_url'].strip()
        password_length = options['password_length']
        should_send = options['send']

        if options['resend']:
            raise CommandError('--resend is disabled: existing credentials and previous attempts are protected.')
        if bool(options.get('file')) == bool(options.get('all_eligible')):
            raise CommandError('Choose exactly one of --file or --all-eligible.')
        if password_length < MINIMUM_TEMPORARY_PASSWORD_LENGTH:
            raise CommandError(
                f'Temporary passwords must be at least '
                f'{MINIMUM_TEMPORARY_PASSWORD_LENGTH} characters.'
            )
        try:
            URLValidator(schemes=['https', 'http'])(login_url)
        except ValidationError as exc:
            raise CommandError(f'Invalid login URL: {login_url}') from exc

        names = None
        if options.get('file'):
            names_path = Path(options['file'])
            if not names_path.is_file():
                raise CommandError(f'Member names file not found: {names_path}')
            if names_path.resolve() == report_path.resolve():
                raise CommandError('The report must not overwrite the member names file.')
            names = self._load_names(names_path)
        report_rows, deliveries, blockers = self._preflight(names)
        self._write_report(report_path, report_rows)
        if blockers:
            raise CommandError(
                f'Welcome delivery blocked: {blockers} target(s) need correction. '
                f'No passwords were changed and no emails were sent. Review {report_path}.'
            )

        ready_count = len(deliveries)
        skipped_count = len(report_rows) - ready_count
        if not should_send:
            self.stdout.write(self.style.SUCCESS(
                f'Dry run passed: {ready_count} member(s) ready, {skipped_count} skipped. '
                f'No passwords were changed and no emails were sent. Review {report_path}, '
                'then rerun with --send.'
            ))
            return

        if connection.in_atomic_block or not connection.get_autocommit():
            raise CommandError('Sending requires autocommit outside an enclosing transaction.')
        if settings.EMAIL_BACKEND not in {
            'django.core.mail.backends.smtp.EmailBackend',
            'django.core.mail.backends.locmem.EmailBackend',
        }:
            raise CommandError('Sending requires SMTP (or the in-memory test backend); credential logging is forbidden.')
        if (
            ready_count
            and settings.EMAIL_BACKEND.endswith('smtp.EmailBackend')
            and (
                not getattr(settings, 'EMAIL_HOST_USER', '')
                or not getattr(settings, 'EMAIL_HOST_PASSWORD', '')
            )
        ):
            raise CommandError(
                'SMTP credentials are not configured. No passwords were changed and no emails were sent.'
            )

        failures = 0
        delivered = 0
        for row in deliveries:
            temporary_password = None
            try:
                # Commit the reservation BEFORE SMTP. A crash or uncertain SMTP response
                # must never roll it back and make this account eligible for another send.
                with transaction.atomic(durable=True):
                    member = MemberProfile.objects.select_for_update().get(pk=row['user_id'])
                    self._update_member_row(row, member)
                    row['status'], row['message'] = self._eligibility(member, self._email_counts())
                    if row['status'] != 'READY':
                        continue
                    original_password = member.password
                    temporary_password = self._temporary_password(password_length, member=member)
                    member.set_password(temporary_password)
                    member.welcome_email_attempted_at = timezone.now()
                    # The conditional update also protects databases without row locks.
                    reserved = MemberProfile.objects.filter(
                        pk=member.pk,
                        password=original_password,
                        email=member.email,
                        is_active=True,
                        is_superuser=False,
                        last_login__isnull=True,
                        welcome_email_sent_at__isnull=True,
                        welcome_email_attempted_at__isnull=True,
                    ).update(
                        password=member.password,
                        welcome_email_attempted_at=member.welcome_email_attempted_at,
                    )
                    if not reserved:
                        row['status'] = 'CHANGED'
                        row['message'] = 'Account changed during reservation; no email sent.'
                        continue
                self._update_member_row(row, member)
                row['status'] = 'ATTEMPTED'
                row['message'] = 'Delivery reserved; investigate before any retry.'
                self._write_report(report_path, report_rows)
                accepted = self._send_email(
                    member=member,
                    temporary_password=temporary_password,
                    login_url=login_url,
                )
                if accepted != 1:
                    raise CommandError('The email backend did not confirm acceptance.')
                member.welcome_email_sent_at = timezone.now()
                member.save(update_fields=['welcome_email_sent_at'])
                self._update_member_row(row, member)
                row['status'] = 'SENT'
                row['message'] = 'Email accepted by backend; inbox delivery is not confirmed.'
                delivered += 1
            except Exception:
                failures += 1
                row['status'] = 'SEND_ERROR'
                # Backend exceptions can contain the complete email, including its password.
                row['message'] = 'Delivery failed or is uncertain. Investigate the attempt before any retry.'
            finally:
                temporary_password = None
                self._write_report(report_path, report_rows)

        skipped_count = sum(row['status'] not in {'SENT', 'SEND_ERROR'} for row in report_rows)
        summary = (
            f'Recorded {delivered} accepted welcome email(s); '
            f'{skipped_count} skipped; {failures} failed or uncertain.'
        )
        if failures:
            raise CommandError(
                f'{summary} Reserved attempts will be skipped on the next run. Review {report_path}.'
            )
        self.stdout.write(self.style.SUCCESS(f'{summary} Review {report_path}.'))

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

    def _preflight(self, names=None):
        users = list(MemberProfile.objects.all().order_by('pk'))
        email_counts = Counter(self._email_key(user.email) for user in users)
        report_rows = []
        deliveries = []
        blockers = 0
        targets = (
            [(user.get_full_name().strip() or user.username, [user]) for user in users]
            if names is None else [
                (name, [user for user in users if self._normalise(name) in self._identity_keys(user)])
                for name in names
            ]
        )
        seen_ids = set()
        for requested_name, matches in targets:
            row = dict.fromkeys(REPORT_FIELDS, '')
            row['requested_name'] = requested_name
            if not matches:
                row['status'] = 'NO_MATCH'
                row['message'] = 'No existing member matched this exact normalised name or username.'
                blockers += 1
            elif len(matches) > 1:
                row['status'] = 'AMBIGUOUS'
                row['message'] = 'Matched multiple users: ' + ', '.join(user.username for user in matches)
                blockers += 1
            else:
                user = matches[0]
                self._update_member_row(row, user)
                row['status'], row['message'] = self._eligibility(user, email_counts)
                if user.pk in seen_ids:
                    row['status'] = 'DUPLICATE_TARGET'
                    row['message'] = 'This account was already selected by another name.'
                seen_ids.add(user.pk)
                if row['status'] == 'READY':
                    deliveries.append(row)
            report_rows.append(row)
        return report_rows, deliveries, blockers

    @staticmethod
    def _email_key(value):
        return (value or '').strip().lower()

    def _email_counts(self):
        return Counter(self._email_key(email) for email in MemberProfile.objects.values_list('email', flat=True))

    def _update_member_row(self, row, user):
        row.update({
            'user_id': user.pk,
            'username': user.username,
            'email': self._email_key(user.email),
            'welcome_sent_at': user.welcome_email_sent_at.isoformat() if user.welcome_email_sent_at else '',
            'welcome_attempted_at': user.welcome_email_attempted_at.isoformat() if user.welcome_email_attempted_at else '',
        })

    def _eligibility(self, user, email_counts):
        if user.is_superuser:
            return 'SUPERUSER', 'Superusers are excluded.'
        if not user.is_active:
            return 'INACTIVE', 'The member account is deactivated.'
        if user.welcome_email_sent_at:
            return 'ALREADY_SENT', 'Welcome credentials were already sent.'
        if user.welcome_email_attempted_at:
            return 'ALREADY_ATTEMPTED', 'A previous delivery was reserved; investigate before any retry.'
        if user.last_login is not None:
            return 'PREVIOUS_LOGIN', 'The member has already logged in.'
        if user.has_usable_password():
            return 'HAS_PASSWORD', 'The member already has login credentials.'
        email = self._email_key(user.email)
        if not email:
            return 'MISSING_EMAIL', 'The member does not have an email address.'
        if not self._valid_email(email):
            return 'INVALID_EMAIL', 'The member has an invalid email address.'
        if email_counts[email] > 1:
            return 'DUPLICATE_EMAIL', 'This email address is shared by multiple user accounts.'
        return 'READY', 'Ready to create initial login credentials and send a welcome email.'

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
            [Command._email_key(member.email)],
        )
        message.attach_alternative(html_body, 'text/html')
        return message.send(fail_silently=False)

    @staticmethod
    def _write_report(path, rows):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('w', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
