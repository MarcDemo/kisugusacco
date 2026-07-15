from dataclasses import dataclass, field
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from deposits.models import DepositSubmission
from fines.models import Fine
from groupcore.models import GroupSettings


FRIDAY = 4
WEEKLY_FINE_TYPE = 'MISSED_WEEKLY_SAVING'


def _first_weekday_on_or_after(day, weekday):
    return day + timedelta(days=(weekday - day.weekday()) % 7)


def _cycle_start(anchor, saving_year, weekday):
    if saving_year == anchor.year:
        return anchor
    return _first_weekday_on_or_after(date(saving_year, 1, 1), weekday)


def _mapped_week(original, source_anchor, target_anchor):
    """Map an aligned source week by saving-year ordinal; return None off-cycle."""
    if original is None or original.year < source_anchor.year:
        return None

    source_start = _cycle_start(source_anchor, original.year, source_anchor.weekday())
    offset_days = (original - source_start).days
    if offset_days < 0 or offset_days % 7:
        return None

    target_start = (
        target_anchor
        if original.year == source_anchor.year
        else _first_weekday_on_or_after(date(original.year, 1, 1), FRIDAY)
    )
    return target_start + timedelta(weeks=offset_days // 7)


def _updated_generated_reason(fine, old_week, new_week):
    late_reason = f'Late weekly saving - Week closing {old_week:%d %b %Y}'
    if fine.reason == late_reason:
        return f'Late weekly saving - Week closing {new_week:%d %b %Y}'

    account_note = f" for account {fine.account.label}" if fine.account_id else ""
    failed_reason = f'Failed to save{account_note} for week closing {old_week}'
    if fine.reason == failed_reason:
        return f'Failed to save{account_note} for week closing {new_week}'

    return fine.reason


@dataclass
class NormalizationPlan:
    source_anchor: date
    target_anchor: date
    deposits: list
    fines: list
    payment_week_changes: int = 0
    starting_week_changes: int = 0
    fine_week_changes: int = 0
    fine_reason_changes: int = 0
    off_cycle_payment_weeks: int = 0
    off_cycle_starting_weeks: int = 0
    off_cycle_fine_weeks: int = 0
    changed_deposit_ids: set = field(default_factory=set)
    changed_fine_ids: set = field(default_factory=set)


class Command(BaseCommand):
    help = (
        'Normalize legacy saving-week dates to Friday while preserving each '
        'date\'s saving year and week ordinal. Runs as a dry run unless '
        '--commit is supplied.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--commit',
            action='store_true',
            help='Apply the displayed normalization plan to the database.',
        )

    def handle(self, *args, **options):
        commit = options['commit']

        with transaction.atomic():
            settings = GroupSettings.objects.select_for_update().order_by('pk').first()
            if settings is None:
                raise CommandError('No active GroupSettings record exists.')

            if settings.week_one_start.weekday() == FRIDAY:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Week 1 already starts on Friday '
                        f'({settings.week_one_start.isoformat()}); no changes are required.'
                    )
                )
                return

            plan = self._build_plan(settings)
            self._preflight_fine_collisions(plan)
            self._write_plan(plan)

            if not commit:
                self.stdout.write(
                    self.style.WARNING(
                        'DRY RUN: no data was changed. Back up the database, then rerun '
                        'with --commit to apply this plan.'
                    )
                )
                return

            self._apply_plan(settings, plan)
            self.stdout.write(
                self.style.SUCCESS(
                    'Normalization complete. The anchor and aligned saving-week '
                    'references now use Friday dates.'
                )
            )

    def _build_plan(self, settings):
        source_anchor = settings.week_one_start
        target_anchor = _first_weekday_on_or_after(source_anchor, FRIDAY)
        plan = NormalizationPlan(
            source_anchor=source_anchor,
            target_anchor=target_anchor,
            deposits=list(
                DepositSubmission.objects.select_for_update().order_by('pk')
            ),
            fines=list(
                Fine.objects.select_for_update()
                .filter(fine_type=WEEKLY_FINE_TYPE, reference_week__isnull=False)
                .select_related('account')
                .order_by('pk')
            ),
        )

        for deposit in plan.deposits:
            if deposit.payment_week:
                mapped = _mapped_week(
                    deposit.payment_week, source_anchor, target_anchor
                )
                if mapped is None:
                    plan.off_cycle_payment_weeks += 1
                elif mapped != deposit.payment_week:
                    deposit.payment_week = mapped
                    plan.payment_week_changes += 1
                    plan.changed_deposit_ids.add(deposit.pk)

            if deposit.starting_week:
                mapped = _mapped_week(
                    deposit.starting_week, source_anchor, target_anchor
                )
                if mapped is None:
                    plan.off_cycle_starting_weeks += 1
                elif mapped != deposit.starting_week:
                    deposit.starting_week = mapped
                    plan.starting_week_changes += 1
                    plan.changed_deposit_ids.add(deposit.pk)

        for fine in plan.fines:
            old_week = fine.reference_week
            mapped = _mapped_week(old_week, source_anchor, target_anchor)
            if mapped is None:
                plan.off_cycle_fine_weeks += 1
                continue
            if mapped == old_week:
                continue

            updated_reason = _updated_generated_reason(fine, old_week, mapped)
            if updated_reason != fine.reason:
                fine.reason = updated_reason
                plan.fine_reason_changes += 1
            fine.reference_week = mapped
            plan.fine_week_changes += 1
            plan.changed_fine_ids.add(fine.pk)

        return plan

    def _preflight_fine_collisions(self, plan):
        final_rows = []
        planned_by_id = {fine.pk: fine for fine in plan.fines}
        for fine in Fine.objects.filter(
            fine_type=WEEKLY_FINE_TYPE,
            reference_week__isnull=False,
        ).only('pk', 'member_id', 'account_id', 'fine_type', 'reference_week'):
            planned = planned_by_id.get(fine.pk)
            final_rows.append(planned or fine)

        seen = {}
        for fine in final_rows:
            key = (
                fine.member_id,
                fine.account_id,
                fine.fine_type,
                fine.reference_week,
            )
            existing_id = seen.get(key)
            if existing_id is not None and (
                fine.pk in plan.changed_fine_ids
                or existing_id in plan.changed_fine_ids
            ):
                raise CommandError(
                    'Normalization blocked: weekly fines '
                    f'#{existing_id} and #{fine.pk} would share the target key '
                    f'(member={fine.member_id}, account={fine.account_id}, '
                    f'week={fine.reference_week.isoformat()}). No data was changed.'
                )
            seen[key] = fine.pk

    def _write_plan(self, plan):
        self.stdout.write('Savings-week normalization plan')
        self.stdout.write(
            f'  Anchor: {plan.source_anchor.isoformat()} '
            f'({plan.source_anchor:%A}) -> {plan.target_anchor.isoformat()} (Friday)'
        )
        self.stdout.write(
            f'  Deposit payment_week: {plan.payment_week_changes} change(s); '
            f'{plan.off_cycle_payment_weeks} off-cycle date(s) unchanged'
        )
        self.stdout.write(
            f'  Deposit starting_week: {plan.starting_week_changes} change(s); '
            f'{plan.off_cycle_starting_weeks} off-cycle date(s) unchanged'
        )
        self.stdout.write(
            f'  Weekly fine reference_week: {plan.fine_week_changes} change(s); '
            f'{plan.off_cycle_fine_weeks} off-cycle date(s) unchanged'
        )
        self.stdout.write(
            f'  Generated fine reasons: {plan.fine_reason_changes} change(s)'
        )

    def _apply_plan(self, settings, plan):
        if plan.changed_deposit_ids:
            DepositSubmission.objects.bulk_update(
                [
                    deposit for deposit in plan.deposits
                    if deposit.pk in plan.changed_deposit_ids
                ],
                ['payment_week', 'starting_week'],
            )

        if plan.changed_fine_ids:
            Fine.objects.bulk_update(
                [fine for fine in plan.fines if fine.pk in plan.changed_fine_ids],
                ['reference_week', 'reason'],
            )

        GroupSettings.objects.filter(pk=settings.pk).update(
            week_one_start=plan.target_anchor
        )
