from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('deposits', '0011_depositsubmission_membership_amount')]
    operations = [
        migrations.AlterField(
            model_name='depositsubmission',
            name='proof',
            field=models.ImageField(blank=True, null=True, upload_to='proofs/'),
        ),
    ]
