"""Sponsor repository, validation, and browser-carousel behavior."""
from dataclasses import replace

import pytest

from split_tracker.repository import InMemoryRaceRepository, RepositoryError, SchoolSponsor
from split_tracker.sponsors import safe_sponsor_website, sponsor_carousel_html, validate_sponsor_logo


def sponsor(name, school="school", order=0, active=True, logo="logo.png", url=""):
    return SchoolSponsor(school_profile_id=school, name=name, logo_path=logo, logo_url=f"https://cdn/{logo}" if logo else "", website_url=url, display_order=order, is_active=active)


def test_sponsor_repository_crud_filter_sort_and_deactivate():
    repo = InMemoryRaceRepository()
    later = repo.create_sponsor(sponsor("Zulu", order=2))
    first_b = repo.create_sponsor(sponsor("Beta", order=1))
    first_a = repo.create_sponsor(sponsor("Alpha", order=1))
    other = repo.create_sponsor(sponsor("Other", school="other", order=0))

    assert [item.name for item in repo.list_sponsors("school")] == ["Alpha", "Beta", "Zulu"]
    assert repo.get_sponsor(later.id) == later
    repo.update_sponsor(replace(first_b, website_url="https://example.com", is_active=False))
    assert [item.name for item in repo.list_active_sponsors("school")] == ["Alpha", "Zulu"]
    assert repo.get_sponsor(first_b.id).website_url == "https://example.com"
    assert repo.delete_sponsor(first_a.id)
    assert repo.get_sponsor(first_a.id) is None
    assert repo.get_sponsor(other.id).school_profile_id == "other"


def test_sponsor_repository_rejects_invalid_required_fields():
    repo = InMemoryRaceRepository()
    with pytest.raises(RepositoryError): repo.create_sponsor(sponsor(" "))
    with pytest.raises(RepositoryError): repo.create_sponsor(sponsor("Name", logo=""))
    with pytest.raises(RepositoryError): repo.create_sponsor(sponsor("Name", order=-1))


def test_logo_mime_validation_accepts_png_jpeg_webp():
    assert validate_sponsor_logo("logo.png", "image/png", 10) == (".png", None)
    assert validate_sponsor_logo("logo.jpg", "image/jpeg", 10) == (".jpg", None)
    assert validate_sponsor_logo("logo.webp", "image/webp", 10) == (".webp", None)
    assert validate_sponsor_logo("logo.png", "image/jpeg", 10)[1]


def test_carousel_empty_one_multiple_and_safe_links():
    assert sponsor_carousel_html([]) == ""
    one = sponsor_carousel_html([sponsor("One & <Co>", url="https://example.com")])
    assert "One &amp; &lt;Co&gt;" in one and "noopener noreferrer" in one
    assert "setInterval" not in one and 'alt="One &amp; &lt;Co&gt; sponsor logo"' in one
    multiple = sponsor_carousel_html([sponsor("One"), sponsor("Two")])
    assert "setInterval" in multiple and "6000" in multiple
    assert "prefers-reduced-motion" in multiple and "object-fit:contain" in multiple


def test_carousel_skips_missing_logo_and_rejects_unsafe_website():
    html = sponsor_carousel_html([
        sponsor("Broken", logo=""),
        sponsor('Unsafe <script>', url="javascript:alert(1)"),
        sponsor("No website"),
    ])
    assert "Broken" not in html and "javascript:" not in html
    assert "Unsafe &lt;script&gt;" in html and "No website" in html
    assert safe_sponsor_website("data:text/plain,bad") is None
    assert safe_sponsor_website("https://safe.example/path") == "https://safe.example/path"


def test_carousel_has_no_streamlit_or_server_rotation_primitives():
    source = open("split_tracker/sponsors.py", encoding="utf-8").read()
    for forbidden in ("time.sleep", "st.rerun", "experimental_rerun", "autorefresh"):
        assert forbidden not in source
    assert "window.setInterval" in source
    page = open("pages/spectator.py", encoding="utf-8").read()
    assert page.index("_render_race = st.fragment(run_every=5)") < page.index("def render()")
    assert page.index("_render_race(", page.index("def render()")) < page.index(
        "_render_sponsors(public_repository)", page.index("def render()")
    )
