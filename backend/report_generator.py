import os
from fpdf import FPDF
from datetime import datetime

class ReportGenerator:
    def __init__(self):
        self.pdf = FPDF()
        self.pdf.set_auto_page_break(auto=True, margin=15)
        
        # Add fonts that support Czech characters if available
        # Default dejavu paths on many linux systems or common mac paths
        font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        font_bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        
        if os.path.exists(font_path):
            self.pdf.add_font("DejaVu", "", font_path)
            if os.path.exists(font_bold_path):
                self.pdf.add_font("DejaVu", "B", font_bold_path)
            self.font_family = "DejaVu"
        else:
            # Fallback to standard Helvetica (might have issues with some CZ chars but better than failing)
            self.font_family = "Helvetica"

    def generate_valuation_report(self, session_data: dict, result: dict) -> bytes:
        self.pdf.add_page()
        
        # Header
        self.pdf.set_font(self.font_family, "B", 16)
        self.pdf.cell(0, 10, "Protokol o online ocenění nemovitosti", ln=True, align="C")
        self.pdf.set_font(self.font_family, "", 10)
        self.pdf.cell(0, 5, f"Vygenerováno: {datetime.now().strftime('%d.%m.%Y %H:%M')}", ln=True, align="C")
        self.pdf.ln(10)
        
        # Property Info
        p_data = result.get("property_data") or {}
        address = session_data.get("property_address") or "Adresa neuvedena"
        
        self.pdf.set_font(self.font_family, "B", 12)
        self.pdf.set_fill_color(240, 240, 240)
        self.pdf.cell(0, 8, "Základní údaje", ln=True, fill=True)
        self.pdf.set_font(self.font_family, "", 10)
        
        self.pdf.cell(40, 7, "Adresa:", 0)
        self.pdf.multi_cell(0, 7, address)
        
        self.pdf.cell(40, 7, "Plocha podlahová:", 0)
        self.pdf.cell(0, 7, f"{p_data.get('celkova_podlahova_plocha', '–')} m2", ln=True)
        
        self.pdf.cell(40, 7, "Plocha pozemku:", 0)
        self.pdf.cell(0, 7, f"{p_data.get('plocha_pozemku', '–')} m2", ln=True)
        
        self.pdf.cell(40, 7, "Stav objektu:", 0)
        self.pdf.cell(0, 7, f"{p_data.get('stav_rodinneho_domu', '–')}", ln=True)
        
        self.pdf.ln(5)
        
        # Verdict / Semaphore
        semaphore = result.get("semaphore", "UNKNOWN")
        color_map = {
            "green": (16, 185, 129), # #10b981
            "orange": (245, 158, 11), # #f59e0b
            "red": (239, 68, 68)      # #ef4444
        }
        color = color_map.get(result.get("semaphore_color", "gray"), (100, 100, 100))
        
        self.pdf.set_font(self.font_family, "B", 12)
        self.pdf.cell(0, 8, "Závěrečné hodnocení", ln=True, fill=True)
        self.pdf.set_font(self.font_family, "B", 14)
        self.pdf.set_text_color(*color)
        self.pdf.cell(0, 10, f"VERDIKT: {semaphore}", ln=True)
        self.pdf.set_text_color(0, 0, 0)
        self.pdf.set_font(self.font_family, "", 10)
        
        # Valuation (NHZP)
        valuation = session_data.get("valuation")
        if valuation and valuation.get("status") == "success":
            details = valuation.get("details", {})
            self.pdf.ln(5)
            self.pdf.set_font(self.font_family, "B", 12)
            self.pdf.cell(0, 8, "Tržní odhad (NHZP)", ln=True, fill=True)
            self.pdf.set_font(self.font_family, "B", 14)
            nhzp = details.get("odhad_czk", 0)
            self.pdf.cell(0, 10, f"{nhzp:,.0f} Kč".replace(",", " "), ln=True)
            self.pdf.set_font(self.font_family, "", 10)
            self.pdf.multi_cell(0, 5, details.get("duvod", ""))
            
            # Samples
            samples = details.get("vzorky", [])
            if samples:
                self.pdf.ln(5)
                self.pdf.set_font(self.font_family, "B", 11)
                self.pdf.cell(0, 7, "Srovnávací vzorky:", ln=True)
                self.pdf.set_font(self.font_family, "", 9)
                for s in samples[:3]: # Top 3 samples
                    self.pdf.cell(0, 5, f"- {s.get('adresa')} | {s.get('cena_czk', 0):,.0f} Kč | {s.get('velikost_domu_m2')} m2".replace(",", " "), ln=True)
        
        # Human Report (Strateg summary)
        strateg = result.get("agents", {}).get("Strateg", {}).get("result", {})
        report_text = strateg.get("details", {}).get("human_report") or strateg.get("summary", "")
        
        if report_text:
            self.pdf.ln(10)
            self.pdf.set_font(self.font_family, "B", 12)
            self.pdf.cell(0, 8, "Souhrnná zpráva", ln=True, fill=True)
            self.pdf.set_font(self.font_family, "", 10)
            # Replace markdown bolds for PDF
            clean_report = report_text.replace("**", "")
            self.pdf.multi_cell(0, 5, clean_report)

        return self.pdf.output()
