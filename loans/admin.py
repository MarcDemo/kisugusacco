from django.contrib import admin

from .models import LoanGuarantorApproval, LoanRepayment, LoanRequest


admin.site.register(LoanRequest)
admin.site.register(LoanRepayment)
admin.site.register(LoanGuarantorApproval)
