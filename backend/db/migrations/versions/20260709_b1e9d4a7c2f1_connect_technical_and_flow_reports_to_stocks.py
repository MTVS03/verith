"""connect technical and flow reports to stocks

Revision ID: b1e9d4a7c2f1
Revises: 6ca978063906
Create Date: 2026-07-09 03:40:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1e9d4a7c2f1'
down_revision = '6ca978063906'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('technical_reports', sa.Column('stock_code', sa.String(), nullable=True))
    op.add_column('flow_reports', sa.Column('stock_code', sa.String(), nullable=True))

    op.execute("UPDATE technical_reports SET stock_code = ticker WHERE stock_code IS NULL")
    op.execute("UPDATE flow_reports SET stock_code = ticker WHERE stock_code IS NULL")

    op.alter_column('technical_reports', 'stock_code', nullable=False)
    op.alter_column('flow_reports', 'stock_code', nullable=False)

    op.create_foreign_key(
        op.f('fk_technical_reports_stock_code_stocks'),
        'technical_reports',
        'stocks',
        ['stock_code'],
        ['stock_code'],
    )
    op.create_foreign_key(
        op.f('fk_flow_reports_stock_code_stocks'),
        'flow_reports',
        'stocks',
        ['stock_code'],
        ['stock_code'],
    )

    op.create_index(
        'ix_technical_reports_stock_code_as_of',
        'technical_reports',
        ['stock_code', sa.literal_column('as_of DESC')],
        unique=False,
    )
    op.create_index(
        'ix_flow_reports_stock_code_base_date',
        'flow_reports',
        ['stock_code', sa.literal_column('base_date DESC')],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_flow_reports_stock_code_base_date', table_name='flow_reports')
    op.drop_index('ix_technical_reports_stock_code_as_of', table_name='technical_reports')
    op.drop_constraint(op.f('fk_flow_reports_stock_code_stocks'), 'flow_reports', type_='foreignkey')
    op.drop_constraint(op.f('fk_technical_reports_stock_code_stocks'), 'technical_reports', type_='foreignkey')
    op.drop_column('flow_reports', 'stock_code')
    op.drop_column('technical_reports', 'stock_code')
