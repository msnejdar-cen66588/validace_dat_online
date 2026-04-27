'use client';
import { useState, useEffect, useRef } from 'react';
import styles from './PipelineCanvas.module.css';
import AgentDetail from './AgentDetail';
import type { UploadResponse } from '@/lib/api';
import type { WSMessage } from '@/hooks/useWebSocket';

interface Props {
    sessionId: string;
    agentStatuses: Record<string, string>;
    agentLogs: Record<string, WSMessage[]>;
    isRunning: boolean;
    onStart: () => void;
    onEdit: () => void;
    uploadData: UploadResponse | null;
}

const AGENTS_CONFIG = [
    {
        name: 'Strazce',
        label: 'Strážce',
        description: 'Kontrola úplnosti fotodokumentace (BR-G4)',
        long_description: 'Rozpoznává místnosti, hodnotí celkovou kvalitu a ostrost fotografií a hlídá, zda nechybí povinné záběry.',
        icon: '🛡️',
        color: '#1e6fd9',
        wave: 'A',
    },
    {
        name: 'ForenzniAnalytik',
        label: 'Forenzní analytik',
        description: 'Detekce manipulace a úprav fotografií',
        long_description: 'Detekuje potenciální podvody. Analyzuje EXIF metadata a hledá stopy po úpravách ve Photoshopu nebo AI generovaných fotkách.',
        icon: '🔬',
        color: '#6366f1',
        wave: 'A',
    },
    {
        name: 'Historik',
        label: 'Historik',
        description: 'Určení věku a kategorizace nemovitosti',
        long_description: 'Odhaduje skutečný věk stavby na základě vizuálních znaků (typ oken, fasáda, materiály) a porovnává s rokem dokončení.',
        icon: '📜',
        color: '#0891b2',
        wave: 'A',
    },
    {
        name: 'Inspektor',
        label: 'Inspektor',
        description: 'Hodnocení technického stavu objektu',
        long_description: 'Prohledává fotky a detekuje technické závady: praskliny, vlhkost, plísně a nedokončené stavební úpravy.',
        icon: '🔍',
        color: '#d97706',
        wave: 'A',
    },
    {
        name: 'PorovnavacDokumentu',
        label: 'DocComparator',
        description: 'Porovnání dat z formuláře vs fotky',
        long_description: 'Křížově ověřuje zjištěná data. Přepočítává podlaží a odhaduje podlahovou plochu zvenku vs zevnitř k zamezení zkreslení.',
        icon: '📄',
        color: '#ea580c',
        wave: 'B',
    },
    {
        name: 'KatastralniAnalytik',
        label: 'Katastrální analýza',
        description: 'Analýza LV – rizika, ortofoto, stavby',
        long_description: 'Stahuje a analyzuje data z Katastru nemovitostí a Listu vlastnictví. Hledá břemena a právní vady.',
        icon: '🏛️',
        color: '#7c3aed',
        wave: 'B',
    },
    {
        name: 'GeoValidator',
        label: 'GeoValidator',
        description: 'Ověření GPS lokace (Mapy.cz panorama)',
        long_description: 'Kontroluje přístupové cesty a rizika v okolí na základě ortofotomap a ověřuje lokaci focení.',
        icon: '📍',
        color: '#db2777',
        wave: 'B',
    },
    {
        name: 'Strateg',
        label: 'Stratég',
        description: 'Agregace výsledků a finální verdikt',
        long_description: 'Syntetizuje veškerá zjištění od předchozích agentů a vydává závěrečné rozhodnutí a doporučení pro odhadce.',
        icon: '🎯',
        color: '#059669',
        wave: 'C',
    },
];

// Wave metadata
const WAVES: Record<string, { label: string; agents: string[] }> = {
    A: { label: 'Vlna A – Analýza fotografií', agents: ['Strazce', 'ForenzniAnalytik', 'Historik', 'Inspektor'] },
    B: { label: 'Vlna B – Dokumenty & lokace', agents: ['PorovnavacDokumentu', 'KatastralniAnalytik', 'GeoValidator'] },
    C: { label: 'Vlna C – Finální verdikt', agents: ['Strateg'] },
};

const STATUS_LABELS: Record<string, string> = {
    idle: 'ČEKÁ',
    queued: 'VE FRONTĚ',
    processing: 'ZPRACOVÁVÁ',
    success: 'HOTOVO',
    fail: 'CHYBA',
    warn: 'UPOZORNĚNÍ',
};

export default function PipelineCanvas({
    sessionId,
    agentStatuses,
    agentLogs,
    isRunning,
    onStart,
    onEdit,
    uploadData,
}: Props) {
    const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
    const [started, setStarted] = useState(false);
    const [elapsed, setElapsed] = useState(0);
    // currentWave tracks which wave is active when WS data is not yet available
    const [simulatedWave, setSimulatedWave] = useState<string | null>(null);
    const startTimeRef = useRef<number | null>(null);

    // Timer
    useEffect(() => {
        if (!started) return;
        startTimeRef.current = Date.now();
        const timer = setInterval(() => {
            if (startTimeRef.current) {
                setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
            }
        }, 100);
        return () => clearInterval(timer);
    }, [started]);

    // Simulated wave progression (fallback when WS isn't delivering statuses)
    useEffect(() => {
        if (!started) return;
        const hasWsStatuses = Object.values(agentStatuses).some(s => s !== 'idle');
        if (hasWsStatuses) {
            setSimulatedWave(null);
            return;
        }
        // Simulate Wave A → B → C with rough timing
        setSimulatedWave('A');
        const tB = setTimeout(() => setSimulatedWave('B'), 20000);
        const tC = setTimeout(() => setSimulatedWave('C'), 35000);
        return () => { clearTimeout(tB); clearTimeout(tC); };
    }, [started, agentStatuses]);

    const handleStart = () => {
        setStarted(true);
        setElapsed(0);
        onStart();
    };

    const isTerminal = (s: string) => ['success', 'fail', 'warn'].includes(s);

    // ─── Determine effective status per agent ────────────────────────────────
    // Supports MULTIPLE agents being "processing" simultaneously (parallel waves).
    const getEffectiveStatus = (name: string): string => {
        if (!started) return 'idle';

        const ws = agentStatuses[name];

        // Real WS status takes priority if it's terminal
        if (ws && isTerminal(ws)) return ws;
        // Real WS says processing
        if (ws === 'processing') return 'processing';

        // If no WS data yet, fall back to simulation
        if (!Object.values(agentStatuses).some(s => s !== 'idle')) {
            const agent = AGENTS_CONFIG.find(a => a.name === name);
            const w = agent?.wave;
            if (!simulatedWave) return 'idle';
            const waveOrder = ['A', 'B', 'C'];
            const simIdx = waveOrder.indexOf(simulatedWave);
            const agentWaveIdx = waveOrder.indexOf(w || 'C');
            if (agentWaveIdx < simIdx) return 'success';
            if (agentWaveIdx === simIdx) return 'processing';
            return 'queued';
        }

        // WS data available but this agent hasn't reported yet
        // Derive from wave: if all agents in the previous wave are done, this wave is processing
        const agent = AGENTS_CONFIG.find(a => a.name === name);
        const wave = agent?.wave || 'C';
        const waveOrder = ['A', 'B', 'C'];
        const waveIdx = waveOrder.indexOf(wave);

        // All agents in waves before this one are terminal → this wave is active
        const previousWavesComplete = waveOrder.slice(0, waveIdx).every(prevWave => {
            const prevAgents = WAVES[prevWave].agents;
            return prevAgents.every(pa => {
                const s = agentStatuses[pa];
                return s && isTerminal(s);
            });
        });

        if (previousWavesComplete) {
            return ws === 'processing' ? 'processing' : (ws && isTerminal(ws) ? ws : 'processing');
        }

        return 'queued';
    };

    const completedCount = AGENTS_CONFIG.filter(a => isTerminal(getEffectiveStatus(a.name))).length;
    const allDone = completedCount >= AGENTS_CONFIG.length;

    // Agents currently processing (can be multiple in a wave)
    const processingAgents = AGENTS_CONFIG.filter(a => getEffectiveStatus(a.name) === 'processing');

    // Active wave label
    const activeWave = processingAgents.length > 0
        ? Object.entries(WAVES).find(([, w]) => w.agents.some(n => processingAgents.find(a => a.name === n)))?.[0]
        : null;
    const activeWaveLabel = activeWave ? WAVES[activeWave].label : null;

    const formatTime = (s: number) => {
        const m = Math.floor(s / 60);
        return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
    };

    // ═══════════════════════════════════════════════════════════════
    // PRE-START
    // ═══════════════════════════════════════════════════════════════
    if (!started) {
        return (
            <>
                <div className={styles.preStartOverlay}>
                    <div className={styles.preStartContent}>
                        {/* Icon */}
                        <div className={styles.preStartIcon}>
                            <svg width="40" height="40" viewBox="0 0 40 40" fill="none">
                                <path d="M8 36V16L20 6L32 16V36H24V26H16V36H8Z" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                                <path d="M16 36V26H24V36" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                        </div>

                        {/* Title */}
                        <h2 className={styles.preStartTitle}>Validační agenti připraveni</h2>
                        <p className={styles.preStartSubtitle}>
                            {uploadData ? `${uploadData.files_processed} fotek zpracováno` : 'Dokumenty nahrány'} • 8 AI agentů v 3 paralelních vlnách
                        </p>

                        {/* Wave chips */}
                        <div className={styles.preStartWaves}>
                            {Object.entries(WAVES).map(([waveKey, wave]) => (
                                <div key={waveKey} className={styles.preStartWaveGroup}>
                                    <div className={styles.preStartWaveLabel}>{wave.label}</div>
                                    <div className={styles.preStartAgentsList}>
                                        {AGENTS_CONFIG.filter(a => a.wave === waveKey).map(agent => (
                                            <div key={agent.name} className={styles.preStartAgentChip}>
                                                <span className={styles.preStartAgentChipIcon}>{agent.icon}</span>
                                                {agent.label}
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            ))}
                        </div>

                        {/* Actions */}
                        <div className={styles.preStartActions}>
                            <button className={styles.editBtn} onClick={onEdit}>
                                <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                                    <path d="M10 2L13 5L5 13H2V10L10 2Z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                                Upravit vstup
                            </button>
                            <button className={styles.startBtn} onClick={handleStart}>
                                <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                                    <path d="M5 3L17 10L5 17V3Z" fill="currentColor" />
                                </svg>
                                Spustit analýzu
                            </button>
                        </div>

                        {/* Info */}
                        <div className={styles.preStartInfo}>
                            <span>⚡</span>
                            Agenti běží paralelně — analýza trvá 30–50 sekund
                        </div>
                    </div>
                </div>

                {selectedAgent && (
                    <AgentDetail
                        name={selectedAgent}
                        config={AGENTS_CONFIG.find(a => a.name === selectedAgent)!}
                        status={agentStatuses[selectedAgent] || 'idle'}
                        logs={agentLogs[selectedAgent] || []}
                        onClose={() => setSelectedAgent(null)}
                        sessionId={sessionId}
                    />
                )}
            </>
        );
    }

    // ═══════════════════════════════════════════════════════════════
    // RUNNING
    // ═══════════════════════════════════════════════════════════════
    return (
        <>
            <div className={styles.overlay}>
                <div className={styles.content}>
                    {/* Animated ring — shows multiple spinning icons when parallel */}
                    <div className={styles.ringContainer}>
                        <div className={styles.ringOuter} />
                        <svg className={styles.ringSvg} viewBox="0 0 140 140">
                            <defs>
                                <linearGradient id="pipelineGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                                    <stop offset="0%" stopColor="#2870ED" />
                                    <stop offset="50%" stopColor="#1A5FD9" />
                                    <stop offset="100%" stopColor="#0D3B78" />
                                </linearGradient>
                            </defs>
                            <circle className={styles.ringTrack} cx="70" cy="70" r="60" />
                            <circle className={styles.ringArc} cx="70" cy="70" r="60" />
                        </svg>
                        <div className={styles.ringIcon}>
                            {allDone
                                ? '✅'
                                : processingAgents.length > 1
                                    ? '⚡'
                                    : processingAgents[0]?.icon ?? '🤖'}
                        </div>
                    </div>

                    {/* Title */}
                    <h2 className={styles.title}>
                        {allDone ? 'Analýza dokončena' : 'Probíhá validace'}
                        {!allDone && (
                            <span className={styles.dots}>
                                <span>.</span><span>.</span><span>.</span>
                            </span>
                        )}
                    </h2>
                    <p className={styles.subtitle}>
                        {allDone
                            ? 'Všichni agenti dokončili kontrolu vašich podkladů'
                            : activeWaveLabel
                                ? activeWaveLabel
                                : 'AI agenti kontrolují vaše podklady — prosím vyčkejte'}
                    </p>

                    {/* Progress header */}
                    <div className={styles.progressHeader}>
                        <div className={styles.progressCounter}>
                            <span className={styles.progressCounterNum}>{completedCount}/{AGENTS_CONFIG.length}</span>
                            <span className={styles.progressTime}>{formatTime(elapsed)}</span>
                        </div>
                        {!allDone ? (
                            <div className={styles.runningBadge}>
                                <span className={styles.runningDot} />
                                {processingAgents.length > 1 ? `${processingAgents.length} paralelně` : 'Probíhá'}
                            </div>
                        ) : (
                            <div className={styles.doneBadge}>
                                ✓ Dokončeno
                            </div>
                        )}
                    </div>

                    {/* Global progress bar */}
                    <div className={styles.globalProgress}>
                        <div
                            className={styles.globalProgressFill}
                            style={{ width: `${(completedCount / AGENTS_CONFIG.length) * 100}%` }}
                        />
                    </div>

                    {/* Currently processing — supports multiple agents */}
                    {processingAgents.length > 0 && (
                        <div className={styles.currentAgentWave}>
                            {processingAgents.map(agent => (
                                <div key={agent.name} className={styles.currentAgent}>
                                    <div className={styles.currentAgentSpinner}>
                                        <svg viewBox="0 0 24 24" width="16" height="16">
                                            <circle cx="12" cy="12" r="10" stroke="rgba(0,0,0,0.08)" strokeWidth="2.5" fill="none" />
                                            <circle cx="12" cy="12" r="10" stroke={agent.color} strokeWidth="2.5" fill="none"
                                                strokeDasharray="31 32" strokeLinecap="round" />
                                        </svg>
                                    </div>
                                    <span className={styles.currentAgentLabel} style={{ color: agent.color }}>
                                        <strong>{agent.icon} {agent.label}</strong>
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Agent steps — grouped by wave */}
                    <div className={styles.agentSteps}>
                        {Object.entries(WAVES).map(([waveKey, wave]) => {
                            const waveAgents = AGENTS_CONFIG.filter(a => a.wave === waveKey);
                            const waveStatuses = waveAgents.map(a => getEffectiveStatus(a.name));
                            const waveAllDone = waveStatuses.every(isTerminal);
                            const waveProcessing = waveStatuses.some(s => s === 'processing');
                            const waveQueued = waveStatuses.every(s => s === 'queued' || s === 'idle');

                            return (
                                <div key={waveKey} className={styles.waveGroup}>
                                    {/* Wave header */}
                                    <div className={`${styles.waveHeader} ${waveAllDone ? styles.waveHeaderDone : waveProcessing ? styles.waveHeaderActive : styles.waveHeaderQueued}`}>
                                        <span className={styles.waveIcon}>
                                            {waveAllDone ? '✓' : waveProcessing ? '⚡' : '○'}
                                        </span>
                                        <span className={styles.waveLabel}>{wave.label}</span>
                                        {waveProcessing && (
                                            <span className={styles.waveSpinnerDot} />
                                        )}
                                    </div>

                                    {/* Agents in this wave */}
                                    <div className={styles.waveAgents}>
                                        {waveAgents.map((agent) => {
                                            const status = getEffectiveStatus(agent.name);
                                            const isProcessing = status === 'processing';
                                            const isDone = isTerminal(status);
                                            const lastLog = (agentLogs[agent.name] || []).slice(-1)[0];

                                            return (
                                                <div
                                                    key={agent.name}
                                                    className={`${styles.agentStep} ${styles[`step_${status}`]}`}
                                                    onClick={() => setSelectedAgent(agent.name)}
                                                    style={{
                                                        '--agent-color': agent.color,
                                                    } as React.CSSProperties}
                                                >
                                                    <div className={styles.stepHeader}>
                                                        {/* Icon */}
                                                        <div
                                                            className={styles.stepIconWrap}
                                                            style={{
                                                                background: isProcessing
                                                                    ? `${agent.color}25`
                                                                    : isDone
                                                                        ? `${agent.color}15`
                                                                        : undefined,
                                                                color: isProcessing || isDone ? agent.color : undefined,
                                                            }}
                                                        >
                                                            {agent.icon}
                                                        </div>

                                                        {/* Text */}
                                                        <div className={styles.stepText}>
                                                            <span className={styles.stepLabel}>{agent.label}</span>
                                                            <span className={styles.stepDesc}>
                                                                {isProcessing && lastLog
                                                                    ? lastLog.message?.substring(0, 60)
                                                                    : isProcessing
                                                                        ? 'Analyzuji...'
                                                                        : agent.description}
                                                            </span>
                                                        </div>

                                                        {/* Status indicator */}
                                                        {isProcessing && <div className={styles.stepSpinner} />}
                                                        {status === 'success' && (
                                                            <svg className={styles.stepCheck} viewBox="0 0 22 22" fill="none">
                                                                <circle cx="11" cy="11" r="10" fill="rgba(5,150,105,0.15)" />
                                                                <path d="M7 11.5L9.5 14L15 8" stroke="var(--accent-green)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                                            </svg>
                                                        )}
                                                        {status === 'fail' && (
                                                            <svg className={styles.stepCheck} viewBox="0 0 22 22" fill="none">
                                                                <circle cx="11" cy="11" r="10" fill="rgba(220,38,38,0.15)" />
                                                                <path d="M8 8L14 14M14 8L8 14" stroke="var(--accent-red)" strokeWidth="2" strokeLinecap="round" />
                                                            </svg>
                                                        )}
                                                        {status === 'warn' && (
                                                            <svg className={styles.stepCheck} viewBox="0 0 22 22" fill="none">
                                                                <circle cx="11" cy="11" r="10" fill="rgba(217,119,6,0.15)" />
                                                                <path d="M11 7V12M11 14.5V15" stroke="var(--accent-orange)" strokeWidth="2" strokeLinecap="round" />
                                                            </svg>
                                                        )}
                                                        {!isProcessing && !isDone && (
                                                            <span className={`${styles.stepStatusBadge} ${styles[`badge_${status}`]}`}>
                                                                {STATUS_LABELS[status] || status}
                                                            </span>
                                                        )}
                                                    </div>

                                                    {/* Processing bar */}
                                                    {isProcessing && (
                                                        <div className={styles.stepProgressBar}>
                                                            <div className={styles.stepProgressFill} style={{ background: agent.color }} />
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            );
                        })}
                    </div>

                    {/* Tip */}
                    <div className={styles.tip}>
                        <span className={styles.tipIcon}>⚡</span>
                        Agenti běží paralelně • {formatTime(elapsed)}
                    </div>
                </div>
            </div>

            {/* Agent Detail Panel */}
            {selectedAgent && (
                <AgentDetail
                    name={selectedAgent}
                    config={AGENTS_CONFIG.find(a => a.name === selectedAgent)!}
                    status={agentStatuses[selectedAgent] || 'idle'}
                    logs={agentLogs[selectedAgent] || []}
                    onClose={() => setSelectedAgent(null)}
                    sessionId={sessionId}
                />
            )}
        </>
    );
}
