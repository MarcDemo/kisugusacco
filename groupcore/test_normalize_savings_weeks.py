from datetime import date, time
from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from deposits.models import DepositSubmission
from fines.models import Fine
from groupcore.models import GroupSettings, MemberProfile, SavingsAccount


class NormalizeSavingsWeeksCommandTests(TestCase):
    def setUp(self):
        self.settings = GroupSettings.objects.create(
            week_one_start=date(2025, 7, 7)
        )
        self.member = MemberProfile.objects.create_user(
            username='week-normalizer-member',
            password='pass12345',
        )
        self.account = SavingsAccount.objects.create(
            owner=self.member,
            label='A',
        )

    def _deposit(self, payment_week, starting_week=None):
        return DepositSubmission.objects.create(
            member=self.member,
            account=self.account,
            submitted_by=self.member,
            payment_week=payment_week,
            starting_week=starting_week or payment_week,
            saving_amount=Decimal('10000.00'),
            payment_date=payment_week,
            payment_time=time(9, 0),
            status='APPROVED',
        )

    def _fine(self, reference_week, reason, member=None, account=None):
        return Fine.objects.create(
            member=member or self.member,
            account=self.account if account is None else account,
            fine_type='MISSED_WEEKLY_SAVING',
            reference_week=reference_week,
            reason=reason,
            amount=Decimal('1000.00'),
            issued_by=None,
        )

    def test_default_mode_is_a_dry_run(self):
        deposit = self._deposit(date(2025, 7, 7))
        fine = self._fine(
            date(2025, 7, 14),
            'Late weekly saving - Week closing 14 Jul 2025',
        )
        output = StringIO()

        call_command('normalize_savings_weeks', stdout=output)

        self.settings.refresh_from_db()
        deposit.refresh_from_db()
        fine.refresh_from_db()
        self.assertEqual(self.settings.week_one_start, date(2025, 7, 7))
        self.assertEqual(deposit.payment_week, date(2025, 7, 7))
        self.assertEqual(fine.reference_week, date(2025, 7, 14))
        self.assertIn('DRY RUN: no data was changed', output.getvalue())
        self.assertIn('2025-07-07 (Monday) -> 2025-07-11 (Friday)', output.getvalue())

    def test_commit_preserves_week_ordinal_across_year_reset(self):
        first_cycle_week = self._deposit(
            date(2025, 7, 7),
            starting_week=date(2025, 7, 14),
        )
        next_year_week_one = self._deposit(date(2026, 1, 5))
        off_cycle = self._deposit(date(2026, 1, 6))
        generated_fine = self._fine(
            date(2026, 1, 12),
            'Late weekly saving - Week closing 12 Jan 2026',
        )
        custom_fine = self._fine(
            date(2025, 7, 21),
            'Custom note mentioning an old saving week',
        )
        failed_to_save_fine = self._fine(
            date(2025, 7, 28),
            'Failed to save for account A for week closing 2025-07-28',
        )

        output = StringIO()
        call_command('normalize_savings_weeks', commit=True, stdout=output)

        self.settings.refresh_from_db()
        first_cycle_week.refresh_from_db()
        next_year_week_one.refresh_from_db()
        off_cycle.refresh_from_db()
        generated_fine.refresh_from_db()
        custom_fine.refresh_from_db()
        failed_to_save_fine.refresh_from_db()
        self.assertEqual(self.settings.week_one_start, date(2025, 7, 11))
        self.assertEqual(first_cycle_week.payment_week, date(2025, 7, 11))
        self.assertEqual(first_cycle_week.starting_week, date(2025, 7, 18))
        self.assertEqual(next_year_week_one.payment_week, date(2026, 1, 2))
        self.assertEqual(off_cycle.payment_week, date(2026, 1, 6))
        self.assertEqual(off_cycle.starting_week, date(2026, 1, 6))
        self.assertEqual(generated_fine.reference_week, date(2026, 1, 9))
        self.assertEqual(
            generated_fine.reason,
            'Late weekly saving - Week closing 09 Jan 2026',
        )
        self.assertEqual(custom_fine.reference_week, date(2025, 7, 25))
        self.assertEqual(custom_fine.reason, 'Custom note mentioning an old saving week')
        self.assertEqual(failed_to_save_fine.reference_week, date(2025, 8, 1))
        self.assertEqual(
            failed_to_save_fine.reason,
            'Failed to save for account A for week closing 2025-08-01',
        )
        self.assertIn('Normalization complete', output.getvalue())

    def test_target_fine_collision_rolls_back_every_change(self):
        deposit = self._deposit(date(2025, 7, 7))
        moving_fine = self._fine(
            date(2026, 1, 5),
            'Late weekly saving - Week closing 05 Jan 2026',
        )
        existing_target = self._fine(
            date(2026, 1, 2),
            'Existing Friday fine',
        )

        with self.assertRaisesMessage(CommandError, 'Normalization blocked'):
            call_command('normalize_savings_weeks', commit=True)

        self.settings.refresh_from_db()
        deposit.refresh_from_db()
        moving_fine.refresh_from_db()
        existing_target.refresh_from_db()
        self.assertEqual(self.settings.week_one_start, date(2025, 7, 7))
        self.assertEqual(deposit.payment_week, date(2025, 7, 7))
        self.assertEqual(moving_fine.reference_week, date(2026, 1, 5))
        self.assertEqual(existing_target.reference_week, date(2026, 1, 2))


class GroupSettingsWeekdayValidationTests(TestCase):
    def test_model_validation_rejects_non_friday_anchor(self):
        settings = GroupSettings(week_one_start=date(2025, 7, 7))

        with self.assertRaises(ValidationError) as raised:
            settings.full_clean()

        self.assertIn('week_one_start', raised.exception.message_dict)
        self.assertEqual(
            raised.exception.message_dict['week_one_start'],
            ['Week 1 start must be a Friday.'],
        )

    def test_singleton_validation_is_preserved(self):
        GroupSettings.objects.create(week_one_start=date(2025, 7, 11))
        duplicate = GroupSettings(week_one_start=date(2026, 1, 2))

        with self.assertRaisesMessage(
            ValidationError,
            'Only one group setting record is allowed.',
        ):
            duplicate.full_clean()
