from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('fines', '0005_fine_relief_fields_and_amounts'),
    ]

    operations = [
        migrations.AddField(
            model_name='fine',
            name='is_voided',
            field=models.BooleanField(
                default=False,
                help_text='Retained for audit but no longer collectible.',
            ),
        ),
        migrations.AddField(
            model_name='fine',
            name='voided_on',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='fine',
            name='voided_reason',
            field=models.TextField(blank=True),
        ),
    ]
