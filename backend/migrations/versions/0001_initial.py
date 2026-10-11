"""initial AstraDeploy schema"""
from alembic import op
import sqlalchemy as sa
revision = '0001_initial'; down_revision = None; branch_labels = None; depends_on = None
def upgrade():
    # The application metadata is authoritative for this MVP migration baseline.
    from app.main import Base
    bind = op.get_bind(); Base.metadata.create_all(bind=bind)
def downgrade():
    from app.main import Base
    bind = op.get_bind(); Base.metadata.drop_all(bind=bind)
