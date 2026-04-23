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
    },
    {
        name: 'ForenzniAnalytik',
        label: 'Forenzní analytik',
        description: 'Detekce manipulace a úprav fotografií',
        long_description: 'Detekuje potenciální podvody. Analyzuje EXIF metadata a hledá stopy po úpravách ve Photoshopu nebo AI generovaných fotkách.',
        icon: '🔬',
        color: '#6366f1',
    },
    {
        name: 'Historik',
        label: 'Historik',
        description: 'Určení věku a kategorizace nemovitosti',
        long_description: 'Odhaduje skutečný věk stavby na základě vizuálních znaků (typ oken, fasáda, materiály) a porovnává s rokem dokončení.',
        icon: '📜',
        color: '#0891b2',
    },
    {
        name: 'Inspektor',
        label: 'Inspektor',
        description: 'Hodnocení technického stavu objektu',
        long_description: 'Prohledává fotky a detekuje technické závady: praskliny, vlhkost, plísně a nedokončené stavební úpravy.',
        icon: '🔍',
        color: '#d97706',
    },
    {
        name: 'GeoValidator',
        label: 'GeoValidator',
        description: 'Ověření GPS lokace (Mapy.cz panorama)',
        long_description: 'Kontroluje přístupové cesty a rizika v okolí na základě ortofotomap a ověřuje lokaci focení.',
        icon: '📍',
        color: '#db2777',
    },
    {
        name: 'PorovnavacDokumentu',
        label: 'DocComparator',
        description: 'Porovnání dat z formuláře vs fotky',
        long_description: 'Křížově ověřuje zjištěná data. Přepočítává podlaží a odhaduje podlahovou plochu zvenku vs zevnitř k zamezení zkreslení.',
        icon: '📄',
        color: '#ea580c',
    },
    {
        name: 'KatastralniAnalytik',
        label: 'Katastrální analýza',
        description: 'Analýza LV – rizika, ortofoto, stavby',
        long_description: 'Stahuje a analyzuje data z Katastru nemovitostí a Listu vlastnictví. Hledá břemena a právní vady.',
        icon: '🏛️',
        color: '#7c3aed',
    },
    {
        name: 'Strateg',
        label: 'Stratég',
        description: 'Agregace výsledků a finální verdikt',
        long_description: 'Syntetizuje veškerá zjištění od předchozích agentů a vydává závěrečné rozhodnutí a doporučení pro odhadce.',
        icon: '🎯',
        color: '#059669',
    },
];

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
    const [simulatedIdx, setSimulatedIdx] = useState(-1);
    const startTimeRef = useRef<number | null>(null);

    // Timer — starts immediately on click, independent of WebSocket
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

    // Simulate agent progression if WebSocket isn't delivering statuses
    useEffect(() => {
        if (!started) return;
        const hasWsStatuses = Object.values(agentStatuses).some(s => s !== 'idle');
        if (hasWsStatuses) {
            setSimulatedIdx(-1);
            return;
        }
        const interval = setInterval(() => {
            setSimulatedIdx(prev => {
                if (prev >= AGENTS_CONFIG.length - 1) {
                    clearInterval(interval);
                    return prev;
                }
                return prev + 1;
            });
        }, 8000);
        setSimulatedIdx(0);
        return () => clearInterval(interval);
    }, [started, agentStatuses]);

    const handleStart = () => {
        setStarted(true);
        setElapsed(0);
        onStart();
    };

    // Merge WS statuses with simulated ones — ENFORCE sequential visual order
    // Guarantees exactly ONE agent always shows as "processing" during the run
    const getEffectiveStatus = (name: string, idx: number): string => {
        if (!started) return 'idle';

        const isTerminal = (s: string) => ['success', 'fail', 'warn'].includes(s);

        // Count how many agents have terminal WS statuses (regardless of visual order)
        const terminalCount = AGENTS_CONFIG.filter(a => {
            const s = agentStatuses[a.name];
            return s && isTerminal(s);
        }).length;

        // All agents done → show their real statuses
        if (terminalCount >= AGENTS_CONFIG.length) {
            return agentStatuses[name] || 'success';
        }

        // Agents in "done" visual slots (0 to terminalCount-1)
        if (idx < terminalCount) {
            const ws = agentStatuses[name];
            // If this specific agent has a terminal status, show it
            if (ws && isTerminal(ws)) return ws;
            // Otherwise it finished out of order — show as success placeholder
            return 'success';
        }

        // The ONE "processing" slot — always exactly at position terminalCount
        if (idx === terminalCount) {
            return 'processing';
        }

        // Everything after: queued
        return 'queued';
    };

    const completedCount = AGENTS_CONFIG.filter((a, i) => {
        const s = getEffectiveStatus(a.name, i);
        return ['success', 'fail', 'warn'].includes(s);
    }).length;

    const processingAgent = AGENTS_CONFIG.find((a, i) =>
        getEffectiveStatus(a.name, i) === 'processing'
    );

    const allDone = completedCount >= AGENTS_CONFIG.length;

    const formatTime = (s: number) => {
        const m = Math.floor(s / 60);
        return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
    };

    // ═══════════════════════════════════════════════════════════════
    // PRE-START: Centered card with agent chips and start button
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
                            {uploadData ? `${uploadData.files_processed} fotek zpracováno` : 'Dokumenty nahrány'} • 8 AI agentů zkontroluje vaše podklady
                        </p>

                        {/* Agent chips */}
                        <div className={styles.preStartAgentsList}>
                            {AGENTS_CONFIG.map(agent => (
                                <div key={agent.name} className={styles.preStartAgentChip}>
                                    <span className={styles.preStartAgentChipIcon}>{agent.icon}</span>
                                    {agent.label}
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
                            <span>⏱️</span>
                            Analýza obvykle trvá 30–60 sekund
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

    // ═══════════════════════════════════════════════════════════════
    // RUNNING: Fullscreen loader with agent steps (ProcessingLoader style)
    // ═══════════════════════════════════════════════════════════════
    return (
        <>
            <div className={styles.overlay}>
                <div className={styles.content}>
                    {/* Animated ring */}
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
                            {processingAgent ? processingAgent.icon : allDone ? '✅' : '🤖'}
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
                                Probíhá
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

                    {/* Currently processing indicator */}
                    {processingAgent && (
                        <div className={styles.currentAgent}>
                            <div className={styles.currentAgentSpinner}>
                                <svg viewBox="0 0 24 24" width="18" height="18">
                                    <circle cx="12" cy="12" r="10" stroke="rgba(0,0,0,0.08)" strokeWidth="2.5" fill="none" />
                                    <circle cx="12" cy="12" r="10" stroke={processingAgent.color} strokeWidth="2.5" fill="none"
                                        strokeDasharray="31 32" strokeLinecap="round" />
                                </svg>
                            </div>
                            <span className={styles.currentAgentLabel}>
                                <strong>{processingAgent.icon} {processingAgent.label}</strong> — {processingAgent.description}
                            </span>
                            <span className={styles.currentAgentDots}>
                                <span>.</span><span>.</span><span>.</span>
                            </span>
                        </div>
                    )}

                    {/* Agent steps */}
                    <div className={styles.agentSteps}>
                        {AGENTS_CONFIG.map((agent, idx) => {
                            const status = getEffectiveStatus(agent.name, idx);
                            const isProcessing = status === 'processing';
                            const isDone = ['success', 'fail', 'warn'].includes(status);
                            const lastLog = (agentLogs[agent.name] || []).slice(-1)[0];

                            return (
                                <div
                                    key={agent.name}
                                    className={`${styles.agentStep} ${styles[`step_${status}`]}`}
                                    onClick={() => setSelectedAgent(agent.name)}
                                    style={{
                                        animationDelay: `${idx * 60}ms`,
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
                                    
                                    {/* Accordion detail */}
                                    <div className={styles.stepDetail}>
                                        {agent.long_description}
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

                    {/* Tip */}
                    <div className={styles.tip}>
                        <span className={styles.tipIcon}>⏱️</span>
                        Analýza obvykle trvá 30–60 sekund • {formatTime(elapsed)}
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
