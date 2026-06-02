'use client';
import { useState, useEffect, useRef } from 'react';
import styles from './TokenCounter.module.css';

interface TokenUsage {
  prompt: number;
  completion: number;
  total: number;
}

interface Props {
  tokenUsage: TokenUsage;
  model?: string;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toString();
}

export default function TokenCounter({ tokenUsage, model }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [pulse, setPulse] = useState(false);
  const prevTotal = useRef(0);

  useEffect(() => {
    if (tokenUsage.total > prevTotal.current) {
      setPulse(true);
      const t = setTimeout(() => setPulse(false), 600);
      prevTotal.current = tokenUsage.total;
      return () => clearTimeout(t);
    }
  }, [tokenUsage.total]);

  const hasData = tokenUsage.total > 0;

  return (
    <div
      className={`${styles.widget} ${expanded ? styles.expanded : ''} ${pulse ? styles.pulse : ''} ${!hasData ? styles.idle : ''}`}
      onClick={() => setExpanded(v => !v)}
      title={expanded ? 'Skrýt detail tokenů' : 'Zobrazit detail tokenů'}
    >
      {!expanded && (
        <div className={styles.pill}>
          <span className={styles.icon}>⬡</span>
          <span className={styles.totalLabel}>{hasData ? formatTokens(tokenUsage.total) : '0'} tok</span>
          <span className={styles.expandArrow}>›</span>
        </div>
      )}

      {expanded && (
        <div className={styles.panel}>
          <div className={styles.panelHeader}>
            <span className={styles.icon}>⬡</span>
            <span className={styles.panelTitle}>Tokeny</span>
            {model && <span className={styles.modelBadge}>{model}</span>}
            <span className={styles.closeArrow}>‹</span>
          </div>
          <div className={styles.rows}>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Vstup</span>
              <span className={styles.rowValue}>{tokenUsage.prompt.toLocaleString('cs-CZ')}</span>
            </div>
            <div className={styles.row}>
              <span className={styles.rowLabel}>Výstup</span>
              <span className={styles.rowValue}>{tokenUsage.completion.toLocaleString('cs-CZ')}</span>
            </div>
            <div className={`${styles.row} ${styles.rowTotal}`}>
              <span className={styles.rowLabel}>Celkem</span>
              <span className={styles.rowValue}>{tokenUsage.total.toLocaleString('cs-CZ')}</span>
            </div>
          </div>
          {!hasData && (
            <div className={styles.emptyNote}>Pipeline zatím nebyla spuštěna</div>
          )}
        </div>
      )}
    </div>
  );
}
