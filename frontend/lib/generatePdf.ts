/**
 * Client-side PDF report generation using jsPDF.
 * Generates the valuation protocol directly in the browser,
 * avoiding dependency on backend session state (which is lost on Render free tier restarts).
 */
import { jsPDF } from 'jspdf';
import type { PipelineResult } from './api';

// Custom font not available in jsPDF by default, so we use Helvetica
// which has decent Latin-2 support via the built-in encoding.

interface PdfReportData {
    result: PipelineResult;
    valuation?: any;
    adjustedNhzp?: number;
}

/**
 * Sanitize text for PDF – replace problematic Czech characters
 * that aren't in the default Helvetica encoding with ASCII equivalents.
 */
function sanitize(text: string): string {
    if (!text) return '';
    // jsPDF with default fonts doesn't support full UTF-8.
    // Map Czech diacritics to their ASCII equivalents for safe rendering.
    const map: Record<string, string> = {
        'á': 'a', 'č': 'c', 'ď': 'd', 'é': 'e', 'ě': 'e',
        'í': 'i', 'ň': 'n', 'ó': 'o', 'ř': 'r', 'š': 's',
        'ť': 't', 'ú': 'u', 'ů': 'u', 'ý': 'y', 'ž': 'z',
        'Á': 'A', 'Č': 'C', 'Ď': 'D', 'É': 'E', 'Ě': 'E',
        'Í': 'I', 'Ň': 'N', 'Ó': 'O', 'Ř': 'R', 'Š': 'S',
        'Ť': 'T', 'Ú': 'U', 'Ů': 'U', 'Ý': 'Y', 'Ž': 'Z',
    };
    return text.replace(/[áčďéěíňóřšťúůýžÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]/g, (ch) => map[ch] || ch);
}

function formatCurrency(value: number): string {
    return value.toLocaleString('cs-CZ') + ' Kc';
}

export function generatePdfReport({ result, valuation, adjustedNhzp }: PdfReportData): void {
    const doc = new jsPDF({ orientation: 'portrait', unit: 'mm', format: 'a4' });
    const pageWidth = doc.internal.pageSize.getWidth();
    const margin = 15;
    const contentWidth = pageWidth - 2 * margin;
    let y = 20;

    const checkPage = (needed: number) => {
        if (y + needed > doc.internal.pageSize.getHeight() - 15) {
            doc.addPage();
            y = 20;
        }
    };

    // ── Header ──
    doc.setFontSize(18);
    doc.setFont('helvetica', 'bold');
    doc.text(sanitize('Protokol o online oceneni nemovitosti'), pageWidth / 2, y, { align: 'center' });
    y += 8;

    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    const now = new Date();
    doc.text(`Vygenerovano: ${now.toLocaleDateString('cs-CZ')} ${now.toLocaleTimeString('cs-CZ', { hour: '2-digit', minute: '2-digit' })}`, pageWidth / 2, y, { align: 'center' });
    y += 12;

    // ── Property info ──
    const pData = result.property_data || {} as any;
    const address = result.property_address || pData.adresa || 'Adresa neuvedena';

    doc.setFillColor(240, 240, 240);
    doc.rect(margin, y - 4, contentWidth, 8, 'F');
    doc.setFontSize(12);
    doc.setFont('helvetica', 'bold');
    doc.text(sanitize('Zakladni udaje'), margin + 2, y + 1);
    y += 10;

    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');

    const infoRows = [
        ['Adresa:', address],
        ['Plocha podlahova:', `${pData.celkova_podlahova_plocha || '–'} m2`],
        ['Plocha pozemku:', `${pData.plocha_pozemku || '–'} m2`],
        ['Stav objektu:', pData.stav_rodinneho_domu || '–'],
    ];

    for (const [label, value] of infoRows) {
        checkPage(7);
        doc.setFont('helvetica', 'bold');
        doc.text(sanitize(label), margin, y);
        doc.setFont('helvetica', 'normal');
        doc.text(sanitize(String(value)), margin + 42, y);
        y += 7;
    }
    y += 5;

    // ── Verdict ──
    checkPage(20);
    doc.setFillColor(240, 240, 240);
    doc.rect(margin, y - 4, contentWidth, 8, 'F');
    doc.setFontSize(12);
    doc.setFont('helvetica', 'bold');
    doc.text(sanitize('Zaverecne hodnoceni'), margin + 2, y + 1);
    y += 10;

    const semaphore = result.semaphore || 'UNKNOWN';
    const semaphoreColor = result.semaphore_color || 'gray';
    const colorMap: Record<string, [number, number, number]> = {
        green: [16, 185, 129],
        orange: [245, 158, 11],
        red: [239, 68, 68],
    };
    const [r, g, b] = colorMap[semaphoreColor] || [100, 100, 100];

    doc.setFontSize(14);
    doc.setFont('helvetica', 'bold');
    doc.setTextColor(r, g, b);
    doc.text(`VERDIKT: ${sanitize(semaphore)}`, margin, y);
    doc.setTextColor(0, 0, 0);
    y += 10;

    // Inspektor verdict
    const inspAgent = result.agents?.['Inspektor'];
    if (inspAgent?.result?.details?.verdikt) {
        checkPage(14);
        doc.setFontSize(10);
        doc.setFont('helvetica', 'bold');
        doc.text(sanitize('Online oceneni:'), margin, y);
        const verdikt = inspAgent.result.details.verdikt;
        const vColor = verdikt === 'ANO' ? [16, 185, 129] : [239, 68, 68];
        doc.setTextColor(vColor[0], vColor[1], vColor[2]);
        doc.text(sanitize(verdikt), margin + 35, y);
        doc.setTextColor(0, 0, 0);
        y += 7;

        if (inspAgent.result.details.duvod) {
            doc.setFont('helvetica', 'normal');
            const lines = doc.splitTextToSize(sanitize(inspAgent.result.details.duvod), contentWidth);
            checkPage(lines.length * 5);
            doc.text(lines, margin, y);
            y += lines.length * 5 + 3;
        }
    }
    y += 5;

    // ── Valuation (NHZP) ──
    if (valuation?.details && adjustedNhzp) {
        checkPage(30);
        doc.setFillColor(240, 240, 240);
        doc.rect(margin, y - 4, contentWidth, 8, 'F');
        doc.setFontSize(12);
        doc.setFont('helvetica', 'bold');
        doc.text(sanitize('Trzni odhad (NHZP)'), margin + 2, y + 1);
        y += 10;

        doc.setFontSize(14);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(30, 64, 175);
        doc.text(formatCurrency(adjustedNhzp), margin, y);
        doc.setTextColor(0, 0, 0);
        y += 8;

        if (valuation.details.duvod) {
            doc.setFontSize(10);
            doc.setFont('helvetica', 'normal');
            const lines = doc.splitTextToSize(sanitize(valuation.details.duvod), contentWidth);
            checkPage(lines.length * 5);
            doc.text(lines, margin, y);
            y += lines.length * 5 + 3;
        }

        // Samples
        const samples = valuation.details.vzorky || [];
        if (samples.length > 0) {
            y += 3;
            checkPage(12);
            doc.setFontSize(11);
            doc.setFont('helvetica', 'bold');
            doc.text(sanitize('Srovnavaci vzorky:'), margin, y);
            y += 6;

            doc.setFontSize(9);
            doc.setFont('helvetica', 'normal');
            for (const s of samples.slice(0, 5)) {
                checkPage(6);
                const cena = typeof s.cena_czk === 'number' ? s.cena_czk : 0;
                const velikost = parseFloat(String(s.velikost_domu_m2 || 0)) || 0;
                const line = `- ${sanitize(s.adresa || '?')} | ${formatCurrency(cena)} | ${velikost} m2`;
                doc.text(line, margin + 2, y);
                y += 5;
            }
        }
        y += 5;
    }

    // ── Geo Validator: Visual Comparison ──
    const geoAgent = result.agents?.['GeoValidator'];
    const cmp = geoAgent?.result?.details?.visual_comparison;
    if (cmp) {
        checkPage(20);
        doc.setFillColor(240, 240, 240);
        doc.rect(margin, y - 4, contentWidth, 8, 'F');
        doc.setFontSize(12);
        doc.setFont('helvetica', 'bold');
        doc.text(sanitize('Vizualni porovnani s panoramou'), margin + 2, y + 1);
        y += 10;

        doc.setFontSize(10);
        doc.setFont('helvetica', 'normal');
        const verdict = cmp.match_verdict === 'shoda' ? 'SHODA' : cmp.match_verdict === 'neshoda' ? 'NESHODA' : 'MOZNA SHODA';
        doc.text(`Verdikt: ${verdict}${cmp.confidence != null ? ` (${Math.round(cmp.confidence * 100)}%)` : ''}`, margin, y);
        y += 6;

        if (cmp.comparison_text) {
            const lines = doc.splitTextToSize(sanitize(cmp.comparison_text), contentWidth);
            checkPage(lines.length * 5);
            doc.text(lines, margin, y);
            y += lines.length * 5 + 3;
        }
        y += 5;
    }

    // ── Summary Report (Strateg) ──
    const strategist = result.agents?.['Strateg'];
    const humanReport = strategist?.result?.details?.human_report || strategist?.result?.summary || '';
    if (humanReport) {
        checkPage(20);
        doc.setFillColor(240, 240, 240);
        doc.rect(margin, y - 4, contentWidth, 8, 'F');
        doc.setFontSize(12);
        doc.setFont('helvetica', 'bold');
        doc.text(sanitize('Souhrnna zprava'), margin + 2, y + 1);
        y += 10;

        doc.setFontSize(10);
        doc.setFont('helvetica', 'normal');
        // Clean markdown bold markers
        const cleanReport = humanReport.replace(/\*\*/g, '');
        const lines = doc.splitTextToSize(sanitize(cleanReport), contentWidth);
        for (let i = 0; i < lines.length; i++) {
            checkPage(5);
            doc.text(lines[i], margin, y);
            y += 5;
        }
    }

    // ── Footer on each page ──
    const totalPages = doc.getNumberOfPages();
    for (let i = 1; i <= totalPages; i++) {
        doc.setPage(i);
        doc.setFontSize(8);
        doc.setFont('helvetica', 'normal');
        doc.setTextColor(150, 150, 150);
        doc.text(
            `Strana ${i} / ${totalPages} | AI Validation Pipeline | Ceska sporitelna`,
            pageWidth / 2,
            doc.internal.pageSize.getHeight() - 8,
            { align: 'center' }
        );
        doc.setTextColor(0, 0, 0);
    }

    // ── Save ──
    const safeName = sanitize(address).replace(/[^\w\s-]/g, '').trim().replace(/\s+/g, '_') || 'report';
    doc.save(`${safeName}.pdf`);
}
