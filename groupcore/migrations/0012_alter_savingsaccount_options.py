from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('groupcore', '0011_financialrecordrevision')]

    operations = [
        migrations.AlterModelOptions(
            name='savingsaccount',
            options={'ordering': ['owner__first_name', 'owner__last_name', 'owner__username', 'label']},
        ),
    ]
