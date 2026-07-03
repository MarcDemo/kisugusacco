# Generated for historical data imports.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0009_add_loan_repayment_amount'),
    ]

    operations = [
        migrations.AddField(
            model_name='depositsubmission',
            name='import_reference',
            field=models.CharField(
                blank=True,
                help_text='Unique source reference used to prevent duplicate historical imports.',
                max_length=120,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name='depositsubmission',
            name='import_batch',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='depositsubmission',
            name='imported_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
