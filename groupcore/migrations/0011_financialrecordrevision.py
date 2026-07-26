from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('groupcore', '0010_alter_savingsaccount_label'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FinancialRecordRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('record_type', models.CharField(max_length=60)),
                ('object_id', models.PositiveBigIntegerField()),
                ('revision_number', models.PositiveIntegerField()),
                ('before_data', models.JSONField()),
                ('after_data', models.JSONField()),
                ('reason', models.TextField()),
                ('edited_at', models.DateTimeField(auto_now_add=True)),
                ('edited_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='financial_record_revisions', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['revision_number', 'edited_at', 'id']},
        ),
        migrations.AddConstraint(
            model_name='financialrecordrevision',
            constraint=models.UniqueConstraint(fields=('record_type', 'object_id', 'revision_number'), name='unique_financial_record_revision'),
        ),
    ]
