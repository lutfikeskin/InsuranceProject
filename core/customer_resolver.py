from sqlalchemy import or_

from core.database import Customer, CustomerEntity


class CustomerResolver:
    def __init__(self, session):
        self.session = session

    def resolve(self, extraction_result: dict) -> dict:
        p = extraction_result.get("policy", {})
        insured_name = (p.get("insured_name") or "").strip()
        policy_type = extraction_result.get("classification", {}).get("policy_type", "")

        if not insured_name:
            return self._no_match("No insured name extracted")

        if policy_type == "personal_auto":
            return self._resolve_personal(insured_name)
        return self._resolve_commercial(insured_name, extraction_result)

    def _resolve_personal(self, insured_name: str) -> dict:
        exact = self.session.query(Customer).filter(Customer.full_name.ilike(insured_name)).first()
        if exact:
            return self._matched(exact, "confirmed", f"Exact name match: '{insured_name}'")

        entity_match = (
            self.session.query(Customer)
            .join(CustomerEntity)
            .filter(
                CustomerEntity.entity_name.ilike(insured_name),
                CustomerEntity.entity_type == "personal",
            )
            .first()
        )
        if entity_match:
            return self._matched(entity_match, "confirmed", f"Known name variant: '{insured_name}'")

        fuzzy = self._fuzzy_name_match(insured_name, entity_type="personal")
        if fuzzy:
            return self._matched(fuzzy["customer"], "suggested", fuzzy["reason"])

        return self._no_match(f"No match found for '{insured_name}'")

    def _resolve_commercial(self, insured_name: str, extraction_result: dict) -> dict:
        entity_match = (
            self.session.query(Customer)
            .join(CustomerEntity)
            .filter(CustomerEntity.entity_name.ilike(insured_name))
            .first()
        )
        if entity_match:
            return self._matched(entity_match, "confirmed", f"Known business entity: '{insured_name}'")

        drivers = extraction_result.get("drivers", [])
        for driver in drivers:
            driver_name = (driver.get("full_name") or "").strip()
            if not driver_name:
                continue
            driver_match = self.session.query(Customer).filter(Customer.full_name.ilike(driver_name)).first()
            if driver_match:
                return self._matched(
                    driver_match,
                    "suggested",
                    (
                        f"Driver '{driver_name}' matches existing customer. "
                        f"Business '{insured_name}' likely owned by them."
                    ),
                )

        return self._no_match(f"Business '{insured_name}' not linked to any known customer")

    def _fuzzy_name_match(self, name: str, entity_type=None):
        tokens = [token for token in name.lower().split() if len(token) > 2]
        if not tokens:
            return None
        last_name = tokens[-1]

        query = self.session.query(Customer).join(CustomerEntity).filter(
            CustomerEntity.entity_name.ilike(f"%{last_name}%")
        )
        if entity_type:
            query = query.filter(CustomerEntity.entity_type == entity_type)

        candidates = query.all()
        if not candidates:
            return None

        best = None
        best_score = 0
        for candidate in candidates:
            for entity in candidate.entities:
                entity_tokens = (entity.entity_name or "").lower().split()
                matches = sum(1 for token in tokens if any(token in entity_token for entity_token in entity_tokens))
                score = matches / len(tokens)
                if score > best_score and score >= 0.6:
                    best_score = score
                    best = {
                        "customer": candidate,
                        "reason": f"Name token match ({int(score*100)}%): '{name}' ~ '{entity.entity_name}'",
                    }
        return best

    def create_customer(
        self,
        full_name: str,
        entity_name: str = None,
        entity_type: str = "personal",
    ) -> Customer:
        customer = Customer(full_name=full_name)
        self.session.add(customer)
        self.session.flush()

        self.session.add(
            CustomerEntity(
                customer_id=customer.id,
                entity_name=full_name,
                entity_type="personal",
                is_primary=True,
                source="extraction",
            )
        )

        if entity_name and entity_name.lower() != full_name.lower():
            self.session.add(
                CustomerEntity(
                    customer_id=customer.id,
                    entity_name=entity_name,
                    entity_type=entity_type,
                    is_primary=False,
                    source="extraction",
                )
            )
        return customer

    def add_entity(
        self,
        customer: Customer,
        entity_name: str,
        entity_type: str,
        source: str = "manual",
    ):
        if not entity_name:
            return
        exists = self.session.query(CustomerEntity).filter_by(
            customer_id=customer.id,
            entity_name=entity_name,
        ).first()
        if not exists:
            self.session.add(
                CustomerEntity(
                    customer_id=customer.id,
                    entity_name=entity_name,
                    entity_type=entity_type,
                    is_primary=False,
                    source=source,
                )
            )

    def merge_customers(self, keep_id: int, merge_id: int) -> dict:
        keep = self.session.query(Customer).get(keep_id)
        merge = self.session.query(Customer).get(merge_id)
        if not keep or not merge:
            return {"success": False, "message": "Customer not found"}

        for policy in merge.policies:
            policy.customer_id = keep.id
        for alias in merge.entities:
            alias.customer_id = keep.id

        self.session.delete(merge)
        self.session.commit()
        return {"success": True, "message": f"Merged into customer {keep_id}"}

    def _matched(self, customer, confidence, reason):
        return {
            "customer": customer,
            "confidence": confidence,
            "match_reason": reason,
            "needs_review": confidence == "suggested",
        }

    def _no_match(self, reason):
        return {
            "customer": None,
            "confidence": "none",
            "match_reason": reason,
            "needs_review": False,
        }
