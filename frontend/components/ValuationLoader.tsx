'use client';
import { useState, useEffect } from 'react';
import styles from './PipelineCanvas.module.css';

interface Props {
    steps: Record<string, string>;
    onComplete?: () => void;
}

const VALUATION_STEPS = [
    {
        key: 'collector',
        icon: '📡',
        label: 'Sběrač vzorků',
        description: 'Stahování reálných inzerátů z realitních portálů a geokódování adresy.',
        color: '#2870ED',
    },
    {
        key: 'analyst',
        icon: '🔎',
        label: 'Analytik vzorků',
        description: 'AI vybírá nejpodobnější vzorky podle velikosti, stavu a lokality.',
        color: '#8b5cf6',
    },
    {
        key: 'coefficients',
        icon: '⚖️',
        label: 'Koeficientový znalec',
        description: 'AI porovnává fotografie a data, stanovuje korekční koeficienty K1–K8.',
        color: '#d97706',
    },
    {
        key: 'calculator',
        icon: '🧮',
        label: 'Cenový kalkulátor',
        description: 'Výpočet tržní hodnoty (NHZP), confidence score a benchmarky.',
        color: '#059669',
    },
];

export default function ValuationLoader({ steps, onComplete }: Props) {
    const [elapsed, setElapsed] = useState(0);

    useEffect(() => {
        const start = Date.now();
        const timer = setInterval(() => {
            setElapsed(Math.floor((Date.now() - start) / 1000));
        }, 1000);
        return () => clearInterval(timer);
    }, []);

    const getStatus = (key: string): string => steps[key] || 'idle';

    const completedCount = VALUATION_STEPS.filter(s =>
        getStatus(s.key) === 'success'
    ).length;

    const processingStep = VALUATION_STEPS.find(s =>
        getStatus(s.key) === 'processing'
    );

    const allDone = completedCount >= VALUATION_STEPS.length;

    useEffect(() => {
        if (allDone && onComplete) {
            const timer = setTimeout(onComplete, 1500);
            return () => clearTimeout(timer);
        }
    }, [allDone, onComplete]);

    const formatTime = (s: number) => {
        const m = Math.floor(s / 60);
        return m > 0 ? `${m}m ${s % 60}s` : `${s}s`;
    };

    return (
        <div className={styles.overlay}>
            <div className={styles.content}>
                {/* Ring */}
                <div className={styles.ringContainer}>
                    <div className={styles.ringOuter} />
                    <svg className={styles.ringSvg} viewBox="0 0 140 140">
                        <defs>
                            <linearGradient id="valGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                                <stop offset="0%" stopColor="#2870ED" />
                                <stop offset="50%" stopColor="#8b5cf6" />
                                <stop offset="100%" stopColor="#059669" />
                            </linearGradient>
                        </defs>
                        <circle className={styles.ringTrack} cx="70" cy="70" r="60" />
                        <circle className={styles.ringArc} cx="70" cy="70" r="60" />
                    </svg>
                    <div className={styles.ringIcon}>
                        {processingStep ? processingStep.icon : allDone ? '✅' : '💰'}
                    </div>
                </div>

                {/* Title */}
                <h2 className={styles.title}>
                    {allDone ? 'Odhad dokončen' : 'Tržní ocenění'}
                    {!allDone && (
                        <span className={styles.dots}>
                            <span>.</span><span>.</span><span>.</span>
                        </span>
                    )}
                </h2>
                <p className={styles.subtitle}>
                    {allDone
                        ? 'Porovnávací metoda (NHZP) byla úspěšně dokončena'
                        : 'AI agenti analyzují trh a stanovují tržní hodnotu'}
                </p>

                {/* Progress */}
                <div className={styles.progressHeader}>
                    <div className={styles.progressCounter}>
                        <span className={styles.progressCounterNum}>
                            {completedCount}/{VALUATION_STEPS.length}
                        </span>
                        <span className={styles.progressTime}>{formatTime(elapsed)}</span>
                    </div>
                    {!allDone ? (
                        <div className={styles.runningBadge}>
                            <span className={styles.runningDot} />
                            Probíhá
                        </div>
                    ) : (
                        <div className={styles.doneBadge}>✓ Dokončeno</div>
                    )}
                </div>

                <div className={styles.globalProgress}>
                    <div
                        className={styles.globalProgressFill}
                        style={{ width: `${(completedCount / VALUATION_STEPS.length) * 100}%` }}
                    />
                </div>

                {/* Current step */}
                {processingStep && (
                    <div className={styles.currentAgent}>
                        <div className={styles.currentAgentSpinner}>
                            <svg viewBox="0 0 24 24" width="18" height="18">
                                <circle cx="12" cy="12" r="10" stroke="rgba(0,0,0,0.08)" strokeWidth="2.5" fill="none" />
                                <circle cx="12" cy="12" r="10" stroke={processingStep.color} strokeWidth="2.5" fill="none"
                                    strokeDasharray="31 32" strokeLinecap="round" />
                            </svg>
                        </div>
                        <span className={styles.currentAgentLabel}>
                            <strong>{processingStep.icon} {processingStep.label}</strong> — {processingStep.description}
                        </span>
                        <span className={styles.currentAgentDots}>
                            <span>.</span><span>.</span><span>.</span>
                        </span>
                    </div>
                )}

                {/* Steps */}
                <div className={styles.agentSteps}>
                    {VALUATION_STEPS.map((step, idx) => {
                        const status = getStatus(step.key);
                        const isProcessing = status === 'processing';
                        const isDone = status === 'success';

                        return (
                            <div
                                key={step.key}
                                className={`${styles.agentStep} ${styles[`step_${isDone ? 'success' : isProcessing ? 'processing' : 'queued'}`]}`}
                                style={{
                                    animationDelay: `${idx * 60}ms`,
                                    '--agent-color': step.color,
                                } as React.CSSProperties}
                            >
                                <div className={styles.stepHeader}>
                                    <div
                                        className={styles.stepIconWrap}
                                        style={{
                                            background: isProcessing
                                                ? `${step.color}25`
                                                : isDone
                                                    ? `${step.color}15`
                                                    : undefined,
                                            color: isProcessing || isDone ? step.color : undefined,
                                        }}
                                    >
                                        {step.icon}
                                    </div>
                                    <div className={styles.stepText}>
                                        <span className={styles.stepLabel}>{step.label}</span>
                                        <span className={styles.stepDesc}>{step.description}</span>
                                    </div>
                                    {isProcessing && <div className={styles.stepSpinner} />}
                                    {isDone && (
                                        <svg className={styles.stepCheck} viewBox="0 0 22 22" fill="none">
                                            <circle cx="11" cy="11" r="10" fill="rgba(5,150,105,0.15)" />
                                            <path d="M7 11.5L9.5 14L15 8" stroke="var(--accent-green)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                                        </svg>
                                    )}
                                    {!isProcessing && !isDone && (
                                        <span className={`${styles.stepStatusBadge} ${styles.badge_queued}`}>
                                            ČEKÁ
                                        </span>
                                    )}
                                </div>
                                {isProcessing && (
                                    <div className={styles.stepProgressBar}>
                                        <div className={styles.stepProgressFill} style={{ background: step.color }} />
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>

                <div className={styles.tip}>
                    <span className={styles.tipIcon}>⏱️</span>
                    Tržní ocenění obvykle trvá 60–120 sekund • {formatTime(elapsed)}
                </div>
            </div>
        </div>
    );
}
