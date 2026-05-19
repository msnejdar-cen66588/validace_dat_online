/* ProcessingLoader component */
function renderProcessingLoader(container, phase) {
  const STEPS = [
    { key: 'uploading', icon: '📤', label: 'Nahrávání souborů', desc: 'Fotografie a dokumenty se přenášejí na server.' },
    { key: 'compressing', icon: '🗜️', label: 'Komprese a optimalizace', desc: 'Server komprimuje fotografie na optimální velikost.' },
    { key: 'starting', icon: '⚙️', label: 'Příprava validačního systému', desc: 'Inicializace session a příprava dat.' },
    { key: 'ready', icon: '✅', label: 'Předání AI agentům', desc: 'Vše připraveno — podklady se předávají agentům.' },
  ];
  const ORDER = { uploading: 0, compressing: 1, starting: 2, ready: 3 };
  const idx = ORDER[phase] || 0;
  const allDone = phase === 'ready';

  container.innerHTML = `
    <div class="proc-overlay">
      <div class="proc-content">
        <div class="proc-ring-header">
          <div class="proc-ring-container">
            <svg class="proc-ring-svg" viewBox="0 0 160 160">
              <circle class="proc-ring-track" cx="80" cy="80" r="70"/>
              <circle class="proc-ring-arc" cx="80" cy="80" r="70"/>
            </svg>
          </div>
          <div>
            <h2 class="proc-title">${allDone ? 'Zpracování dokončeno' : 'Zpracování podkladů<span class="dots"><span>.</span><span>.</span><span>.</span></span>'}</h2>
            <p class="proc-subtitle">${allDone ? 'Soubory jsou připraveny pro AI analýzu' : 'Nahrávání a příprava souborů — prosím vyčkejte'}</p>
          </div>
        </div>
        <div class="proc-progress-bar"><div class="proc-progress-fill" style="width:${((idx + (allDone ? 1 : 0.5)) / STEPS.length) * 100}%"></div></div>
        <div class="proc-steps">
          ${STEPS.map((s, i) => {
            const active = i === idx && !allDone;
            const done = i < idx || (i === idx && allDone);
            return `<div class="proc-step ${active ? 'proc-step-active' : ''} ${done ? 'proc-step-done' : ''}">
              <div class="proc-step-header">
                <div class="proc-step-icon">${s.icon}</div>
                <div class="proc-step-text"><span class="proc-step-label">${s.label}</span><span class="proc-step-desc">${s.desc}</span></div>
                ${active ? '<div class="proc-step-spinner"></div>' : ''}
                ${done ? '<svg class="proc-step-check" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="rgba(5,150,105,0.15)"/><path d="M6 10.5L8.5 13L14 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>' : ''}
              </div>
            </div>`;
          }).join('')}
        </div>
        <div class="proc-tip"><span>⏱️</span> Příprava podkladů obvykle trvá 5–15 sekund</div>
      </div>
    </div>`;
}
