import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('loans', '0003_loanrepayment'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='loanrequest',
            name='status',
            field=models.CharField(
                choices=[
                    ('PENDING_GUARANTOR', 'Pending Guarantor Approval'),
                    ('PENDING', 'Pending Management Approval'),
                    ('APPROVED', 'Approved'),
                    ('REJECTED', 'Rejected'),
                    ('REJECTED_GUARANTOR', 'Rejected by Guarantor'),
                ],
                default='PENDING',
                max_length=30,
            ),
        ),
        migrations.CreateModel(
            name='LoanGuarantorApproval',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected')], default='PENDING', max_length=10)),
                ('comments', models.TextField(blank=True)),
                ('decided_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('guarantor', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='loan_guarantee_requests', to=settings.AUTH_USER_MODEL)),
                ('loan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='guarantor_approvals', to='loans.loanrequest')),
            ],
            options={
                'ordering': ['created_at', 'id'],
                'unique_together': {('loan', 'guarantor')},
            },
        ),
    ]
