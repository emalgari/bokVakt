"""user accounts + tax parameter extras (kommun_name, total_rate)

Revision ID: c3a7f10b0006
Revises: 525c59bcf550
Create Date: 2026-09-30

Phase 1 foundation (accounts + single-file backups). Additive only:

* new table ``user_accounts`` — local app accounts with Argon2id password
  and recovery-code hashes (core.accounts). The legacy ``users`` /
  ``user_sessions`` tables are untouched.
* ``tax_parameters`` gains ``kommun_name`` (which municipality the rates
  belong to) and ``total_rate`` (user-owned stored total). Existing columns
  keep their roles: municipal_rate ≙ municipal_tax_pct, funeral_rate ≙
  burial_pct. No existing column, default or logic is changed.
* ``invoice_income_link`` is intentionally NOT created: invoices already
  link to income via ``income_entries.invoice_id`` (populated on finalize).

File named 0006 per the phase plan; the repository head before this revision
is 0004 (525c59bcf550) — there is no 0005, the gap is cosmetic (Alembic
chains by revision id). SQLite note: plain ``op.add_column`` with constant
server defaults (same pattern as 0004) — no batch mode, no ALTER-add of
constraints, legacy rows stay valid.
"""
from alembic import op
import sqlalchemy as sa
import firmabok.core.db as app_db


revision = 'c3a7f10b0006'
down_revision = '525c59bcf550'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('user_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('password_hash', sa.String(length=256), nullable=False),
    sa.Column('recovery_hash', sa.String(length=256), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_password_change_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_recovery_regen_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_accounts_email', 'user_accounts', ['email'], unique=True)
    op.add_column('tax_parameters', sa.Column('kommun_name', sa.String(length=120),
                                              nullable=False, server_default=''))
    op.add_column('tax_parameters', sa.Column('total_rate', app_db.Money(2),
                                              nullable=False, server_default='0.00'))


def downgrade() -> None:
    op.drop_column('tax_parameters', 'total_rate')
    op.drop_column('tax_parameters', 'kommun_name')
    op.drop_index('ix_user_accounts_email', table_name='user_accounts')
    op.drop_table('user_accounts')
