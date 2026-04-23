'use client';
import { useState, useEffect } from 'react';
import styles from './ProcessingLoader.module.css';

interface Props {
  phase: 'uploading' | 'compressing' | 'starting' | 'ready';
}

const PROCESSING_STEPS = [
  {
    key: 'uploading',
    icon: '📤',
    label: 'Nahrávání souborů',
    desc: 'Fotografie a dokumenty se přenášejí na server ke zpracování.',
  },
  {
    key: 'compressing',
    icon: '🗜️',
    label: 'Komprese a optimalizace',
    desc: 'Server komprimuje fotografie na optimální velikost pro AI analýzu (max 2 MB).',
  },
  {
    key: 'starting',
    icon: '⚙️',
    label: 'Příprava validačního systému',
    desc: 'Inicializace session a příprava dat pro předání AI agentům.',
  },
  {
    key: 'ready',
    icon: '✅',
    label: 'Předání AI agentům',
    desc: 'Vše je připraveno — podklady se předávají validačním agentům.',
  },
];

const PHASE_ORDER: Record<string, number> = {
  uploading: 0,
  compressing: 1,
  starting: 2,
  ready: 3,
};

export default function ProcessingLoader({ phase }: Props) {
  const [elapsed, setElapsed] = useState(0);

  // Global timer
  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  const activeIndex = PHASE_ORDER[phase] ?? 0;
  const completedCount = activeIndex;
  const allDone = phase === 'ready';

  return (
    <div className={styles.overlay}>
      <div className={styles.content}>

        {/* Animated ring */}
        <div className={styles.ringHeader}>
          <div className={styles.ringContainer}>
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
          </div>
          <div className={styles.titleWrapper}>
            <h2 className={styles.title}>
              {allDone ? 'Zpracování dokončeno' : 'Zpracování podkladů'}
              {!allDone && (
                <span className={styles.dots}>
                  <span>.</span><span>.</span><span>.</span>
                </span>
              )}
            </h2>
            <p className={styles.subtitle}>
              {allDone
                ? 'Soubory jsou připraveny pro AI analýzu'
                : 'Nahrávání a příprava souborů — prosím vyčkejte'}
            </p>
          </div>
        </div>

        {/* Progress bar */}
        <div className={styles.progressBar}>
          <div
            className={styles.progressFill}
            style={{ width: `${((completedCount + (allDone ? 1 : 0.5)) / PROCESSING_STEPS.length) * 100}%` }}
          />
        </div>

        {/* Steps */}
        <div className={styles.steps}>
          {PROCESSING_STEPS.map((step, idx) => {
            const isActive = idx === activeIndex;
            const isDone = idx < activeIndex || (idx === activeIndex && phase === 'ready');

            return (
              <div
                key={step.key}
                className={`${styles.stepItem} ${isActive && !isDone ? styles.stepItemActive : ''} ${isDone ? styles.stepItemDone : ''}`}
              >
                <div className={styles.stepHeader}>
                  <div className={styles.stepIcon}>{step.icon}</div>
                  <div className={styles.stepText}>
                    <span className={styles.stepLabel}>{step.label}</span>
                    <span className={styles.stepDesc}>{step.desc}</span>
                  </div>
                  {isActive && !isDone && <div className={styles.stepSpinner} />}
                  {isDone && (
                    <svg className={styles.stepCheck} viewBox="0 0 20 20" fill="none">
                      <circle cx="10" cy="10" r="9" fill="rgba(5,150,105,0.15)" />
                      <path d="M6 10.5L8.5 13L14 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>

              </div>
            );
          })}
        </div>

        {/* Tip */}
        <div className={styles.tip}>
          <span className={styles.tipIcon}>⏱️</span>
          <span>Příprava podkladů obvykle trvá 5–15 sekund • <strong>{elapsed}s</strong></span>
        </div>

      </div>
    </div>
  );
}
