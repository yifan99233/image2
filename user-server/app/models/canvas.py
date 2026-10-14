from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base


class CanvasProject(Base):
    __tablename__ = "canvas_projects"
    __table_args__ = (
        Index("idx_canvas_projects_owner_created", "site_id", "user_id", "created_at", "id"),
        CheckConstraint("revision > 0", name="ck_canvas_projects_revision"),
    )

    site_id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), primary_key=True)
    id = Column(String(64), primary_key=True)
    title = Column(String(200), nullable=False)
    node_count = Column(Integer, nullable=False, default=0)
    connection_count = Column(Integer, nullable=False, default=0)
    document = Column(JSONB, nullable=False)
    revision = Column(Integer, nullable=False)
    mutation_id = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at = Column(DateTime(timezone=True))
