from django.db import models
from incomes.models import OtherIncome
from groupcore.models import GroupSettings

# Create your models here.


class Expenditure(models.Model):
    PURPOSE_CHOICES = [
        ('SAVINGS', 'Savings'),
        ('WELFARE', 'Welfare'),
        ('FINES', 'Fines'),
        ('ANNUAL_SUBSCRIPTIONS', 'Annual Subscriptions'),
        ('MEMBERSHIP', 'Membership Fees'),
        ('SHARES', 'Shares'),
    ]
    description = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date_spent = models.DateField()
    source = models.CharField(max_length=30, choices=PURPOSE_CHOICES)
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.description} - UGX {self.amount}"


class Asset(models.Model):
    name = models.CharField(max_length=100)
    value = models.DecimalField(max_digits=12, decimal_places=2)
    date_acquired = models.DateField()
    remarks = models.TextField(blank=True, null=True)
    source = models.CharField(max_length=30, choices=Expenditure.PURPOSE_CHOICES)

    def __str__(self):
        return f"{self.name} (UGX {self.value})"
