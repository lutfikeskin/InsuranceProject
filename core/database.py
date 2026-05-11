from sqlalchemy import create_engine, Column, Integer, String, Date, Boolean, ForeignKey, Float, DateTime, Text, JSON, inspect, text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
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

class Customer(Base):
    __tablename__ = 'customers'

    id = Column(Integer, primary_key=True)
    full_name = Column(String, nullable=False)
    primary_email = Column(String, nullable=True)
    primary_phone = Column(String, nullable=True)
    needs_real_name_entry = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    entities = relationship("CustomerEntity", back_populates="customer", cascade="all, delete-orphan")
    policies = relationship("Policy", back_populates="customer")

class CustomerEntity(Base):
    __tablename__ = 'customer_entities'

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'))
    entity_name = Column(String, nullable=False)
    entity_type = Column(String)  # personal, business, dba, maiden_name
    is_primary = Column(Boolean, default=False)
    source = Column(String)  # extraction, manual
    first_seen = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="entities")

class Policy(Base):
    __tablename__ = 'policies'
    
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=True)
    carrier_name = Column(String)
    underwriter_name = Column(String, nullable=True)
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
    policy_status = Column(String, default='active')
    replaced_by_policy_id = Column(Integer, ForeignKey('policies.id'), nullable=True)
    field_confidences = Column(JSON, nullable=True)
    premium_audit_flag = Column(String, nullable=True)
    document_type = Column(String, nullable=True)
    policy_data_source = Column(String, nullable=True)
    layout_fingerprint = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow) # New Timestamp Field

    # Ontology / compliance / extra fields not mapped to relational columns (JSON string)
    extraction_extras = Column(Text, nullable=True)

    # Relationships
    vehicles = relationship("Vehicle", back_populates="policy", cascade="all, delete-orphan")
    drivers = relationship("Driver", back_populates="policy", cascade="all, delete-orphan")
    coverages = relationship("Coverage", back_populates="policy", cascade="all, delete-orphan")
    history = relationship("PolicyHistory", back_populates="policy", cascade="all, delete-orphan")
    additional_interests = relationship("AdditionalInterest", back_populates="policy", cascade="all, delete-orphan")
    customer = relationship("Customer", back_populates="policies")
    policy_relationships = relationship(
        "PolicyRelationship",
        foreign_keys="PolicyRelationship.policy_id",
        back_populates="policy",
        cascade="all, delete-orphan",
    )
    related_policy_relationships = relationship(
        "PolicyRelationship",
        foreign_keys="PolicyRelationship.related_policy_id",
        back_populates="related_policy",
        cascade="all, delete-orphan",
    )
    endorsements = relationship(
        "PolicyEndorsement",
        foreign_keys="PolicyEndorsement.parent_policy_id",
        back_populates="parent_policy",
        cascade="all, delete-orphan",
    )

class PolicyRelationship(Base):
    __tablename__ = 'policy_relationships'

    id = Column(Integer, primary_key=True)
    policy_id = Column(Integer, ForeignKey('policies.id'))
    related_policy_id = Column(Integer, ForeignKey('policies.id'))
    relationship_type = Column(String)  # renewal, rewrite, mid_term_change, same_customer_new_policy, canceled_replaced
    confidence = Column(String)  # confirmed, suggested
    created_at = Column(DateTime, default=datetime.utcnow)

    policy = relationship("Policy", foreign_keys=[policy_id], back_populates="policy_relationships")
    related_policy = relationship("Policy", foreign_keys=[related_policy_id], back_populates="related_policy_relationships")


class PolicyEndorsement(Base):
    __tablename__ = 'policy_endorsements'

    id = Column(Integer, primary_key=True)
    parent_policy_id = Column(Integer, ForeignKey('policies.id'), nullable=True)
    parent_policy_number = Column(String)
    endorsement_type = Column(String)
    endorsement_form_number = Column(String, nullable=True)
    effective_date = Column(Date, nullable=True)
    changes_summary = Column(Text, nullable=True)
    file_hash = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    parent_policy = relationship("Policy", foreign_keys=[parent_policy_id], back_populates="endorsements")

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
    For SQLite, adds new columns when the file already exists without them.
    """
    engine = create_engine(f'sqlite:///{db_name}')
    Base.metadata.create_all(engine)
    if engine.dialect.name == "sqlite":
        insp = inspect(engine)
        policy_cols = {c["name"] for c in insp.get_columns("policies")}
        if "extraction_extras" not in policy_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE policies ADD COLUMN extraction_extras TEXT"))
        if "underwriter_name" not in policy_cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE policies ADD COLUMN underwriter_name VARCHAR"))
        customer_cols = {c["name"] for c in insp.get_columns("customers")}
        with engine.begin() as conn:
            if "primary_email" not in customer_cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN primary_email VARCHAR"))
            if "primary_phone" not in customer_cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN primary_phone VARCHAR"))
            if "needs_real_name_entry" not in customer_cols:
                conn.execute(text("ALTER TABLE customers ADD COLUMN needs_real_name_entry BOOLEAN DEFAULT 0"))
        entity_cols = {c["name"] for c in insp.get_columns("customer_entities")}
        with engine.begin() as conn:
            if "entity_name" not in entity_cols:
                conn.execute(text("ALTER TABLE customer_entities ADD COLUMN entity_name VARCHAR"))
            if "entity_type" not in entity_cols:
                conn.execute(text("ALTER TABLE customer_entities ADD COLUMN entity_type VARCHAR"))
            if "is_primary" not in entity_cols:
                conn.execute(text("ALTER TABLE customer_entities ADD COLUMN is_primary BOOLEAN DEFAULT 0"))
            if "source" not in entity_cols:
                conn.execute(text("ALTER TABLE customer_entities ADD COLUMN source VARCHAR"))
            if "first_seen" not in entity_cols:
                conn.execute(text("ALTER TABLE customer_entities ADD COLUMN first_seen DATETIME"))
    return engine

def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()

# Late import to register PolicyHistory model with SQLAlchemy mapper
# before any session uses Policy.history relationship. Do not move.
from core import history_model  # noqa: F401, E402
PolicyHistory = history_model.PolicyHistory
