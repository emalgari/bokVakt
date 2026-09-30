"""vat method, template fields

Revision ID: a9dc2d5c3468
Revises: 6f0706aa6a01
Create Date: 2026-09-29 17:36:39.808143
"""
from alembic import op
import sqlalchemy as sa
import app.db


revision = 'a9dc2d5c3468'
down_revision = '6f0706aa6a01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('company_profile', schema=None) as batch_op:
        batch_op.add_column(sa.Column('vat_method', sa.String(length=10), nullable=False,
                                      server_default='faktura'))
        batch_op.add_column(sa.Column('input_vat_on_payment', sa.Boolean(), nullable=False,
                                      server_default=sa.text('0')))
        batch_op.add_column(sa.Column('late_interest_text', sa.Text(), nullable=False,
                                      server_default='Vid betalning efter förfallodagen debiteras ränta enligt räntelagen.'))
        batch_op.add_column(sa.Column('round_total_to_krona', sa.Boolean(), nullable=False,
                                      server_default=sa.text('0')))
        batch_op.add_column(sa.Column('sni_codes', sa.String(length=64), nullable=False,
                                      server_default=''))
        batch_op.add_column(sa.Column('business_description', sa.String(length=200), nullable=False,
                                      server_default=''))

    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.add_column(sa.Column('payment_date', sa.Date(), nullable=True))

    with op.batch_alter_table('invoice_lines', schema=None) as batch_op:
        batch_op.add_column(sa.Column('article_no', sa.String(length=32), nullable=False,
                                      server_default=''))

    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.add_column(sa.Column('delivery_date', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('rounding_amount', app.db.Money(2), nullable=False,
                                      server_default='0.00'))


def downgrade() -> None:
    with op.batch_alter_table('invoices', schema=None) as batch_op:
        batch_op.drop_column('rounding_amount')
        batch_op.drop_column('delivery_date')

    with op.batch_alter_table('invoice_lines', schema=None) as batch_op:
        batch_op.drop_column('article_no')

    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_column('payment_date')

    with op.batch_alter_table('company_profile', schema=None) as batch_op:
        batch_op.drop_column('business_description')
        batch_op.drop_column('sni_codes')
        batch_op.drop_column('round_total_to_krona')
        batch_op.drop_column('late_interest_text')
        batch_op.drop_column('input_vat_on_payment')
        batch_op.drop_column('vat_method')
