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
    apiBase?: string;
}

async function fetchImageBase64(url: string): Promise<string | null> {
    try {
        const response = await fetch(url);
        if (!response.ok) return null;
        const blob = await response.blob();
        return new Promise((resolve) => {
            const reader = new FileReader();
            reader.onloadend = () => resolve(reader.result as string);
            reader.readAsDataURL(blob);
        });
    } catch (e) {
        console.warn('PDF image fetch failed', e);
        return null;
    }
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

export async function generatePdfReport({ result, valuation, adjustedNhzp, apiBase = '' }: PdfReportData): Promise<void> {
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

    const docAgent = result.agents?.['PorovnavacDokumentu'];
    const checks = docAgent?.result?.details?.checks || [];

    doc.setFillColor(240, 240, 240);
    doc.rect(margin, y - 4, contentWidth, 8, 'F');
    doc.setFontSize(12);
    doc.setFont('helvetica', 'bold');
    doc.text(sanitize('Zakladni udaje a porovnani (Klient vs AI)'), margin + 2, y + 1);
    y += 10;

    checkPage(10);
    doc.setFontSize(9);
    doc.setFont('helvetica', 'bold');
    doc.text('Parametr', margin, y);
    doc.text('Z klienta (Deklarovano)', margin + 45, y);
    doc.text('Podle AI z fotodokumentace', margin + 115, y);
    y += 6;
    doc.line(margin, y - 4, pageWidth - margin, y - 4);
    y += 4;

    doc.setFont('helvetica', 'normal');
    
    // Always show address
    doc.text('Adresa:', margin, y);
    doc.text(sanitize(address), margin + 45, y);
    doc.text('-', margin + 115, y);
    y += 6;

    if (checks.length > 0) {
        for (const check of checks) {
            checkPage(10);
            const fieldText = sanitize(check.field || '');
            const declaredText = sanitize(String(check.declared || '–'));
            const observedText = sanitize(String(check.observed || '–'));
            
            doc.text(fieldText, margin, y);
            
            const declLines = doc.splitTextToSize(declaredText, 65);
            const obsLines = doc.splitTextToSize(observedText, 65);
            
            doc.text(declLines, margin + 45, y);
            
            if (check.match === false) {
                doc.setTextColor(220, 38, 38); // red for mismatch
            } else if (check.match === true) {
                doc.setTextColor(22, 163, 74); // green
            }
            doc.text(obsLines, margin + 115, y);
            doc.setTextColor(0, 0, 0); // reset
            
            y += Math.max(declLines.length, obsLines.length) * 5 + 3;
        }
    } else {
        const infoRows = [
            ['Plocha podlahova:', String(pData.celkova_podlahova_plocha || '–'), '–'],
            ['Plocha pozemku:', String(pData.plocha_pozemku || '–'), '–'],
            ['Stav objektu:', String(pData.stav_rodinneho_domu || '–'), '–'],
        ];

        for (const [label, val1, val2] of infoRows) {
            checkPage(7);
            doc.text(sanitize(label), margin, y);
            doc.text(sanitize(val1), margin + 45, y);
            doc.text(sanitize(val2), margin + 115, y);
            y += 7;
        }
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

    // ── Valuation (NHZP) – Professional Layout ──
    if (valuation?.details && adjustedNhzp) {
        checkPage(30);
        doc.setFillColor(240, 240, 240);
        doc.rect(margin, y - 4, contentWidth, 8, 'F');
        doc.setFontSize(12);
        doc.setFont('helvetica', 'bold');
        doc.text(sanitize('Trzni odhad (NHZP) – porovnavaci metoda'), margin + 2, y + 1);
        y += 12;

        // Main price
        doc.setFontSize(16);
        doc.setFont('helvetica', 'bold');
        doc.setTextColor(30, 64, 175);
        doc.text(formatCurrency(adjustedNhzp), margin, y);
        doc.setTextColor(0, 0, 0);
        y += 7;

        // Price range
        if (valuation.details.odhad_min && valuation.details.odhad_max) {
            doc.setFontSize(10);
            doc.setFont('helvetica', 'normal');
            doc.setTextColor(100, 116, 139);
            doc.text(
                `Cenove rozpeti: ${formatCurrency(valuation.details.odhad_min)} - ${formatCurrency(valuation.details.odhad_max)}`,
                margin, y
            );
            doc.setTextColor(0, 0, 0);
            y += 6;
        }

        // Benchmark
        if (valuation.details.benchmark) {
            doc.setFontSize(9);
            doc.text(
                sanitize(`Prumerna cena v ${valuation.details.benchmark.okres}: ${valuation.details.benchmark.czk_per_m2.toLocaleString('cs-CZ')} Kc/m2`),
                margin, y
            );
            y += 5;
        }

        // Confidence
        if (valuation.details.confidence) {
            const cs = valuation.details.confidence.score;
            const csLabel = cs >= 70 ? 'vysoka' : cs >= 40 ? 'stredni' : 'nizka';
            doc.text(sanitize(`Spolehlivost odhadu: ${cs} % (${csLabel})`), margin, y);
            y += 5;
        }
        y += 3;

        if (valuation.details.duvod) {
            doc.setFontSize(10);
            doc.setFont('helvetica', 'normal');
            const lines = doc.splitTextToSize(sanitize(valuation.details.duvod), contentWidth);
            checkPage(lines.length * 5);
            doc.text(lines, margin, y);
            y += lines.length * 5 + 3;
        }

        // ── Coefficient Table ──
        const samples = valuation.details.vzorky || [];
        if (samples.length > 0) {
            y += 3;
            checkPage(20 + samples.length * 6);
            doc.setFontSize(11);
            doc.setFont('helvetica', 'bold');
            doc.text(sanitize('Tabulka koeficientu K1-K8:'), margin, y);
            y += 7;

            // Table header
            doc.setFontSize(7);
            doc.setFont('helvetica', 'bold');
            const colW = [40, 14, 14, 14, 14, 14, 14, 14, 14, 16, 16];
            const headers = ['Vzorek', 'K1', 'K2', 'K3', 'K4', 'K5', 'K6', 'K7', 'K8', 'IO', 'Upr.JC'];
            let x = margin;
            doc.setFillColor(226, 232, 240);
            doc.rect(margin, y - 3, contentWidth, 5, 'F');
            for (let i = 0; i < headers.length; i++) {
                doc.text(headers[i], x + 1, y);
                x += colW[i];
            }
            y += 5;

            // Table rows
            doc.setFont('helvetica', 'normal');
            doc.setFontSize(7);
            for (const s of samples.slice(0, 8)) {
                checkPage(6);
                x = margin;
                const addr = sanitize(s.adresa || '?').substring(0, 22);
                doc.text(addr, x + 1, y);
                x += colW[0];

                const koef = s.koeficienty || {};
                ['k1', 'k2', 'k3', 'k4', 'k5', 'k6', 'k7', 'k8'].forEach((k, ki) => {
                    const val = koef[k] ?? 1.0;
                    doc.text(String(val), x + 1, y);
                    x += colW[ki + 1];
                });
                doc.text(String(s.io ?? '-'), x + 1, y);
                x += colW[9];
                doc.text(String(s.upravena_jc ?? '-'), x + 1, y);
                y += 5;
            }

            // Sample details below table
            y += 4;
            doc.setFontSize(9);
            doc.setFont('helvetica', 'normal');
            for (const s of samples.slice(0, 8)) {
                checkPage(6);
                const cena = typeof s.cena_czk === 'number' ? s.cena_czk : 0;
                const velikost = parseFloat(String(s.velikost_domu_m2 || 0)) || 0;
                const stav = s.stav ? ` | ${sanitize(s.stav)}` : '';
                const rok = s.rok_stavby ? ` | ${s.rok_stavby}` : '';
                const line = `- ${sanitize(s.adresa || '?')} | ${formatCurrency(cena)} | ${velikost} m2${stav}${rok}`;
                doc.text(line, margin + 2, y);
                y += 5;
            }
        }
        y += 5;
    }

    // ── Geo Validator: Visual Comparison ──
    const geoAgent = result.agents?.['GeoValidator'];
    const cmp = geoAgent?.result?.details?.visual_comparison;
    const panoramaUrl = geoAgent?.result?.details?.panorama_url;
    const frontPhotoId = geoAgent?.result?.details?.front_photo_id;

    if (cmp) {
        checkPage(50); // Misto pro minimalne hlavicku a text
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
            checkPage(lines.length * 5 + 40); // pricteme pripadne i misto pro obrazky dopredu
            doc.text(lines, margin, y);
            y += lines.length * 5 + 3;
        }

        // Vlozeni obrazku vedle sebe (Nahrané foto vs Panorama)
        if (apiBase && (frontPhotoId || panoramaUrl)) {
            const imgWidth = (contentWidth - 10) / 2;
            const imgHeight = (imgWidth * 9) / 16; // 16:9 ratio assumption pro rozlozeni

            let highestY = y;
            
            if (frontPhotoId) {
                const frontUrl = `${apiBase}/uploads/${result.session_id}/${frontPhotoId}.jpg`;
                const frontB64 = await fetchImageBase64(frontUrl);
                if (frontB64) {
                    doc.setFontSize(8);
                    doc.text('Nahrane foto', margin, y);
                    doc.addImage(frontB64, 'JPEG', margin, y + 2, imgWidth, imgHeight);
                    highestY = Math.max(highestY, y + 2 + imgHeight);
                }
            }

            if (panoramaUrl) {
                const panoUrl = `${apiBase}${panoramaUrl}`;
                const panoB64 = await fetchImageBase64(panoUrl);
                if (panoB64) {
                    doc.setFontSize(8);
                    doc.text('Panorama - Mapy.cz', margin + imgWidth + 10, y);
                    doc.addImage(panoB64, 'JPEG', margin + imgWidth + 10, y + 2, imgWidth, imgHeight);
                    highestY = Math.max(highestY, y + 2 + imgHeight);
                }
            }

            if (highestY > y) {
                y = highestY + 8;
            }
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
