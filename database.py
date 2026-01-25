from sqlalchemy import create_engine, Column, Integer, String, Date, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os
from datetime import datetime

Base = declarative_base()

class Policy(Base):
    __tablename__ = 'policies'
    
    id = Column(Integer, primary_key=True)
    carrier_name = Column(String)
    policy_number = Column(String, unique=True, nullable=False)
    effective_date = Column(Date)
    expiration_date = Column(Date)
    account_type = Column(String)  # Personal or Commercial
    insured_name = Column(String)
    business_name = Column(String)
    
    # New Fields
    premium = Column(String) # Keeping as string to handle currency symbols if needed, or extract as float later
    state = Column(String)
    financial_responsibility_name = Column(String)
    liability_limit = Column(String)
    cargo_limit = Column(String)
    has_full_collision = Column(Boolean)

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
    type = Column(String)
    limit_per_person = Column(Integer, nullable=True)
    limit_per_accident = Column(Integer, nullable=True)
    deductible = Column(Integer, nullable=True)

    policy = relationship("Policy", back_populates="coverages")
    vehicle = relationship("Vehicle", back_populates="coverages")

def init_db(db_name="insurance_data.db"):
    """
    Initializes the SQLite database.
    """
    engine = create_engine(f'sqlite:///{db_name}')
    Base.metadata.create_all(engine)
    return engine

def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()
