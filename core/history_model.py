from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class PolicyHistory(Base):
    __tablename__ = 'policy_history'

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(Integer, ForeignKey('policies.id'), nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    source = Column(String, nullable=True) # e.g., "AI_Extraction", "Manual_Edit"
    event_type = Column(String, nullable=False, default="UPDATE") # "AI_EXTRACTION", "MANUAL_EDIT", "SYSTEM_REPROCESS"
    policy_version = Column(Integer, nullable=False, default=1)   # 1, 2, 3...
    
    # Store the diff as structured JSON
    # Format: [{"field": "cargo_limit", "old_value": "100000", "new_value": "0"}]
    changes = Column(JSON, nullable=False)
    
    # Optional: Snapshot of the full object state at this time?
    # For now, just changes to keep it lightweight as requested.

    # Relationships
    policy = relationship("Policy", back_populates="history")
