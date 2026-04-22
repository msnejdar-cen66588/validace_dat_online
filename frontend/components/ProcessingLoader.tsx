'use client';
import { useState, useEffect } from 'react';
import styles from './ProcessingLoader.module.css';

interface Props {
  /** We keep the prop for compatibility, but we will ignore it and run our own simulation */
  phase?: string; 
}

const AGENT_STEPS = [
  {
    key: 'kata',
    icon: '🏛️',
    label: 'Katastrální analytik & Geo',
    desc: 'Stahuje a analyzuje data z Katastru nemovitostí a Listu vlastnictví. Kontroluje přístupové cesty z ortofotomap.',
    duration: 5000,
  },
  {
    key: 'guardian',
    icon: '👁️',
    label: 'Strážce (Guardian)',
    desc: 'Rozpoznává místnosti, hodnotí celkovou kvalitu a ostrost fotografií a hlídá, zda nechybí povinné záběry.',
    duration: 5500,
  },
  {
    key: 'forensic',
    icon: '🔎',
    label: 'Forenzní analytik',
    desc: 'Detekuje potenciální podvody. Analyzuje EXIF metadata a hledá stopy po úpravách ve Photoshopu nebo AI generovaných fotkách.',
    duration: 4500,
  },
  {
    key: 'historian',
    icon: '🕰️',
    label: 'Historik',
    desc: 'Odhaduje skutečný věk stavby na základě vizuálních znaků (typ oken, fasáda, materiály) a porovnává s rokem dokončení.',
    duration: 5000,
  },
  {
    key: 'inspector',
    icon: '👷',
    label: 'Inspektor (Technik)',
    desc: 'Prohledává fotky a detekuje technické závady: praskliny, vlhkost, plísně a nedokončené stavební úpravy.',
    duration: 6000,
  },
  {
    key: 'comparator',
    icon: '⚖️',
    label: 'Porovnávač dokumentů',
    desc: 'Křížově ověřuje zjištěná data. Přepočítává podlaží a odhaduje podlahovou plochu zvenku vs zevnitř k zamezení zkreslení.',
    duration: 5000,
  },
  {
    key: 'strategist',
    icon: '♟️',
    label: 'Strateg (Verdikt)',
    desc: 'Syntetizuje veškerá zjištění od předchozích agentů a vydává závěrečné rozhodnutí a doporučení pro odhadce.',
    duration: 4000,
  },
];

export default function ProcessingLoader({ phase }: Props) {
  const [elapsed, setElapsed] = useState(0);
  const [activeIndex, setActiveIndex] = useState(0);

  // Global timer
  useEffect(() => {
    const start = Date.now();
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, []);

  // Sequence timer for agents
  useEffect(() => {
    let timeoutId: NodeJS.Timeout;

    const processNext = (index: number) => {
      if (index >= AGENT_STEPS.length) return; // All done
      setActiveIndex(index);
      
      timeoutId = setTimeout(() => {
        processNext(index + 1);
      }, AGENT_STEPS[index].duration);
    };

    processNext(0);

    return () => {
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, []);

  return (
    <div className={styles.overlay}>
      <div className={styles.content}>
        
        {/* Header */}
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
              Probíhá AI analýza
              <span className={styles.dots}>
                <span>.</span><span>.</span><span>.</span>
              </span>
            </h2>
            <p className={styles.subtitle}>
              Prosím vyčkejte, systém prochází křížovou kontrolou
            </p>
          </div>
        </div>

        {/* Steps */}
        <div className={styles.steps}>
          {AGENT_STEPS.map((step, idx) => {
            // "ready" phase on backend means everything is loading or done.
            const isActive = idx === activeIndex;
            const isDone = idx < activeIndex;
            
            return (
              <div
                key={step.key}
                className={`${styles.stepItem} ${isActive ? styles.stepItemActive : ''} ${isDone ? styles.stepItemDone : ''}`}
              >
                <div className={styles.stepHeader}>
                  <div className={styles.stepIcon}>{step.icon}</div>
                  <div className={styles.stepText}>
                    <span className={styles.stepLabel}>{step.label}</span>
                  </div>
                  {isActive && <div className={styles.stepSpinner} />}
                  {isDone && (
                    <svg className={styles.stepCheck} viewBox="0 0 20 20" fill="none">
                      <circle cx="10" cy="10" r="9" fill="rgba(5,150,105,0.15)" />
                      <path d="M6 10.5L8.5 13L14 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>
                {/* Accordion detail */}
                <div className={styles.stepDetail}>
                  {step.desc}
                </div>
              </div>
            );
          })}
        </div>

        {/* Tip */}
        <div className={styles.tip}>
          <span className={styles.tipIcon}>⏱️</span>
          <span>Analýza trvá zhruba 35–45 sekund • <strong>{elapsed}s</strong></span>
        </div>

      </div>
    </div>
  );
}
