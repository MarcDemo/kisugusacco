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
        inferred_accounts = 0
        normalized_weeks = 0
        carried_forward = 0
        entries = []

        for deposit in deposits:
            account = deposit.account
            if not account:
                possible_accounts = list(
                    deposit.member.savings_accounts.filter(is_active=True)[:2]
                )
                if len(possible_accounts) != 1:
                    invalid.append((
                        deposit.id,
                        'missing account and member does not have exactly one active account',
                    ))
                    continue
                account = possible_accounts[0]
                inferred_accounts += 1
            if not deposit.payment_week:
                invalid.append((deposit.id, 'missing payment week'))
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

            preferred_week = deposit.payment_week + timedelta(
                days=4 - deposit.payment_week.weekday()
            )
            if preferred_week != deposit.payment_week:
                normalized_weeks += 1
            entries.append({
                'deposit': deposit,
                'account': account,
                'preferred_week': preferred_week,
                'source_year': preferred_week.year,
                'remaining': remaining,
            })

        # Reserve every deposit's explicit week before bulk-payment extras are
        # spread. This prevents an early bulk deposit from consuming the exact
        # weeks recorded by later weekly deposits.
        for entry in entries:
            preferred = entry['preferred_week']
            account_id = entry['account'].id
            weeks = weeks_cache.setdefault(
                preferred.year, cycle_weeks(preferred.year, settings)
            )
            if (
                entry['remaining'] > 0
                and preferred in weeks
                and preferred not in occupied[account_id]
            ):
                occupied[account_id].add(preferred)
                planned.append((
                    entry['deposit'], entry['account'], preferred
                ))
                entry['remaining'] -= 1

        # Allocate bulk extras FIFO. If the closing-year calendar is full,
        # preserve the money as future-year welfare prepayment.
        for entry in entries:
            account_id = entry['account'].id
            selected = []
            allocation_year = entry['source_year']
            years_checked = 0
            while entry['remaining'] > 0 and years_checked < 100:
                weeks = weeks_cache.setdefault(
                    allocation_year, cycle_weeks(allocation_year, settings)
                )
                available = [
                    week for week in weeks
                    if week not in occupied[account_id]
                    and week not in selected
                ]
                take = available[:entry['remaining']]
                selected.extend(take)
                entry['remaining'] -= len(take)
                allocation_year += 1
                years_checked += 1
            if entry['remaining'] > 0:
                overflow.append((
                    entry['deposit'].id,
                    entry['remaining'],
                    len(selected),
                ))
                continue
            for week in selected:
                occupied[account_id].add(week)
                planned.append((
                    entry['deposit'], entry['account'], week
                ))
                if week.year > entry['source_year']:
                    carried_forward += 1

        if commit:
            DepositWelfareAllocation.objects.bulk_create([
                DepositWelfareAllocation(
                    deposit=deposit,
                    account=account,
                    welfare_week=week,
                    amount=WEEKLY_WELFARE,
                )
                for deposit, account, week in planned
            ])
        else:
            transaction.set_rollback(True)

        action = 'Created' if commit else 'Would create'
        self.stdout.write(self.style.SUCCESS(
            f'{action} {len(planned)} welfare-week allocation(s) '
            f'from {len(deposits)} legacy deposit(s).'
        ))
        self.stdout.write(f'Already complete: {already_complete}')
        self.stdout.write(f'Inferred unique accounts: {inferred_accounts}')
        self.stdout.write(f'Normalized legacy weeks to Friday: {normalized_weeks}')
        self.stdout.write(f'Carried into later saving years: {carried_forward}')
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
