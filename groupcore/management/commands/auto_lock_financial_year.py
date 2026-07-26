from django.core.management.base import BaseCommand

from groupcore.year_close import ensure_automatic_year_lock


class Command(BaseCommand):
    help = 'Automatically lock the prior financial year on January’s first Friday.'

    def handle(self, *args, **options):
        state = ensure_automatic_year_lock()
        self.stdout.write(
            self.style.SUCCESS(
                f'{state.year}: {state.get_state_display()}'
                + (' (automatically locked)' if state.auto_locked else '')
            )
        )
