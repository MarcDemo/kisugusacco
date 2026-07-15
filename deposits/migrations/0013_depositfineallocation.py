from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('deposits', '0012_alter_depositsubmission_proof'),
        ('fines', '0004_fine_amount_paid_and_unique'),
    ]

    operations = [
        migrations.CreateModel(
            name='DepositFineAllocation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=10)),
                ('deposit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fine_allocations', to='deposits.depositsubmission')),
                ('fine', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='deposit_allocations', to='fines.fine')),
            ],
        ),
        migrations.AddConstraint(
            model_name='depositfineallocation',
            constraint=models.UniqueConstraint(fields=('deposit', 'fine'), name='unique_deposit_fine_allocation'),
        ),
        migrations.AddConstraint(
            model_name='depositfineallocation',
            constraint=models.CheckConstraint(condition=models.Q(('amount__gt', 0)), name='deposit_fine_allocation_amount_positive'),
        ),
    ]
