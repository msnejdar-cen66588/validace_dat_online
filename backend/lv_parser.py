"""Parser for List Vlastnictví (LV) – property ownership certificate from Czech cadastre.

Extracts structured data from LV PDF:
- Header: kat. území, LV number, okres, obec
- Section A: owners (name, address, identifier, share)
- Section B: parcels (number, area, type) and buildings
- Section B1: rights in favor
- Section C: encumbrances (liens, easements, alienation bans)
- Section D: notes + seals (plomby)
"""
import io
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

import pdfplumber


@dataclass
class LVOwner:
    """Owner entry from section A."""
    name: str = ""
    address: str = ""
    identifier: str = ""  # RČ/IČO
    share: str = ""  # e.g. "1/2"


@dataclass
class LVParcel:
    """Parcel entry from section B."""
    parcel_number: str = ""  # e.g. "1951/12"
    area_m2: int = 0  # výměra v m²
    land_type: str = ""  # druh pozemku (zastavěná plocha, zahrada, ...)
    land_use: str = ""  # způsob využití
    protection: str = ""  # způsob ochrany
    selected: bool = True  # user can toggle in UI


@dataclass
class LVBuilding:
    """Building entry from section B."""
    part_of: str = ""  # "Součástí je stavba: Oslavany, č.p. 425, rod.dům"
    on_parcel: str = ""  # "Stavba stojí na pozemku p.č.: 1953"


@dataclass
class LVEncumbrance:
    """Entry from section C – liens, easements, bans."""
    type: str = ""  # "zástavní právo smluvní", "zákaz zcizení", "věcné břemeno"
    description: str = ""  # full text description
    beneficiary: str = ""  # oprávněný
    parcels: list[str] = field(default_factory=list)  # affected parcels
    amount: str = ""  # e.g. "5.540.000,00 Kč"
    document: str = ""  # listina reference


@dataclass
class LVAcquisitionTitle:
    """Entry from section E – Nabývací tituly (historical transactions)."""
    type: str = ""              # "Kupní smlouva", "Darovací smlouva", etc.
    date: str = ""              # e.g. "15.03.2018"
    price_czk: int = 0          # Extracted price if available
    description: str = ""       # Full text
    legal_effect: str = ""      # "právní účinky vkladu od ..."


@dataclass
class LVData:
    """Full parsed LV data."""
    # Header
    kat_uzemi_kod: str = ""  # e.g. "713180"
    kat_uzemi_nazev: str = ""  # e.g. "Oslavany"
    lv_number: str = ""  # e.g. "1606"
    okres: str = ""  # e.g. "CZ0643 Brno-venkov"
    obec: str = ""  # e.g. "583588 Oslavany"

    # Sections
    owners: list[LVOwner] = field(default_factory=list)
    parcels: list[LVParcel] = field(default_factory=list)
    buildings: list[LVBuilding] = field(default_factory=list)
    rights_in_favor: str = ""  # Section B1 text
    encumbrances: list[LVEncumbrance] = field(default_factory=list)
    notes: str = ""  # Section D
    seals: str = ""  # Plomby
    acquisition_titles: list[LVAcquisitionTitle] = field(default_factory=list)  # Section E

    def to_dict(self) -> dict:
        return asdict(self)

    def is_empty(self) -> bool:
        return not self.kat_uzemi_kod and not self.parcels


def parse_lv(pdf_bytes: bytes) -> LVData:
    """Parse a List Vlastnictví PDF and return structured data."""
    data = LVData()
    full_text = ""

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n"

    if not full_text.strip():
        return data

    # ── Header parsing ──
    # "Kat.území: 713180 Oslavany"
    m = re.search(r"Kat\.?\s*[úu]zem[ií]\s*:?\s*(\d+)\s+(\S+)", full_text, re.IGNORECASE)
    if m:
        data.kat_uzemi_kod = m.group(1)
        data.kat_uzemi_nazev = m.group(2)

    # "List vlastnictví: 1606"
    m = re.search(r"List\s+vlastnictv[ií]\s*:?\s*(\d+)", full_text, re.IGNORECASE)
    if m:
        data.lv_number = m.group(1)

    # "Okres: CZ0643 Brno-venkov"
    m = re.search(r"Okres\s*:?\s*(.+?)(?:\s{2,}|$)", full_text, re.IGNORECASE | re.MULTILINE)
    if m:
        data.okres = m.group(1).strip()

    # "Obec: 583588 Oslavany"
    m = re.search(r"Obec\s*:?\s*(.+?)(?:\s{2,}|$)", full_text, re.IGNORECASE | re.MULTILINE)
    if m:
        data.obec = m.group(1).strip()

    # ── Section A: Owners ──
    owners_section = _extract_section(full_text, r"A\s+Vlastn[ií]k", r"B\s+Nemovitosti")
    if owners_section:
        # Pattern: "Name, Address    Identifier    Share"
        owner_lines = re.findall(
            r"([A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+(?:\s+[A-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ][a-záčďéěíňóřšťúůýž]+)*(?:,\s*[^\n]+?))\s+(\d{6}/\d{4})\s+(\d+/\d+)",
            owners_section, re.IGNORECASE
        )
        for name_addr, ident, share in owner_lines:
            parts = name_addr.split(",", 1)
            owner = LVOwner(
                name=parts[0].strip(),
                address=parts[1].strip() if len(parts) > 1 else "",
                identifier=ident,
                share=share,
            )
            data.owners.append(owner)

    # ── Section B: Parcels ──
    parcels_section = _extract_section(full_text, r"B\s+Nemovitosti", r"B1\s+V[ěe]cn[áa]\s+pr[áa]va")
    if parcels_section:
        # Parse "Pozemky" table — pattern: "1951/12  478  ostatní plocha  ostatní komunikace"
        parcel_matches = re.findall(
            r"(\d+(?:/\d+)?)\s+(\d+)\s+([\w\s]+?)(?:\s{2,}([\w\s]*?))?(?:\s{2,}([\w\s]*?))?\s*$",
            parcels_section, re.MULTILINE
        )
        for pm in parcel_matches:
            num, area, land_type = pm[0], pm[1], pm[2].strip()
            land_use = pm[3].strip() if len(pm) > 3 else ""
            protection = pm[4].strip() if len(pm) > 4 else ""
            # Skip header rows
            if num and area.isdigit() and int(area) > 0:
                data.parcels.append(LVParcel(
                    parcel_number=num,
                    area_m2=int(area),
                    land_type=land_type,
                    land_use=land_use,
                    protection=protection,
                ))

        # Parse buildings
        building_matches = re.findall(
            r"Sou[čc][áa]st[ií]\s+je\s+stavba\s*:\s*(.+?)$",
            parcels_section, re.MULTILINE | re.IGNORECASE
        )
        for bm in building_matches:
            building = LVBuilding(part_of=bm.strip())
            data.buildings.append(building)

        on_parcel_matches = re.findall(
            r"Stavba\s+stoj[ií]\s+na\s+pozemku\s+p\.?\s*[čc]\.?\s*:?\s*(.+?)$",
            parcels_section, re.MULTILINE | re.IGNORECASE
        )
        for i, opm in enumerate(on_parcel_matches):
            if i < len(data.buildings):
                data.buildings[i].on_parcel = opm.strip()

    # ── Section B1: Rights in favor ──
    b1_section = _extract_section(
        full_text,
        r"B1\s+V[ěe]cn[áa]\s+pr[áa]va\s+slou[žz][ií]c[ií]",
        r"C\s+V[ěe]cn[áa]\s+pr[áa]va\s+zat[ěe][žz]uj[ií]c[ií]"
    )
    if b1_section:
        data.rights_in_favor = b1_section.strip()

    # ── Section C: Encumbrances ──
    c_section = _extract_section(
        full_text,
        r"C\s+V[ěe]cn[áa]\s+pr[áa]va\s+zat[ěe][žz]uj[ií]c[ií]",
        r"D\s+Pozn[áa]mky"
    )
    if c_section:
        _parse_encumbrances(c_section, data)

    # ── Section D: Notes ──
    d_section = _extract_section(full_text, r"D\s+Pozn[áa]mky", r"Plomby\s+a\s+upozorn[ěe]n[ií]")
    if d_section:
        data.notes = d_section.strip()

    # ── Plomby ──
    plomby_section = _extract_section(
        full_text,
        r"Plomby\s+a\s+upozorn[ěe]n[ií]",
        r"E\s+Nab[ýy]vac[ií]\s+tituly"
    )
    if plomby_section:
        data.seals = plomby_section.strip()

    # ── Section E: Nabývací tituly (Acquisition titles / historical transactions) ──
    e_section = _extract_section(
        full_text,
        r"E\s+Nab[\u00fd\u00fdy]vac[\u00ed\u00edi]\s+tituly",
        r"F\s+|Nemovitosti\s+jsou|Vyhotoveno"
    )
    if e_section:
        _parse_acquisition_titles(e_section, data)

    return data


def _extract_section(text: str, start_pattern: str, end_pattern: str) -> str:
    """Extract text between two section headers."""
    start = re.search(start_pattern, text, re.IGNORECASE)
    if not start:
        return ""
    end = re.search(end_pattern, text[start.end():], re.IGNORECASE)
    if end:
        return text[start.end():start.end() + end.start()]
    return text[start.end():]


def _parse_encumbrances(section_text: str, data: LVData):
    """Parse section C for liens, easements, and alienation bans."""
    # Split by bullet points (• or -)
    entries = re.split(r"\n\s*[•\-]\s+", section_text)

    for entry in entries:
        entry = entry.strip()
        if not entry or len(entry) < 10:
            continue

        enc = LVEncumbrance()

        # Detect type
        entry_lower = entry.lower()
        if "zástavní právo" in entry_lower:
            enc.type = "zástavní právo"
        elif "zákaz zcizení" in entry_lower:
            enc.type = "zákaz zcizení"
        elif "věcné břemeno" in entry_lower:
            enc.type = "věcné břemeno"
        elif "exekuční" in entry_lower or "exekuce" in entry_lower:
            enc.type = "exekuce"
        elif "předkupní" in entry_lower:
            enc.type = "předkupní právo"
        elif "nájemní" in entry_lower:
            enc.type = "nájemní právo"
        else:
            enc.type = "jiné"

        enc.description = entry

        # Extract beneficiary
        m = re.search(r"Opr[áa]vn[ěe]n[ií]\s+(?:pro|k)\s*:?\s*\n?\s*(.+?)(?:\n|Povinnost)", entry, re.DOTALL | re.IGNORECASE)
        if m:
            enc.beneficiary = re.sub(r"\s+", " ", m.group(1)).strip()

        # Extract amount
        m = re.search(r"(\d[\d\s.]+,\d{2}\s*K[čc])", entry)
        if m:
            enc.amount = m.group(1).strip()

        # Extract parcels
        parcel_matches = re.findall(r"Parcela\s*:\s*(\d+(?:/\d+)?)", entry)
        enc.parcels = parcel_matches

        # Extract document reference
        m = re.search(r"Listina\s*:\s*(.+?)$", entry, re.MULTILINE | re.IGNORECASE)
        if m:
            enc.document = m.group(1).strip()

        data.encumbrances.append(enc)


def _parse_acquisition_titles(section_text: str, data: LVData) -> None:
    """Parse section E – Nabývací tituly for historical transaction data."""
    # Split into individual title entries – separated by blank lines or V- markers
    entries = re.split(r"\n\s*\n|\n(?=V-\d+)", section_text.strip())

    for entry in entries:
        entry = entry.strip()
        if not entry or len(entry) < 10:
            continue

        title = LVAcquisitionTitle()
        title.description = entry

        # Detect type
        entry_lower = entry.lower()
        if "kupní smlouv" in entry_lower:
            title.type = "Kupní smlouva"
        elif "darovací smlouv" in entry_lower:
            title.type = "Darovací smlouva"
        elif "dědic" in entry_lower:
            title.type = "Dědictví"
        elif "rozsud" in entry_lower:
            title.type = "Rozsudek"
        elif "usnesení" in entry_lower:
            title.type = "Usnesení"
        elif "smlouv" in entry_lower:
            title.type = "Smlouva"
        else:
            title.type = "Jiný titul"

        # Extract date (DD.MM.YYYY)
        date_match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", entry)
        if date_match:
            title.date = date_match.group(1)

        # Extract price – patterns: "5.540.000,00 Kč", "5 540 000 Kč", "za 3000000"
        price_patterns = [
            r"(\d[\d\.\s]+(?:,\d{2})?)\s*(?:Kč|CZK|,-)",
            r"za\s+(\d[\d\.\s,]+)\s",
        ]
        for pat in price_patterns:
            price_match = re.search(pat, entry)
            if price_match:
                price_str = price_match.group(1)
                # Remove thousands separators (dots, spaces) and parse
                clean = re.sub(r"[\.\s]", "", price_str).replace(",", ".")
                try:
                    title.price_czk = int(float(clean))
                except (ValueError, TypeError):
                    pass
                if title.price_czk > 0:
                    break

        # Extract legal effect date
        effect_match = re.search(
            r"[Pp]rávní\s+účinky\s+(?:vkladu|zápisu)\s+(?:ke?\s+dni|ode?\s+dne)\s+(\d{1,2}\.\d{1,2}\.\d{4})",
            entry
        )
        if effect_match:
            title.legal_effect = effect_match.group(1)

        data.acquisition_titles.append(title)

