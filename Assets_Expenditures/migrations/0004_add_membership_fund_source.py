from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('Assets_Expenditures', '0003_expand_fund_sources'),
    ]

    operations = [
        migrations.AlterField(
            model_name='asset',
            name='source',
            field=models.CharField(choices=[('SAVINGS', 'Savings'), ('WELFARE', 'Welfare'), ('FINES', 'Fines'), ('ANNUAL_SUBSCRIPTIONS', 'Annual Subscriptions'), ('MEMBERSHIP', 'Membership Fees'), ('SHARES', 'Shares')], max_length=30),
        ),
        migrations.AlterField(
            model_name='expenditure',
            name='source',
            field=models.CharField(choices=[('SAVINGS', 'Savings'), ('WELFARE', 'Welfare'), ('FINES', 'Fines'), ('ANNUAL_SUBSCRIPTIONS', 'Annual Subscriptions'), ('MEMBERSHIP', 'Membership Fees'), ('SHARES', 'Shares')], max_length=30),
        ),
    ]
