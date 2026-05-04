"""PDF Parser for ČS apartment (bytová jednotka) valuation forms.

Supports the form: "Zadané údaje pro on-line ocenění bytu"

Extracts key fields grouped into:
 - Žadatel (applicant)
 - Oceňovaný byt (valued apartment)
 - Informace o budově (building info)
 - Byt (apartment details)
"""
import io
import re
from dataclasses import dataclass, asdict
from typing import Optional

import pdfplumber


@dataclass
class ApartmentData:
    """Structured data extracted from the BJ valuation PDF."""
    # Žadatel
    jmeno_prijmeni: Optional[str] = None
    kupni_cena: Optional[str] = None
    # Oceňovaný byt
    list_vlastnictvi: Optional[str] = None
    katastral_uzemi: Optional[str] = None
    ulice: Optional[str] = None
    cislo_popisne_bytu: Optional[str] = None  # "1649 / 8"
    obec: Optional[str] = None
    psc: Optional[str] = None
    # Informace o budově
    rok_dokonceni_budovy: Optional[str] = None
    rok_rekonstrukce: Optional[str] = None
    konstrukce: Optional[str] = None        # Panelový, Cihlový, ...
    stav_budovy: Optional[str] = None
    vytah: Optional[str] = None             # ano / ne
    podlazi_jednotky: Optional[str] = None
    pocet_nadz_podlazi: Optional[str] = None
    pocet_podz_podlazi: Optional[str] = None
    typ_strechy: Optional[str] = None       # plochá, sedlová, ...
    obytne_podkrovi: Optional[str] = None   # ano / ne
    zatepleni: Optional[str] = None
    typ_oken: Optional[str] = None
    ohrev_vody: Optional[str] = None
    vetrani: Optional[str] = None
    rekuperace: Optional[str] = None
    solarni_panely: Optional[str] = None
    # Byt
    typ_jednotky: Optional[str] = None      # 1+1, 2+kk, ...
    pocet_garazi: Optional[str] = None
    typ_vytapeni: Optional[str] = None
    plocha_bytu: Optional[str] = None       # "33 m²"
    plocha_terasy: Optional[str] = None
    plocha_balkonu: Optional[str] = None
    plocha_sklepa: Optional[str] = None
    plocha_zahrady: Optional[str] = None
    stav_bytu: Optional[str] = None
    # Derived
    adresa: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def is_empty(self) -> bool:
        """Check if all fields are None/empty."""
        return all(v is None or v == "" for v in asdict(self).values())


# ── Known label fragments for truncation (same technique as RD parser) ──
_BJ_KNOWN_LABELS = [
    r"Rok\s+dokon[čc]en[ií]", r"Rok\s+rekonstrukce", r"Konstrukce",
    r"Stav\s+budovy", r"V[ýy]tah", r"Podla[žz][ií].*bytov",
    r"Po[čc]et\s+nadzemn", r"Po[čc]et\s+podzemn",
    r"Jakou?\s+m[áa]\s+budova\s+st[řr]echu", r"M[áa]\s+d[ůu]m\s+obytn",
    r"Je\s+budova\s+zateplen", r"Jak[áa]\s+m[áa]\s+budova\s+okna",
    r"Jak\s+se\s+v\s+budov", r"Jak\s+se\s+budova\s+v[ěe]tr",
    r"M[áa]\s+budova\s+rekuperac", r"M[áa]te\s+sol[áa]rn",
    r"Typ\s+jednotky", r"Po[čc]et\s+gar[áa][žz]", r"Typ\s+vyt[áa]p",
    r"Plocha\s+bytu", r"Plocha\s+terasy", r"Plocha\s+balkonu",
    r"Plocha\s+sklepa", r"Plocha\s+zahrady", r"Stav\s+bytu",
    r"Jm[ée]no", r"Kupn[ií]\s+cena", r"List\s+vlastnictv",
    r"Katastr[áa]ln[ií]", r"Ulice", r"[ČC][ií]slo\s+popisn",
    r"Obec", r"PS[ČC]", r"Jak\s+vyu[žz][ií]v", r"Kolik\s+m[áa]te",
    r"Jak\s+dlouho", r"V[ýy]kon\s+st[áa]vaj",
]

_BJ_LABEL_START_RE = re.compile(
    r"^(?:" + "|".join(_BJ_KNOWN_LABELS) + r")", re.IGNORECASE
)

_BJ_LABEL_BOUNDARY_RE = re.compile(
    r"\s+(?=" + "|".join(_BJ_KNOWN_LABELS) + r")", re.IGNORECASE
)


def _truncate_at_next_label(value: str) -> str:
    """Truncate a value string at the start of any known field label."""
    if _BJ_LABEL_START_RE.match(value):
        return ""
    m = _BJ_LABEL_BOUNDARY_RE.search(value)
    if m:
        return value[:m.start()].strip()
    return value


# ── Regex patterns for BJ fields ──
_BJ_PATTERNS = {
    "jmeno_prijmeni": [
        re.compile(r"Jm[ée]no\s+a\s+p[řr][ií]jmen[ií]\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "kupni_cena": [
        re.compile(r"Kupn[ií]\s+cena\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "list_vlastnictvi": [
        re.compile(r"List\s+vlastnictv[ií]\s*:?\s*(\S+)", re.IGNORECASE),
    ],
    "katastral_uzemi": [
        re.compile(r"Katastr[áa]ln[ií]\s+[úu]zem[ií]\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "cislo_popisne_bytu": [
        re.compile(r"[ČC][ií]slo\s+popisn[ée]\s*/\s*[čc][ií]slo\s+bytu\s*:?\s*(.+)", re.IGNORECASE),
        re.compile(r"[ČC][ií]slo\s+popisn[ée]\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "rok_dokonceni_budovy": [
        re.compile(r"Rok\s+dokon[čc]en[ií]\s+budovy[^:]*:?\s*(\d{4})", re.IGNORECASE),
        re.compile(r"Rok\s+dokon[čc]en[ií]\s*:?\s*(\d{4})", re.IGNORECASE),
    ],
    "rok_rekonstrukce": [
        re.compile(r"Rok\s+rekonstrukce[^:]*:?\s*(.+)", re.IGNORECASE),
    ],
    "konstrukce": [
        re.compile(r"Konstrukce\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "stav_budovy": [
        re.compile(r"Stav\s+budovy\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "vytah": [
        re.compile(r"V[ýy]tah\s*:?\s*(ano|ne|ANO|NE|Ano|Ne)", re.IGNORECASE),
    ],
    "podlazi_jednotky": [
        re.compile(r"Podla[žz][ií].*bytov[áa]\s+jednotka\s*:?\s*(\d+)", re.IGNORECASE),
        re.compile(r"Podla[žz][ií].*je\s+bytov[áa]\s*:?\s*(\d+)", re.IGNORECASE),
        re.compile(r"Podla[žz][ií].*kter[ée]m.*byt\s*:?\s*(\d+)", re.IGNORECASE),
    ],
    "pocet_nadz_podlazi": [
        re.compile(r"Po[čc]et\s+nadzemn[ií]ch\s+podla[žz][ií]\s+budovy\s*:?\s*(\d+)", re.IGNORECASE),
        re.compile(r"Po[čc]et\s+nadzemn[ií]ch\s+podla[žz][ií]\s*:?\s*(\d+)", re.IGNORECASE),
    ],
    "pocet_podz_podlazi": [
        re.compile(r"Po[čc]et\s+podzemn[ií]ch\s+podla[žz][ií]\s*:?\s*(\d+)", re.IGNORECASE),
    ],
    "typ_strechy": [
        re.compile(r"Jakou?\s+m[áa]\s+budova\s+st[řr]echu\??\s*:?\s*(.+)", re.IGNORECASE),
        re.compile(r"Typ\s+st[řr]echy\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "obytne_podkrovi": [
        re.compile(r"M[áa]\s+d[ůu]m\s+obytn[ée]\s+podkrov[ií]\??\s*:?\s*(ano|ne|ANO|NE|Ano|Ne)", re.IGNORECASE),
        re.compile(r"Obytn[ée]\s+podkrov[ií]\s*:?\s*(ano|ne|ANO|NE|Ano|Ne)", re.IGNORECASE),
    ],
    "zatepleni": [
        re.compile(r"Je\s+budova\s+zateplen[áa]\??\s*:?\s*(.+)", re.IGNORECASE),
        re.compile(r"Zateplen[ií]\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "typ_oken": [
        re.compile(r"Jak[áa]\s+m[áa]\s+budova\s+okna\??\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "ohrev_vody": [
        re.compile(r"Jak\s+se\s+v\s+budov[ěe]\s+oh[řr][ií]v[áa]\s+voda\??\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "vetrani": [
        re.compile(r"Jak\s+se\s+budova\s+v[ěe]tr[áa]\??\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "rekuperace": [
        re.compile(r"M[áa]\s+budova\s+rekuperac[ií]\s*.*\??\s*:?\s*(ano|ne|ANO|NE|Ano|Ne)", re.IGNORECASE),
    ],
    "solarni_panely": [
        re.compile(r"M[áa]te\s+sol[áa]rn[ií]\s+nebo\s+fotovoltaick[ée]\s+panely\??\s*:?\s*(ano|ne|ANO|NE|Ano|Ne)", re.IGNORECASE),
    ],
    "typ_jednotky": [
        re.compile(r"Typ\s+jednotky\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "pocet_garazi": [
        re.compile(r"Po[čc]et\s+gar[áa][žz][ií]/st[áa]n[ií]\s*:?\s*(\d+)", re.IGNORECASE),
        re.compile(r"Po[čc]et\s+gar[áa][žz][ií]\s*:?\s*(\d+)", re.IGNORECASE),
    ],
    "typ_vytapeni": [
        re.compile(r"Typ\s+vyt[áa]p[ěe]n[ií]\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "plocha_bytu": [
        re.compile(r"Plocha\s+bytu\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "plocha_terasy": [
        re.compile(r"Plocha\s+terasy\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "plocha_balkonu": [
        re.compile(r"Plocha\s+balkonu\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "plocha_sklepa": [
        re.compile(r"Plocha\s+sklepa/skladu\s*:?\s*(.+)", re.IGNORECASE),
        re.compile(r"Plocha\s+sklepa\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "plocha_zahrady": [
        re.compile(r"Plocha\s+zahrady\s*:?\s*(.+)", re.IGNORECASE),
    ],
    "stav_bytu": [
        re.compile(r"Stav\s+bytu\s*:?\s*(.+)", re.IGNORECASE),
    ],
}

# Table label map – Czech labels to dataclass field names
_BJ_TABLE_LABEL_MAP = {
    "jméno a příjmení": "jmeno_prijmeni",
    "kupní cena": "kupni_cena",
    "list vlastnictví": "list_vlastnictvi",
    "katastrální území": "katastral_uzemi",
    "ulice": "ulice",
    "číslo popisné / číslo bytu": "cislo_popisne_bytu",
    "číslo popisné": "cislo_popisne_bytu",
    "obec": "obec",
    "psč": "psc",
    "rok dokončení budovy (není-li znám rok, je uvedeno desetiletí)": "rok_dokonceni_budovy",
    "rok dokončení budovy": "rok_dokonceni_budovy",
    "rok dokončení": "rok_dokonceni_budovy",
    "rok rekonstrukce / rozsah (není-li znám rok, je uvedeno desetiletí)": "rok_rekonstrukce",
    "rok rekonstrukce": "rok_rekonstrukce",
    "konstrukce": "konstrukce",
    "stav budovy": "stav_budovy",
    "výtah": "vytah",
    "podlaží, ve kterém je bytová jednotka": "podlazi_jednotky",
    "počet nadzemních podlaží budovy": "pocet_nadz_podlazi",
    "počet nadzemních podlaží": "pocet_nadz_podlazi",
    "počet podzemních podlaží budovy": "pocet_podz_podlazi",
    "počet podzemních podlaží": "pocet_podz_podlazi",
    "jakou má budova střechu?": "typ_strechy",
    "typ střechy": "typ_strechy",
    "má dům obytné podkroví?": "obytne_podkrovi",
    "obytné podkroví": "obytne_podkrovi",
    "je budova zateplená?": "zatepleni",
    "zateplení": "zatepleni",
    "jaká má budova okna?": "typ_oken",
    "jak se v budově ohřívá voda?": "ohrev_vody",
    "ohřev vody": "ohrev_vody",
    "jak se budova větrá?": "vetrani",
    "větrání": "vetrani",
    "má budova rekuperaci pro ohřev teplé vody?": "rekuperace",
    "rekuperace": "rekuperace",
    "máte solární nebo fotovoltaické panely?": "solarni_panely",
    "typ jednotky": "typ_jednotky",
    "počet garáží/stání": "pocet_garazi",
    "typ vytápění": "typ_vytapeni",
    "plocha bytu": "plocha_bytu",
    "plocha terasy": "plocha_terasy",
    "plocha balkonu": "plocha_balkonu",
    "plocha sklepa/skladu": "plocha_sklepa",
    "plocha sklepa": "plocha_sklepa",
    "plocha zahrady": "plocha_zahrady",
    "stav bytu": "stav_bytu",
}

# Address part patterns
_BJ_ADDRESS_PARTS = {
    "ulice": re.compile(r"Ulice\s*:?\s*(.+)", re.IGNORECASE),
    "cislo_popisne": re.compile(r"[ČC][ií]slo\s+popisn[ée]\s*:?\s*(\S+)", re.IGNORECASE),
    "obec": re.compile(r"Obec\s*:?\s*(.+)", re.IGNORECASE),
    "psc": re.compile(r"PS[ČC]\s*:?\s*(\d+)", re.IGNORECASE),
}


def is_bj_pdf(text: str) -> bool:
    """Detect if a PDF is a BJ (apartment) valuation form rather than RD."""
    bj_indicators = [
        "ocenění bytu",
        "oceňovaný byt",
        "bytová jednotka",
        "typ jednotky",
        "plocha bytu",
        "podlaží, ve kterém je bytová jednotka",
        "stav bytu",
    ]
    text_lower = text.lower()
    matches = sum(1 for ind in bj_indicators if ind in text_lower)
    return matches >= 2


def parse_bj_pdf(pdf_bytes: bytes) -> ApartmentData:
    """Parse a BJ valuation PDF and extract key fields.

    Supports the ČS "Zadané údaje pro on-line ocenění bytu" form layout.
    Uses table extraction (primary) + regex fallback.
    """
    data = ApartmentData()

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        full_text = ""

        # ── Primary: table-based extraction ──
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"

            tables = page.extract_tables()
            if not tables:
                tables = page.extract_tables(
                    table_settings={"vertical_strategy": "text", "horizontal_strategy": "text"}
                )
            for table in tables:
                for row in table:
                    if not row:
                        continue
                    cells = [
                        re.sub(r"\s+", " ", (c or "")).strip()
                        for c in row
                    ]

                    # Process pairs: (label, value)
                    i = 0
                    while i < len(cells) - 1:
                        label = cells[i].lower().rstrip(":").rstrip("?").strip()
                        value = cells[i + 1].strip()

                        if label and value:
                            field_name = _BJ_TABLE_LABEL_MAP.get(label)
                            if field_name and not getattr(data, field_name, None):
                                setattr(data, field_name, value)

                        i += 2

    if not full_text.strip():
        return data

    # ── Fallback: regex-based extraction ──
    lines = full_text.split("\n")
    cleaned_lines = []
    for line in lines:
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            cleaned_lines.append(cleaned)

    full_cleaned = "\n".join(cleaned_lines)

    for field_name, patterns in _BJ_PATTERNS.items():
        if getattr(data, field_name, None):
            continue
        for pattern in patterns:
            match = pattern.search(full_cleaned)
            if match:
                value = match.group(1).strip()
                value = re.sub(r"\s+$", "", value)
                value = _truncate_at_next_label(value)
                if value:
                    setattr(data, field_name, value)
                    break

    # ── Post-processing ──

    # Extract year from rok_dokonceni_budovy
    if data.rok_dokonceni_budovy:
        year_match = re.search(r"(\d{4})", data.rok_dokonceni_budovy)
        if year_match:
            data.rok_dokonceni_budovy = year_match.group(1)

    # Normalize ANO/NE fields
    for field in ["vytah", "obytne_podkrovi", "rekuperace", "solarni_panely"]:
        val = getattr(data, field, None)
        if val:
            setattr(data, field, val.lower())

    # Compose address from separate fields
    if not data.adresa:
        parts = {}
        for part_name, pattern in _BJ_ADDRESS_PARTS.items():
            match = pattern.search(full_cleaned)
            if match:
                val = _truncate_at_next_label(match.group(1).strip())
                if val:
                    parts[part_name] = val

        # Also use already extracted fields
        if not parts.get("ulice") and data.ulice:
            parts["ulice"] = data.ulice
        if not parts.get("obec") and data.obec:
            parts["obec"] = data.obec
        if not parts.get("psc") and data.psc:
            parts["psc"] = data.psc

        if parts:
            addr_parts = []
            street = parts.get("ulice", "")
            cislo = data.cislo_popisne_bytu or parts.get("cislo_popisne", "")
            if street:
                addr_parts.append(f"{street} {cislo}".strip() if cislo else street)
            elif cislo:
                addr_parts.append(cislo)

            psc = parts.get("psc", "")
            obec = parts.get("obec", "")
            if psc and obec:
                addr_parts.append(f"{psc} {obec}")
            elif obec:
                addr_parts.append(obec)
            elif psc:
                addr_parts.append(psc)

            if addr_parts:
                data.adresa = ", ".join(addr_parts)

    return data
