import random
from datetime import datetime, timedelta
from database import init_db, get_session, Policy, Vehicle, Driver, Coverage
from sqlalchemy.orm import Session
from coverage_ontology import CoverageFamily, LineOfBusiness

# Sample Data
CARRIERS = [
    ("Progressive", "10101"),
    ("State Farm", "25143"),
    ("Geico", "35882"),
    ("Allstate", "19232"),
    ("Liberty Mutual", "23043"),
    ("Nationwide", "23787"),
    ("Travelers", "25658"),
    ("Hartford", "19682")
]

INSURED_NAMES = [
    "John Doe", "Jane Smith", "Robert Johnson", "Michael Brown", "William Davis",
    "David Miller", "Richard Wilson", "Joseph Moore", "Thomas Taylor", "Christopher Anderson"
]

BUSINESS_NAMES = [
    "Apex Logistics LLC", "Skyline Construction", "Main Street Bakery", "Green Valley Landscaping",
    "Elite Services Inc", "Coastal Maritime", "Global Tech Solutions", "Reliable Transport",
    "Northern Star Trading", "Pioneer Distribution"
]

CITIES = [
    ("Los Angeles", "CA", "90001"),
    ("New York", "NY", "10001"),
    ("Chicago", "IL", "60601"),
    ("Houston", "TX", "77001"),
    ("Phoenix", "AZ", "85001"),
    ("Philadelphia", "PA", "19101"),
    ("San Antonio", "TX", "78201"),
    ("San Diego", "CA", "92101")
]

MAKES = ["Freightliner", "Volvo", "Peterbilt", "Kenworth", "International", "Ford", "Chevrolet"]
MODELS = ["Cascadia", "VNL", "579", "T680", "LT", "F-150", "Silverado"]

def clear_data(session: Session):
    print("Clearing existing mock data...")
    session.query(Coverage).delete()
    session.query(Vehicle).delete()
    session.query(Driver).delete()
    session.query(Policy).delete()
    session.commit()

def create_policy_blueprint(idx):
    """Creates a diverse set of policy packages."""
    blueprints = [
        # 1. Commercial Long-Haul Trucker
        {
            "name": "High-Risk Transport",
            "type": "commercial_auto",
            "insured_is_business": True,
            "coverages": [
                {"code": "AUTO_LIAB_CSL", "family": CoverageFamily.AUTO_LIABILITY, "limits": {"combined_single_limit": 1000000}},
                {"code": "COMP", "family": CoverageFamily.PHYSICAL_DAMAGE, "deductible": 1000},
                {"code": "COLL", "family": CoverageFamily.PHYSICAL_DAMAGE, "deductible": 1000},
                {"code": "CARGO_LEGAL_LIAB", "family": CoverageFamily.CARGO, "limits": {"per_occurrence": 100000}, "deductible": 1000}
            ],
            "vehicles": 3,
            "drivers": 2
        },
        # 2. Small Business BOP
        {
            "name": "Main Street Package",
            "type": "bop",
            "insured_is_business": True,
            "coverages": [
                {"code": "GL_OCCURRENCE", "family": CoverageFamily.GENERAL_LIABILITY, "limits": {"per_occurrence": 1000000, "aggregate": 2000000}},
                {"code": "PROPERTY_STRUCTURE", "family": "property", "limits": {"per_occurrence": 500000}, "deductible": 2500}
            ],
            "vehicles": 0,
            "drivers": 0
        },
        # 3. Personal High-Net-Worth
        {
            "name": "Elite Personal Auto",
            "type": "personal_auto",
            "insured_is_business": False,
            "coverages": [
                {"code": "AUTO_LIAB_BI", "family": CoverageFamily.AUTO_LIABILITY, "limits": {"per_person": 250000, "per_accident": 500000}},
                {"code": "AUTO_LIAB_PD", "family": CoverageFamily.AUTO_LIABILITY, "limits": {"per_occurrence": 100000}},
                {"code": "UM_BI", "family": CoverageFamily.UNINSURED_MOTORIST, "limits": {"per_person": 250000, "per_accident": 500000}},
                {"code": "COMP", "family": CoverageFamily.PHYSICAL_DAMAGE, "deductible": 250},
                {"code": "COLL", "family": CoverageFamily.PHYSICAL_DAMAGE, "deductible": 500}
            ],
            "vehicles": 2,
            "drivers": 2
        },
        # 4. Local Contractor
        {
            "name": "Contractor Special",
            "type": "general_liability",
            "insured_is_business": True,
            "coverages": [
                {"code": "GL_OCCURRENCE", "family": CoverageFamily.GENERAL_LIABILITY, "limits": {"per_occurrence": 1000000, "aggregate": 1000000}}
            ],
            "vehicles": 0,
            "drivers": 0
        },
        # 5. Delivery Services
        {
            "name": "Last-Mile Delivery",
            "type": "commercial_auto",
            "insured_is_business": True,
            "coverages": [
                {"code": "AUTO_LIAB_CSL", "family": CoverageFamily.AUTO_LIABILITY, "limits": {"combined_single_limit": 500000}},
                {"code": "COMP", "family": CoverageFamily.PHYSICAL_DAMAGE, "deductible": 500},
                {"code": "COLL", "family": CoverageFamily.PHYSICAL_DAMAGE, "deductible": 500}
            ],
            "vehicles": 5,
            "drivers": 4
        }
    ]
    return blueprints[idx % len(blueprints)]

def generate_mock_data(num_policies=20):
    engine = init_db()
    session = get_session(engine)
    
    clear_data(session)
    
    print(f"Generating {num_policies} enhanced mock policies...")
    
    for i in range(num_policies):
        blueprint = create_policy_blueprint(i)
        carrier, naic = random.choice(CARRIERS)
        
        if blueprint["insured_is_business"]:
            insured = BUSINESS_NAMES[i % len(BUSINESS_NAMES)]
            business = insured
        else:
            insured = INSURED_NAMES[i % len(INSURED_NAMES)]
            business = None
            
        city, state, zip_code = random.choice(CITIES)
        effective_date = datetime.now() - timedelta(days=random.randint(0, 300))
        expiration_date = effective_date + timedelta(days=365)
        
        policy_number = f"POL-{random.randint(100000, 999999)}-{i:02d}"
        
        policy = Policy(
            carrier_name=carrier,
            naic_number=naic,
            policy_number=policy_number,
            effective_date=effective_date.date(),
            expiration_date=expiration_date.date(),
            account_type="Commercial" if blueprint["insured_is_business"] else "Personal",
            insured_name=insured,
            business_name=business,
            insured_address=f"{random.randint(100, 9999)} Oak Street",
            insured_city=city,
            insured_state_code=state,
            insured_zip=zip_code,
            premium=f"${random.randint(2000, 75000):,.2f}",
            state=state,
            policy_type=blueprint["type"],
            has_general_liability=blueprint["type"] in ["general_liability", "bop"],
            has_auto_liability="auto" in blueprint["type"] or blueprint["type"] == "umbrella",
            has_full_collision="auto" in blueprint["type"]
        )
        
        # Add Vehicles
        for _ in range(blueprint["vehicles"]):
            v = Vehicle(
                year=random.randint(2018, 2025),
                make=random.choice(MAKES),
                model=random.choice(MODELS),
                vin=f"1VIN{random.randint(1000000000000, 9999999999999)}",
                gvw=random.randint(5000, 80000),
                vehicle_type="Tractor" if blueprint["type"] == "commercial_auto" else "Passenger"
            )
            policy.vehicles.append(v)
            
        # Add Drivers
        for _ in range(blueprint["drivers"]):
            d = Driver(
                full_name=f"{random.choice(INSURED_NAMES).split()[0]} {random.choice(INSURED_NAMES).split()[-1]}",
                license_number=f"LIC-{random.randint(100000, 999999)}",
                is_excluded=False
            )
            policy.drivers.append(d)
            
        # Add Coverages
        liab_display = None
        cargo_display = None

        for c_data in blueprint["coverages"]:
            lims = c_data.get("limits", {})
            policy.coverages.append(Coverage(
                type=c_data["code"], # Display name fallback
                coverage_code=c_data["code"],
                family=c_data["family"],
                per_person=lims.get("per_person"),
                per_accident=lims.get("per_accident"),
                per_occurrence=lims.get("per_occurrence"),
                combined_single_limit=lims.get("combined_single_limit"),
                aggregate=lims.get("aggregate"),
                deductible=c_data.get("deductible")
            ))

            # Set summary display strings for UI
            if c_data["family"] == CoverageFamily.AUTO_LIABILITY:
                if "combined_single_limit" in lims:
                    liab_display = f"${lims['combined_single_limit']:,} CSL"
                elif "per_person" in lims and "per_accident" in lims:
                    liab_display = f"{lims['per_person']//1000}/{lims['per_accident']//1000}"
            elif c_data["family"] == CoverageFamily.GENERAL_LIABILITY:
                if "per_occurrence" in lims:
                    liab_display = f"${lims['per_occurrence']:,} Occ"
            elif c_data["family"] == CoverageFamily.CARGO:
                if "per_occurrence" in lims:
                    cargo_display = f"${lims['per_occurrence']:,}"

        policy.liability_limit = liab_display
        policy.cargo_limit = cargo_display
            
        session.add(policy)
        
    session.commit()
    print(f"Successfully added {num_policies} enhanced mock policies with detailed coverages.")

if __name__ == "__main__":
    generate_mock_data(20)
