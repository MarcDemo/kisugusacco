from django.db.models import Case, CharField, F, Q, Value, When
from django.db.models.functions import Concat, Lower, Trim


def alphabetical_members(queryset):
    return queryset.annotate(
        _display_name=Case(
            When(
                Q(first_name='') & Q(last_name=''),
                then=F('username'),
            ),
            default=Trim(Concat('first_name', Value(' '), 'last_name')),
            output_field=CharField(),
        )
    ).order_by(Lower('_display_name'), Lower('username'))
