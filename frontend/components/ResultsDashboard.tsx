'use client';
import { useState, useEffect, useRef } from 'react';
import styles from './ResultsDashboard.module.css';
import type { PipelineResult } from '@/lib/api';
import { API_BASE } from '@/lib/api';
import { generatePdfReport } from '@/lib/generatePdf';

interface Props {
    result: PipelineResult;
    onReset: () => void;
    onEdit: () => void;
}

const AGENT_META: Record<string, { icon: string; label: string; color: string }> = {
    Strazce: { icon: '🛡️', label: 'Fotodokumentace', color: '#3b82f6' },
    ForenzniAnalytik: { icon: '🔬', label: 'Autenticita fotek', color: '#8b5cf6' },
    Historik: { icon: '📜', label: 'Věk nemovitosti', color: '#06b6d4' },
    Inspektor: { icon: '🔍', label: 'Technický stav', color: '#f59e0b' },
    GeoValidator: { icon: '📍', label: 'Ověření lokace', color: '#ec4899' },
    PorovnavacDokumentu: { icon: '📄', label: 'PDF vs Fotky', color: '#f97316' },
    KatastralniAnalytik: { icon: '🏛️', label: 'Katastr & LV', color: '#7c3aed' },
    Strateg: { icon: '🎯', label: 'Závěrečné hodnocení', color: '#10b981' },
};

// ── Leaflet Map Component (loads from CDN to avoid SSR issues) ──
function ValuationMap({ propertyGps, samples }: { propertyGps: { lat: number; lon: number }; samples: any[] }) {
    const mapRef = useRef<HTMLDivElement>(null);
    const mapInstanceRef = useRef<any>(null);

    useEffect(() => {
        if (!mapRef.current || mapInstanceRef.current) return;

        // Load Leaflet CSS
        if (!document.getElementById('leaflet-css')) {
            const link = document.createElement('link');
            link.id = 'leaflet-css';
            link.rel = 'stylesheet';
            link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
            document.head.appendChild(link);
        }

        // Load Leaflet JS
        const loadLeaflet = () => {
            if ((window as any).L) {
                initMap((window as any).L);
                return;
            }
            if (!document.getElementById('leaflet-js')) {
                const script = document.createElement('script');
                script.id = 'leaflet-js';
                script.src = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.js';
                script.onload = () => initMap((window as any).L);
                document.head.appendChild(script);
            } else {
                // Script loading, wait
                const interval = setInterval(() => {
                    if ((window as any).L) {
                        clearInterval(interval);
                        initMap((window as any).L);
                    }
                }, 100);
            }
        };

        const initMap = (L: any) => {
            if (!mapRef.current || mapInstanceRef.current) return;
            const map = L.map(mapRef.current).setView([propertyGps.lat, propertyGps.lon], 13);
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap',
                maxZoom: 18,
            }).addTo(map);

            // Property marker (blue)
            const blueIcon = L.divIcon({
                html: '<div style="background:#1e40af;width:14px;height:14px;border-radius:50%;border:3px solid #fff;box-shadow:0 2px 6px rgba(0,0,0,0.3)"></div>',
                iconSize: [20, 20],
                iconAnchor: [10, 10],
                className: '',
            });
            L.marker([propertyGps.lat, propertyGps.lon], { icon: blueIcon })
                .addTo(map)
                .bindPopup('<b>Oceňovaný dům</b>');

            // Sample markers (red)
            const redIcon = L.divIcon({
                html: '<div style="background:#ef4444;width:12px;height:12px;border-radius:50%;border:2px solid #fff;box-shadow:0 2px 4px rgba(0,0,0,0.3)"></div>',
                iconSize: [16, 16],
                iconAnchor: [8, 8],
                className: '',
            });
            const bounds = [L.latLng(propertyGps.lat, propertyGps.lon)];
            for (const s of samples) {
                if (s.gps?.lat && s.gps?.lon) {
                    const m = L.marker([s.gps.lat, s.gps.lon], { icon: redIcon }).addTo(map);
                    m.bindPopup(`<b>${s.adresa}</b><br>${s.cena_czk?.toLocaleString('cs-CZ')} Kč<br>${s.velikost_domu_m2} m²`);
                    bounds.push(L.latLng(s.gps.lat, s.gps.lon));
                }
            }
            if (bounds.length > 1) {
                map.fitBounds(L.latLngBounds(bounds).pad(0.15));
            }
            mapInstanceRef.current = map;
        };

        loadLeaflet();

        return () => {
            if (mapInstanceRef.current) {
                mapInstanceRef.current.remove();
                mapInstanceRef.current = null;
            }
        };
    }, [propertyGps, samples]);

    return (
        <div style={{ marginTop: '16px' }}>
            <h4 style={{ fontSize: '14px', fontWeight: 600, color: '#334155', marginBottom: '8px' }}>🗺️ Mapa vzorků</h4>
            <div ref={mapRef} style={{ width: '100%', height: '320px', borderRadius: '12px', border: '1px solid #cbd5e1', overflow: 'hidden' }} />
            <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '4px', display: 'flex', gap: '12px' }}>
                <span>🔵 Oceňovaný dům</span>
                <span>🔴 Srovnávací vzorky</span>
            </div>
        </div>
    );
}


export default function ResultsDashboard({ result, onReset, onEdit }: Props) {
    const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
    const [valuation, setValuation] = useState<any>(null);
    const [isValuing, setIsValuing] = useState(false);
    const [isSetupOpen, setIsSetupOpen] = useState(false);
    const [valError, setValError] = useState('');
    const [customCoeffs, setCustomCoeffs] = useState<Record<number, Record<string, string>>>({});
    const [setupData, setSetupData] = useState({ adresa: '', plocha: '', pozemek: '', stav: '' });
    const [isDownloading, setIsDownloading] = useState(false);

    const openSetup = () => {
        const pData = result.property_data || {} as any;
        setSetupData({
            adresa: pData.adresa || result.property_address || '',
            plocha: pData.celkova_podlahova_plocha || '',
            pozemek: pData.plocha_pozemku || '',
            stav: pData.stav_rodinneho_domu || ''
        });
        setIsSetupOpen(true);
    };

    const confirmSetup = async () => {
        setIsSetupOpen(false);
        setIsValuing(true);
        setValError('');
        try {
            const res = await fetch(`${API_BASE}/api/pipeline/valuation/${result.session_id}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(setupData)
            });
            if (!res.ok) throw new Error('Nepodařilo se vytvořit odhad');
            const data = await res.json();
            setValuation(data);
        } catch (err: any) {
            setValError(err.message);
        } finally {
            setIsValuing(false);
        }
    };

    const handleCoeffChange = (id: number, key: string, val: string) => {
        setCustomCoeffs(prev => {
            const currentObj = prev[id] || {};
            return { ...prev, [id]: { ...currentObj, [key]: val } };
        });
    };

    const K_LABELS: Record<string, string> = {
        'k1': 'K1: Redukce pram.',
        'k2': 'K2: Velikost',
        'k3': 'K3: Poloha',
        'k4': 'K4: Provedení',
        'k5': 'K5: Celk. stav',
        'k6': 'K6: Vliv pozemku',
        'k7': 'K7: Úvaha',
        'k8': 'K8: En. náročnost',
    };

    // ── Výpočet NHZP porovnávací metodou ──
    // Použij AI odhad jako základ, přepočítej pouze pokud uživatel upravil koeficienty.
    // Vzorec: JC = cena_vzorku / plocha_vzorku; IO = K1 × K2 × ... × K8;
    //         Upravená JC = JC × IO; NHZP = průměr(Upravené JC) × plocha_našeho_domu
    let adjustedNhzp = 0;
    const hasCustomCoeffs = Object.keys(customCoeffs).length > 0;

    if (valuation?.details?.odhad_czk) {
        adjustedNhzp = valuation.details.odhad_czk;
        const samples = valuation.details.vzorky || [];

        // Podlahová plocha – přednostně z backendu, fallback na setupData
        const backendArea = valuation.details.plocha_ocenovaneho || 0;
        const rawArea = backendArea > 0
            ? backendArea
            : (parseFloat(String(setupData.plocha).replace(',', '.').replace(/[^0-9.]/g, '')) || 0);
        const analyzedArea = rawArea > 0 ? Math.min(rawArea, 500) : 0;

        const parseK = (val: any, key: string): number => {
            const strVal = String(val ?? '1.0');
            let num = parseFloat(strVal.replace(',', '.')) || 1.0;
            // Ochrana proti tomu, když AI vrátí procenta (85 místo 0.85)
            if (num > 5.0) num = num / 100.0;
            // Per-key ranges přesně dle backendu (COEFFICIENT_RANGES)
            const ranges: Record<string, [number, number]> = {
                'k1': [0.80, 0.90],
                'k2': [0.90, 1.10],
                'k3': [0.90, 1.10],
                'k4': [0.85, 1.15],
                'k5': [0.80, 1.20],
                'k6': [0.90, 1.10],
                'k7': [0.95, 1.05],
                'k8': [0.95, 1.05],
            };
            const [lo, hi] = ranges[key] || [0.80, 1.20];
            return Math.max(lo, Math.min(num, hi));
        };

        // Přepočítej NHZP pokud uživatel upravil koeficienty NEBO vždy (pro konzistenci)
        if (samples.length > 0 && analyzedArea > 0) {
            let totalUpravenaJc = 0;

            samples.forEach((s: any) => {
                const kData = hasCustomCoeffs ? (customCoeffs[s.id] || s.koeficienty || {}) : (s.koeficienty || {});

                // Index odlišnosti = součin K1..K8
                let io = 1.0;
                ['k1', 'k2', 'k3', 'k4', 'k5', 'k6', 'k7', 'k8'].forEach(k => {
                    io *= parseK(kData[k], k);
                });

                // Jednotková cena vzorku (Kč/m²)
                const strVelikost = String(s.velikost_domu_m2 ?? '0');
                const sampleArea = Math.max(parseFloat(strVelikost.replace(/[^0-9.]/g, '')) || 1, 10);
                const jc = s.cena_czk / sampleArea;

                // Upravená JC = JC × IO
                totalUpravenaJc += jc * io;
            });

            const avgUpravenaJc = totalUpravenaJc / samples.length;
            const computed = Math.round(avgUpravenaJc * analyzedArea);

            // Sanity checks:
            // 1. Nesmí překročit 1.5× AI odhad
            const aiEstimate = valuation.details.odhad_czk;
            // 2. Absolutní strop 25 mil Kč pro běžný RD
            const maxAbsolute = 25_000_000;
            // 3. Nesmí překročit max cenu vzorku * 1.15
            const maxSamplePrice = Math.max(...samples.map((s: any) => s.cena_czk || 0));
            const maxFromSamples = Math.round(maxSamplePrice * 1.15);

            let finalNhzp = computed;
            if (aiEstimate > 0 && finalNhzp > aiEstimate * 1.5) {
                finalNhzp = Math.round(aiEstimate * 1.5);
            }
            if (maxFromSamples > 0 && finalNhzp > maxFromSamples) {
                finalNhzp = maxFromSamples;
            }
            if (finalNhzp > maxAbsolute) {
                finalNhzp = maxAbsolute;
            }
            adjustedNhzp = finalNhzp;

        } else if (samples.length > 0) {
            // Nelze přepočítat NHZP bez zadané plochy – zobrazíme AI odhad
            adjustedNhzp = valuation.details.odhad_czk || 0;
        }
    }


    const handleDownloadPdf = async () => {
        setIsDownloading(true);
        try {
            await generatePdfReport({
                result,
                valuation,
                adjustedNhzp: adjustedNhzp || undefined,
                apiBase: API_BASE,
            });
        } catch (err: any) {
            alert('Chyba pri generovani PDF: ' + err.message);
        } finally {
            setIsDownloading(false);
        }
    };

    const semaphore = result.semaphore || 'UNKNOWN';
    const semaphoreColor = result.semaphore_color || 'gray';
    const finalCategory = result.final_category;
    const agents = result.agents || {};
    const strategist = agents['Strateg'];
    const humanReport = strategist?.result?.details?.human_report || strategist?.result?.summary || '';

    const semaphoreLabel = semaphoreColor === 'green'
        ? 'Proces může pokračovat online'
        : semaphoreColor === 'orange'
            ? 'Vyžaduje dohled pracovníka'
            : 'Vrátit klientovi k doplnění';

    const semaphoreIcon = semaphoreColor === 'green' ? '✅' : semaphoreColor === 'orange' ? '⚠️' : '🔴';

    const photoIds = Object.keys(agents['Strazce']?.result?.details?.classifications || {});

    const renderWithLinks = (text: string | React.ReactNode) => {
        if (typeof text !== 'string' || !text) return text;
        // Záchytná skupina pro 32znakový HEX nebo jedno ze známých uložených ID,
        // navíc k němu volitelně připojíme případnou příponu nalezenou v textu.
        const escapedIds = photoIds.map(id => id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
        const knownIdsPattern = escapedIds.length > 0 ? `|${escapedIds.join('|')}` : '';
        const combinedRegex = new RegExp(`((?:[a-f0-9]{32}${knownIdsPattern})(?:\\.(?:jpg|jpeg|png))?)`, 'gi');
        
        const parts = text.split(combinedRegex);
        return parts.map((part, i) => {
            // Protože se dělí přes string s parsováním (capture group), každý lichý prvek
            // je hledaný shluk zachycený naším Regexem.
            if (i % 2 !== 0 && part) {
                // Odstranění přípony z UUID jen pro účely konstrukce adresy backendu
                const cleanId = part.replace(/\.(jpg|jpeg|png)$/i, '');
                return (
                    <a
                        key={i}
                        href={`${API_BASE}/uploads/${result.session_id}/${cleanId}.jpg`}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: '#3b82f6', textDecoration: 'underline', fontWeight: 500 }}
                        title="Zobrazit detail fotky"
                        onClick={(e) => e.stopPropagation()}
                    >
                        {part}
                    </a>
                );
            }
            return part;
        });
    };

    const getStatusBadge = (status: string) => {
        switch (status) {
            case 'success': return { text: 'Bez nálezu', class: 'badgeSuccess' };
            case 'warn': return { text: 'Varování', class: 'badgeWarn' };
            case 'fail': return { text: 'Problém', class: 'badgeFail' };
            default: return { text: '–', class: '' };
        }
    };

    return (
        <section className={styles.section}>
            <div className={styles.container}>

                {/* ── Verdict Header ── */}
                <div className={`${styles.verdictCard} ${styles[`verdict_${semaphoreColor}`]}`}>
                    <div className={styles.verdictLeft}>
                        <span className={styles.verdictIcon}>{semaphoreIcon}</span>
                        <div>
                            <h2 className={styles.verdictTitle}>{semaphore}</h2>
                            <p className={styles.verdictSubtitle}>{semaphoreLabel}</p>
                        </div>
                    </div>
                    {agents?.['Inspektor']?.result?.details?.verdikt && (
                        <div className={styles.categoryChip}>
                            <span className={styles.categoryLabel}>Online ocenění</span>
                            <span className={styles.categoryValue} style={{
                                color: agents['Inspektor'].result!.details.verdikt === 'ANO' ? '#10b981' : '#ef4444'
                            }}>
                                {agents['Inspektor'].result!.details.verdikt}
                            </span>
                        </div>
                    )}
                </div>

                {/* ── PDF Download Action ── */}
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '16px' }}>
                    <button 
                        className={styles.downloadBtn} 
                        onClick={handleDownloadPdf}
                        disabled={isDownloading}
                    >
                        {isDownloading ? (
                            <span className={styles.spinner} style={{ width: '16px', height: '16px', border: '2px solid white', borderTopColor: 'transparent' }} />
                        ) : (
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v4" />
                                <polyline points="7 10 12 15 17 10" />
                                <line x1="12" y1="15" x2="12" y2="3" />
                            </svg>
                        )}
                        <span>{isDownloading ? 'Generuji PDF...' : 'Stáhnout PDF report'}</span>
                    </button>
                </div>

                {/* ── Valuation Button ── */}
                {!isSetupOpen && !valuation && (
                    <div style={{ marginTop: '16px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                        <button
                            className="btn btn-primary"
                            style={{ background: '#1428A0', fontSize: '16px', padding: '14px 28px', width: '100%', maxWidth: '420px', display: 'flex', justifyContent: 'center', gap: '8px', borderRadius: '12px', border: 'none', color: '#fff', fontWeight: 700, cursor: 'pointer', boxShadow: '0 2px 12px rgba(20,40,160,0.2)' }}
                            onClick={openSetup}
                            disabled={isValuing}
                        >
                            <span>💰</span>
                            {isValuing ? 'Vypracovávám odhad online...' : 'Vypracovat tržní odhad (porovnávací metoda)'}
                        </button>
                        {valError && <div style={{ color: '#ef4444', fontSize: '13px' }}>{valError}</div>}
                    </div>
                )}

                {/* ── Valuation Setup Form ── */}
                {isSetupOpen && (
                    <div className={styles.comparisonCard} style={{ marginTop: '24px', border: '2px solid #1428A0', background: '#f0f2ff', padding: '24px' }}>
                        <h3 className={styles.comparisonTitle} style={{ color: '#1428A0', marginBottom: '16px' }}>⚙️ Nastavení parametrů pro ocenění</h3>
                        <p style={{ fontSize: '14px', color: '#475569', marginBottom: '16px' }}>Zkontrolujte a případně upravte vstupní údaje před odesláním umělé inteligenci pro srovnávací metodu.</p>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '20px' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                <label style={{ fontSize: '13px', fontWeight: 600, color: '#334155' }}>Cílová adresa:</label>
                                <input type="text" value={setupData.adresa} onChange={(e) => setSetupData(p => ({ ...p, adresa: e.target.value }))} style={{ padding: '10px 12px', borderRadius: '10px', border: '1px solid #e8ecf1', fontSize: '14px', outline: 'none' }} />
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                    <label style={{ fontSize: '13px', fontWeight: 600, color: '#334155' }}>Užitná/Podlahová plocha (m²):</label>
                                    <input type="text" value={setupData.plocha} onChange={(e) => setSetupData(p => ({ ...p, plocha: e.target.value }))} style={{ padding: '10px 12px', borderRadius: '10px', border: '1px solid #e8ecf1', fontSize: '14px', outline: 'none' }} />
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                    <label style={{ fontSize: '13px', fontWeight: 600, color: '#334155' }}>Plocha pozemku (m²):</label>
                                    <input type="text" value={setupData.pozemek} onChange={(e) => setSetupData(p => ({ ...p, pozemek: e.target.value }))} style={{ padding: '10px 12px', borderRadius: '10px', border: '1px solid #e8ecf1', fontSize: '14px', outline: 'none' }} />
                                </div>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                <label style={{ fontSize: '13px', fontWeight: 600, color: '#334155' }}>Technický stav objektu:</label>
                                <input type="text" value={setupData.stav} onChange={(e) => setSetupData(p => ({ ...p, stav: e.target.value }))} style={{ padding: '10px 12px', borderRadius: '10px', border: '1px solid #e8ecf1', fontSize: '14px', outline: 'none' }} />
                            </div>
                        </div>

                        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                            <button className="btn btn-secondary" onClick={() => setIsSetupOpen(false)} style={{ padding: '12px 24px', borderRadius: '10px' }}>Zrušit</button>
                            <button className="btn btn-primary" onClick={confirmSetup} style={{ padding: '12px 24px', background: '#1428A0', borderRadius: '10px', border: 'none', color: '#fff', fontWeight: 700, cursor: 'pointer' }}>Spočítat NHZP</button>
                        </div>
                    </div>
                )}

                {/* ── Valuation Results ── */}
                {valuation && valuation.details && (
                    <div className={styles.comparisonCard} style={{ marginTop: '24px', border: '1px solid #d8deff', background: 'linear-gradient(135deg, #f5f7ff 0%, #ffffff 40%)' }}>
                        <div className={styles.comparisonHeader}>
                            <h3 className={styles.comparisonTitle} style={{ color: '#1428A0' }}>
                                📊 Tržní odhad (NHZP)
                            </h3>
                        </div>

                        {/* ── Main Price + Range + Confidence ── */}
                        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '32px', padding: '16px 0', flexWrap: 'wrap' }}>
                            <div style={{ textAlign: 'center', flex: '1 1 auto' }}>
                                <div style={{ fontSize: '14px', color: '#475569', marginBottom: '4px' }}>Odhadovaná obvyklá cena</div>
                                <div style={{ fontSize: '40px', fontWeight: 800, color: '#1428A0', letterSpacing: '-1px' }}>
                                    {adjustedNhzp.toLocaleString('cs-CZ')} Kč
                                </div>
                                {valuation.details.odhad_min && valuation.details.odhad_max && (
                                    <div style={{ fontSize: '14px', color: '#64748b', marginTop: '4px' }}>
                                        Cenové rozpětí: {valuation.details.odhad_min.toLocaleString('cs-CZ')} – {valuation.details.odhad_max.toLocaleString('cs-CZ')} Kč
                                    </div>
                                )}
                                {valuation.details.benchmark && (
                                    <div style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', marginTop: '10px', background: '#ecfdf5', border: '1px solid #86efac', borderRadius: '100px', padding: '6px 16px', fontSize: '13px', color: '#166534', fontWeight: 600 }}>
                                        📍 Prům. cena v {valuation.details.benchmark.okres}: {valuation.details.benchmark.czk_per_m2.toLocaleString('cs-CZ')} Kč/m²
                                    </div>
                                )}
                            </div>

                            {/* ── Confidence Gauge ── */}
                            {valuation.details.confidence && (
                                <div style={{ flex: '0 0 auto', textAlign: 'center' }}>
                                    <div style={{ position: 'relative', width: '90px', height: '90px' }}>
                                        <svg width="90" height="90" viewBox="0 0 90 90">
                                            <circle cx="45" cy="45" r="38" fill="none" stroke="#e2e8f0" strokeWidth="8" />
                                            <circle
                                                cx="45" cy="45" r="38" fill="none"
                                                stroke={valuation.details.confidence.score >= 70 ? '#22c55e' : valuation.details.confidence.score >= 40 ? '#f59e0b' : '#ef4444'}
                                                strokeWidth="8"
                                                strokeDasharray={`${(valuation.details.confidence.score / 100) * 238.76} 238.76`}
                                                strokeLinecap="round"
                                                transform="rotate(-90 45 45)"
                                            />
                                        </svg>
                                        <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', fontSize: '20px', fontWeight: 800, color: valuation.details.confidence.score >= 70 ? '#22c55e' : valuation.details.confidence.score >= 40 ? '#f59e0b' : '#ef4444' }}>
                                            {valuation.details.confidence.score}%
                                        </div>
                                    </div>
                                    <div style={{ fontSize: '11px', color: '#64748b', marginTop: '4px' }}>Spolehlivost</div>
                                    {/* Confidence factors tooltip */}
                                    <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px', display: 'flex', flexDirection: 'column', gap: '1px' }}>
                                        {valuation.details.confidence.factors?.slice(0, 3).map((f: any, i: number) => (
                                            <span key={i}>{f.points > 0 ? '✓' : '·'} {f.label}</span>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>

                        <div style={{ fontSize: '14px', color: '#64748b', maxWidth: '600px', margin: '8px auto', textAlign: 'center' }}>
                            {valuation.details.duvod}
                        </div>

                        {/* ── Historical prices from LV ── */}
                        {(() => {
                            const katAgent = agents['KatastralniAnalytik'];
                            const acqTitles = katAgent?.result?.details?.acquisition_titles || [];
                            const priced = acqTitles.filter((t: any) => t.price_czk > 0);
                            if (priced.length === 0) return null;
                            return (
                                <div style={{ marginTop: '14px', background: '#fff7ed', border: '1px solid #fed7aa', borderRadius: '14px', padding: '14px 18px' }}>
                                    <div style={{ fontSize: '13px', fontWeight: 600, color: '#9a3412', marginBottom: '6px' }}>📜 Historické kupní ceny (z LV)</div>
                                    {priced.map((t: any, i: number) => (
                                        <div key={i} style={{ fontSize: '13px', color: '#78350f' }}>
                                            {t.type}{t.date ? ` (${t.date})` : ''}: <strong>{t.price_czk.toLocaleString('cs-CZ')} Kč</strong>
                                        </div>
                                    ))}
                                </div>
                            );
                        })()}

                        {/* ── LEAFLET MAP ── */}
                        {valuation.details.property_gps && (
                            <ValuationMap
                                propertyGps={valuation.details.property_gps}
                                samples={valuation.details.vzorky || []}
                            />
                        )}

                        <div style={{ marginTop: '16px' }}>
                            <h4 style={{ fontSize: '15px', fontWeight: 600, color: '#334155', marginBottom: '12px' }}>Srovnávací vzorky (upravte koeficienty pro automatický přepočet)</h4>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                {valuation.details.vzorky?.map((s: any) => {
                                    const currentCoeff = customCoeffs[s.id] !== undefined ? customCoeffs[s.id] : String(s.koeficient_podobnosti);
                                    return (
                                        <div key={s.id} style={{ background: '#fff', padding: '20px', borderRadius: '16px', border: '1px solid #e8ecf1', display: 'flex', flexDirection: 'column', gap: '10px', boxShadow: '0 1px 8px rgba(20,40,160,0.04)' }}>
                                            {s.obrazek_url && (
                                                <img src={s.obrazek_url} alt="Srovnávací vzorek" style={{ width: '100%', height: '220px', objectFit: 'cover', borderRadius: '12px', marginBottom: '8px' }} />
                                            )}
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                                <div>
                                                    <div style={{ fontWeight: 700, color: '#0f172a', fontSize: '15px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                        {s.adresa}
                                                        {s.zdroj_url && (
                                                            <a href={s.zdroj_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '12px', fontWeight: 700, color: '#1428A0', textDecoration: 'none', background: '#eef1ff', padding: '3px 10px', borderRadius: '100px', border: '1px solid #c7d0ff' }}>
                                                                Otevřít inzerát ↗
                                                            </a>
                                                        )}
                                                    </div>
                                                    <div style={{ fontSize: '13px', color: '#64748b', marginTop: '4px' }}>
                                                        Dům: {s.velikost_domu_m2} m² | Pozemek: {s.velikost_pozemku_m2} m²
                                                        {s.stav ? ` | ${s.stav}` : ''}
                                                        {s.rok_stavby ? ` | ${s.rok_stavby}` : ''}
                                                        {s.distance_km != null && ` | ${s.distance_km} km`}
                                                    </div>
                                                </div>
                                                <div style={{ textAlign: 'right' }}>
                                                    <div style={{ fontWeight: 700, color: '#0f172a', fontSize: '16px' }}>{s.cena_czk.toLocaleString('cs-CZ')} Kč</div>
                                                    {s.upravena_jc > 0 && (
                                                        <div style={{ fontSize: '12px', color: '#64748b' }}>JC: {s.jc?.toLocaleString('cs-CZ')} Kč/m² → {s.upravena_jc?.toLocaleString('cs-CZ')} Kč/m²</div>
                                                    )}
                                                </div>
                                            </div>
                                            <div style={{ fontSize: '13px', color: '#475569', background: '#f8fafc', padding: '10px 14px', borderRadius: '10px' }}>
                                                {s.oduvodneni_koeficientu}
                                            </div>
                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginTop: '6px', borderTop: '1px solid #e8ecf1', paddingTop: '14px' }}>
                                                {['k1', 'k2', 'k3', 'k4', 'k5', 'k6', 'k7', 'k8'].map(k => {
                                                    const kData = customCoeffs[s.id] || s.koeficienty || {};
                                                    const currentCoeff = kData[k] !== undefined ? String(kData[k]) : '1';
                                                    return (
                                                        <div key={k} style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                                            <label style={{ fontSize: '10px', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', textAlign: 'center', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={K_LABELS[k]}>{K_LABELS[k]}</label>
                                                            <input
                                                                type="text"
                                                                value={currentCoeff}
                                                                onChange={(e) => handleCoeffChange(s.id, k, e.target.value)}
                                                                style={{ width: '100%', padding: '6px 4px', borderRadius: '8px', border: '1px solid #e8ecf1', fontSize: '13px', textAlign: 'center', outline: 'none' }}
                                                            />
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    </div>
                )}

                {/* ── Meta info ── */}
                <div className={styles.metaStrip}>
                    <span>Doba analýzy: {result.total_time?.toFixed(1)}s</span>
                    <span>•</span>
                    <span>Pipeline: {result.pipeline_id}</span>
                    {finalCategory && (
                        <>
                            <span>•</span>
                            <span>Kategorie: {finalCategory}</span>
                        </>
                    )}
                </div>

                {/* ── Order 2: Photo Completeness (Strazce) ── */}
                {(() => {
                    const guardAgent = agents['Strazce'];
                    const guardDetails = guardAgent?.result?.details;
                    if (!guardDetails) return null;

                    const missing = guardDetails.missing_views || [];
                    const statusColor = missing.length === 0 ? '#10b981' : (guardAgent.result?.status === 'fail' ? '#ef4444' : '#f59e0b');
                    const statusIcon = missing.length === 0 ? '✓' : (guardAgent.result?.status === 'fail' ? '✗' : '⚠');
                    const statusText = missing.length === 0 ? 'Kompletní fotodokumentace' : 'Neúplná fotodokumentace';

                    return (
                        <div className={styles.comparisonCard}>
                            <div className={styles.comparisonHeader}>
                                <h3 className={styles.comparisonTitle}>
                                    🛡️ Kontrola fotodokumentace
                                </h3>
                                <span
                                    className={styles.comparisonVerdictBadge}
                                    style={{ background: `${statusColor}22`, color: statusColor, borderColor: `${statusColor}44` }}
                                >
                                    {statusIcon} {statusText}
                                </span>
                            </div>
                            <div className={styles.comparisonText}>
                                <p>{guardAgent?.result?.summary || 'Fotografie byly úspěšně zkontrolovány.'}</p>
                            </div>
                            {missing.length > 0 && (
                                <div className={styles.featureCol} style={{ marginTop: '12px' }}>
                                    <span className={styles.featureLabel}>Chybějící pohledy</span>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                        {missing.map((m: string, i: number) => (
                                            <span key={i} className={styles.featureTag + ' ' + styles.featureDiff}>{m}</span>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    );
                })()}

                {/* ── Order 3: Technical State (Inspektor) ── */}
                {(() => {
                    const inspAgent = agents['Inspektor'];
                    const inspDetails = inspAgent?.result?.details;
                    if (!inspDetails) return null;

                    const verdikt = inspDetails.verdikt;
                    const statusColor = verdikt === 'ANO' ? '#10b981' : '#ef4444';
                    const statusIcon = verdikt === 'ANO' ? '✓' : '✗';

                    return (
                        <div className={styles.comparisonCard}>
                            <div className={styles.comparisonHeader}>
                                <h3 className={styles.comparisonTitle}>
                                    🔍 Technický stav (Online Ocenění)
                                </h3>
                                <span
                                    className={styles.comparisonVerdictBadge}
                                    style={{ background: `${statusColor}22`, color: statusColor, borderColor: `${statusColor}44` }}
                                >
                                    {statusIcon} {verdikt === 'ANO' ? 'Způsobilé' : 'Nezpůsobilé'}
                                </span>
                            </div>
                            <div className={styles.comparisonText}>
                                <p><strong>Důvod:</strong> {inspDetails.duvod}</p>
                            </div>

                            {inspAgent.result?.warnings && inspAgent.result.warnings.length > 0 && (
                                <div className={styles.featureCol} style={{ marginTop: '12px' }}>
                                    <span className={styles.featureLabel}>Upozornění AI</span>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                        {inspAgent.result.warnings.map((w: string, i: number) => (
                                            <span key={i} className={styles.warnLine}>⚠️ {w}</span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {inspDetails.defects && inspDetails.defects.length > 0 && (
                                <div className={styles.featureCol} style={{ marginTop: '16px' }}>
                                    <span className={styles.featureLabel}>Zjištěné vady a nedostatky</span>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                                        {inspDetails.defects.map((f: any, i: number) => (
                                            <span key={i} className={styles.featureTag + ' ' + styles.featureDiff}>{f.description}</span>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                    );
                })()}

                {/* ── Order 1: Verdict Header (KEPT AS IS) ── */}
                {/* ── Order 2: Visual Comparison (GeoValidator) ── */}
                {(() => {
                    const geoAgent = agents['GeoValidator'];
                    const geoDetails = geoAgent?.result?.details;
                    const cmp = geoDetails?.visual_comparison;
                    const panoramaUrl = geoDetails?.panorama_url;
                    const frontPhotoId = geoDetails?.front_photo_id;

                    // Find the front photo path from the pipeline result images
                    const allImages = Object.values(agents).flatMap(
                        (a: any) => a?.result?.details?.classifications || []
                    );

                    if (!cmp || !panoramaUrl) return null;

                    const verdictColor = cmp.match_verdict === 'shoda'
                        ? '#10b981'
                        : cmp.match_verdict === 'neshoda'
                            ? '#ef4444'
                            : '#f59e0b';

                    const verdictLabel = cmp.match_verdict === 'shoda'
                        ? '✓ Shoda'
                        : cmp.match_verdict === 'neshoda'
                            ? '✗ Neshoda'
                            : '⚠ Možná shoda';

                    return (
                        <div className={styles.comparisonCard}>
                            <div className={styles.comparisonHeader}>
                                <h3 className={styles.comparisonTitle}>
                                    📍 Vizuální porovnání s panoramou
                                </h3>
                                <span
                                    className={styles.comparisonVerdictBadge}
                                    style={{ background: `${verdictColor}22`, color: verdictColor, borderColor: `${verdictColor}44` }}
                                >
                                    {verdictLabel}
                                    {cmp.confidence != null && (
                                        <span className={styles.confidenceTag}>
                                            {Math.round(cmp.confidence * 100)}%
                                        </span>
                                    )}
                                </span>
                            </div>

                            <div className={styles.comparisonImages}>
                                {frontPhotoId && (
                                    <div className={styles.comparisonImgWrap}>
                                        <span className={styles.imgLabel}>Nahrané foto</span>
                                        <div className={styles.imgFrame}>
                                            <img
                                                src={`${API_BASE}/uploads/${result.session_id}/${frontPhotoId}.jpg`}
                                                alt="Nahrané foto"
                                                className={styles.comparisonImg}
                                                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                            />
                                        </div>
                                    </div>
                                )}
                                <div className={styles.comparisonImgWrap}>
                                    <span className={styles.imgLabel}>Panorama – Mapy.cz</span>
                                    <div className={styles.imgFrame}>
                                        <img
                                            src={`${API_BASE}${panoramaUrl}`}
                                            alt="Panorama z Mapy.cz"
                                            className={styles.comparisonImg}
                                        />
                                    </div>
                                </div>
                            </div>

                            <div className={styles.comparisonText}>
                                <p>{cmp.comparison_text}</p>
                            </div>

                            {(cmp.matching_features?.length > 0 || cmp.differing_features?.length > 0) && (
                                <div className={styles.featureGrid}>
                                    {cmp.matching_features?.length > 0 && (
                                        <div className={styles.featureCol}>
                                            <span className={styles.featureLabel}>✓ Shodné prvky</span>
                                            {cmp.matching_features.map((f: string, i: number) => (
                                                <span key={i} className={styles.featureTag + ' ' + styles.featureMatch}>{f}</span>
                                            ))}
                                        </div>
                                    )}
                                    {cmp.differing_features?.length > 0 && (
                                        <div className={styles.featureCol}>
                                            <span className={styles.featureLabel}>✗ Odlišné prvky</span>
                                            {cmp.differing_features.map((f: string, i: number) => (
                                                <span key={i} className={styles.featureTag + ' ' + styles.featureDiff}>{f}</span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}

                            {cmp.notes && (
                                <p className={styles.comparisonNote}>
                                    💡 {cmp.notes}
                                </p>
                            )}
                        </div>
                    );
                })()}



                {/* ── Order 5: Document Comparator Results (MOVED UP) ── */}

                {/* ── Order 6: KatastralniAnalytik: Ortofoto + Risks (MOVED UP) ── */}
                {(() => {
                    const cadAgent = agents['KatastralniAnalytik'];
                    const cadDetails = cadAgent?.result?.details;
                    if (!cadDetails || cadDetails.skipped) return null;

                    const ortofotoUrl = cadDetails.ortofoto_annotated_url || cadDetails.ortofoto_url;
                    const originalUrl = cadDetails.ortofoto_url;
                    const risks = cadDetails.risks || [];
                    const analysis = cadDetails.ortofoto_analysis;
                    const lvData = cadDetails.lv_data;

                    const riskColors: Record<string, string> = {
                        'vysoké': '#ef4444',
                        'střední': '#f59e0b',
                        'nízké': '#22c55e',
                    };

                    return (
                        <div className={styles.comparisonCard}>
                            <div className={styles.comparisonHeader}>
                                <h3 className={styles.comparisonTitle}>
                                    🏛️ Katastr & LV — ortofoto funkčního celku
                                </h3>
                                {lvData && (
                                    <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                                        LV {lvData.lv_number} · k.ú. {lvData.kat_uzemi_nazev}
                                    </span>
                                )}
                            </div>

                            {/* Ortofoto image */}
                            {ortofotoUrl && (
                                <div style={{ margin: '16px 0' }}>
                                    <div style={{
                                        border: '1px solid var(--border-color)',
                                        borderRadius: '12px',
                                        overflow: 'hidden',
                                        background: 'var(--bg-secondary)',
                                    }}>
                                        <img
                                            src={`${API_BASE}${ortofotoUrl}`}
                                            alt="Ortofoto funkčního celku"
                                            style={{ width: '100%', display: 'block' }}
                                            onError={(e) => {
                                                // Fallback to original if annotated fails
                                                if (originalUrl && (e.target as HTMLImageElement).src.includes('annotated')) {
                                                    (e.target as HTMLImageElement).src = `${API_BASE}${originalUrl}`;
                                                }
                                            }}
                                        />
                                    </div>
                                    <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px', textAlign: 'center' }}>
                                        Ortofoto ČÚZK — {cadDetails.ortofoto_annotated_url ? 'se zvýrazněnými stavbami' : 'funkční celek'}
                                    </div>
                                </div>
                            )}

                            {/* Overall assessment from AI */}
                            {analysis?.overall_assessment && (
                                <div className={styles.comparisonText}>
                                    <p>{analysis.overall_assessment}</p>
                                </div>
                            )}

                            {/* LV Risk summary */}
                            {cadDetails.lv_risk_summary && (
                                <div className={styles.comparisonText} style={{ marginTop: '8px' }}>
                                    <p>📋 {cadDetails.lv_risk_summary}</p>
                                </div>
                            )}

                            {/* Access assessment */}
                            {cadDetails.access_assessment && (() => {
                                const access = cadDetails.access_assessment;
                                const aColor = access.status === 'zajištěný' ? '#22c55e'
                                    : access.status === 'nezajištěný' ? '#ef4444' : '#f59e0b';
                                const aIcon = access.status === 'zajištěný' ? '✓'
                                    : access.status === 'nezajištěný' ? '✗' : '?';
                                return (
                                    <div style={{
                                        marginTop: '10px',
                                        padding: '10px 14px',
                                        borderRadius: '8px',
                                        border: `1px solid ${aColor}33`,
                                        background: `${aColor}08`,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '10px',
                                    }}>
                                        <span style={{
                                            fontSize: '16px',
                                            fontWeight: 700,
                                            color: aColor,
                                            width: '24px',
                                            textAlign: 'center',
                                        }}>{aIcon}</span>
                                        <div>
                                            <div style={{ fontSize: '13px', fontWeight: 600, color: aColor }}>
                                                Přístup k nemovitosti: {access.status}
                                            </div>
                                            {access.reason && (
                                                <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginTop: '2px' }}>
                                                    {access.reason}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                );
                            })()}

                            {/* Risks table */}
                            {risks.length > 0 && (
                                <div style={{ marginTop: '16px' }}>
                                    <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px', color: 'var(--text-secondary)' }}>
                                        Nalezená rizika
                                    </div>
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                                        {risks.map((r: any, i: number) => (
                                            <div key={i} style={{
                                                display: 'flex',
                                                alignItems: 'flex-start',
                                                gap: '10px',
                                                padding: '10px 12px',
                                                background: 'var(--bg-secondary)',
                                                border: `1px solid ${riskColors[r.severity] || '#ccc'}44`,
                                                borderRadius: '8px',
                                            }}>
                                                <span style={{
                                                    fontSize: '11px',
                                                    fontWeight: 700,
                                                    padding: '2px 8px',
                                                    borderRadius: '128px',
                                                    background: `${riskColors[r.severity] || '#ccc'}15`,
                                                    color: riskColors[r.severity] || '#666',
                                                    textTransform: 'uppercase',
                                                    whiteSpace: 'nowrap',
                                                    flexShrink: 0,
                                                }}>
                                                    {r.severity}
                                                </span>
                                                <div style={{ flex: 1, minWidth: 0 }}>
                                                    <div style={{ fontSize: '13px', color: 'var(--text-primary)' }}>
                                                        {r.description}
                                                    </div>
                                                    {r.recommendation && (
                                                        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '4px' }}>
                                                            💡 {r.recommendation}
                                                        </div>
                                                    )}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {risks.length === 0 && !cadDetails.skipped && (
                                <div style={{
                                    textAlign: 'center',
                                    padding: '16px',
                                    color: '#22c55e',
                                    fontSize: '14px',
                                }}>
                                    ✓ Žádná rizika v katastru nezjištěna
                                </div>
                            )}
                        </div>
                    );
                })()}

                {/* ── Order 7: Summary Report (MOVED DOWN) ── */}
                <div className={styles.reportCard}>
                    <div className={styles.reportHeader}>
                        <h3 className={styles.reportTitle}>Souhrnná zpráva</h3>
                    </div>
                    <div className={styles.reportBody}>
                        {humanReport.split('\n').map((line: string, i: number) => {
                            if (!line.trim()) return <br key={i} />;
                            // Bold lines that look like section headers
                            const isHeader = /^\d+\.|^\*\*|^Shrnutí|^Fotodokumentace|^Stav|^Věk|^Ověření|^Doporučení/i.test(line.trim());
                            return (
                                <p key={i} className={isHeader ? styles.reportSection : styles.reportText}>
                                    {renderWithLinks(line.replace(/\*\*/g, ''))}
                                </p>
                            );
                        })}
                    </div>
                </div>

                {/* ── Order 8: Agent Results Grid (MOVED DOWN) ── */}
                <h3 style={{ fontSize: '16px', fontWeight: 700, margin: '32px 0 16px', color: 'var(--text-primary)' }}>
                    Výsledky jednotlivých agentů
                </h3>
                <div className={styles.overviewGrid}>
                    {['Strazce', 'Inspektor', 'ForenzniAnalytik', 'Historik', 'GeoValidator', 'PorovnavacDokumentu', 'KatastralniAnalytik'].map(name => {
                        const agent = agents[name];
                        if (!agent) return null;
                        const meta = AGENT_META[name];
                        const badge = getStatusBadge(agent.result?.status || 'idle');
                        const details = agent.result?.details || {};
                        const warnings = agent.result?.warnings || [];
                        const isExpanded = expandedAgent === name;

                        return (
                            <div
                                key={name}
                                className={`${styles.overviewCard} ${styles[`ov_${agent.result?.status}`]} ${isExpanded ? styles.ovExpanded : ''}`}
                                onClick={() => setExpandedAgent(isExpanded ? null : name)}
                            >
                                <div className={styles.ovHeader}>
                                    <span className={styles.ovIcon}>{meta.icon}</span>
                                    <span className={`${styles.ovBadge} ${styles[badge.class]}`}>{badge.text}</span>
                                </div>
                                <h4 className={styles.ovTitle}>{meta.label}</h4>
                                <p className={styles.ovSummary}>
                                    {renderWithLinks(agent.result?.summary || '–')}
                                </p>

                                {/* Key details per agent */}
                                {name === 'Strazce' && details.classifications && (
                                    <div className={styles.ovDetails}>
                                        <span>📸 {Object.keys(details.classifications).length} fotek klasifikováno</span>
                                    </div>
                                )}
                                {name === 'Historik' && details.effective_age != null && (
                                    <div className={styles.ovDetails}>
                                        <span>📅 Efektivní věk: {details.effective_age} let</span>
                                        {agent.result?.category && <span>Kategorie: {agent.result.category}</span>}
                                    </div>
                                )}
                                {name === 'Inspektor' && details.verdikt && (
                                    <div className={styles.ovDetails}>
                                        <span>🔍 Online ocenění: {details.verdikt}</span>
                                    </div>
                                )}
                                {name === 'GeoValidator' && details.visual_comparison && (
                                    <div className={styles.ovDetails}>
                                        <span>🗺️ Shoda panorama: {Math.round(details.visual_comparison.confidence * 100)}%</span>
                                    </div>
                                )}
                                {name === 'KatastralniAnalytik' && details.risks && (
                                    <div className={styles.ovDetails}>
                                        <span>📋 {details.risks.length} rizik(a) nalezeno</span>
                                        {details.ortofoto_url && <span>🛰️ Ortofoto staženo</span>}
                                    </div>
                                )}

                                {agent.elapsed_time != null && (
                                    <span className={styles.ovTime}>{agent.elapsed_time.toFixed(1)}s</span>
                                )}

                                {isExpanded && agent.result && (
                                    <div className={styles.ovExpandedRaw} onClick={(e) => e.stopPropagation()}>
                                        {agent.result.warnings?.length > 0 && (
                                            <div className={styles.detailWarnings} style={{ marginBottom: 12 }}>
                                                {agent.result.warnings.map((w: string, i: number) => (
                                                    <div key={i} className={styles.warnLine}>⚠️ {renderWithLinks(w)}</div>
                                                ))}
                                            </div>
                                        )}
                                        {agent.result.errors?.length > 0 && (
                                            <div className={styles.detailErrors} style={{ marginBottom: 12 }}>
                                                {agent.result.errors.map((e: string, i: number) => (
                                                    <div key={i} className={styles.errLine}>❌ {renderWithLinks(e)}</div>
                                                ))}
                                            </div>
                                        )}
                                        {agent.result.details && name !== 'Strateg' && (
                                            <details className={styles.rawDetails} open>
                                                <summary className={styles.rawToggle}>Technická data</summary>
                                                <pre className={styles.rawJson}>
                                                    {JSON.stringify(agent.result.details, null, 2)}
                                                </pre>
                                            </details>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
                {(() => {
                    const docAgent = agents['PorovnavacDokumentu'];
                    const docDetails = docAgent?.result?.details;
                    if (!docDetails || docDetails.skipped) return null;

                    const verdict = docDetails.verdict || 'UNKNOWN';
                    const confidence = docDetails.confidence || 0;
                    const checks = docDetails.checks || [];
                    const recommendations = docDetails.recommendations || [];
                    const overallSummary = docDetails.overall_summary || '';
                    const propData = docDetails.property_data || {};

                    const verdictColor = verdict === 'SHODA'
                        ? '#10b981'
                        : verdict === 'NESHODA'
                            ? '#ef4444'
                            : '#f59e0b';

                    const verdictLabel = verdict === 'SHODA'
                        ? '✓ Shoda'
                        : verdict === 'NESHODA'
                            ? '✗ Neshoda'
                            : '⚠ Částečná shoda';

                    return (
                        <div className={styles.comparisonCard}>
                            <div className={styles.comparisonHeader}>
                                <h3 className={styles.comparisonTitle}>
                                    📄 Porovnání PDF formuláře s fotodokumentací
                                </h3>
                                <span
                                    className={styles.comparisonVerdictBadge}
                                    style={{ background: `${verdictColor}22`, color: verdictColor, borderColor: `${verdictColor}44` }}
                                >
                                    {verdictLabel}
                                    <span className={styles.confidenceTag}>
                                        {Math.round(confidence * 100)}%
                                    </span>
                                </span>
                            </div>

                            {/* Property data summary */}
                            {Object.keys(propData).length > 0 && (
                                <div className={styles.techDataSummary}>
                                    <h4 className={styles.techDataTitle}>📋 Technická data z formuláře</h4>
                                    <div className={styles.techDataGrid}>
                                        {propData.year_built && (
                                            <div className={styles.techDataItem}>
                                                <span className={styles.techDataLabel}>Rok dokončení</span>
                                                <span className={styles.techDataValue}>{propData.year_built}</span>
                                            </div>
                                        )}
                                        {propData.floor_count && (
                                            <div className={styles.techDataItem}>
                                                <span className={styles.techDataLabel}>Počet podlaží</span>
                                                <span className={styles.techDataValue}>{propData.floor_count}</span>
                                            </div>
                                        )}
                                        {propData.total_floor_area && (
                                            <div className={styles.techDataItem}>
                                                <span className={styles.techDataLabel}>Celk. podl. plocha</span>
                                                <span className={styles.techDataValue}>{propData.total_floor_area} m²</span>
                                            </div>
                                        )}
                                        {propData.roof_type && (
                                            <div className={styles.techDataItem}>
                                                <span className={styles.techDataLabel}>Typ střechy</span>
                                                <span className={styles.techDataValue}>{propData.roof_type}</span>
                                            </div>
                                        )}
                                        {propData.condition && (
                                            <div className={styles.techDataItem}>
                                                <span className={styles.techDataLabel}>Stav</span>
                                                <span className={styles.techDataValue}>{propData.condition}</span>
                                            </div>
                                        )}
                                        {propData.basement && (
                                            <div className={styles.techDataItem}>
                                                <span className={styles.techDataLabel}>Podsklepení</span>
                                                <span className={styles.techDataValue}>{propData.basement}</span>
                                            </div>
                                        )}
                                        {propData.heating && (
                                            <div className={styles.techDataItem}>
                                                <span className={styles.techDataLabel}>Vytápění</span>
                                                <span className={styles.techDataValue}>{propData.heating}</span>
                                            </div>
                                        )}
                                        {propData.property_address && (
                                            <div className={styles.techDataItem}>
                                                <span className={styles.techDataLabel}>Adresa</span>
                                                <span className={styles.techDataValue}>{propData.property_address}</span>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            )}

                            {overallSummary && (
                                <div className={styles.comparisonText}>
                                    <p>{overallSummary}</p>
                                </div>
                            )}

                            {/* Checks table */}
                            {checks.length > 0 && (
                                <div className={styles.checksTable}>
                                    <table>
                                        <thead>
                                            <tr>
                                                <th>Parametr</th>
                                                <th>Formulář</th>
                                                <th>Z fotek</th>
                                                <th>Shoda</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {checks.map((c: any, i: number) => (
                                                <tr key={i} className={c.match ? styles.checkMatch : styles.checkMismatch}>
                                                    <td className={styles.checkField}>{c.field}</td>
                                                    <td>{c.declared || '–'}</td>
                                                    <td>{c.observed || '–'}</td>
                                                    <td>
                                                        <span className={c.match ? styles.checkYes : styles.checkNo}>
                                                            {c.match ? '✓' : '✗'}
                                                        </span>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                    {checks.some((c: any) => c.note) && (
                                        <div className={styles.checkNotes}>
                                            {checks.filter((c: any) => c.note).map((c: any, i: number) => (
                                                <div key={i} className={styles.checkNote}>
                                                    <strong>{c.field}:</strong> {c.note}
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}

                            {recommendations.length > 0 && (
                                <div className={styles.comparisonNote}>
                                    <strong>💡 Doporučení:</strong>
                                    <ul style={{ margin: '6px 0 0 16px', padding: 0 }}>
                                        {recommendations.map((r: string, i: number) => (
                                            <li key={i} style={{ fontSize: '13px', marginBottom: '4px' }}>{r}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </div>
                    );
                })()}



                <div className={styles.actions}>
                    <button
                        className="btn"
                        onClick={onEdit}
                        style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}
                    >
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                            <path d="M10 2L13 5L5 13H2V10L10 2Z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        Upravit a spustit znovu
                    </button>
                    <button className="btn btn-primary" onClick={onReset}>
                        Nová analýza
                    </button>
                </div>
            </div>
        </section>
    );
}
