'use client';
import { useState, useEffect } from 'react';
import styles from './ProcessingLoader.module.css';

interface Props {
  /** Current processing phase: 'uploading' | 'compressing' | 'starting' | 'ready' */
  phase: 'uploading' | 'compressing' | 'starting' | 'ready';
}

const STEPS = [
  {
    key: 'uploading',
    icon: '📤',
    label: 'Nahrávání souborů',
    desc: 'Odesílání dokumentů a fotografií na server',
  },
  {
    key: 'compressing',
    icon: '🔍',
    label: 'Předzpracování fotografií',
    desc: 'Komprese a optimalizace snímků',
  },
  {
    key: 'starting',
    icon: '🤖',
    label: 'Spouštění AI agentů',
    desc: 'Inicializace validačního systému',
  },
  {
    key: 'ready',
    icon: '📊',
    label: 'Příprava pipeline',
    desc: 'Napojení na validační vrstvu',
  },
];

export default function ProcessingLoader({ phase }: Props) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const currentIdx = STEPS.findIndex(s => s.key === phase);

  return (
    <div className={styles.overlay}>
      <div className={styles.content}>
        {/* Animated ring */}
        <div className={styles.ringContainer}>
          <div className={styles.ringOuter} />
          <svg className={styles.ringSvg} viewBox="0 0 160 160">
            <defs>
              <linearGradient id="loaderGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stopColor="#2870ED" />
                <stop offset="50%" stopColor="#1A5FD9" />
                <stop offset="100%" stopColor="#0D3B78" />
              </linearGradient>
            </defs>
            <circle className={styles.ringTrack} cx="80" cy="80" r="70" />
            <circle className={styles.ringArc} cx="80" cy="80" r="70" />
          </svg>
          <div className={styles.ringIcon}>
            <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
              <path d="M6 28V12L16 4L26 12V28H20V20H12V28H6Z" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M12 28V20H20V28" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
        </div>

        {/* Title */}
        <h2 className={styles.title}>
          Zpracovávám vaše dokumenty
          <span className={styles.dots}>
            <span>.</span><span>.</span><span>.</span>
          </span>
        </h2>
        <p className={styles.subtitle}>
          Prosím vyčkejte, probíhá analýza nahraných podkladů
        </p>

        {/* Step indicators */}
        <div className={styles.steps}>
          {STEPS.map((step, idx) => {
            const isActive = idx === currentIdx;
            const isDone = idx < currentIdx;
            return (
              <div
                key={step.key}
                className={`${styles.stepItem} ${isActive ? styles.stepItemActive : ''} ${isDone ? styles.stepItemDone : ''}`}
              >
                <div className={styles.stepIcon}>{step.icon}</div>
                <div className={styles.stepText}>
                  <span className={styles.stepLabel}>{step.label}</span>
                  <span className={styles.stepDesc}>{step.desc}</span>
                </div>
                {isActive && <div className={styles.stepSpinner} />}
                {isDone && (
                  <svg className={styles.stepCheck} viewBox="0 0 20 20" fill="none">
                    <circle cx="10" cy="10" r="9" fill="rgba(5,150,105,0.15)" />
                    <path d="M6 10.5L8.5 13L14 7" stroke="var(--accent-green)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </div>
            );
          })}
        </div>

        {/* Tip */}
        <div className={styles.tip}>
          <span className={styles.tipIcon}>⏱️</span>
          Analýza obvykle trvá 30–60 sekund • {elapsed}s
        </div>
      </div>
    </div>
  );
}
