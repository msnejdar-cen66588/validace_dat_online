'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { getWebSocketUrl, getPipelineResults } from '@/lib/api';

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
}

const MAX_RECONNECT_ATTEMPTS = 5;
const RECONNECT_BASE_DELAY = 2000;
const POLL_INTERVAL = 5000;

export function useWebSocket(sessionId: string | null) {
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

    // Fallback: HTTP polling for results when WS is flaky
    const startPolling = useCallback(() => {
        if (!sessionId || pollTimer.current) return;
        pollTimer.current = setInterval(async () => {
            try {
                const result = await getPipelineResults(sessionId);
                if (result && result.agents) {
                    setPipelineResult(result);
                    setIsRunning(false);
                    // Stop polling once we have results
                    if (pollTimer.current) {
                        clearInterval(pollTimer.current);
                        pollTimer.current = null;
                    }
                }
            } catch {
                // Results not ready yet, keep polling
            }
        }, POLL_INTERVAL);
    }, [sessionId]);

    const stopPolling = useCallback(() => {
        if (pollTimer.current) {
            clearInterval(pollTimer.current);
            pollTimer.current = null;
        }
    }, []);

    const connect = useCallback(() => {
        if (!sessionId) return;
        if (reconnectCount.current >= MAX_RECONNECT_ATTEMPTS) {
            console.warn(`[WS] Max reconnect attempts (${MAX_RECONNECT_ATTEMPTS}) reached, falling back to polling`);
            startPolling();
            return;
        }

        const ws = new WebSocket(getWebSocketUrl(sessionId));
        wsRef.current = ws;

        ws.onopen = () => {
            setConnected(true);
            reconnectCount.current = 0; // Reset on successful connect
            stopPolling(); // WS is working, stop polling
        };

        ws.onclose = () => {
            setConnected(false);
            reconnectCount.current += 1;
            const delay = RECONNECT_BASE_DELAY * Math.min(reconnectCount.current, 5);
            reconnectTimer.current = setTimeout(() => {
                if (sessionId) connect();
            }, delay);
        };

        ws.onerror = () => {
            // onclose will fire after onerror, so reconnect is handled there
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
                        // Initialize all agents as idle
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
                }
            } catch (e) {
                console.error('WS parse error:', e);
            }
        };
    }, [sessionId, startPolling, stopPolling]);

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
        startPolling,
    };
}
