"""PDF Report Generator for pipeline results (RD + BJ).

Generates a professional PDF report containing:
1. Semaphore verdict (ONLINE / SUPERVISED / VRÁTIT KLIENTOVI) with reasoning
2. Property basic info
3. Panorama vs photo visual comparison (images side-by-side)
4. Document comparison table (formulář vs AI findings)
5. Agent results summary table
6. Human-readable Strateg report
"""
import logging
import os
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from fpdf import FPDF

from config import UPLOAD_DIR

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generate a comprehensive PDF report from pipeline results."""

    # Font paths (resolved once at class level)
    _FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
    _FONT_PATH = os.path.join(_FONT_DIR, "Roboto-Regular.ttf")
    _FONT_BOLD_PATH = os.path.join(_FONT_DIR, "Roboto-Bold.ttf")

    def __init__(self):
        self.pdf: FPDF | None = None
        self.font_family = "Roboto" if os.path.exists(self._FONT_PATH) else "Helvetica"

    def _init_pdf(self):
        """Create a fresh PDF instance (called at the start of each report)."""
        self.pdf = FPDF()
        self.pdf.set_auto_page_break(auto=True, margin=15)
        if self.font_family == "Roboto":
            self.pdf.add_font("Roboto", "", self._FONT_PATH)
            if os.path.exists(self._FONT_BOLD_PATH):
                self.pdf.add_font("Roboto", "B", self._FONT_BOLD_PATH)

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_valuation_report(self, session_data: dict, result: dict) -> bytes:
        """Generate PDF for RD or BJ pipeline results. Unified entry point."""
        self._init_pdf()  # Fresh PDF for every call — safe for reuse

        is_bj = result.get("pipeline_type") == "bj" or "StrategBJ" in result.get("agents", {})
        agents = result.get("agents", {})

        self.pdf.add_page()

        sections = [
            ("header", lambda: self._header(is_bj)),
            ("property_info", lambda: self._property_info(session_data, result, is_bj)),
            ("semaphore", lambda: self._semaphore_section(result, agents, is_bj)),
            ("strateg_report", lambda: self._strateg_report(agents, is_bj)),
            ("panorama", lambda: self._panorama_comparison(session_data, result, agents)),
            ("comparison_table", lambda: self._comparison_table(agents, is_bj)),
            ("agent_summary", lambda: self._agent_summary_table(agents, is_bj)),
            ("valuation", lambda: self._valuation_section(session_data, result)),
            ("footer", lambda: self._footer()),
        ]

        for name, fn in sections:
            try:
                # Safety: reset X to left margin before each section
                self.pdf.set_x(self.pdf.l_margin)
                fn()
            except Exception as e:
                logger.error("Error in section '%s': %s", name, e, exc_info=True)
                # Try to recover: reset state and add page if needed
                self.pdf.set_text_color(0, 0, 0)
                self.pdf.set_x(self.pdf.l_margin)
                try:
                    self.pdf.set_font(self.font_family, "", 8)
                    self.pdf.cell(0, 5, f"(Sekce '{name}' se nepodařilo vykreslit)", ln=True)
                except Exception:
                    pass

        return self.pdf.output()

    # ── Private sections ──────────────────────────────────────────────────────

    def _header(self, is_bj: bool):
        prop_type = "Bytová jednotka" if is_bj else "Rodinný dům"
        # Logo/Brand text
        self.pdf.set_font(self.font_family, "B", 14)
        self.pdf.set_text_color(0, 51, 153) # Česká spořitelna blue
        self.pdf.cell(0, 8, "Česká spořitelna", ln=True, align="L")
        
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.set_font(self.font_family, "B", 20)
        self.pdf.cell(0, 10, f"Protokol o validaci - {prop_type}", ln=True, align="L")
        
        self.pdf.set_font(self.font_family, "", 10)
        self.pdf.set_text_color(100, 100, 100)
        now = datetime.now(tz=ZoneInfo("Europe/Prague"))
        self.pdf.cell(0, 6, f"Generováno automatickým AI systémem: {now.strftime('%d.%m.%Y %H:%M')}", ln=True, align="L")
        
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.ln(4)
        # Thick divider
        self.pdf.set_fill_color(0, 51, 153)
        self.pdf.cell(0, 1, "", fill=True, ln=True)
        self.pdf.ln(6)

    def _property_info(self, session_data: dict, result: dict, is_bj: bool):
        p_data = result.get("property_data") or session_data.get("property_data") or {}
        address = session_data.get("property_address") or result.get("property_address") or "Adresa neuvedena"

        self._section_title("Základní údaje o nemovitosti")

        rows = [("Adresa:", address)]

        if is_bj:
            rows.append(("Typ:", "Bytová jednotka"))
            floor_area = p_data.get("plocha_bytu") or p_data.get("podlahova_plocha") or "–"
            rows.append(("Podlahová plocha:", f"{floor_area} m²"))
            if p_data.get("patro"):
                rows.append(("Patro:", str(p_data["patro"])))
            if p_data.get("dispozice"):
                rows.append(("Dispozice:", str(p_data["dispozice"])))
        else:
            rows.append(("Typ:", "Rodinný dům"))
            if p_data.get("celkova_podlahova_plocha"):
                rows.append(("Podlahová plocha:", f"{p_data['celkova_podlahova_plocha']} m²"))
            if p_data.get("plocha_pozemku"):
                rows.append(("Plocha pozemku:", f"{p_data['plocha_pozemku']} m²"))
            if p_data.get("stav_rodinneho_domu"):
                rows.append(("Stav:", str(p_data["stav_rodinneho_domu"])))
            if p_data.get("pocet_nadzemich_podlazi"):
                rows.append(("Počet podlaží:", str(p_data["pocet_nadzemich_podlazi"])))

        for label, value in rows:
            self.pdf.set_font(self.font_family, "B", 10)
            self.pdf.cell(50, 6, label, 0, 0)
            self.pdf.set_font(self.font_family, "", 10)
            # Use cell for short values, multi_cell would run out of space
            val_str = str(value)
            if len(val_str) > 60:
                self.pdf.ln()
                self.pdf.set_x(60)
                self.pdf.multi_cell(0, 6, val_str)
            else:
                self.pdf.cell(0, 6, val_str, ln=True)

        self.pdf.ln(4)

    def _semaphore_section(self, result: dict, agents: dict, is_bj: bool):
        """Big semaphore verdict box with reasoning."""
        semaphore = result.get("semaphore", "UNKNOWN")
        sem_color = result.get("semaphore_color", "gray")

        color_map = {
            "green": ((16, 185, 129), "ONLINE – Plně online ocenění"),
            "orange": ((245, 158, 11), "SUPERVISED – Vyžaduje dohled"),
            "red": ((220, 50, 50), "VRÁTIT KLIENTOVI"),
        }
        rgb, label = color_map.get(sem_color, ((100, 100, 100), semaphore))

        # Colored verdict box
        self._section_title("Rozhodovací logika – SEMAFOR")

        self.pdf.set_fill_color(*rgb)
        self.pdf.set_text_color(255, 255, 255)
        self.pdf.set_font(self.font_family, "B", 16)
        # Draw a nice padded cell
        self.pdf.cell(0, 16, f"   {label}", ln=True, fill=True, border=0)
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.ln(4)

        # Reasoning
        strateg_key = "StrategBJ" if is_bj else "Strateg"
        strateg = agents.get(strateg_key, {})
        s_details = strateg.get("result", {}).get("details", {})
        reason = s_details.get("semaphore_reason") or ""

        if reason:
            self.pdf.set_font(self.font_family, "B", 10)
            self.pdf.cell(0, 6, "Důvod:", ln=True)
            self.pdf.set_font(self.font_family, "", 10)
            self.pdf.multi_cell(0, 5, _sanitize(reason))
            self.pdf.ln(2)

        # Failing agents
        failing = s_details.get("failing_agents") or []
        if failing:
            self.pdf.set_font(self.font_family, "B", 10)
            self.pdf.set_text_color(200, 30, 30)
            self.pdf.cell(0, 6, "Blokované agenty:", ln=True)
            self.pdf.set_text_color(0, 0, 0)
            self.pdf.set_font(self.font_family, "", 9)
            for name in failing:
                agent_data = agents.get(name, {})
                summary = agent_data.get("result", {}).get("summary", "")
                self.pdf.cell(0, 5, f"  - {name}: {_sanitize(summary[:120])}", ln=True)

        self.pdf.ln(4)

    def _strateg_report(self, agents: dict, is_bj: bool):
        """Human-readable report from Strateg."""
        strateg_key = "StrategBJ" if is_bj else "Strateg"
        strateg = agents.get(strateg_key, {})
        report_text = (
            strateg.get("result", {}).get("details", {}).get("human_report")
            or strateg.get("result", {}).get("summary", "")
        )

        if not report_text:
            return

        self._section_title("Souhrnná zpráva")
        self.pdf.set_font(self.font_family, "", 10)
        clean = _sanitize(report_text.replace("**", ""))
        self.pdf.multi_cell(0, 5, clean)
        self.pdf.ln(4)

    def _panorama_comparison(self, session_data: dict, result: dict, agents: dict):
        """Side-by-side: client photo vs panorama from Mapy.cz."""
        geo = agents.get("GeoValidator", {})
        geo_details = geo.get("result", {}).get("details", {})
        vc = geo_details.get("visual_comparison") or {}

        pano_url = geo_details.get("panorama_url") or vc.get("panorama_url")
        front_id = geo_details.get("front_photo_id")
        session_id = result.get("session_id") or session_data.get("session_id", "")

        if not pano_url and not front_id:
            return

        # Ensure enough space for images (~70mm) — add page if near bottom
        if self.pdf.get_y() > 200:
            self.pdf.add_page()

        self._section_title("Porovnání fotografie s panoramou")

        img_w = 88  # mm width per image
        y_start = self.pdf.get_y()
        images_placed = 0
        y_imgs = y_start + 4

        # UPLOAD_DIR imported at module level

        # Client's front photo
        if front_id and session_id:
            front_path = os.path.join(UPLOAD_DIR, session_id, f"{front_id}.jpg")
            if os.path.exists(front_path):
                try:
                    self.pdf.set_font(self.font_family, "B", 8)
                    self.pdf.set_text_color(80, 80, 80)
                    self.pdf.cell(img_w, 4, "Nahrané foto klientem", ln=False)
                    self.pdf.set_text_color(0, 0, 0)

                    x_col2 = 10 + img_w + 4
                    self.pdf.set_xy(x_col2, y_start)

                    if pano_url:
                        self.pdf.set_font(self.font_family, "B", 8)
                        self.pdf.set_text_color(80, 80, 80)
                        self.pdf.cell(img_w, 4, "Panorama z Mapy.cz", ln=True)
                        self.pdf.set_text_color(0, 0, 0)
                    else:
                        self.pdf.ln(4)

                    y_imgs = self.pdf.get_y()
                    self.pdf.image(front_path, x=10, y=y_imgs, w=img_w)
                    images_placed += 1
                except Exception:
                    pass

        # Panorama image – load from local file (saved by GeoValidator)
        if pano_url and session_id:
            pano_local = os.path.join(UPLOAD_DIR, session_id, "panorama_mapy.jpg")
            if os.path.exists(pano_local):
                try:
                    x_pos = (10 + img_w + 4) if images_placed > 0 else 10
                    self.pdf.image(pano_local, x=x_pos, y=y_imgs, w=img_w)
                    images_placed += 1
                except Exception:
                    pass

        # Move cursor below images and ALWAYS reset to left margin
        if images_placed > 0:
            self.pdf.set_y(y_imgs + img_w * 0.625 + 4)
        else:
            self.pdf.set_font(self.font_family, "", 9)
            self.pdf.cell(0, 5, "(Obrázky panoramy nejsou k dispozici v PDF)", ln=True)

        # Force X to left margin before any text output
        self.pdf.set_x(self.pdf.l_margin)

        # Comparison verdict
        if vc:
            try:
                verdict = vc.get("match_verdict", "–")
                confidence = vc.get("confidence")
                comparison_text = vc.get("comparison_text", "")

                verdict_labels = {
                    "shoda": "SHODA",
                    "mozna_shoda": "MOŽNÁ SHODA",
                    "neshoda": "NESHODA",
                }
                v_label = verdict_labels.get(verdict, verdict)

                self.pdf.set_font(self.font_family, "B", 11)
                verdict_line = f"Výsledek porovnání: {v_label}"
                if confidence is not None:
                    verdict_line += f" (jistota {int(confidence * 100)}%)"
                self.pdf.cell(0, 7, verdict_line, ln=True)

                if comparison_text:
                    self.pdf.set_x(self.pdf.l_margin)
                    self.pdf.set_font(self.font_family, "", 9)
                    self.pdf.multi_cell(0, 5, _sanitize(comparison_text))

                # Features
                matching = vc.get("matching_features", [])
                differing = vc.get("differing_features", [])

                if matching:
                    self.pdf.set_x(self.pdf.l_margin)
                    self.pdf.set_font(self.font_family, "B", 9)
                    self.pdf.multi_cell(0, 5, "Shodné znaky: " + ", ".join(matching))
                if differing:
                    self.pdf.set_x(self.pdf.l_margin)
                    self.pdf.set_font(self.font_family, "B", 9)
                    self.pdf.set_text_color(180, 80, 0)
                    self.pdf.multi_cell(0, 5, "Rozdíly: " + ", ".join(differing))
                    self.pdf.set_text_color(0, 0, 0)
            except Exception:
                # If text rendering fails, just skip the verdict
                self.pdf.set_text_color(0, 0, 0)
                self.pdf.set_x(self.pdf.l_margin)

        self.pdf.ln(4)

    def _comparison_table(self, agents: dict, is_bj: bool):
        """Table: declared vs observed values from PorovnavacDokumentu."""
        doc_key = "PorovnavacDokumentuBJ" if is_bj else "PorovnavacDokumentu"
        doc_agent = agents.get(doc_key, {})
        checks = doc_agent.get("result", {}).get("details", {}).get("checks", [])

        if not checks:
            return

        self._section_title("Porovnání formuláře vs. AI zjištění")

        # Table header
        col_w = [60, 45, 60, 25]
        self.pdf.set_draw_color(220, 220, 225) # Soft gray borders
        self.pdf.set_font(self.font_family, "B", 9)
        self.pdf.set_fill_color(240, 244, 248) # Slightly bluish light gray
        self.pdf.cell(col_w[0], 8, "Položka", 1, 0, "L", True)
        self.pdf.cell(col_w[1], 8, "Od klienta", 1, 0, "L", True)
        self.pdf.cell(col_w[2], 8, "Zjištěno AI", 1, 0, "L", True)
        self.pdf.cell(col_w[3], 8, "Stav", 1, 1, "C", True)

        self.pdf.set_font(self.font_family, "", 9)

        for c in checks:
            # Page-break guard: re-render header on new page
            if self.pdf.get_y() > 265:
                self.pdf.add_page()
                self.pdf.set_font(self.font_family, "B", 9)
                self.pdf.set_fill_color(240, 244, 248)
                self.pdf.cell(col_w[0], 8, "Položka", 1, 0, "L", True)
                self.pdf.cell(col_w[1], 8, "Od klienta", 1, 0, "L", True)
                self.pdf.cell(col_w[2], 8, "Zjištěno AI", 1, 0, "L", True)
                self.pdf.cell(col_w[3], 8, "Stav", 1, 1, "C", True)
                self.pdf.set_font(self.font_family, "", 9)

            field = _sanitize(c.get("field", "–"))[:35]
            declared = _sanitize(str(c.get("declared") or c.get("form_value") or "–"))[:25]
            observed = _sanitize(str(c.get("observed") or c.get("observed_value") or "–"))[:35]
            is_match = c.get("match") == "YES" or c.get("match") is True

            # Row colors
            if is_match:
                self.pdf.set_fill_color(240, 253, 244)
                icon = "OK"
            else:
                self.pdf.set_fill_color(254, 242, 242)
                icon = "X"

            self.pdf.cell(col_w[0], 7, field, 1, 0, "L", True)
            self.pdf.cell(col_w[1], 7, declared, 1, 0, "L", True)
            self.pdf.cell(col_w[2], 7, observed, 1, 0, "L", True)

            # Color the status cell
            if is_match:
                self.pdf.set_text_color(22, 101, 52)
            else:
                self.pdf.set_text_color(153, 27, 27)
            self.pdf.set_font(self.font_family, "B", 9)
            self.pdf.cell(col_w[3], 7, icon, 1, 1, "C", True)
            self.pdf.set_text_color(0, 0, 0)
            self.pdf.set_font(self.font_family, "", 9)

        self.pdf.ln(4)

    def _agent_summary_table(self, agents: dict, is_bj: bool):
        """Summary table of all agent results (name, status, key finding)."""
        agent_order = (
            ["StrazceBJ", "InspektorBJ", "ForenzniAnalytik", "Historik",
             "GeoValidator", "GDPRValidator", "PorovnavacDokumentuBJ", "KatastralniAnalytik"]
            if is_bj else
            ["Strazce", "Inspektor", "ForenzniAnalytik", "Historik",
             "GeoValidator", "GDPRValidator", "PorovnavacDokumentu", "KatastralniAnalytik"]
        )

        agent_labels = {
            "Strazce": "Fotodokumentace",
            "StrazceBJ": "Fotodokumentace bytu",
            "Inspektor": "Technicky stav",
            "InspektorBJ": "Technicky stav bytu",
            "ForenzniAnalytik": "Autenticita fotek",
            "Historik": "Vek nemovitosti",
            "GeoValidator": "Overeni lokace (GPS)",
            "GDPRValidator": "GDPR kontrola",
            "PorovnavacDokumentu": "PDF vs Fotky",
            "PorovnavacDokumentuBJ": "PDF vs Fotky (BJ)",
            "KatastralniAnalytik": "Katastr & LV",
        }

        self._section_title("Přehled výsledků jednotlivých agentů")

        col_w = [55, 25, 110]
        self.pdf.set_draw_color(220, 220, 225)
        self.pdf.set_font(self.font_family, "B", 9)
        self.pdf.set_fill_color(240, 244, 248)
        self.pdf.cell(col_w[0], 8, "Agent", 1, 0, "L", True)
        self.pdf.cell(col_w[1], 8, "Stav", 1, 0, "C", True)
        self.pdf.cell(col_w[2], 8, "Shrnutí", 1, 1, "L", True)

        self.pdf.set_font(self.font_family, "", 8)

        for name in agent_order:
            agent = agents.get(name)
            if not agent:
                continue

            # Page-break guard: re-render header on new page
            if self.pdf.get_y() > 265:
                self.pdf.add_page()
                self.pdf.set_font(self.font_family, "B", 9)
                self.pdf.set_fill_color(240, 244, 248)
                self.pdf.cell(col_w[0], 8, "Agent", 1, 0, "L", True)
                self.pdf.cell(col_w[1], 8, "Stav", 1, 0, "C", True)
                self.pdf.cell(col_w[2], 8, "Shrnutí", 1, 1, "L", True)
                self.pdf.set_font(self.font_family, "", 8)

            r = agent.get("result", {})
            status = r.get("status", "–")
            summary = _sanitize(r.get("summary", ""))[:80]
            label = agent_labels.get(name, name)

            # Status colors
            if status == "success":
                self.pdf.set_fill_color(240, 253, 244)
                status_text = "OK"
            elif status == "warn":
                self.pdf.set_fill_color(255, 251, 235)
                status_text = "WARN"
            elif status == "fail":
                self.pdf.set_fill_color(254, 242, 242)
                status_text = "FAIL"
            else:
                self.pdf.set_fill_color(248, 250, 252)
                status_text = "–"

            self.pdf.cell(col_w[0], 7, label, 1, 0, "L", True)

            # Color status text
            if status == "success":
                self.pdf.set_text_color(22, 101, 52)
            elif status == "warn":
                self.pdf.set_text_color(180, 83, 9)
            elif status == "fail":
                self.pdf.set_text_color(153, 27, 27)
            self.pdf.set_font(self.font_family, "B", 8)
            self.pdf.cell(col_w[1], 7, status_text, 1, 0, "C", True)
            self.pdf.set_text_color(0, 0, 0)
            self.pdf.set_font(self.font_family, "", 8)

            self.pdf.cell(col_w[2], 7, summary, 1, 1, "L", True)

        self.pdf.ln(4)

    def _valuation_section(self, session_data: dict, result: dict):
        """NHZP valuation if available."""
        valuation = session_data.get("valuation")
        if not valuation or valuation.get("status") != "success":
            return

        details = valuation.get("details", {})
        self._section_title("Tržní odhad (NHZP)")

        self.pdf.set_font(self.font_family, "B", 14)
        nhzp_raw = details.get("odhad_czk", 0)
        try:
            nhzp = float(nhzp_raw)
        except (ValueError, TypeError):
            nhzp = 0
        self.pdf.cell(0, 10, f"{nhzp:,.0f} Kč".replace(",", " "), ln=True)
        self.pdf.set_font(self.font_family, "", 10)
        if details.get("duvod"):
            self.pdf.multi_cell(0, 5, _sanitize(details["duvod"]))

        # Samples
        samples = details.get("vzorky", [])
        if samples:
            self.pdf.ln(3)
            self.pdf.set_font(self.font_family, "B", 10)
            self.pdf.cell(0, 6, "Srovnávací vzorky:", ln=True)
            self.pdf.set_font(self.font_family, "", 9)
            for s in samples[:5]:
                try:
                    cena = float(s.get("cena_czk", 0))
                except (ValueError, TypeError):
                    cena = 0
                try:
                    vel = float(s.get("velikost_domu_m2") or 0)
                except (ValueError, TypeError):
                    vel = 0
                self.pdf.cell(
                    0, 5,
                    f"  - {s.get('adresa', '–')} | {cena:,.0f} Kč | {vel:,.0f} m²".replace(",", " "),
                    ln=True,
                )

        self.pdf.ln(4)

    def _footer(self):
        """Simple footer with disclaimer."""
        self.pdf.ln(6)
        self.pdf.set_draw_color(200, 200, 200)
        self.pdf.line(10, self.pdf.get_y(), 200, self.pdf.get_y())
        self.pdf.ln(3)
        self.pdf.set_font(self.font_family, "", 7)
        self.pdf.set_text_color(130, 130, 130)
        self.pdf.multi_cell(
            0, 3,
            "Tento protokol byl vygenerován automatickým AI systémem pro validaci vstupních dat. "
            "Výsledky slouží jako podklad pro rozhodnutí odhadce a nenahrazují odborný posudek."
        )
        self.pdf.set_text_color(0, 0, 0)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _section_title(self, title: str):
        """Render a styled section title."""
        self.pdf.ln(2)
        self.pdf.set_font(self.font_family, "B", 13)
        self.pdf.set_text_color(30, 41, 59) # Dark slate
        # Use a nice underline instead of full fill
        self.pdf.cell(0, 8, title, ln=True, align="L")
        
        # Subtle underline
        self.pdf.set_draw_color(203, 213, 225) # Slate-300
        self.pdf.set_line_width(0.3)
        self.pdf.line(10, self.pdf.get_y(), 200, self.pdf.get_y())
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.ln(3)




def _sanitize(text: str) -> str:
    """Remove characters that fpdf2 can't handle and normalize."""
    if not text:
        return ""
    # Replace common problematic Unicode characters
    replacements = {
        "–": "-", "—": "-", "'": "'", "'": "'",
        """: '"', """: '"', "…": "...",
        "✅": "[OK]", "⚠️": "[!]", "🔴": "[X]",
        "❌": "[X]", "🟢": "[OK]", "🟡": "[!]",
        "📍": "", "🛡️": "", "🔬": "", "📜": "",
        "🎯": "", "🔍": "", "📄": "", "🏛️": "",
        "📷": "", "📐": "", "💡": "",
        "\u200b": "",  # zero-width space
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text
