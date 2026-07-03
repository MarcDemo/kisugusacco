from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0004_guarantor_workflow'),
    ]

    operations = [
        migrations.AlterField(
            model_name='loanrequest',
            name='monthly_interest_rate',
            field=models.DecimalField(decimal_places=2, default=Decimal('2.00'), max_digits=5),
        ),
    ]
