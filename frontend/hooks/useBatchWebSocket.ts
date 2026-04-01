'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getBatchWebSocketUrl, getBatchStatus, type BatchCase } from '@/lib/api';

export interface BatchWSMessage {
    type: string;
    batch_id?: string;
    case_id?: string;
    rev_id?: string;
    index?: number;
    total_cases?: number;
    case_ids?: string[];
    rev_ids?: string[];
    semaphore?: string;
    semaphore_color?: string;
    total_time?: number;
    estimated_remaining?: number;
    semaphore_summary?: Record<string, number>;
    timestamp?: number;
}

const MAX_RECONNECT = 8;
const RECONNECT_DELAY = 3000;
const POLL_INTERVAL = 10000;

export function useBatchWebSocket(batchId: string | null) {
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectCount = useRef(0);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
    const [connected, setConnected] = useState(false);
    const [cases, setCases] = useState<BatchCase[]>([]);
    const [currentIndex, setCurrentIndex] = useState(-1);
    const [estimatedRemaining, setEstimatedRemaining] = useState<number | null>(null);
    const [batchComplete, setBatchComplete] = useState(false);
    const [batchTotalTime, setBatchTotalTime] = useState<number | null>(null);
    const [semaphoreSummary, setSemaphoreSummary] = useState<Record<string, number>>({});
    const [isRunning, setIsRunning] = useState(false);

    // Fallback HTTP polling
    const startPolling = useCallback(() => {
        if (!batchId || pollTimer.current) return;
        pollTimer.current = setInterval(async () => {
            try {
                const status = await getBatchStatus(batchId);
                setCases(status.cases);
                setCurrentIndex(status.current_case_index);
                setEstimatedRemaining(status.estimated_remaining);
                if (status.status === 'completed') {
                    setBatchComplete(true);
                    setBatchTotalTime(status.total_time);
                    setIsRunning(false);
                    if (pollTimer.current) {
                        clearInterval(pollTimer.current);
                        pollTimer.current = null;
                    }
                }
            } catch { /* keep polling */ }
        }, POLL_INTERVAL);
    }, [batchId]);

    const stopPolling = useCallback(() => {
        if (pollTimer.current) {
            clearInterval(pollTimer.current);
            pollTimer.current = null;
        }
    }, []);

    const connect = useCallback(() => {
        if (!batchId) return;
        if (reconnectCount.current >= MAX_RECONNECT) {
            startPolling();
            return;
        }

        if (wsRef.current) {
            try { wsRef.current.close(); } catch { /* ignore */ }
        }

        const ws = new WebSocket(getBatchWebSocketUrl(batchId));
        wsRef.current = ws;

        ws.onopen = () => {
            setConnected(true);
            reconnectCount.current = 0;
            stopPolling();
        };

        ws.onclose = () => {
            setConnected(false);
            if (wsRef.current === ws) {
                reconnectCount.current += 1;
                const delay = RECONNECT_DELAY * Math.min(reconnectCount.current, 5);
                reconnectTimer.current = setTimeout(() => {
                    if (batchId) connect();
                }, delay);
            }
        };

        ws.onerror = () => {};

        ws.onmessage = (event) => {
            try {
                const msg: BatchWSMessage = JSON.parse(event.data);

                switch (msg.type) {
                    case 'batch_start':
                        setIsRunning(true);
                        setBatchComplete(false);
                        setCurrentIndex(-1);
                        break;

                    case 'batch_case_preparing':
                        setCurrentIndex(msg.index ?? -1);
                        setCases(prev => prev.map(c =>
                            c.case_id === msg.case_id
                                ? { ...c, status: 'preparing' }
                                : c
                        ));
                        break;

                    case 'batch_case_start':
                        setCurrentIndex(msg.index ?? -1);
                        setCases(prev => prev.map(c =>
                            c.case_id === msg.case_id
                                ? { ...c, status: 'processing' }
                                : c
                        ));
                        break;

                    case 'batch_case_complete':
                        setCases(prev => prev.map(c =>
                            c.case_id === msg.case_id
                                ? {
                                    ...c,
                                    status: 'completed',
                                    semaphore: msg.semaphore,
                                    semaphore_color: msg.semaphore_color,
                                    total_time: msg.total_time,
                                    address: (msg as any).address || c.address,
                                }
                                : c
                        ));
                        setEstimatedRemaining(msg.estimated_remaining ?? null);
                        break;

                    case 'batch_complete':
                        setIsRunning(false);
                        setBatchComplete(true);
                        setBatchTotalTime(msg.total_time ?? null);
                        setSemaphoreSummary(msg.semaphore_summary ?? {});
                        stopPolling();
                        break;

                    // Forward individual agent events for the currently processing case
                    case 'agent_status':
                    case 'agent_log':
                    case 'pipeline_start':
                    case 'pipeline_complete':
                        // These are forwarded from the orchestrator but we don't need
                        // to handle them at batch level – they're for agent-level detail
                        break;
                }
            } catch (e) {
                console.error('Batch WS parse error:', e);
            }
        };
    }, [batchId, startPolling, stopPolling]);

    useEffect(() => {
        reconnectCount.current = 0;
        connect();
        return () => {
            wsRef.current?.close();
            if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
            stopPolling();
        };
    }, [connect, stopPolling]);

    return {
        connected,
        cases,
        setCases,
        currentIndex,
        estimatedRemaining,
        batchComplete,
        batchTotalTime,
        semaphoreSummary,
        isRunning,
    };
}
