from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0005_alter_loanrequest_monthly_interest_rate'),
    ]

    operations = [
        migrations.AlterField(
            model_name='loanrequest',
            name='duration_months',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='import_reference',
            field=models.CharField(
                blank=True,
                help_text='Unique source reference used to prevent duplicate historical loan imports.',
                max_length=120,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='import_batch',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='imported_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='loanrepayment',
            name='import_reference',
            field=models.CharField(
                blank=True,
                help_text='Unique source reference used to prevent duplicate historical repayment imports.',
                max_length=120,
                null=True,
                unique=True,
            ),
        ),
        migrations.AddField(
            model_name='loanrepayment',
            name='import_batch',
            field=models.CharField(blank=True, max_length=120, null=True),
        ),
        migrations.AddField(
            model_name='loanrepayment',
            name='imported_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
