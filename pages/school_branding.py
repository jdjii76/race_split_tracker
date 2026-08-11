"""Administrator-only School & Branding settings."""
from __future__ import annotations
from dataclasses import replace
import streamlit as st
from split_tracker.auth import AuthenticationError, require_admin
from split_tracker.branding import DEFAULT_SCHOOL_PROFILE, SchoolProfile, render_school_header, validate_logo_upload, validate_profile
from split_tracker.branding_service import save_profile
from split_tracker.repository import RepositoryError

STYLE_LABELS = {"Standard banner": "standard", "Logo left": "logo_left", "Compact": "compact", "Text only": "text_only"}


def _uploaded_asset(repository, upload, kind: str) -> str:
    suffix, error = validate_logo_upload(upload.name, upload.type, upload.size)
    if error:
        raise ValueError(error)
    object_path = f"schools/default/{'logo' if kind == 'logo' else 'icon'}{suffix}"
    return repository.upload_branding_asset(object_path, upload.getvalue(), upload.type)


def _draft_profile(current: SchoolProfile) -> tuple[SchoolProfile, object | None, object | None, bool, bool]:
    c1, c2 = st.columns(2)
    school_name = c1.text_input("School name", current.school_name)
    short_name = c2.text_input("Short name", current.short_name)
    program_name = c1.text_input("Program name", current.program_name)
    mascot = c2.text_input("Mascot", current.mascot)
    city = c1.text_input("City", current.city)
    state = c2.text_input("State", current.state)
    app_title = st.text_input("App title", current.app_title)
    colors = st.columns(4)
    primary = colors[0].color_picker("Primary", current.primary_color)
    secondary = colors[1].color_picker("Secondary", current.secondary_color)
    accent = colors[2].color_picker("Accent", current.accent_color)
    text = colors[3].color_picker("Header text", current.text_on_primary)
    selected_label = st.selectbox("Header style", list(STYLE_LABELS), index=list(STYLE_LABELS.values()).index(current.header_style))
    show_dashboard = st.checkbox("Show logo on dashboard", current.show_logo_on_dashboard)
    show_timing = st.checkbox("Show compact logo on timing page", current.show_logo_on_timing)
    export_branding = st.checkbox("Include school branding on exports", current.include_branding_on_exports)
    full_upload = st.file_uploader("Full school logo", type=["png", "jpg", "jpeg"], key="branding_logo_upload")
    compact_upload = st.file_uploader("Compact school icon", type=["png", "jpg", "jpeg"], key="branding_icon_upload")
    remove_logo = st.checkbox("Remove custom full logo reference")
    remove_icon = st.checkbox("Remove custom compact icon reference")
    draft = SchoolProfile(
        school_name=school_name, short_name=short_name, program_name=program_name, mascot=mascot,
        city=city, state=state, app_title=app_title, primary_color=primary, secondary_color=secondary,
        accent_color=accent, text_on_primary=text, logo_path=None if remove_logo else current.logo_path,
        compact_logo_path=None if remove_icon else current.compact_logo_path, header_style=STYLE_LABELS[selected_label],
        show_logo_on_dashboard=show_dashboard, show_logo_on_timing=show_timing,
        include_branding_on_exports=export_branding,
    )
    return draft, full_upload, compact_upload, remove_logo, remove_icon


def render() -> None:
    try:
        require_admin(st.session_state.get("app_identity"))
    except AuthenticationError as exc:
        st.error(str(exc))
        return
    profile = st.session_state.get("school_profile_stored", st.session_state.school_profile)
    render_school_header(profile, "School & Branding Settings")
    repository = st.session_state.repository
    if repository is None:
        st.error("Branding cannot be saved while persistent storage is unavailable. Race-day features remain available.")
        return
    draft, full_upload, compact_upload, _, _ = _draft_profile(profile)
    errors, warnings = validate_profile(draft)
    for message in errors:
        st.error(message)
    for message in warnings:
        st.warning(message)
    st.subheader("Branding Preview")
    render_school_header(draft, "Current Meet", subtitle="Example Invitational")
    render_school_header(draft, "Boys Varsity 5K", subtitle="Example Invitational • Ready", compact=True)
    with st.container(border=True):
        st.write("**Boys Varsity 5K**")
        st.caption("12 athletes • Ready")
        st.button("Start Timing", type="primary", disabled=True, key="branding_preview_action")
    for label, upload in (("Full logo preview", full_upload), ("Compact icon preview", compact_upload)):
        if upload is not None:
            _, upload_error = validate_logo_upload(upload.name, upload.type, upload.size)
            if upload_error:
                st.error(upload_error)
            else:
                st.caption(label)
                st.image(upload.getvalue(), width=140)
    save_col, reset_col, defaults_col = st.columns(3)
    if save_col.button("Save Changes", type="primary", disabled=bool(errors), use_container_width=True):
        try:
            for upload in (full_upload, compact_upload):
                if upload is not None:
                    _, upload_error = validate_logo_upload(upload.name, upload.type, upload.size)
                    if upload_error:
                        raise ValueError(upload_error)
            saved_draft = draft
            if full_upload is not None:
                saved_draft = replace(saved_draft, logo_path=_uploaded_asset(repository, full_upload, "logo"))
            if compact_upload is not None:
                saved_draft = replace(saved_draft, compact_logo_path=_uploaded_asset(repository, compact_upload, "icon"))
            save_profile(st.session_state, repository, saved_draft)
            st.session_state.branding_flash = "School branding saved."
            st.rerun()
        except (RepositoryError, ValueError) as exc:
            st.error(str(exc))
    if reset_col.button("Reset Unsaved Changes", use_container_width=True):
        st.rerun()
    confirm = defaults_col.checkbox("Confirm restore KMHS defaults")
    retain = defaults_col.checkbox("Retain uploaded logo references")
    if defaults_col.button("Restore KMHS Defaults", disabled=not confirm, use_container_width=True):
        try:
            defaults = replace(DEFAULT_SCHOOL_PROFILE, logo_path=profile.logo_path, compact_logo_path=profile.compact_logo_path) if retain else DEFAULT_SCHOOL_PROFILE
            save_profile(st.session_state, repository, defaults)
            st.session_state.branding_flash = "KMHS defaults restored. Uploaded storage objects were not deleted."
            st.rerun()
        except RepositoryError as exc:
            st.error(str(exc))
