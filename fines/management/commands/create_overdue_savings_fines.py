from django.core.management.base import BaseCommand

from groupcore.savings_calendar import ensure_overdue_fines


class Command(BaseCommand):
    help = 'Create missing UGX 1,000 late-saving fines (safe to run repeatedly).'

    def handle(self, *args, **options):
        created = ensure_overdue_fines()
        self.stdout.write(self.style.SUCCESS(f'Created {created} overdue saving fine(s).'))
