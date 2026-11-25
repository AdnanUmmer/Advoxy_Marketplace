"""
Brand configuration: the ONE place for name, logo, fonts and contact details.

Colors and font stacks live in the matching theme file: static/brand/theme.css.
To rebrand: edit this file, edit static/brand/theme.css, replace the files in static/brand/.
"""

BRAND = {
    "name": "Advoxy",
    "tagline": "Homes across Africa, thoughtfully listed.",
    "logo": "brand/logo.svg",          # path under static/
    "logo_mark": "brand/mark.svg",     # square mark, used for favicon and compact headers
    "favicon": "brand/mark.svg",
    # Web fonts. Family names must match --brand-font-* in theme.css.
    "fonts_url": (
        "https://fonts.googleapis.com/css2?"
        "family=Fraunces:opsz,wght@9..144,300..600&"
        "family=Instrument+Sans:wght@400..600&display=swap"
    ),
    "support_email": "hello@example.com",
    "legal_name": "Advoxy Ltd.",
}
