from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('groupcore', '0015_savingsaccountownershiptransfer'),
    ]

    operations = [
        migrations.AddField(
            model_name='memberprofile',
            name='welcome_email_attempted_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='When a welcome delivery was reserved; prevents retries after uncertain delivery.',
            ),
        ),
    ]
