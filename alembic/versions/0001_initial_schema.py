"""Initial schema: job_offers, job_embeddings, workflow_counters.

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.core.config import get_settings

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EMBEDDING_DIM = get_settings().embedding_dim


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "job_offers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("url_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("company", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("modality", sa.String(length=16), nullable=False, server_default="Unknown"),
        sa.Column("location", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("salary", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("seniority", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("relevance_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("discord_message_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("url_fingerprint", name="uq_job_url_fingerprint"),
    )
    op.create_index("ix_job_offers_url_fingerprint", "job_offers", ["url_fingerprint"])
    op.create_index("ix_job_offers_category", "job_offers", ["category"])

    op.create_table(
        "job_embeddings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "offer_id",
            sa.Integer(),
            sa.ForeignKey("job_offers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(_EMBEDDING_DIM), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_job_embeddings_offer_id", "job_embeddings", ["offer_id"])
    # IVFFlat index for approximate cosine-distance search.
    op.execute(
        "CREATE INDEX ix_job_embeddings_vector ON job_embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    op.create_table(
        "workflow_counters",
        sa.Column("name", sa.String(length=64), primary_key=True),
        sa.Column("value", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("workflow_counters")
    op.drop_index("ix_job_embeddings_vector", table_name="job_embeddings")
    op.drop_index("ix_job_embeddings_offer_id", table_name="job_embeddings")
    op.drop_table("job_embeddings")
    op.drop_index("ix_job_offers_category", table_name="job_offers")
    op.drop_index("ix_job_offers_url_fingerprint", table_name="job_offers")
    op.drop_table("job_offers")
    op.execute("DROP EXTENSION IF EXISTS vector")
