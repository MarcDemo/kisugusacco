from django.utils import timezone


def current_report_year():
    return timezone.localdate().year


def parse_report_year(raw_year, default_year=None):
    default_year = default_year or current_report_year()
    try:
        year = int(raw_year)
    except (TypeError, ValueError):
        return default_year
    return year if 1 <= year <= 9999 else default_year


def years_from_dates(queryset, field_name):
    return [
        year_start.year
        for year_start in queryset.dates(field_name, 'year', order='DESC')
        if year_start is not None
    ]


def merge_year_options(*year_groups, selected_year=None, default_year=None):
    years = {default_year or current_report_year()}
    if selected_year:
        years.add(selected_year)
    for year_group in year_groups:
        years.update(year for year in year_group if year)
    return sorted(years, reverse=True)


def pagination_query(request):
    """Preserve active filters while replacing the current page number."""
    query = request.GET.copy()
    for key in list(query):
        if key == 'page' or key.endswith('_page'):
            query.pop(key, None)
    return query.urlencode()
