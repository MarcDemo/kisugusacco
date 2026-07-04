# Generated for preserving full imported savings account names.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('groupcore', '0009_alter_memberprofile_role'),
    ]

    operations = [
        migrations.AlterField(
            model_name='savingsaccount',
            name='label',
            field=models.CharField(
                help_text='e.g. A, B, C, or an account/member name',
                max_length=100,
            ),
        ),
    ]
