from sqlalchemy import create_engine, Column, Integer, String, Date, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os
from datetime import datetime

Base = declarative_base()

class Policy(Base):
    __tablename__ = 'policies'
    
    id = Column(Integer, primary_key=True)
    carrier_name = Column(String)
    naic_number = Column(String)  # New
    policy_number = Column(String, unique=True, nullable=False)
    effective_date = Column(Date)
    expiration_date = Column(Date)
    account_type = Column(String)  # Personal or Commercial
    insured_name = Column(String)
    business_name = Column(String)
    
    # Insured Address Fields
    insured_address = Column(String)
    insured_city = Column(String)
    insured_state_code = Column(String)
    insured_zip = Column(String)
    
    # New Fields
    premium = Column(String) # Keeping as string to handle currency symbols if needed, or extract as float later
    state = Column(String)
    financial_responsibility_name = Column(String)
    liability_limit = Column(String)
    cargo_limit = Column(String)
    cargo_deductible = Column(String) # New
    has_full_collision = Column(Boolean)
    
    # Classification Metadata
    policy_type = Column(String)
    classification_confidence = Column(String)
    classification_signals = Column(String) # Stored as JSON string
    
    # Conditional Coverages
    has_general_liability = Column(Boolean, default=True) # New
    has_auto_liability = Column(Boolean, default=True) # New

    # Relationships
    vehicles = relationship("Vehicle", back_populates="policy", cascade="all, delete-orphan")
    drivers = relationship("Driver", back_populates="policy", cascade="all, delete-orphan")
    coverages = relationship("Coverage", back_populates="policy", cascade="all, delete-orphan")

class Vehicle(Base):
    __tablename__ = 'vehicles'
    
    id = Column(Integer, primary_key=True)
    policy_id = Column(Integer, ForeignKey('policies.id'))
    year = Column(Integer)
    make = Column(String)
    model = Column(String)
    vin = Column(String)
    gvw = Column(Integer) # Gross Vehicle Weight
    vehicle_type = Column(String)

    policy = relationship("Policy", back_populates="vehicles")
    coverages = relationship("Coverage", back_populates="vehicle")

class Driver(Base):
    __tablename__ = 'drivers'
    
    id = Column(Integer, primary_key=True)
    policy_id = Column(Integer, ForeignKey('policies.id'))
    full_name = Column(String)
    license_number = Column(String)
    is_excluded = Column(Boolean, default=False)

    policy = relationship("Policy", back_populates="drivers")

class Coverage(Base):
    __tablename__ = 'coverages'
    
    id = Column(Integer, primary_key=True)
    policy_id = Column(Integer, ForeignKey('policies.id'))
    vehicle_id = Column(Integer, ForeignKey('vehicles.id'), nullable=True)
    type = Column(String) # Legacy "display name"
    coverage_code = Column(String) # New Ontology Code
    family = Column(String) # New Ontology Family
    
    # Ontology Limits
    per_person = Column(Integer, nullable=True)     # Replaces limit_per_person
    per_accident = Column(Integer, nullable=True)   # Replaces limit_per_accident
    per_occurrence = Column(Integer, nullable=True) # New
    combined_single_limit = Column(Integer, nullable=True) # New (CSL)
    aggregate = Column(Integer, nullable=True)      # New
    
    # Legacy aliases (mapped to new columns in code if needed, or kept for backward compat)
    limit_per_person = Column(Integer, nullable=True)
    limit_per_accident = Column(Integer, nullable=True)
    limit_property_damage = Column(Integer, nullable=True) # Maps to per_occurrence for PD
    
    deductible = Column(Integer, nullable=True)

    policy = relationship("Policy", back_populates="coverages")
    vehicle = relationship("Vehicle", back_populates="coverages")

def init_db(db_name="insurance_data.db"):
    """
    Initializes the SQLite database.
    """
    engine = create_engine(f'sqlite:///{db_name}')
    Base.metadata.create_all(engine)
    
    # --- Simple Migration Check ---
    # Since we are using SQLite, we can inspect and alter if needed.
    # This avoids crashes when user pulls updates but has old DB.
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    columns = [c['name'] for c in inspector.get_columns('policies')]
    
    with engine.connect() as conn:
        if 'insured_address' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN insured_address VARCHAR"))
        if 'insured_city' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN insured_city VARCHAR"))
        if 'insured_state_code' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN insured_state_code VARCHAR"))
        if 'insured_zip' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN insured_zip VARCHAR"))
            
        # Migration for Logic Improv (NAIC, Deductible, Flags)
        if 'naic_number' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN naic_number VARCHAR"))
        if 'cargo_deductible' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN cargo_deductible VARCHAR"))
        if 'has_general_liability' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN has_general_liability BOOLEAN DEFAULT 1"))
        if 'has_auto_liability' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN has_auto_liability BOOLEAN DEFAULT 1"))
            
        # Classification Metadata Migrations
        if 'policy_type' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN policy_type VARCHAR"))
        if 'classification_confidence' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN classification_confidence VARCHAR"))
        if 'classification_signals' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN classification_signals VARCHAR"))
            
        # Coverage Migrations
        cov_columns = [c['name'] for c in inspector.get_columns('coverages')]
        if 'limit_property_damage' not in cov_columns:
            conn.execute(text("ALTER TABLE coverages ADD COLUMN limit_property_damage INTEGER"))

        # Ontology Migrations
        if 'coverage_code' not in cov_columns:
            conn.execute(text("ALTER TABLE coverages ADD COLUMN coverage_code VARCHAR"))
        if 'family' not in cov_columns:
            conn.execute(text("ALTER TABLE coverages ADD COLUMN family VARCHAR"))
        if 'per_person' not in cov_columns:
            conn.execute(text("ALTER TABLE coverages ADD COLUMN per_person INTEGER"))
        if 'per_accident' not in cov_columns:
            conn.execute(text("ALTER TABLE coverages ADD COLUMN per_accident INTEGER"))
        if 'per_occurrence' not in cov_columns:
            conn.execute(text("ALTER TABLE coverages ADD COLUMN per_occurrence INTEGER"))
        if 'combined_single_limit' not in cov_columns:
            conn.execute(text("ALTER TABLE coverages ADD COLUMN combined_single_limit INTEGER"))
        if 'aggregate' not in cov_columns:
            conn.execute(text("ALTER TABLE coverages ADD COLUMN aggregate INTEGER"))
            
        conn.commit()
            
    return engine

def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()
