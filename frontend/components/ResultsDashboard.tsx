'use client';
import { useState } from 'react';
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
    // 1. Pro každý vzorek: jednotková cena (JC) = cena_vzorku / plocha_vzorku
    // 2. Index odlišnosti (IO) = K1 × K2 × ... × K8
    //    - K < 1.0 → vzorek je LEPŠÍ než náš dům → snižuje cenu
    //    - K > 1.0 → vzorek je HORŠÍ → zvyšuje cenu
    // 3. Upravená JC = JC × IO
    // 4. NHZP = průměr(upravené JC) × podlahová plocha našeho domu
    let adjustedNhzp = 0;
    if (valuation?.details?.odhad_czk) {
        adjustedNhzp = valuation.details.odhad_czk;
        const samples = valuation.details.vzorky || [];

        // Podlahová plocha NAŠEHO domu (ne pozemku!)
        const rawArea = parseFloat(String(setupData.plocha).replace(',', '.').replace(/[^0-9.]/g, '')) || 0;
        // Sanity check: podlahová plocha RD by neměla přesáhnout 500 m²
        const analyzedArea = rawArea > 0 ? Math.min(rawArea, 500) : 0;

        const parseK = (val: any): number => {
            const strVal = String(val ?? '1.0');
            let num = parseFloat(strVal.replace(',', '.')) || 1.0;
            // Ochrana proti tomu, když AI vrátí procenta (85 místo 0.85)
            if (num > 5.0) num = num / 100.0;
            // Koeficient musí být v rozumném rozmezí 0.55 – 1.45
            return Math.max(0.55, Math.min(num, 1.45));
        };

        if (samples.length > 0 && analyzedArea > 0) {
            let totalUpravenaJc = 0;

            samples.forEach((s: any) => {
                const kData = customCoeffs[s.id] || s.koeficienty || {};

                // Index odlišnosti = součin K1..K8
                let io = 1.0;
                ['k1', 'k2', 'k3', 'k4', 'k5', 'k6', 'k7', 'k8'].forEach(k => {
                    io *= parseK(kData[k]);
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

            // Sanity check: výsledek by neměl být více než 3× AI odhad
            const aiEstimate = valuation.details.odhad_czk;
            adjustedNhzp = (aiEstimate > 0 && computed > aiEstimate * 3)
                ? aiEstimate
                : computed;

        } else if (samples.length > 0) {
            // Fallback bez plochy – průměr cen vzorků × IO
            let totalVal = 0;
            samples.forEach((s: any) => {
                const kData = customCoeffs[s.id] || s.koeficienty || {};
                let io = 1.0;
                ['k1', 'k2', 'k3', 'k4', 'k5', 'k6', 'k7', 'k8'].forEach(k => {
                    io *= parseK(kData[k]);
                });
                totalVal += s.cena_czk * io;
            });
            adjustedNhzp = Math.round(totalVal / samples.length);
        }
    }

    const handleDownloadPdf = () => {
        setIsDownloading(true);
        try {
            generatePdfReport({
                result,
                valuation,
                adjustedNhzp: adjustedNhzp || undefined,
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

    const renderWithLinks = (text: string) => {
        if (!text || photoIds.length === 0) return text;
        // Escape photoIds for regex to be safe
        const escapedIds = photoIds.map(id => id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
        const regex = new RegExp(`(${escapedIds.join('|')})`, 'g');
        const parts = text.split(regex);
        return parts.map((part, i) => {
            if (photoIds.includes(part)) {
                return (
                    <a
                        key={i}
                        href={`${API_BASE}/uploads/${result.session_id}/${part}.jpg`}
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
                            style={{ background: '#3b82f6', fontSize: '16px', padding: '12px 24px', width: '100%', maxWidth: '400px', display: 'flex', justifyContent: 'center', gap: '8px' }}
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
                    <div className={styles.comparisonCard} style={{ marginTop: '24px', border: '2px solid #3b82f6', background: '#eff6ff', padding: '20px' }}>
                        <h3 className={styles.comparisonTitle} style={{ color: '#1e3a8a', marginBottom: '16px' }}>⚙️ Nastavení parametrů pro ocenění</h3>
                        <p style={{ fontSize: '14px', color: '#475569', marginBottom: '16px' }}>Zkontrolujte a případně upravte vstupní údaje před odesláním umělé inteligenci pro srovnávací metodu.</p>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '20px' }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                <label style={{ fontSize: '13px', fontWeight: 600, color: '#334155' }}>Cílová adresa:</label>
                                <input type="text" value={setupData.adresa} onChange={(e) => setSetupData(p => ({ ...p, adresa: e.target.value }))} style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                    <label style={{ fontSize: '13px', fontWeight: 600, color: '#334155' }}>Užitná/Podlahová plocha (m²):</label>
                                    <input type="text" value={setupData.plocha} onChange={(e) => setSetupData(p => ({ ...p, plocha: e.target.value }))} style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                    <label style={{ fontSize: '13px', fontWeight: 600, color: '#334155' }}>Plocha pozemku (m²):</label>
                                    <input type="text" value={setupData.pozemek} onChange={(e) => setSetupData(p => ({ ...p, pozemek: e.target.value }))} style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
                                </div>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                                <label style={{ fontSize: '13px', fontWeight: 600, color: '#334155' }}>Technický stav objektu:</label>
                                <input type="text" value={setupData.stav} onChange={(e) => setSetupData(p => ({ ...p, stav: e.target.value }))} style={{ padding: '8px', borderRadius: '6px', border: '1px solid #cbd5e1' }} />
                            </div>
                        </div>

                        <div style={{ display: 'flex', gap: '12px', justifyContent: 'flex-end' }}>
                            <button className="btn btn-secondary" onClick={() => setIsSetupOpen(false)} style={{ padding: '10px 20px' }}>Zrušit</button>
                            <button className="btn btn-primary" onClick={confirmSetup} style={{ padding: '10px 20px', background: '#3b82f6' }}>Spočítat NHZP</button>
                        </div>
                    </div>
                )}

                {/* ── Valuation Results ── */}
                {valuation && valuation.details && (
                    <div className={styles.comparisonCard} style={{ marginTop: '24px', border: '2px solid #3b82f6', background: '#eff6ff' }}>
                        <div className={styles.comparisonHeader}>
                            <h3 className={styles.comparisonTitle} style={{ color: '#1e3a8a' }}>
                                📊 Tržní odhad (NHZP)
                            </h3>
                        </div>
                        <div style={{ textAlign: 'center', padding: '16px 0' }}>
                            <div style={{ fontSize: '14px', color: '#475569', marginBottom: '4px' }}>Odhadovaná obvyklá cena</div>
                            <div style={{ fontSize: '36px', fontWeight: 800, color: '#1e40af' }}>
                                {adjustedNhzp.toLocaleString('cs-CZ')} Kč
                            </div>
                            <div style={{ fontSize: '14px', color: '#64748b', marginTop: '8px', maxWidth: '600px', margin: '8px auto 0' }}>
                                {valuation.details.duvod}
                            </div>
                        </div>

                        <div style={{ marginTop: '16px' }}>
                            <h4 style={{ fontSize: '15px', fontWeight: 600, color: '#334155', marginBottom: '12px' }}>Srovnávací vzorky (upravte koeficienty pro automatický přepočet)</h4>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                {valuation.details.vzorky?.map((s: any) => {
                                    const currentCoeff = customCoeffs[s.id] !== undefined ? customCoeffs[s.id] : String(s.koeficient_podobnosti);
                                    return (
                                        <div key={s.id} style={{ background: '#fff', padding: '16px', borderRadius: '12px', border: '1px solid #cbd5e1', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                            {s.obrazek_url && (
                                                <img src={s.obrazek_url} alt="Srovnávací vzorek" style={{ width: '100%', height: '220px', objectFit: 'cover', borderRadius: '8px', marginBottom: '8px' }} />
                                            )}
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                                                <div>
                                                    <div style={{ fontWeight: 700, color: '#0f172a', fontSize: '15px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                                        {s.adresa}
                                                        {s.zdroj_url && (
                                                            <a href={s.zdroj_url} target="_blank" rel="noopener noreferrer" style={{ fontSize: '12px', fontWeight: 600, color: '#2563eb', textDecoration: 'none', background: '#eff6ff', padding: '2px 8px', borderRadius: '12px', border: '1px solid #bfdbfe' }}>
                                                                Otevřít inzerát ↗
                                                            </a>
                                                        )}
                                                    </div>
                                                    <div style={{ fontSize: '13px', color: '#64748b', marginTop: '4px' }}>Dům: {s.velikost_domu_m2} m² | Pozemek: {s.velikost_pozemku_m2} m²</div>
                                                    <div style={{ fontSize: '13px', color: '#64748b' }}>Stav: {s.stav}</div>
                                                </div>
                                                <div style={{ textAlign: 'right' }}>
                                                    <div style={{ fontWeight: 700, color: '#0f172a', fontSize: '16px' }}>{s.cena_czk.toLocaleString('cs-CZ')} Kč</div>
                                                </div>
                                            </div>
                                            <div style={{ fontSize: '13px', color: '#475569', background: '#f8fafc', padding: '8px', borderRadius: '6px' }}>
                                                {s.oduvodneni_koeficientu}
                                            </div>
                                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '8px', marginTop: '4px', borderTop: '1px solid #e2e8f0', paddingTop: '12px' }}>
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
                                                                style={{ width: '100%', padding: '4px 4px', borderRadius: '4px', border: '1px solid #cbd5e1', fontSize: '13px', textAlign: 'center' }}
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
                                    {line.replace(/\*\*/g, '')}
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
                                    {agent.result?.summary || '–'}
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
