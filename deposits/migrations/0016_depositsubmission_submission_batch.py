from datetime import timedelta
import uuid

from django.db import migrations, models


PURPOSE_FIELDS = (
    'welfare_amount',
    'annual_subscription_amount',
    'membership_amount',
    'fine_amount',
    'shares_amount',
    'loan_repayment_amount',
)


def backfill_submission_batches(apps, schema_editor):
    DepositSubmission = apps.get_model('deposits', 'DepositSubmission')
    rows = list(
        DepositSubmission.objects.all().order_by(
            'member_id',
            'account_id',
            'submitted_by_id',
            'payment_date',
            'payment_time',
            'status',
            'date_submitted',
            'id',
        )
    )

    current = []
    current_key = None
    previous_submitted_at = None
    weeks = set()
    special_rows = 0

    def flush():
        if not current:
            return
        batch = uuid.uuid4()
        DepositSubmission.objects.filter(
            pk__in=[row.pk for row in current]
        ).update(submission_batch=batch)

    for row in rows:
        key = (
            row.member_id,
            row.account_id,
            row.submitted_by_id,
            row.payment_date,
            row.payment_time,
            row.status,
        )
        is_special = bool(row.proof) or any(
            getattr(row, field_name) for field_name in PURPOSE_FIELDS
        )
        close_in_time = (
            previous_submitted_at is not None
            and row.date_submitted - previous_submitted_at <= timedelta(seconds=3)
        )
        compatible = (
            current
            and key == current_key
            and close_in_time
            and row.payment_week not in weeks
            and not (is_special and special_rows)
        )
        if not compatible:
            flush()
            current = []
            weeks = set()
            special_rows = 0

        current.append(row)
        current_key = key
        previous_submitted_at = row.date_submitted
        weeks.add(row.payment_week)
        special_rows += int(is_special)

    flush()


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0015_depositsubmission_loan_repayment_loan'),
    ]

    operations = [
        migrations.AddField(
            model_name='depositsubmission',
            name='submission_batch',
            field=models.UUIDField(blank=True, db_index=True, editable=False, null=True),
        ),
        migrations.RunPython(backfill_submission_batches, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='depositsubmission',
            name='submission_batch',
            field=models.UUIDField(
                db_index=True,
                default=uuid.uuid4,
                editable=False,
                help_text='Identifier shared by every weekly record created by one deposit submission.',
            ),
        ),
    ]
