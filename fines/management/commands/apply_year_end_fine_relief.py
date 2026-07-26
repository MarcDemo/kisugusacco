from django.core.management.base import BaseCommand

from groupcore.savings_calendar import apply_year_end_fine_relief


class Command(BaseCommand):
    help = 'Apply permanent second-Friday-of-December relief to qualifying fines.'

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int)

    def handle(self, *args, **options):
        changed = apply_year_end_fine_relief(year=options.get('year'))
        self.stdout.write(self.style.SUCCESS(f'Updated {changed} qualifying fine(s).'))
