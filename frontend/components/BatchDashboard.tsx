'use client';
import { useState } from 'react';
import styles from './BatchDashboard.module.css';
import ResultsDashboard from './ResultsDashboard';
import { getBatchCaseResult, type BatchCase, type PipelineResult } from '@/lib/api';

interface Props {
    batchId: string;
    cases: BatchCase[];
    currentIndex: number;
    estimatedRemaining: number | null;
    batchComplete: boolean;
    batchTotalTime: number | null;
    semaphoreSummary: Record<string, number>;
    isRunning: boolean;
    onReset: () => void;
}

function formatTime(seconds: number): string {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

function getSemaphoreClass(color?: string): string {
    switch (color?.toLowerCase()) {
        case 'green': return styles.caseSemaphoreGreen;
        case 'yellow': return styles.caseSemaphoreYellow;
        case 'red': return styles.caseSemaphoreRed;
        default: return styles.caseSemaphoreGray;
    }
}

export default function BatchDashboard({
    batchId,
    cases,
    currentIndex,
    estimatedRemaining,
    batchComplete,
    batchTotalTime,
    semaphoreSummary,
    isRunning,
    onReset,
}: Props) {
    const [selectedCase, setSelectedCase] = useState<{ case: BatchCase; result: PipelineResult } | null>(null);
    const [loadingCaseId, setLoadingCaseId] = useState<string | null>(null);

    const completedCount = cases.filter(c => c.status === 'completed').length;
    const totalCount = cases.length;
    const progressPercent = totalCount > 0 ? (completedCount / totalCount) * 100 : 0;

    const handleCaseClick = async (c: BatchCase) => {
        if (c.status !== 'completed') return;
        setLoadingCaseId(c.case_id);
        try {
            const result = await getBatchCaseResult(batchId, c.case_id);
            setSelectedCase({ case: c, result });
        } catch (e) {
            console.error('Failed to load case result:', e);
        } finally {
            setLoadingCaseId(null);
        }
    };

    // ── Detail view for a single case ──
    if (selectedCase) {
        return (
            <div className={styles.detailOverlay}>
                <div className={styles.detailHeader}>
                    <button
                        className={styles.backBtn}
                        onClick={() => setSelectedCase(null)}
                    >
                        ← Zpět na přehled
                    </button>
                    <span className={styles.detailRevId}>REV {selectedCase.case.rev_id}</span>
                    {selectedCase.case.address && (
                        <span className={styles.detailAddress}>{selectedCase.case.address}</span>
                    )}
                </div>
                <ResultsDashboard
                    result={selectedCase.result}
                    onEdit={() => setSelectedCase(null)}
                    onReset={() => setSelectedCase(null)}
                />
            </div>
        );
    }

    // ── Main batch dashboard ──
    return (
        <div className={styles.batchContainer}>
            <div className={styles.batchHeader}>
                <h2 className={styles.batchTitle}>
                    <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
                        <rect x="2" y="3" width="18" height="16" rx="2" stroke="currentColor" strokeWidth="1.8" fill="none" />
                        <path d="M2 7H20" stroke="currentColor" strokeWidth="1.5" />
                        <path d="M6 11H16M6 14H12" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity="0.6" />
                    </svg>
                    Hromadná kontrola
                </h2>
                <p className={styles.batchSubtitle}>
                    {totalCount} {totalCount === 1 ? 'případ' : totalCount < 5 ? 'případy' : 'případů'} • Batch {batchId}
                </p>
            </div>

            {/* Completed summary */}
            {batchComplete && batchTotalTime && (
                <div className={styles.batchSummary}>
                    <div className={styles.batchSummaryTitle}>✅ Hromadná kontrola dokončena</div>
                    <div className={styles.batchSummaryTime}>
                        Celkový čas: {formatTime(batchTotalTime)} • {totalCount} případů zpracováno
                    </div>
                    {Object.keys(semaphoreSummary).length > 0 && (
                        <div className={styles.semaphoreSummary} style={{ justifyContent: 'center' }}>
                            {semaphoreSummary.GREEN > 0 && (
                                <span className={styles.semaphoreBadge}>
                                    <span className={`${styles.semaphoreDot} ${styles.semaphoreDotGreen}`} />
                                    {semaphoreSummary.GREEN}× zelená
                                </span>
                            )}
                            {semaphoreSummary.YELLOW > 0 && (
                                <span className={styles.semaphoreBadge}>
                                    <span className={`${styles.semaphoreDot} ${styles.semaphoreDotYellow}`} />
                                    {semaphoreSummary.YELLOW}× žlutá
                                </span>
                            )}
                            {semaphoreSummary.RED > 0 && (
                                <span className={styles.semaphoreBadge}>
                                    <span className={`${styles.semaphoreDot} ${styles.semaphoreDotRed}`} />
                                    {semaphoreSummary.RED}× červená
                                </span>
                            )}
                            {(semaphoreSummary.ERROR ?? 0) > 0 && (
                                <span className={styles.semaphoreBadge}>
                                    <span className={`${styles.semaphoreDot} ${styles.semaphoreDotGray}`} />
                                    {semaphoreSummary.ERROR}× chyba
                                </span>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Progress section */}
            <div className={styles.progressSection}>
                <div className={styles.progressRow}>
                    <span className={styles.progressLabel}>
                        {batchComplete ? 'Dokončeno' : isRunning ? 'Zpracovávání...' : 'Připraveno ke spuštění'}
                    </span>
                    <div className={styles.progressStats}>
                        <span className={styles.progressStat}>
                            Hotovo: <span className={styles.progressStatValue}>{completedCount}/{totalCount}</span>
                        </span>
                        {isRunning && currentIndex >= 0 && (
                            <span className={styles.progressStat}>
                                Aktuální: <span className={styles.progressStatValue}>
                                    {cases[currentIndex]?.rev_id || `#${currentIndex + 1}`}
                                </span>
                            </span>
                        )}
                    </div>
                </div>
                <div className={styles.progressBarTrack}>
                    <div
                        className={styles.progressBarFill}
                        style={{ width: `${progressPercent}%` }}
                    />
                </div>
                {isRunning && estimatedRemaining !== null && estimatedRemaining > 0 && (
                    <div className={styles.timeEstimate}>
                        <span className={styles.timeEstimateIcon}>⏱</span>
                        Odhadovaný zbývající čas:
                        <span className={styles.timeEstimateValue}>{formatTime(estimatedRemaining)}</span>
                    </div>
                )}
            </div>

            {/* Case list */}
            <div className={styles.caseList}>
                {cases.map((c, i) => {
                    const isProcessing = c.status === 'processing';
                    const isCompleted = c.status === 'completed';
                    const isLoading = loadingCaseId === c.case_id;

                    return (
                        <div
                            key={c.case_id}
                            className={`${styles.caseRow} ${isCompleted ? styles.caseRowCompleted : ''} ${isProcessing ? styles.caseRowProcessing : ''}`}
                            onClick={() => handleCaseClick(c)}
                        >
                            <div className={`${styles.caseIndex} ${isProcessing ? styles.caseIndexProcessing : ''} ${isCompleted ? styles.caseIndexCompleted : ''}`}>
                                {i + 1}
                            </div>

                            <span className={styles.caseRevId}>REV {c.rev_id}</span>

                            <span className={styles.caseAddress}>
                                {c.address || '—'}
                            </span>

                            {c.file_counts && (
                                <span className={styles.caseFileCounts}>
                                    📷 {c.file_counts.images} • 📄 {c.file_counts.pdfs}
                                </span>
                            )}

                            {isCompleted && c.total_time && (
                                <span className={styles.caseTime}>{formatTime(c.total_time)}</span>
                            )}

                            {isProcessing && <div className={styles.miniSpinner} />}
                            {isLoading && <div className={styles.miniSpinner} />}

                            {isCompleted && c.semaphore_color && (
                                <div className={`${styles.caseSemaphore} ${getSemaphoreClass(c.semaphore_color)}`} />
                            )}

                            <span className={`${styles.caseStatus} ${
                                isProcessing ? styles.caseStatusProcessing :
                                isCompleted ? styles.caseStatusCompleted :
                                styles.caseStatusPending
                            }`}>
                                {isProcessing ? 'Zpracovává se' :
                                 isCompleted ? 'Hotovo' : 'Čeká'}
                            </span>

                            {isCompleted && (
                                <span className={styles.caseArrow}>→</span>
                            )}
                        </div>
                    );
                })}
            </div>

            {/* Reset button */}
            {batchComplete && (
                <div style={{ textAlign: 'center', marginTop: '24px' }}>
                    <button
                        className="btn btn-primary"
                        onClick={onReset}
                        style={{ padding: '12px 32px' }}
                    >
                        Nová hromadná kontrola
                    </button>
                </div>
            )}
        </div>
    );
}
