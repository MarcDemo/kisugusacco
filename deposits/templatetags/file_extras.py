from django import template

register = template.Library()

@register.filter
def is_pdf(file_url):
    return file_url.lower().endswith('.pdf')
