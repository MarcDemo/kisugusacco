from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('groupcore', '0013_financial_year_settlement'),
    ]

    operations = [
        migrations.AddField(
            model_name='memberprofile',
            name='welcome_email_sent_at',
            field=models.DateTimeField(
                blank=True,
                help_text='When initial login credentials were successfully emailed to this member.',
                null=True,
            ),
        ),
    ]
