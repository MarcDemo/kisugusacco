import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0001_initial'),
        ('groupcore', '0009_alter_memberprofile_role'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveField(
            model_name='loanrequest',
            name='overseer_approved_by',
        ),
        migrations.RemoveField(
            model_name='loanrequest',
            name='secretary_approved_by',
        ),
        migrations.AddField(
            model_name='loanrequest',
            name='vice_chairman_approved_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='vice_chairman_approved_loans',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
