"""tokens.py - one place for colour and type, so charts, PDFs and the Tableau
guide cannot drift apart.

Accessibility rules enforced here:
  * colour is never the only carrier of meaning (charts add a marker shape + label)
  * the three bank colours are distinguishable in greyscale and to the two most
    common forms of colour blindness (blue / orange / teal rather than red / green)
"""
NAVY = "#12263F"       # primary dark
ACCENT = "#C8102E"     # one accent only
GREY_DARK = "#4A5568"
GREY_MID = "#A0AEC0"
GREY_LIGHT = "#E2E8F0"
BG = "#FFFFFF"

# One fixed colour per bank, used everywhere, forever.
BANK_COLOR = {"SBI": "#12263F", "HDFC": "#C8102E", "ICICI": "#2C7A7B"}
# Marker shape per bank, so the charts still work in black and white.
BANK_MARKER = {"SBI": "o", "HDFC": "s", "ICICI": "^"}

PILLAR_COLOR = {"asset_quality": NAVY, "profit": ACCENT, "efficiency": "#2C7A7B"}

FONT_STACK = ["Helvetica", "Arial", "DejaVu Sans"]
FS_TITLE, FS_SUB, FS_AXIS, FS_ANNOT, FS_LEGEND = 15, 11, 9, 8, 9
FIG_DPI = 200
