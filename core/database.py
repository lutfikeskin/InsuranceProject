from sqlalchemy import create_engine, Column, Integer, String, Date, Boolean, ForeignKey, Float, DateTime
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os
from datetime import datetime

Base = declarative_base()

class ApiUsage(Base):
    __tablename__ = 'api_usage'
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    model_name = Column(String)
    input_tokens = Column(Integer)
    output_tokens = Column(Integer)
    cost = Column(Float) # Estimated USD
    status = Column(String) # success/failure
    request_type = Column(String) # e.g. "scout", "extraction", "query"

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
    general_liability_limit = Column(String) # New
    has_full_collision = Column(Boolean)
    
    # Classification Metadata
    policy_type = Column(String)
    classification_confidence = Column(String)
    classification_signals = Column(String) # Stored as JSON string
    
    # Conditional Coverages
    has_general_liability = Column(Boolean, default=True) # New
    has_auto_liability = Column(Boolean, default=True) # New
    
    # Expanded Coverage Summaries
    um_uim_limit = Column(String)
    med_pay_limit = Column(String)
    pip_limit = Column(String)
    comp_deductible = Column(String)
    coll_deductible = Column(String)

    status = Column(String, default='Active') # New Status Field

    # Relationships
    vehicles = relationship("Vehicle", back_populates="policy", cascade="all, delete-orphan")
    drivers = relationship("Driver", back_populates="policy", cascade="all, delete-orphan")
    coverages = relationship("Coverage", back_populates="policy", cascade="all, delete-orphan")
    history = relationship("PolicyHistory", back_populates="policy", cascade="all, delete-orphan")
    additional_interests = relationship("AdditionalInterest", back_populates="policy", cascade="all, delete-orphan")

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
    chassis = Column(String)
    body = Column(String)

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

class AdditionalInterest(Base):
    __tablename__ = 'additional_interests'
    
    id = Column(Integer, primary_key=True)
    policy_id = Column(Integer, ForeignKey('policies.id'))
    name = Column(String)
    address = Column(String)
    interest_type = Column(String) # e.g. "Certificate Holder", "Additional Insured", "Loss Payee"
    
    policy = relationship("Policy", back_populates="additional_interests")

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
        if 'general_liability_limit' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN general_liability_limit VARCHAR"))
        if 'has_general_liability' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN has_general_liability BOOLEAN DEFAULT 1"))
        if 'has_auto_liability' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN has_auto_liability BOOLEAN DEFAULT 1"))
        
        # Expanded Visibility Migrations
        if 'um_uim_limit' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN um_uim_limit VARCHAR"))
        if 'med_pay_limit' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN med_pay_limit VARCHAR"))
        if 'pip_limit' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN pip_limit VARCHAR"))
        if 'comp_deductible' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN comp_deductible VARCHAR"))
        if 'coll_deductible' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN coll_deductible VARCHAR"))
            
        # Classification Metadata Migrations
        if 'policy_type' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN policy_type VARCHAR"))
        if 'classification_confidence' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN classification_confidence VARCHAR"))
        if 'classification_signals' not in columns:
            conn.execute(text("ALTER TABLE policies ADD COLUMN classification_signals VARCHAR"))
        
        # New Status Column
        if 'status' not in columns:
             conn.execute(text("ALTER TABLE policies ADD COLUMN status VARCHAR DEFAULT 'Active'"))
            
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
            
        # Vehicle Migrations
        veh_columns = [c['name'] for c in inspector.get_columns('vehicles')]
        if 'chassis' not in veh_columns:
            conn.execute(text("ALTER TABLE vehicles ADD COLUMN chassis VARCHAR"))
        if 'body' not in veh_columns:
            conn.execute(text("ALTER TABLE vehicles ADD COLUMN body VARCHAR"))
        
        # Additional Interest Table is created by Base.metadata.create_all if it doesn't exist
        # But if we were migrating an existing DB that didn't have it, create_all does it.

        # History Migrations
        if inspector.has_table("policy_history"):
            hist_columns = [c['name'] for c in inspector.get_columns('policy_history')]
            if 'event_type' not in hist_columns:
                 conn.execute(text("ALTER TABLE policy_history ADD COLUMN event_type VARCHAR DEFAULT 'UPDATE'"))
            if 'policy_version' not in hist_columns:
                 conn.execute(text("ALTER TABLE policy_history ADD COLUMN policy_version INTEGER DEFAULT 1"))
            # Fix for missing base columns
            if 'source' not in hist_columns:
                 conn.execute(text("ALTER TABLE policy_history ADD COLUMN source VARCHAR"))
            if 'changes' not in hist_columns:
                 # SQLite doesn't have JSON type, effectively TEXT
                 conn.execute(text("ALTER TABLE policy_history ADD COLUMN changes TEXT"))
            if 'timestamp' not in hist_columns:
                 conn.execute(text("ALTER TABLE policy_history ADD COLUMN timestamp DATETIME"))
            
        # API Usage Migration Note: 
        # Base.metadata.create_all(engine) above handles new tables like api_usage
        # But for consistency, we ensures the transaction is committed.
        conn.commit()
            
    return engine

def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()
