"""Sponsor validation and isolated browser-carousel rendering helpers."""
from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import urlparse

SPONSOR_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
MAX_SPONSOR_LOGO_BYTES = 5 * 1024 * 1024


def validate_sponsor_logo(name: str, mime_type: str, size: int) -> tuple[str | None, str | None]:
    suffix = Path(name).suffix.lower()
    if SPONSOR_MIME_TYPES.get(suffix) != mime_type:
        return None, "Upload a PNG, JPG, JPEG, or WebP image with a matching file type."
    if size > MAX_SPONSOR_LOGO_BYTES:
        return None, "Sponsor logo must be 5 MB or smaller."
    return suffix, None


def safe_sponsor_website(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    return text if parsed.scheme in {"http", "https"} and bool(parsed.netloc) else None


def sponsor_carousel_html(sponsors: list[object], *, interval_ms: int = 6000) -> str:
    """Return a self-contained component; rotation occurs only in its browser iframe."""
    usable = [item for item in sponsors if getattr(item, "logo_url", "") and getattr(item, "name", "").strip()]
    if not usable:
        return ""
    slides = []
    for index, sponsor in enumerate(usable):
        name = escape(sponsor.name.strip())
        logo = escape(sponsor.logo_url, quote=True)
        website = safe_sponsor_website(getattr(sponsor, "website_url", None))
        image = f'<img src="{logo}" alt="{name} sponsor logo" loading="lazy">'
        if website:
            image = f'<a href="{escape(website, quote=True)}" target="_blank" rel="noopener noreferrer">{image}</a>'
        slides.append(
            f'<section class="slide{" active" if index == 0 else ""}">{image}<div class="name">{name}</div></section>'
        )
    script = ""
    if len(slides) > 1:
        script = f"""<script>
        (() => {{ const slides=[...document.querySelectorAll('.slide')]; let current=0;
          window.setInterval(() => {{ slides[current].classList.remove('active'); current=(current+1)%slides.length; slides[current].classList.add('active'); }}, {interval_ms});
        }})();
        </script>"""
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
      *{{box-sizing:border-box}} body{{margin:0;font-family:Arial,sans-serif;color:#243447}}
      .wrap{{border-top:1px solid #ddd;border-bottom:1px solid #ddd;height:190px;text-align:center;padding:12px 8px}}
      .label{{font-size:13px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;margin-bottom:7px}}
      .stage{{position:relative;height:142px}} .slide{{position:absolute;inset:0;opacity:0;visibility:hidden;transition:opacity .6s ease}}
      .slide.active{{opacity:1;visibility:visible}} img{{display:block;max-width:min(340px,90vw);max-height:110px;width:auto;height:auto;object-fit:contain;margin:0 auto 5px}}
      .name{{font-size:14px;font-weight:700}} @media(max-width:430px){{.wrap{{height:160px}}.stage{{height:112px}}img{{max-height:82px}}}}
      @media(prefers-reduced-motion:reduce){{.slide{{transition:none}}}}
    </style></head><body><div class="wrap"><div class="label">Race supported by</div><div class="stage">{''.join(slides)}</div></div>{script}</body></html>"""
