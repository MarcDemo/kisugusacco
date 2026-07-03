from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0008_add_shares_amount'),
    ]

    operations = [
        migrations.AddField(
            model_name='depositsubmission',
            name='loan_repayment_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
    ]
