from django.contrib import admin
from .models import OtherIncome, WelfareLedger, AnnualSubscription, ShareContribution

# Register your models here.
admin.site.register(OtherIncome)
admin.site.register(WelfareLedger)
admin.site.register(AnnualSubscription)
admin.site.register(ShareContribution)