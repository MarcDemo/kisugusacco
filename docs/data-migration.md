# Historical Member Data Migration

## Recommended Workflow

Deploy the system code and database schema first, then import the existing member accounts and historical savings into the fresh production MySQL database before opening the system to members.

Best-practice sequence:

1. Deploy the app to cPanel with the production `.env`.
2. Create an empty MySQL database.
3. Run `python manage.py migrate`.
4. Prepare the members and transactions import files.
5. Run a dry-run import and review the generated report.
6. Correct any errors in the source files.
7. Run the same command with `--commit`.
8. Verify member totals, weekly totals, and reports.
9. Open the system for live use.

Do not import historical data into local SQLite and then copy that database to the server. Production data should be created in the production database through migrations and controlled import commands.

## Why Import After Deployment

Importing after deployment is safer because:

- The real production schema, database engine, timezone, and constraints are used.
- The local test database is never copied to the server.
- Imports can be dry-run and reported before any production data is written.
- Deployment remains code-only, while production data stays on the server.
- The same import process can be repeated later for additional historical records.

For maximum confidence, first run the exact import on a staging copy of the production setup, then run it on production during a controlled go-live window.

## Import Command

Dry-run first:

```bash
python manage.py import_historical_data \
  --members imports/members.csv \
  --transactions imports/transactions.csv \
  --submitted-by treasurer_username \
  --report imports/import_report.csv
```

Commit only after the report is clean:

```bash
python manage.py import_historical_data \
  --members imports/members.csv \
  --transactions imports/transactions.csv \
  --submitted-by treasurer_username \
  --report imports/import_report.csv \
  --commit
```

The command accepts CSV files or XLSX files. XLSX files should use `Members` and `Transactions` sheets by default, or pass `--members-sheet` and `--transactions-sheet`.

## Members File

Required columns:

- `username`
- `account_labels`

Optional columns:

- `first_name`
- `last_name`
- `email`
- `phone_number`
- `next_of_kin_name`
- `next_of_kin_contact`
- `role`, defaults to `MEMBER`
- `is_active`, defaults to true

Use semicolons for multiple savings accounts, for example `A1;A2`.

Members are created with unusable passwords for security. They should receive passwords through the normal password reset/admin process instead of sharing a default password.

## Transactions File

Required columns:

- `transaction_reference`
- `username`
- `account_label`
- `payment_week`
- `payment_date`
- at least one amount column greater than zero

Amount columns:

- `saving_amount`
- `welfare_amount`
- `annual_subscription_amount`
- `fine_amount`
- `shares_amount`
- `loan_repayment_amount`

Optional columns:

- `payment_time`, defaults to `00:00`
- `status`, defaults to `APPROVED`
- `expected_total`, validates that the amount columns add up correctly
- `remarks`
- `proof_reference`

Dates should be entered as `YYYY-MM-DD`. `payment_week` must be the Friday saving-week closing date used by the group ledger. `payment_date` remains the real date the member paid.

## Duplicate Protection

Every historical transaction must have a stable `transaction_reference`, such as a receipt number, mobile money transaction ID, or old ledger row ID. The system stores that value as `import_reference` and will skip a transaction if the same reference is imported again.

The import blocks:

- duplicate usernames in the same members file
- duplicate transaction references in the same transactions file
- transactions for missing members/accounts
- negative amounts
- rows where `expected_total` does not match the amount breakdown
- payment weeks that are not Friday saving-week closing dates

## Reports

The report CSV lists each source row as:

- `VALID_NEW_MEMBER`
- `VALID_EXISTING_MEMBER`
- `VALID_NEW_TRANSACTION`
- `CREATED_MEMBER`
- `EXISTING_MEMBER`
- `CREATED_TRANSACTION`
- `SKIPPED_DUPLICATE`
- `ERROR`

If any row has `ERROR`, the command refuses to write data until the source file is corrected.
