'use client';
import { useSearchParams } from 'next/navigation';
import { useState, useEffect, Suspense } from 'react';
import { getBatchCaseResult, type PipelineResult } from '@/lib/api';
import ResultsDashboard from '@/components/ResultsDashboard';

function BatchResultContent() {
    const params = useSearchParams();
    const batchId = params.get('batchId');
    const caseId = params.get('caseId');
    const revId = params.get('revId') || '';
    const address = params.get('address') || '';

    const [result, setResult] = useState<PipelineResult | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!batchId || !caseId) {
            setError('Chybí parametry batch_id nebo case_id.');
            setLoading(false);
            return;
        }
        (async () => {
            try {
                const res = await getBatchCaseResult(batchId, caseId);
                setResult(res);
            } catch (e: any) {
                setError(e.message || 'Nepodařilo se načíst výsledek.');
            } finally {
                setLoading(false);
            }
        })();
    }, [batchId, caseId]);

    if (loading) {
        return (
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: '60vh',
                gap: '16px',
            }}>
                <div style={{
                    width: '36px',
                    height: '36px',
                    border: '3px solid rgba(40, 112, 237, 0.15)',
                    borderTopColor: '#2870ED',
                    borderRadius: '50%',
                    animation: 'spin 0.8s linear infinite',
                }} />
                <p style={{ color: 'var(--text-muted)', fontSize: '14px' }}>Načítám výsledky...</p>
                <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
            </div>
        );
    }

    if (error) {
        return (
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: '60vh',
                color: 'var(--text-muted)',
                flexDirection: 'column',
                gap: '12px',
            }}>
                <p style={{ fontSize: '18px', fontWeight: 600, color: '#ef4444' }}>Chyba</p>
                <p>{error}</p>
            </div>
        );
    }

    return (
        <main style={{ minHeight: '100vh', background: 'var(--bg-primary, #f8fafc)' }}>
            {/* Header bar */}
            <div style={{
                position: 'sticky',
                top: 0,
                zIndex: 10,
                background: 'var(--surface-card, #fff)',
                borderBottom: '1px solid var(--border-subtle, #e2e8f0)',
                padding: '14px 24px',
                display: 'flex',
                alignItems: 'center',
                gap: '14px',
            }}>
                <span style={{
                    fontSize: '16px',
                    fontWeight: 700,
                    color: 'var(--text-primary)',
                }}>
                    REV {revId}
                </span>
                {address && (
                    <span style={{
                        fontSize: '13px',
                        color: 'var(--text-muted)',
                        marginLeft: 'auto',
                    }}>
                        {address}
                    </span>
                )}
            </div>

            {result && (
                <ResultsDashboard
                    result={result}
                    onEdit={() => window.close()}
                    onReset={() => window.close()}
                />
            )}
        </main>
    );
}

export default function BatchResultPage() {
    return (
        <Suspense fallback={
            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: '60vh',
            }}>
                <p style={{ color: 'var(--text-muted)' }}>Načítám...</p>
            </div>
        }>
            <BatchResultContent />
        </Suspense>
    );
}
