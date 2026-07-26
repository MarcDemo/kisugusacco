from django import template

from groupcore.models import FinancialRecordRevision


register = template.Library()


@register.simple_tag
def revision_count(record_type, object_id):
    return FinancialRecordRevision.objects.filter(
        record_type=record_type, object_id=object_id
    ).count()
