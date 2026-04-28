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
            for suffix in ("coi_desc_area_", "coi_desc_bulk_"):
                old_desc = f"{suffix}{prev_id}"
                if old_desc in st.session_state:
                    del st.session_state[old_desc]
            old_agg = f"coi_gl_gen_agg_{prev_id}"
            if old_agg in st.session_state:
                del st.session_state[old_agg]
        st.session_state["coi_last_policy_id"] = p.id

        st.info(f"Filling COI for: **{p.insured_name}** ({p.policy_number})")

        st.subheader("Certificate Holder Details")

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

                _, desc_lines = coi_service.prepare_coi_data(p)
                desc_lines.append("Radius of Operation: Unlimited")
                desc_lines.append("Certificate Holder is also listed as an additional insured")
                default_desc = "\n".join(desc_lines)

                desc_key = f"coi_desc_area_{p.id}"
                if desc_key not in st.session_state:
                    st.session_state[desc_key] = default_desc

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

            _, desc_lines = coi_service.prepare_coi_data(p)
            desc_lines.append("Radius of Operation: Unlimited")
            desc_lines.append("Certificate Holder is also listed as an additional insured")
            default_desc = "\n".join(desc_lines)

            bulk_desc_key = f"coi_desc_bulk_{p.id}"
            if bulk_desc_key not in st.session_state:
                st.session_state[bulk_desc_key] = default_desc

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
                value=p.has_general_liability if p.has_general_liability is not None else True,
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
                value=p.has_auto_liability if p.has_auto_liability is not None else True,
            )
        with gc3:
            ui_has_cargo = st.checkbox("Motor Truck Cargo", value=bool(p.cargo_limit))

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
                "has_general_liability": ui_has_gl,
                "has_auto_liability": ui_has_auto,
                "has_cargo": ui_has_cargo,
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
                else:
                    gen = COIGenerator()
                    p_data = prepare_p_data()
                    h_data = {
                        "name": h_name,
                        "address": h_addr,
                        "city": h_city,
                        "state": h_state,
                        "zip": h_zip,
                        "description": h_desc,
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
                else:
                    gen = COIGenerator()
                    p_data = prepare_p_data()

                    zip_buffer = io.BytesIO()
                    try:
                        with zipfile.ZipFile(zip_buffer, "w") as zf:
                            for comp_name in selected_companies:
                                comp_data = st.session_state.coi_companies.get(comp_name, {})
                                h_data = {
                                    "name": comp_data.get("name", ""),
                                    "address": comp_data.get("address", ""),
                                    "city": comp_data.get("city", ""),
                                    "state": comp_data.get("state", ""),
                                    "zip": comp_data.get("zip", ""),
                                    "description": h_desc,
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
