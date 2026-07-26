from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from deposits.models import DepositSubmission, DepositWelfareAllocation
from groupcore.models import GroupSettings
from groupcore.week_cycle import first_friday_of_year, saving_year_closing_date


WEEKLY_WELFARE = Decimal('1000.00')


def cycle_weeks(year, settings):
    start = (
        settings.week_one_start
        if settings.week_one_start.year == year
        else first_friday_of_year(year)
    )
    closing = saving_year_closing_date(year)
    weeks = []
    current = start
    while current <= closing:
        weeks.append(current)
        current += timedelta(weeks=1)
    return weeks


class Command(BaseCommand):
    help = (
        'Backfill exact welfare-week allocations for legacy deposits. '
        'Runs as a dry-run unless --commit is supplied.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--commit',
            action='store_true',
            help='Write the reviewed allocations to the database.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        commit = options['commit']
        settings = GroupSettings.get_active()
        if not settings:
            raise CommandError('Configure the group saving year before backfilling welfare.')

        deposits = list(
            DepositSubmission.objects.select_for_update()
            .filter(
                status__in=('APPROVED', 'PENDING'),
                welfare_amount__gt=0,
            )
            .select_related('account', 'member')
            .prefetch_related('welfare_allocations')
            .order_by(
                'account_id', 'payment_week', 'payment_date',
                'payment_time', 'date_submitted', 'id',
            )
        )
        occupied = defaultdict(set)
        for account_id, welfare_week in (
            DepositWelfareAllocation.objects.filter(
                deposit__status__in=('APPROVED', 'PENDING')
            ).values_list('account_id', 'welfare_week')
        ):
            occupied[account_id].add(welfare_week)

        weeks_cache = {}
        planned = []
        invalid = []
        overflow = []
        already_complete = 0

        for deposit in deposits:
            if not deposit.account_id or not deposit.payment_week:
                invalid.append((deposit.id, 'missing account or payment week'))
                continue
            amount = deposit.welfare_amount or Decimal('0.00')
            units, remainder = divmod(amount, WEEKLY_WELFARE)
            if remainder or units <= 0:
                invalid.append((
                    deposit.id,
                    f'UGX {amount} is not a positive multiple of UGX 1,000',
                ))
                continue

            existing_weeks = {
                allocation.welfare_week
                for allocation in deposit.welfare_allocations.all()
            }
            remaining = int(units) - len(existing_weeks)
            if remaining < 0:
                invalid.append((
                    deposit.id,
                    'existing allocations exceed the recorded welfare amount',
                ))
                continue
            if remaining == 0:
                already_complete += 1
                continue

            year = deposit.payment_week.year
            weeks = weeks_cache.setdefault(year, cycle_weeks(year, settings))
            available = [
                week for week in weeks
                if week not in occupied[deposit.account_id]
            ]
            selected = []
            if deposit.payment_week in available:
                selected.append(deposit.payment_week)
                available.remove(deposit.payment_week)
            selected.extend(available[:remaining - len(selected)])

            if len(selected) != remaining:
                overflow.append((
                    deposit.id,
                    remaining,
                    len(selected),
                ))
                continue

            for week in selected:
                occupied[deposit.account_id].add(week)
                planned.append((deposit, week))

        if commit:
            DepositWelfareAllocation.objects.bulk_create([
                DepositWelfareAllocation(
                    deposit=deposit,
                    account=deposit.account,
                    welfare_week=week,
                    amount=WEEKLY_WELFARE,
                )
                for deposit, week in planned
            ])
        else:
            transaction.set_rollback(True)

        action = 'Created' if commit else 'Would create'
        self.stdout.write(self.style.SUCCESS(
            f'{action} {len(planned)} welfare-week allocation(s) '
            f'from {len(deposits)} legacy deposit(s).'
        ))
        self.stdout.write(f'Already complete: {already_complete}')
        self.stdout.write(f'Invalid deposits: {len(invalid)}')
        self.stdout.write(f'Overflow deposits: {len(overflow)}')
        for deposit_id, reason in invalid[:20]:
            self.stdout.write(self.style.WARNING(
                f'Invalid Deposit #{deposit_id}: {reason}'
            ))
        for deposit_id, needed, available_count in overflow[:20]:
            self.stdout.write(self.style.WARNING(
                f'Overflow Deposit #{deposit_id}: needs {needed} week(s), '
                f'only {available_count} available'
            ))
        if not commit:
            self.stdout.write(self.style.WARNING(
                'Dry run only. Review these counts, back up the database, '
                'then rerun with --commit.'
            ))
