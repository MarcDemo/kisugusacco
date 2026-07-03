from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('groupcore', '0008_alter_memberprofile_role_savingsaccount'),
    ]

    operations = [
        migrations.AlterField(
            model_name='memberprofile',
            name='role',
            field=models.CharField(
                choices=[
                    ('MEMBER', 'Member'),
                    ('TREASURER', 'Treasurer'),
                    ('CHAIRMAN', 'Chairman'),
                    ('VICE_CHAIRMAN', 'Vice Chairman'),
                    ('SECRETARY', 'Secretary'),
                    ('MOBILIZER', 'Mobilizer'),
                    ('OVERSEER', 'Overseer'),
                ],
                default='MEMBER',
                max_length=15,
            ),
        ),
    ]
