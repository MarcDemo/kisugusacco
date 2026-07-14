from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('loans', '0006_historical_loan_import_fields')]
    operations = [
        migrations.CreateModel(
            name='LoanApprovalAudit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('original_approver_role', models.CharField(choices=[('GUARANTOR', 'Guarantor'), ('SECRETARY', 'Secretary'), ('VICE_CHAIRMAN', 'Vice Chairman'), ('CHAIRMAN', 'Chairman')], max_length=20)),
                ('reason', models.TextField()),
                ('approved_at', models.DateTimeField(auto_now_add=True)),
                ('actual_approver', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='loan_override_approvals', to=settings.AUTH_USER_MODEL)),
                ('loan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='approval_audits', to='loans.loanrequest')),
                ('on_behalf_of', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='loan_approvals_overridden', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['approved_at', 'id']},
        ),
    ]
