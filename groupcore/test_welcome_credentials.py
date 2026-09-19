import csv
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from groupcore.management.commands.send_welcome_credentials import Command
from groupcore.models import MemberProfile


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='info@kisugusacco.org',
)
class BulkWelcomeCredentialsTests(TransactionTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.report = Path(self.directory.name) / 'report.csv'
        self.member = self.create_member('new-member')
        self.stdout = StringIO()
        self.stderr = StringIO()

    def create_member(self, username, **kwargs):
        defaults = {'email': f'{username}@example.com', 'password': None}
        defaults.update(kwargs)
        return MemberProfile.objects.create_user(username=username, **defaults)

    def run_command(self, **options):
        defaults = {
            'all_eligible': True,
            'report': str(self.report),
            'stdout': self.stdout,
            'stderr': self.stderr,
        }
        defaults.update(options)
        if not defaults.get('all_eligible'):
            defaults.pop('all_eligible', None)
        call_command('send_welcome_credentials', **defaults)
        with self.report.open(newline='', encoding='utf-8') as handle:
            return list(csv.DictReader(handle))

    def statuses(self, rows):
        return {row['username']: row['status'] for row in rows}

    def test_dry_run_is_read_only(self):
        original = self.member.password
        rows = self.run_command()
        self.assertEqual(self.statuses(rows), {'new-member': 'READY'})
        self.member.refresh_from_db()
        self.assertEqual(self.member.password, original)
        self.assertIsNone(self.member.welcome_email_sent_at)
        self.assertIsNone(self.member.welcome_email_attempted_at)
        self.assertEqual(len(mail.outbox), 0)

    def test_send_commits_before_smtp_and_rerun_skips(self):
        send_email = Command._send_email

        def inspect_reservation(**kwargs):
            self.assertFalse(connection.in_atomic_block)
            member = MemberProfile.objects.get(pk=kwargs['member'].pk)
            self.assertIsNotNone(member.welcome_email_attempted_at)
            self.assertIsNone(member.welcome_email_sent_at)
            self.assertTrue(member.check_password(kwargs['temporary_password']))
            return send_email(**kwargs)

        with patch.object(Command, '_send_email', side_effect=inspect_reservation):
            rows = self.run_command(send=True)
        self.assertEqual(self.statuses(rows), {'new-member': 'SENT'})
        self.assertTrue(rows[0]['welcome_attempted_at'])
        self.assertTrue(rows[0]['welcome_sent_at'])
        password = next(line.split(': ', 1)[1] for line in mail.outbox[0].body.splitlines()
                        if line.startswith('Temporary password: '))
        self.assertIsNotNone(authenticate(username=self.member.username, password=password))
        self.member.refresh_from_db()
        original = self.member.password
        for value in (password, original):
            self.assertNotIn(value, self.report.read_text())
            self.assertNotIn(value, self.stdout.getvalue() + self.stderr.getvalue())
        rows = self.run_command(send=True)
        self.assertEqual(self.statuses(rows), {'new-member': 'ALREADY_SENT'})
        self.assertEqual(len(mail.outbox), 1)
        self.member.refresh_from_db()
        self.assertEqual(self.member.password, original)

    def test_all_account_protections_apply_in_both_modes(self):
        protected = [
            (self.create_member('password', password='Existing-pass-123'), 'HAS_PASSWORD'),
            (self.create_member('login', last_login=timezone.now()), 'PREVIOUS_LOGIN'),
            (self.create_member('welcomed', welcome_email_sent_at=timezone.now()), 'ALREADY_SENT'),
            (self.create_member('attempted', welcome_email_attempted_at=timezone.now()), 'ALREADY_ATTEMPTED'),
            (self.create_member('inactive', is_active=False), 'INACTIVE'),
            (self.create_member('superuser', is_superuser=True), 'SUPERUSER'),
        ]
        for file_mode in (False, True):
            with self.subTest(file_mode=file_mode):
                options = {}
                if file_mode:
                    names = Path(self.directory.name) / 'names.txt'
                    names.write_text('\n'.join(member.username for member, _ in protected))
                    options = {'all_eligible': False, 'file': str(names)}
                statuses = self.statuses(self.run_command(send=True, **options))
                for member, status in protected:
                    self.assertEqual(statuses[member.username], status)
                    original = member.password
                    member.refresh_from_db()
                    self.assertEqual(member.password, original)
        self.assertEqual(len(mail.outbox), 1)

    def test_bad_and_shared_addresses_skip_while_eligible_member_sends(self):
        self.create_member('missing', email='  ')
        self.create_member('invalid', email='invalid-address')
        self.create_member('shared', email=' SHARED@example.com ')
        self.create_member('other', email='shared@EXAMPLE.com', password='Existing-pass-123', is_active=False)
        statuses = self.statuses(self.run_command(send=True))
        self.assertEqual(statuses['missing'], 'MISSING_EMAIL')
        self.assertEqual(statuses['invalid'], 'INVALID_EMAIL')
        self.assertEqual(statuses['shared'], 'DUPLICATE_EMAIL')
        self.assertEqual(statuses['new-member'], 'SENT')
        self.assertEqual(len(mail.outbox), 1)

    def test_file_selection_checks_shared_email_outside_target_list(self):
        self.create_member('other', email=self.member.email.upper(), is_superuser=True)
        names = Path(self.directory.name) / 'names.txt'
        names.write_text(self.member.username)
        rows = self.run_command(all_eligible=False, file=str(names), send=True)
        self.assertEqual(rows[0]['status'], 'DUPLICATE_EMAIL')
        self.assertEqual(len(mail.outbox), 0)

    def test_rechecks_changes_after_preflight(self):
        changes = [
            ({'password': 'changed-password-hash'}, 'HAS_PASSWORD'),
            ({'last_login': timezone.now()}, 'PREVIOUS_LOGIN'),
            ({'welcome_email_sent_at': timezone.now()}, 'ALREADY_SENT'),
            ({'welcome_email_attempted_at': timezone.now()}, 'ALREADY_ATTEMPTED'),
            ({'is_active': False}, 'INACTIVE'),
            ({'is_superuser': True}, 'SUPERUSER'),
            ({'email': 'invalid'}, 'INVALID_EMAIL'),
        ]
        preflight = Command._preflight
        for fields, expected in changes:
            with self.subTest(expected=expected):
                MemberProfile.objects.filter(pk=self.member.pk).update(
                    password=self.member.password, last_login=None, welcome_email_sent_at=None,
                    welcome_email_attempted_at=None, is_active=True, is_superuser=False,
                    email=self.member.email,
                )

                def change_after_preview(command, names=None):
                    result = preflight(command, names)
                    MemberProfile.objects.filter(pk=self.member.pk).update(**fields)
                    return result

                with patch.object(Command, '_preflight', change_after_preview):
                    rows = self.run_command(send=True)
                self.assertEqual(rows[0]['status'], expected)
        self.assertEqual(len(mail.outbox), 0)

    def test_rechecks_shared_addresses_before_reservation(self):
        preflight = Command._preflight

        def add_duplicate(command, names=None):
            result = preflight(command, names)
            self.create_member('duplicate', email=self.member.email)
            return result

        with patch.object(Command, '_preflight', add_duplicate):
            rows = self.run_command(send=True)
        self.assertEqual(rows[0]['status'], 'DUPLICATE_EMAIL')
        self.assertEqual(len(mail.outbox), 0)

    def test_smtp_failures_and_zero_acceptance_reserve_without_leaking_credentials(self):
        for outcome in ('exception', 'zero'):
            with self.subTest(outcome=outcome):
                MemberProfile.objects.filter(pk=self.member.pk).update(
                    password=self.member.password, welcome_email_attempted_at=None,
                )
                secret = 'Secret-for-test-123'

                def fail(**kwargs):
                    if outcome == 'exception':
                        raise RuntimeError(kwargs['temporary_password'])
                    return 0

                with patch.object(Command, '_temporary_password', return_value=secret), \
                        patch.object(Command, '_send_email', side_effect=fail):
                    with self.assertRaises(CommandError):
                        self.run_command(send=True)
                self.member.refresh_from_db()
                self.assertIsNotNone(self.member.welcome_email_attempted_at)
                self.assertIsNone(self.member.welcome_email_sent_at)
                self.assertNotIn(secret, self.report.read_text())
                self.assertNotIn(secret, self.stdout.getvalue() + self.stderr.getvalue())
                rows = self.run_command(send=True)
                self.assertEqual(rows[0]['status'], 'ALREADY_ATTEMPTED')
                self.member.set_unusable_password()
        self.assertEqual(len(mail.outbox), 0)

    def test_interrupted_attempt_is_not_retried(self):
        with patch.object(Command, '_send_email', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.run_command(send=True)
        self.member.refresh_from_db()
        self.assertIsNotNone(self.member.welcome_email_attempted_at)
        self.assertIsNone(self.member.welcome_email_sent_at)
        self.assertEqual(self.run_command(send=True)[0]['status'], 'ALREADY_ATTEMPTED')
        self.assertEqual(len(mail.outbox), 0)

    def test_overlapping_run_skips_committed_attempt(self):
        send_email = Command._send_email

        def run_again_before_smtp(**kwargs):
            rows = self.run_command(send=True)
            self.assertEqual(rows[0]['status'], 'ALREADY_ATTEMPTED')
            return send_email(**kwargs)

        with patch.object(Command, '_send_email', side_effect=run_again_before_smtp):
            self.run_command(send=True)
        self.assertEqual(len(mail.outbox), 1)

    def test_backend_zero_return_does_not_mark_sent(self):
        with patch('groupcore.management.commands.send_welcome_credentials.EmailMultiAlternatives.send', return_value=0):
            with self.assertRaises(CommandError):
                self.run_command(send=True)
        self.member.refresh_from_db()
        self.assertIsNone(self.member.welcome_email_sent_at)
        self.assertIsNotNone(self.member.welcome_email_attempted_at)

    def test_failed_member_does_not_stop_other_eligible_deliveries(self):
        self.create_member('second')
        send_email = Command._send_email

        def fail_first(**kwargs):
            if kwargs['member'].pk == self.member.pk:
                raise RuntimeError('SMTP unavailable')
            return send_email(**kwargs)

        with patch.object(Command, '_send_email', side_effect=fail_first):
            with self.assertRaises(CommandError):
                self.run_command(send=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['second@example.com'])
        rows = self.run_command(send=True)
        self.assertEqual(self.statuses(rows), {'new-member': 'ALREADY_ATTEMPTED', 'second': 'ALREADY_SENT'})

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.smtp.EmailBackend',
        EMAIL_HOST_USER='',
        EMAIL_HOST_PASSWORD='',
    )
    def test_missing_smtp_settings_do_not_reserve_attempt(self):
        with self.assertRaisesMessage(CommandError, 'SMTP credentials are not configured'):
            self.run_command(send=True)
        self.member.refresh_from_db()
        self.assertIsNone(self.member.welcome_email_attempted_at)
        self.assertFalse(self.member.has_usable_password())

    def test_accepted_email_with_failed_success_record_is_not_retried(self):
        save = MemberProfile.save

        def fail_success_record(member, *args, **kwargs):
            if kwargs.get('update_fields') == ['welcome_email_sent_at']:
                raise RuntimeError('Database unavailable')
            return save(member, *args, **kwargs)

        with patch.object(MemberProfile, 'save', fail_success_record):
            with self.assertRaises(CommandError):
                self.run_command(send=True)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(self.run_command(send=True)[0]['status'], 'ALREADY_ATTEMPTED')
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_and_unsafe_backends_are_rejected(self):
        with self.assertRaisesMessage(CommandError, '--resend is disabled'):
            self.run_command(send=True, resend=True)
        for backend in ('console', 'filebased', 'dummy'):
            with self.subTest(backend=backend), override_settings(
                EMAIL_BACKEND=f'django.core.mail.backends.{backend}.EmailBackend',
            ):
                with self.assertRaisesMessage(CommandError, 'credential logging is forbidden'):
                    self.run_command(send=True)
        self.member.refresh_from_db()
        self.assertFalse(self.member.has_usable_password())
        self.assertIsNone(self.member.welcome_email_attempted_at)

    def test_nested_transaction_is_rejected_before_reservation(self):
        with transaction.atomic():
            with self.assertRaisesMessage(CommandError, 'outside an enclosing transaction'):
                self.run_command(send=True)
        self.member.refresh_from_db()
        self.assertIsNone(self.member.welcome_email_attempted_at)

    def test_bulk_selection_uses_ids_for_members_with_identical_names(self):
        self.member.first_name = 'Same'
        self.member.last_name = 'Name'
        self.member.save()
        self.create_member('second', first_name='Same', last_name='Name')
        rows = self.run_command(send=True)
        self.assertEqual([row['status'] for row in rows], ['SENT', 'SENT'])
        self.assertEqual(len(mail.outbox), 2)

    def test_multiple_aliases_for_one_account_send_only_once(self):
        self.member.first_name = 'Some'
        self.member.last_name = 'Member'
        self.member.save()
        names = Path(self.directory.name) / 'names.txt'
        names.write_text('new-member\nSome Member')
        rows = self.run_command(all_eligible=False, file=str(names), send=True)
        self.assertEqual([row['status'] for row in rows], ['SENT', 'DUPLICATE_TARGET'])
        self.assertEqual(len(mail.outbox), 1)

    def test_selection_is_required_and_mutually_exclusive(self):
        with self.assertRaises(CommandError):
            self.run_command(all_eligible=False)
        with self.assertRaises(CommandError):
            self.run_command(file='names.txt')
