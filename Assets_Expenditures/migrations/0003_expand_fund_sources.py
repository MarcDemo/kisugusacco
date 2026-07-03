from django.db import migrations, models


def remap_legacy_sources(apps, schema_editor):
    Expenditure = apps.get_model('Assets_Expenditures', 'Expenditure')
    Asset = apps.get_model('Assets_Expenditures', 'Asset')

    Expenditure.objects.filter(source='DEPOSITS').update(source='SAVINGS')
    Expenditure.objects.filter(source='INCOME').update(source='SHARES')
    Asset.objects.filter(source='DEPOSITS').update(source='SAVINGS')
    Asset.objects.filter(source='INCOME').update(source='SHARES')


def reverse_legacy_sources(apps, schema_editor):
    Expenditure = apps.get_model('Assets_Expenditures', 'Expenditure')
    Asset = apps.get_model('Assets_Expenditures', 'Asset')

    Expenditure.objects.filter(source='SAVINGS').update(source='DEPOSITS')
    Expenditure.objects.filter(source='SHARES').update(source='INCOME')
    Asset.objects.filter(source='SAVINGS').update(source='DEPOSITS')
    Asset.objects.filter(source='SHARES').update(source='INCOME')


class Migration(migrations.Migration):

    dependencies = [
        ('Assets_Expenditures', '0002_alter_asset_date_acquired_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='asset',
            name='source',
            field=models.CharField(choices=[('SAVINGS', 'Savings'), ('WELFARE', 'Welfare'), ('FINES', 'Fines'), ('ANNUAL_SUBSCRIPTIONS', 'Annual Subscriptions'), ('SHARES', 'Shares')], max_length=30),
        ),
        migrations.AlterField(
            model_name='expenditure',
            name='source',
            field=models.CharField(choices=[('SAVINGS', 'Savings'), ('WELFARE', 'Welfare'), ('FINES', 'Fines'), ('ANNUAL_SUBSCRIPTIONS', 'Annual Subscriptions'), ('SHARES', 'Shares')], max_length=30),
        ),
        migrations.RunPython(remap_legacy_sources, reverse_legacy_sources),
    ]