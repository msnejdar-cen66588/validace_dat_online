'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getWebSocketUrl, getBjWebSocketUrl, getPipelineResults, getBjPipelineResults } from '@/lib/api';

export interface WSMessage {
    type: string;
    pipeline_id?: string;
    agent?: string;
    status?: string;
    message?: string;
    level?: string;
    timestamp?: number;
    elapsed_time?: number;
    result?: any;
    agents?: string[];
    step?: string;
}

const MAX_RECONNECT_ATTEMPTS = 8;
const RECONNECT_BASE_DELAY = 3000;
const POLL_INTERVAL = 15000; // 15 seconds — gentle on Render

export function useWebSocket(sessionId: string | null, pipelineType: 'rd' | 'bj' = 'rd') {
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectCount = useRef(0);
    const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
    const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);
    const [connected, setConnected] = useState(false);
    const [messages, setMessages] = useState<WSMessage[]>([]);
    const [agentStatuses, setAgentStatuses] = useState<Record<string, string>>({});
    const [agentLogs, setAgentLogs] = useState<Record<string, WSMessage[]>>({});
    const [pipelineResult, setPipelineResult] = useState<any>(null);
    const [isRunning, setIsRunning] = useState(false);
    // Valuation pipeline state
    const [valuationSteps, setValuationSteps] = useState<Record<string, string>>({});
    const [valuationResult, setValuationResult] = useState<any>(null);
    const [isValuating, setIsValuating] = useState(false);

    // Fallback: HTTP polling — ONLY used after WebSocket max retries exhausted
    const startPolling = useCallback(() => {
        if (!sessionId || pollTimer.current) return;
        console.log('[Pipeline] WebSocket unavailable, falling back to HTTP polling every 15s');
        pollTimer.current = setInterval(async () => {
            try {
                const result: any = pipelineType === 'bj'
                    ? await getBjPipelineResults(sessionId)
                    : await getPipelineResults(sessionId);
                // Only accept truly completed results
                if (result && result.completed && result.semaphore) {
                    console.log('[Pipeline] Got completed result via polling');
                    setPipelineResult(result);
                    setIsRunning(false);
                    if (pollTimer.current) {
                        clearInterval(pollTimer.current);
                        pollTimer.current = null;
                    }
                }
            } catch {
                // Results not ready yet, keep polling silently
            }
        }, POLL_INTERVAL);
    }, [sessionId, pipelineType]);

    const stopPolling = useCallback(() => {
        if (pollTimer.current) {
            clearInterval(pollTimer.current);
            pollTimer.current = null;
        }
    }, []);

    const connect = useCallback(() => {
        if (!sessionId) return;
        if (reconnectCount.current >= MAX_RECONNECT_ATTEMPTS) {
            console.warn(`[WS] Max reconnect attempts reached, falling back to polling`);
            startPolling();
            return;
        }

        // Close any existing WS before creating a new one
        if (wsRef.current) {
            try { wsRef.current.close(); } catch { /* ignore */ }
        }

        const wsUrl = pipelineType === 'bj'
            ? getBjWebSocketUrl(sessionId)
            : getWebSocketUrl(sessionId);
        console.log(`[WS] Connecting to ${wsUrl} (pipelineType=${pipelineType})`);
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
            setConnected(true);
            reconnectCount.current = 0;
            stopPolling(); // WS works, no need for polling
        };

        ws.onclose = () => {
            setConnected(false);
            // Only reconnect if we haven't been replaced by a newer connection
            if (wsRef.current === ws) {
                reconnectCount.current += 1;
                const delay = RECONNECT_BASE_DELAY * Math.min(reconnectCount.current, 5);
                reconnectTimer.current = setTimeout(() => {
                    if (sessionId) connect();
                }, delay);
            }
        };

        ws.onerror = () => {
            // onclose fires after onerror, reconnect handled there
        };

        ws.onmessage = (event) => {
            try {
                const msg: WSMessage = JSON.parse(event.data);
                setMessages(prev => [...prev, msg]);

                switch (msg.type) {
                    case 'pipeline_start':
                        setIsRunning(true);
                        setAgentStatuses({});
                        setAgentLogs({});
                        setPipelineResult(null);
                        msg.agents?.forEach(name => {
                            setAgentStatuses(prev => ({ ...prev, [name]: 'idle' }));
                        });
                        break;

                    case 'agent_status':
                        if (msg.agent && msg.status) {
                            setAgentStatuses(prev => ({ ...prev, [msg.agent!]: msg.status! }));
                        }
                        break;

                    case 'agent_log':
                        if (msg.agent) {
                            setAgentLogs(prev => ({
                                ...prev,
                                [msg.agent!]: [...(prev[msg.agent!] || []), msg],
                            }));
                        }
                        break;

                    case 'pipeline_complete':
                        setIsRunning(false);
                        setPipelineResult(msg.result);
                        stopPolling();
                        break;

                    case 'valuation_start':
                        setIsValuating(true);
                        setValuationSteps({});
                        setValuationResult(null);
                        break;

                    case 'valuation_step':
                        if (msg.step && msg.status) {
                            setValuationSteps(prev => ({ ...prev, [msg.step!]: msg.status! }));
                        }
                        if (msg.agent) {
                            setAgentLogs(prev => ({
                                ...prev,
                                [msg.agent!]: [...(prev[msg.agent!] || []), msg],
                            }));
                        }
                        break;

                    case 'valuation_complete':
                        setIsValuating(false);
                        setValuationResult(msg.result);
                        break;
                }
            } catch (e) {
                console.error('WS parse error:', e);
            }
        };
    }, [sessionId, pipelineType, startPolling, stopPolling]);

    useEffect(() => {
        reconnectCount.current = 0;
        connect();
        return () => {
            wsRef.current?.close();
            if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
            stopPolling();
        };
    }, [connect, stopPolling]);

    const sendMessage = useCallback((msg: any) => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify(msg));
        }
    }, []);

    return {
        connected,
        messages,
        agentStatuses,
        agentLogs,
        pipelineResult,
        isRunning,
        sendMessage,
        valuationSteps,
        valuationResult,
        isValuating,
    };
}
