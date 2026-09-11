import re

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Phone numbers reach this system from two sides of the market: candidates are
# mostly Moroccan (+212, or the local 0-prefixed form), while the client
# companies are Dutch-speaking (+31 Netherlands, +32 Belgium) and some CVs carry
# a French number (+33). A generic +CC branch accepts any other country rather
# than silently dropping the field; the digit-count check in cv_parser.py is what
# guards against a false positive being stored.
PHONE_RE = re.compile(
    r"""
    (?<![\w/])                          # not glued to a word or a date separator
    (?:
        \+\s?\d{1,3}                    # international prefix: +212, +31, +32, +33...
        (?:[\s.\-()]*\d){7,13}          # 8 to 14 digits total, separators allowed
      |
        0                               # local form: leading 0 (e.g. 0612345678)
        (?:[\s.\-()]*\d){8,12}          # 9 to 13 digits total
    )
    (?!\d)                              # not truncating a longer number
    """,
    re.VERBOSE,
)

# Country prefixes relevant to this project, used to normalise the local form.
LOCAL_TO_INTERNATIONAL = "+212"  # a leading 0 in this corpus means Morocco


def find_email(text: str) -> str | None:
    m = EMAIL_RE.search(text)
    return m.group(0) if m else None


def find_phone(text: str, normalize: bool = False) -> str | None:
    """Find the first plausible phone number and strip its separators.

    With normalize=True, a Moroccan local number (leading 0) is rewritten in
    international form, so the same person written '0612...' on one CV and
    '+212612...' on another produces a single comparable value.
    """
    m = PHONE_RE.search(text)
    if not m:
        return None

    number = re.sub(r"[\s.\-()]", "", m.group(0))

    if normalize and number.startswith("0"):
        number = LOCAL_TO_INTERNATIONAL + number[1:]

    return number
