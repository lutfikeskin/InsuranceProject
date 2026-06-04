from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UploadedDocument(Base):
    __tablename__ = "uploaded_documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    file_hash = Column(String, nullable=False, index=True)
    byte_size = Column(Integer, nullable=False)
    content_type = Column(String, nullable=True)
    source = Column(String, nullable=False, default="manual_upload")
    storage_uri = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    extraction_runs = relationship(
        "ExtractionRun",
        back_populates="upload",
        cascade="all, delete-orphan",
    )
    review_tasks = relationship(
        "ReviewTask",
        back_populates="upload",
        cascade="all, delete-orphan",
    )


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id = Column(Integer, primary_key=True, index=True)
    upload_id = Column(
        Integer,
        ForeignKey("uploaded_documents.id"),
        nullable=False,
        index=True,
    )
    status = Column(String, nullable=False, default="pending")
    policy_data_source = Column(String, nullable=True)
    document_type = Column(String, nullable=True)
    policy_type = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    cache_source = Column(String, nullable=True)
    force_refresh = Column(Integer, nullable=False, default=0)
    usage = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, default=_utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    upload = relationship("UploadedDocument", back_populates="extraction_runs")
    review_tasks = relationship(
        "ReviewTask",
        back_populates="extraction_run",
        cascade="all, delete-orphan",
    )


class ReviewTask(Base):
    __tablename__ = "review_tasks"

    id = Column(Integer, primary_key=True, index=True)
    upload_id = Column(
        Integer,
        ForeignKey("uploaded_documents.id"),
        nullable=False,
        index=True,
    )
    extraction_run_id = Column(
        Integer,
        ForeignKey("extraction_runs.id"),
        nullable=False,
        index=True,
    )
    status = Column(String, nullable=False, default="pending")
    decision = Column(String, nullable=True)
    target_policy_id = Column(Integer, ForeignKey("policies.id"), nullable=True, index=True)
    extraction_result = Column(JSON, nullable=False)
    human_edits = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    updated_at = Column(DateTime, default=_utcnow, nullable=False)
    reviewed_at = Column(DateTime, nullable=True)

    upload = relationship("UploadedDocument", back_populates="review_tasks")
    extraction_run = relationship("ExtractionRun", back_populates="review_tasks")
    target_policy = relationship("Policy")
