import re
import streamlit as st
import io
import zipfile
from core.services import PolicyService, COIService
from core.database import get_session
from modules.coi import COIGenerator, load_companies
from utils.naic_utils import get_naic_for_carrier
from core.constants import POLICY_SEARCH_PAGE_LIMIT


def _reset_coi_holder_session():
    for k in (
        "h_name",
        "h_addr",
        "h_city",
        "h_state",
        "h_zip",
        "selected_coi_company",
    ):
        if k in st.session_state:
            del st.session_state[k]


GL_AGGREGATE_OPTIONS = ("$1,000,000", "$2,000,000")
COI_TYPE_OPTIONS = ("Additional Insured", "Certificate Holder", "Lienholder")
LIENHOLDER_HOLDER_PLACEHOLDER = "[Certificate Holder Name]"


def _format_vehicle_option(v) -> str:
    """Render a vehicle for the Lienholder multiselect: 'Year Make Model - VIN'."""
    parts = [str(v.year or "").strip(), (v.make or "").strip(), (v.model or "").strip()]
    head = " ".join(p for p in parts if p) or "Vehicle"
    return f"{head} - {v.vin or 'no VIN'}"


def _format_vehicle_for_description(v) -> str:
    """Render a vehicle inside the Loss Payee clause: 'Year Make Model (VIN: ...)'."""
    parts = [str(v.year or "").strip(), (v.make or "").strip(), (v.model or "").strip()]
    head = " ".join(p for p in parts if p) or "Vehicle"
    return f"{head} (VIN: {v.vin or 'N/A'})"


def _build_default_desc(coi_service, p, coi_type, selected_vehicle_objs, holder_name):
    """Build the default Operations Description for a given COI type.

    Reuses COIService.prepare_coi_data for the policy-derived lines (vehicles, drivers,
    compliance) and only varies the trailing clause based on coi_type.
    """
    _, desc_lines = coi_service.prepare_coi_data(p)

    # Lienholder: vehicles are named inline in the Loss Payee clause, so drop the
    # redundant "Vehicle List: ..." line produced by prepare_coi_data.
    if coi_type == "Lienholder":
        desc_lines = [ln for ln in desc_lines if not ln.startswith("Vehicle List:")]

    desc_lines.append("Radius of Operation: Unlimited")

    if coi_type == "Additional Insured":
        desc_lines.append("Certificate Holder is also listed as an additional insured")
    elif coi_type == "Lienholder":
        veh_str = " ".join(_format_vehicle_for_description(v) for v in (selected_vehicle_objs or []))
        if not veh_str:
            veh_str = "[Selected Vehicles]"

        def _fmt_ded(val):
            s = (val or "").strip().lstrip("$").strip()
            return f"${s}" if s else "—"

        comp = _fmt_ded(p.comp_deductible)
        coll = _fmt_ded(p.coll_deductible)
        holder_token = (holder_name or "").strip() or LIENHOLDER_HOLDER_PLACEHOLDER
        desc_lines.append(
            f"{holder_token} is also listed as a Loss Payee for {veh_str} "
            f"with Comp Ded: {comp} / Coll Ded: {coll}"
        )
    # "Certificate Holder" → no extra clause appended.

    return "\n".join(desc_lines)


def _safe_coi_pdf_filename(insured_name: str, holder_name: str) -> str:
    """Build a Windows-safe COI PDF filename."""
    safe_insured = (insured_name or "").strip() or "Unknown Insured"
    safe_holder = (holder_name or "").strip() or "Unknown Holder"

    filename = f"COI - {safe_insured} - {safe_holder}.pdf"
    # Replace Windows-invalid filename characters, then collapse extra whitespace.
    filename = re.sub(r'[\\/:*?"<>|]+', " ", filename)
    filename = re.sub(r"\s+", " ", filename).strip()
    return filename


def _safe_bulk_zip_filename(insured_name: str) -> str:
    """Build a Windows-safe bulk ZIP filename."""
    safe_insured = (insured_name or "").strip() or "Unknown Insured"
    filename = f"COIs - {safe_insured} - Bulk.zip"
    filename = re.sub(r'[\\/:*?"<>|]+', " ", filename)
    filename = re.sub(r"\s+", " ", filename).strip()
    return filename


def _default_gl_agg_display_value(policy) -> str:
    """Pick default general-aggregate radio from policy limit text."""
    parts = [
        str(policy.general_liability_limit or ""),
        str(policy.liability_limit or ""),
    ]
    blob = " ".join(parts).lower()
    compact = re.sub(r"[\s,$]", "", blob)
    if "2000000" in compact:
        return GL_AGGREGATE_OPTIONS[1]
    if re.search(r"\b2m\b", blob):
        return GL_AGGREGATE_OPTIONS[1]
    return GL_AGGREGATE_OPTIONS[0]


def page_create_coi():
    st.title("📝 Create COI")
    st.markdown("Generate a Certificate of Insurance using data from an existing policy.")

    session = get_session(st.session_state.db_engine)
    service = PolicyService(session)
    coi_service = COIService()

    try:
        coi_search = st.text_input(
            "Search policies by number or insured name",
            "",
            key="coi_policy_search",
            help=f"Shows up to {POLICY_SEARCH_PAGE_LIMIT} matches. Leave empty for most recent.",
        )
        term = coi_search.strip() or None
        policies = service.search_policies(term, limit=POLICY_SEARCH_PAGE_LIMIT)
        total = service.count_policies(term)
        if total > len(policies):
            st.caption(f"Showing {len(policies)} of {total} matches — refine search if needed.")

        raw_coi_id = st.session_state.pop("coi_policy_id", None)
        if raw_coi_id is not None:
            try:
                tid = int(raw_coi_id)
            except (TypeError, ValueError):
                tid = None
            extra = service.get_policy_by_id(tid) if tid is not None else None
            if extra:
                if not any(p.id == extra.id for p in policies):
                    policies = [extra] + [p for p in policies if p.id != extra.id][
                        : POLICY_SEARCH_PAGE_LIMIT - 1
                    ]
                pick = f"{extra.policy_number} - {extra.insured_name}"
                st.session_state["coi_policy_pick"] = pick

        if not policies:
            st.warning("No policies match this search.")
            return

        options = {f"{p.policy_number} - {p.insured_name}": p for p in policies}
        keys = list(options.keys())

        col_sel, col_mode = st.columns([2, 1])
        with col_sel:
            selected_key = st.selectbox(
                "Select Policy",
                options=keys,
                key="coi_policy_pick",
            )
        bulk_mode = col_mode.toggle(
            "Bulk Mode",
            value=False,
            help="Generate COIs for multiple companies at once",
        )

        if not selected_key:
            return

        p = options[selected_key]

        prev_id = st.session_state.get("coi_last_policy_id")
        if prev_id is not None and prev_id != p.id:
            _reset_coi_holder_session()
            for suffix in (
                "coi_desc_area_",
                "coi_desc_bulk_",
                "coi_type_",
                "coi_lien_vehicles_",
                "coi_desc_state_",
                "coi_desc_state_bulk_",
            ):
                old_key = f"{suffix}{prev_id}"
                if old_key in st.session_state:
                    del st.session_state[old_key]
            old_agg = f"coi_gl_gen_agg_{prev_id}"
            if old_agg in st.session_state:
                del st.session_state[old_agg]
        st.session_state["coi_last_policy_id"] = p.id

        st.info(f"Filling COI for: **{p.insured_name}** ({p.policy_number})")

        st.subheader("Certificate Holder Details")

        # COI Type selector — drives ADDL INSD column, description clause, and Cargo↔Comp/Coll swap.
        coi_type_key = f"coi_type_{p.id}"
        coi_type = st.radio(
            "COI Type",
            options=COI_TYPE_OPTIONS,
            horizontal=True,
            key=coi_type_key,
            help=(
                "Additional Insured: standard COI. "
                "Certificate Holder: drops the 'also listed as additional insured' clause and clears the ADDL INSD column. "
                "Lienholder: pick covered vehicles and replace Cargo with Comp/Coll deductibles."
            ),
        )

        # Lienholder needs a per-vehicle picker so we know which units appear in the Loss Payee clause.
        selected_vehicle_objs = []
        if coi_type == "Lienholder":
            policy_vehicles = list(p.vehicles or [])
            if not policy_vehicles:
                st.warning("This policy has no vehicles to list as Loss Payee items.")
            veh_options = {_format_vehicle_option(v): v for v in policy_vehicles}
            selected_labels = st.multiselect(
                "Vehicles covered by Loss Payee clause",
                options=list(veh_options.keys()),
                key=f"coi_lien_vehicles_{p.id}",
            )
            selected_vehicle_objs = [veh_options[lbl] for lbl in selected_labels if lbl in veh_options]

        if "coi_companies" not in st.session_state:
            st.session_state.coi_companies = load_companies("data/Additionalinsuredcomps.xlsx")

        company_options = sorted(list(st.session_state.coi_companies.keys()))

        if not bulk_mode:
            company_options_single = ["None"] + company_options

            def on_company_select():
                selected = st.session_state.get("selected_coi_company")
                if selected and selected != "None":
                    comp_data = st.session_state.coi_companies.get(selected, {})
                    st.session_state["h_name"] = comp_data.get("name", "")
                    st.session_state["h_addr"] = comp_data.get("address", "")
                    st.session_state["h_city"] = comp_data.get("city", "")
                    st.session_state["h_state"] = comp_data.get("state", "")
                    st.session_state["h_zip"] = comp_data.get("zip", "")

            st.selectbox(
                "Quick Fill from Company List",
                options=company_options_single,
                key="selected_coi_company",
                on_change=on_company_select,
            )

            c1, c2 = st.columns(2)
            with c1:
                if "h_name" not in st.session_state:
                    st.session_state["h_name"] = ""
                if "h_addr" not in st.session_state:
                    st.session_state["h_addr"] = ""
                if "h_city" not in st.session_state:
                    st.session_state["h_city"] = ""

                h_name = st.text_input("Holder Name", key="h_name")
                h_addr = st.text_input("Address", key="h_addr")
                h_city = st.text_input("City", key="h_city")
            with c2:
                if "h_state" not in st.session_state:
                    st.session_state["h_state"] = ""
                if "h_zip" not in st.session_state:
                    st.session_state["h_zip"] = ""

                h_state = st.text_input("State", key="h_state")
                h_zip = st.text_input("Zip", key="h_zip")

                # Regenerate the default description whenever the COI type, selected
                # vehicles, or holder name changes. User edits inside the textarea are
                # preserved as long as those inputs stay the same.
                desc_key = f"coi_desc_area_{p.id}"
                desc_state_key = f"coi_desc_state_{p.id}"
                current_desc_state = (
                    coi_type,
                    tuple(v.id for v in selected_vehicle_objs),
                    st.session_state.get("h_name", "") or "",
                )
                if (
                    desc_key not in st.session_state
                    or st.session_state.get(desc_state_key) != current_desc_state
                ):
                    st.session_state[desc_key] = _build_default_desc(
                        coi_service,
                        p,
                        coi_type,
                        selected_vehicle_objs,
                        st.session_state.get("h_name", ""),
                    )
                    st.session_state[desc_state_key] = current_desc_state

                h_desc = st.text_area(
                    "Operations Description",
                    height=150,
                    key=desc_key,
                )
                h_desc_font_size = st.slider(
                    "Description Font Size (pt)",
                    min_value=4,
                    max_value=12,
                    value=8,
                    key="single_desc_font",
                )
        else:
            selected_companies = st.multiselect("Select Companies", options=company_options)

            # Bulk mode applies the same description to many holders, so use the
            # placeholder token; we substitute it per-company at generation time.
            bulk_desc_key = f"coi_desc_bulk_{p.id}"
            bulk_state_key = f"coi_desc_state_bulk_{p.id}"
            bulk_state = (coi_type, tuple(v.id for v in selected_vehicle_objs))
            if (
                bulk_desc_key not in st.session_state
                or st.session_state.get(bulk_state_key) != bulk_state
            ):
                st.session_state[bulk_desc_key] = _build_default_desc(
                    coi_service,
                    p,
                    coi_type,
                    selected_vehicle_objs,
                    holder_name="",
                )
                st.session_state[bulk_state_key] = bulk_state

            if coi_type == "Lienholder":
                st.caption(
                    f"Bulk Lienholder COIs replace `{LIENHOLDER_HOLDER_PLACEHOLDER}` "
                    "with each company's name when generating."
                )

            h_desc = st.text_area(
                "Operations Description (applied to all)",
                height=150,
                key=bulk_desc_key,
            )
            h_desc_font_size = st.slider(
                "Description Font Size (pt)",
                min_value=4,
                max_value=12,
                value=8,
                key="bulk_desc_font",
            )

            if selected_companies:
                st.info(f"Selected {len(selected_companies)} companies for bulk generation.")

        st.divider()
        st.subheader("Insured Details (Edit if needed)")

        ic1, ic2 = st.columns(2)
        with ic1:
            i_name = st.text_input("Insured Name", value=p.insured_name if p.insured_name else "")
            i_addr = st.text_input("Insured Address", value=p.insured_address if p.insured_address else "")
            i_city = st.text_input("Insured City", value=p.insured_city if p.insured_city else "")
        with ic2:
            i_state = st.text_input("Insured State", value=p.insured_state_code if p.insured_state_code else "")
            i_zip = st.text_input("Insured Zip", value=p.insured_zip if p.insured_zip else "")

            default_naic = p.naic_number if p.naic_number else get_naic_for_carrier(p.carrier_name)
            i_naic = st.text_input("Insurer NAIC #", value=default_naic)

        st.divider()
        st.subheader("🛡️ Coverages to Include")
        gc1, gc2, gc3 = st.columns(3)
        with gc1:
            ui_has_gl = st.checkbox(
                "General Liability",
                value=bool(p.has_general_liability),
            )
            gl_agg_key = f"coi_gl_gen_agg_{p.id}"
            if ui_has_gl:
                if gl_agg_key not in st.session_state:
                    st.session_state[gl_agg_key] = _default_gl_agg_display_value(p)
                st.radio(
                    "General aggregate",
                    options=GL_AGGREGATE_OPTIONS,
                    horizontal=True,
                    key=gl_agg_key,
                )
        with gc2:
            ui_has_auto = st.checkbox(
                "Automobile Liability",
                value=bool(p.has_auto_liability),
            )
        with gc3:
            cargo_disabled = coi_type == "Lienholder"
            ui_has_cargo = st.checkbox(
                "Motor Truck Cargo",
                value=bool(p.cargo_limit) and not cargo_disabled,
                disabled=cargo_disabled,
                help=(
                    "Disabled for Lienholder COIs — the Other Policy box is reused for Comp/Coll deductibles."
                    if cargo_disabled
                    else None
                ),
            )

        def prepare_p_data():
            gl_agg = None
            if ui_has_gl:
                gl_agg = st.session_state.get(
                    gl_agg_key, _default_gl_agg_display_value(p)
                )
            return {
                "carrier_name": p.carrier_name,
                "naic_number": i_naic,
                "policy_number": p.policy_number,
                "effective_date": p.effective_date,
                "expiration_date": p.expiration_date,
                "liability_limit": p.liability_limit,
                "gl_general_aggregate": gl_agg,
                "cargo_limit": p.cargo_limit,
                "cargo_deductible": p.cargo_deductible if p.cargo_deductible else "1000",
                "comp_deductible": p.comp_deductible,
                "coll_deductible": p.coll_deductible,
                "has_general_liability": ui_has_gl,
                "has_auto_liability": ui_has_auto,
                "has_cargo": ui_has_cargo and coi_type != "Lienholder",
                "coi_type": coi_type,
                "insured_name": i_name,
                "insured_address": i_addr,
                "insured_city": i_city,
                "insured_state_code": i_state,
                "insured_zip": i_zip,
                "vehicle_list_str": "",
                "driver_list_str": "",
            }

        if not bulk_mode:
            if st.button("Generate & Download PDF", type="primary"):
                if not h_name:
                    st.error("Holder Name is required.")
                elif coi_type == "Lienholder" and not selected_vehicle_objs:
                    st.error("Lienholder COIs require at least one selected vehicle.")
                else:
                    gen = COIGenerator()
                    p_data = prepare_p_data()
                    # Substitute the placeholder in case the user kept it after switching back to a holder.
                    final_desc = (h_desc or "").replace(LIENHOLDER_HOLDER_PLACEHOLDER, h_name or "")
                    h_data = {
                        "name": h_name,
                        "address": h_addr,
                        "city": h_city,
                        "state": h_state,
                        "zip": h_zip,
                        "description": final_desc,
                    }

                    try:
                        pdf = gen.generate_coi(p_data, h_data, desc_font_size=h_desc_font_size)
                        if pdf:
                            st.success("Successfully generated COI!")
                            st.download_button(
                                "📥 Download COI PDF",
                                data=pdf,
                                file_name=_safe_coi_pdf_filename(i_name, h_name),
                                mime="application/pdf",
                            )
                    except Exception as e:
                        st.error(f"Generation failed: {e}")
        else:
            if st.button("Generate Bulk COIs", type="primary"):
                if not selected_companies:
                    st.error("Please select at least one company.")
                elif coi_type == "Lienholder" and not selected_vehicle_objs:
                    st.error("Lienholder COIs require at least one selected vehicle.")
                else:
                    gen = COIGenerator()
                    p_data = prepare_p_data()

                    zip_buffer = io.BytesIO()
                    try:
                        with zipfile.ZipFile(zip_buffer, "w") as zf:
                            for comp_name in selected_companies:
                                comp_data = st.session_state.coi_companies.get(comp_name, {})
                                holder_name = comp_data.get("name", "")
                                # Substitute the holder placeholder per-company so each
                                # bulk-generated COI carries the correct name.
                                per_holder_desc = (h_desc or "").replace(
                                    LIENHOLDER_HOLDER_PLACEHOLDER, holder_name
                                )
                                h_data = {
                                    "name": holder_name,
                                    "address": comp_data.get("address", ""),
                                    "city": comp_data.get("city", ""),
                                    "state": comp_data.get("state", ""),
                                    "zip": comp_data.get("zip", ""),
                                    "description": per_holder_desc,
                                }
                                pdf = gen.generate_coi(p_data, h_data, desc_font_size=h_desc_font_size)
                                if pdf:
                                    zf.writestr(
                                        _safe_coi_pdf_filename(i_name, comp_data.get("name", "")),
                                        pdf,
                                    )

                        st.success(f"Successfully generated {len(selected_companies)} COIs!")
                        st.download_button(
                            "📥 Download All (ZIP)",
                            data=zip_buffer.getvalue(),
                            file_name=_safe_bulk_zip_filename(i_name),
                            mime="application/zip",
                        )
                    except Exception as e:
                        st.error(f"Bulk generation failed: {e}")
    finally:
        session.close()
