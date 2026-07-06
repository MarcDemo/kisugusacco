from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0010_depositsubmission_import_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='depositsubmission',
            name='membership_amount',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), max_digits=10),
        ),
    ]
