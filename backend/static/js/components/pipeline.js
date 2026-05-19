/* PipelineCanvas – agent progress tracking */
const AGENTS_CONFIG_RD = [
  { name:'Strazce', label:'Strážce', desc:'Kontrola úplnosti fotodokumentace (BR-G4)', icon:'🛡️', color:'#1e6fd9', wave:'A' },
  { name:'ForenzniAnalytik', label:'Forenzní analytik', desc:'Detekce manipulace a úprav fotografií', icon:'🔬', color:'#6366f1', wave:'A' },
  { name:'Historik', label:'Historik', desc:'Určení věku a kategorizace nemovitosti', icon:'📜', color:'#0891b2', wave:'A' },
  { name:'Inspektor', label:'Inspektor', desc:'Hodnocení technického stavu objektu', icon:'🔍', color:'#d97706', wave:'A' },
  { name:'PorovnavacDokumentu', label:'DocComparator', desc:'Porovnání dat z formuláře vs fotky', icon:'📄', color:'#ea580c', wave:'B' },
  { name:'KatastralniAnalytik', label:'Katastrální analýza', desc:'Analýza LV – rizika, ortofoto', icon:'🏛️', color:'#7c3aed', wave:'B' },
  { name:'GeoValidator', label:'GeoValidator', desc:'Ověření GPS lokace (Mapy.cz)', icon:'📍', color:'#db2777', wave:'B' },
  { name:'Strateg', label:'Stratég', desc:'Agregace výsledků a finální verdikt', icon:'🎯', color:'#059669', wave:'C' },
];

const WAVES_RD = {
  A: { label:'Vlna A – Analýza fotografií', agents:['Strazce','ForenzniAnalytik','Historik','Inspektor'] },
  B: { label:'Vlna B – Dokumenty & lokace', agents:['PorovnavacDokumentu','KatastralniAnalytik','GeoValidator'] },
  C: { label:'Vlna C – Finální verdikt', agents:['Strateg'] },
};

const AGENTS_CONFIG_BJ = [
  { name:'StrazceBJ', label:'Strážce BJ', desc:'Kontrola úplnosti fotodokumentace bytu', icon:'🛡️', color:'#1e6fd9', wave:'A' },
  { name:'ForenzniAnalytik', label:'Forenzní analytik', desc:'Detekce manipulace a úprav fotografií', icon:'🔬', color:'#6366f1', wave:'A' },
  { name:'Historik', label:'Historik', desc:'Určení věku a kategorizace nemovitosti', icon:'📜', color:'#0891b2', wave:'A' },
  { name:'InspektorBJ', label:'Inspektor BJ', desc:'Hodnocení technického stavu bytu', icon:'🔍', color:'#d97706', wave:'A' },
  { name:'PorovnavacDokumentuBJ', label:'DocComparator BJ', desc:'Porovnání dat z formuláře vs fotky', icon:'📄', color:'#ea580c', wave:'B' },
  { name:'KatastralniAnalytik', label:'Katastrální analýza', desc:'Analýza LV – rizika, ortofoto', icon:'🏛️', color:'#7c3aed', wave:'B' },
  { name:'GeoValidator', label:'GeoValidator', desc:'Ověření GPS lokace (Mapy.cz)', icon:'📍', color:'#db2777', wave:'B' },
  { name:'StrategBJ', label:'Stratég BJ', desc:'Agregace výsledků a finální verdikt', icon:'🎯', color:'#059669', wave:'C' },
];

const WAVES_BJ = {
  A: { label:'Vlna A – Analýza fotografií bytu', agents:['StrazceBJ','ForenzniAnalytik','Historik','InspektorBJ'] },
  B: { label:'Vlna B – Dokumenty & lokace', agents:['PorovnavacDokumentuBJ','KatastralniAnalytik','GeoValidator'] },
  C: { label:'Vlna C – Finální verdikt', agents:['StrategBJ'] },
};

const STATUS_LABELS = { idle:'ČEKÁ', queued:'VE FRONTĚ', processing:'ZPRACOVÁVÁ', success:'HOTOVO', fail:'CHYBA', warn:'UPOZORNĚNÍ' };

function renderPipelineCanvas(container, state) {
  const { agentStatuses, agentLogs, started, elapsed, uploadData, onStart, onEdit, mode } = state;
  const isTerminal = s => ['success','fail','warn'].includes(s);
  
  const activeAgentsConfig = mode === 'bj' ? AGENTS_CONFIG_BJ : AGENTS_CONFIG_RD;
  const activeWaves = mode === 'bj' ? WAVES_BJ : WAVES_RD;

  function getStatus(name) {
    if (!started) return 'idle';
    const ws = agentStatuses[name];
    if (ws && isTerminal(ws)) return ws;
    if (ws === 'processing') return 'processing';
    const hasAny = Object.values(agentStatuses).some(s => s !== 'idle' && s);
    if (!hasAny) return 'queued';
    const agent = activeAgentsConfig.find(a => a.name === name);
    const wave = agent?.wave || 'C';
    const order = ['A','B','C'];
    const wIdx = order.indexOf(wave);
    const prevDone = order.slice(0, wIdx).every(pw =>
      activeWaves[pw].agents.every(pa => isTerminal(agentStatuses[pa] || ''))
    );
    if (prevDone) return ws || 'processing';
    return 'queued';
  }

  const completed = activeAgentsConfig.filter(a => isTerminal(getStatus(a.name))).length;
  const allDone = completed >= activeAgentsConfig.length;
  const processing = activeAgentsConfig.filter(a => getStatus(a.name) === 'processing');

  if (!started) {
    container.innerHTML = `
      <div class="pipe-prestart">
        <div class="pipe-prestart-content">
          <div class="pipe-prestart-icon"><svg width="40" height="40" viewBox="0 0 40 40" fill="none"><path d="M8 36V16L20 6L32 16V36H24V26H16V36H8Z" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg></div>
          <h2>Validační agenti připraveni</h2>
          <p class="pipe-prestart-sub">${uploadData ? uploadData.files_processed + ' fotek zpracováno' : 'Dokumenty nahrány'} • 8 AI agentů v 3 paralelních vlnách</p>
          <div class="pipe-prestart-waves">
            ${Object.entries(activeWaves).map(([k, w]) => `
              <div class="pipe-wave-group"><div class="pipe-wave-label">${w.label}</div>
                <div class="pipe-agent-chips">${activeAgentsConfig.filter(a => a.wave === k).map(a => `<div class="pipe-agent-chip"><span>${a.icon}</span> ${a.label}</div>`).join('')}</div>
              </div>`).join('')}
          </div>
          <div class="pipe-prestart-actions">
            <button class="btn btn-secondary" id="pipe-edit-btn"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 2L13 5L5 13H2V10L10 2Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg> Upravit vstup</button>
            <button class="btn btn-primary" id="pipe-start-btn"><svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M5 3L17 10L5 17V3Z" fill="currentColor"/></svg> Spustit analýzu</button>
          </div>
          <div class="pipe-prestart-info">⚡ Agenti běží paralelně — analýza trvá 30–50 sekund</div>
        </div>
      </div>`;
    const editBtn = container.querySelector('#pipe-edit-btn');
    const startBtn = container.querySelector('#pipe-start-btn');
    if (editBtn) editBtn.onclick = onEdit;
    if (startBtn) startBtn.onclick = onStart;
    return;
  }

  // Running state
  container.innerHTML = `
    <div class="pipe-overlay">
      <div class="pipe-content">
        <div class="pipe-ring-container">
          <svg class="pipe-ring-svg" viewBox="0 0 140 140">
            <circle class="pipe-ring-track" cx="70" cy="70" r="60"/>
            <circle class="pipe-ring-arc" cx="70" cy="70" r="60"/>
          </svg>
          <div class="pipe-ring-icon">${allDone ? '✅' : processing.length > 1 ? '⚡' : processing[0]?.icon || '🤖'}</div>
        </div>
        <h2 class="pipe-title">${allDone ? 'Analýza dokončena' : 'Probíhá validace<span class="dots"><span>.</span><span>.</span><span>.</span></span>'}</h2>
        <p class="pipe-subtitle">${allDone ? 'Všichni agenti dokončili kontrolu' : 'AI agenti kontrolují vaše podklady'}</p>
        <div class="pipe-progress-header">
          <span class="pipe-counter">${completed}/${activeAgentsConfig.length}</span>
          <span class="pipe-time">${U.formatTime(elapsed)}</span>
          ${!allDone ? '<div class="pipe-running-badge"><span class="pipe-running-dot"></span> '+(processing.length>1?processing.length+' paralelně':'Probíhá')+'</div>' : '<div class="pipe-done-badge">✓ Dokončeno</div>'}
        </div>
        <div class="pipe-global-progress"><div class="pipe-global-fill" style="width:${(completed/activeAgentsConfig.length)*100}%"></div></div>
        ${processing.length > 0 ? `<div class="pipe-current-wave">${processing.map(a => `<div class="pipe-current-agent" style="color:${a.color}"><strong>${a.icon} ${a.label}</strong></div>`).join('')}</div>` : ''}
        <div class="pipe-agent-steps">
          ${Object.entries(activeWaves).map(([wk, w]) => {
            const wa = activeAgentsConfig.filter(a => a.wave === wk);
            const wDone = wa.every(a => isTerminal(getStatus(a.name)));
            const wProc = wa.some(a => getStatus(a.name) === 'processing');
            return `<div class="pipe-wave"><div class="pipe-wave-header ${wDone?'done':wProc?'active':'queued'}"><span>${wDone?'✓':wProc?'⚡':'○'}</span> ${w.label}</div>
              <div class="pipe-wave-agents">${wa.map(a => {
                const st = getStatus(a.name);
                const isProc = st === 'processing';
                const isDone = isTerminal(st);
                const logs = agentLogs[a.name] || [];
                const lastLog = logs[logs.length - 1];
                return `<div class="pipe-step pipe-step-${st}" style="--agent-color:${a.color}">
                  <div class="pipe-step-header">
                    <div class="pipe-step-icon" style="background:${isProc||isDone ? a.color+'25':''}; color:${isProc||isDone?a.color:''}">${a.icon}</div>
                    <div class="pipe-step-text"><span class="pipe-step-label">${a.label}</span><span class="pipe-step-desc">${isProc && lastLog ? lastLog.message?.substring(0,60) : isProc ? 'Analyzuji...' : a.desc}</span></div>
                    ${isProc ? '<div class="pipe-step-spinner"></div>' : ''}
                    ${st==='success' ? '<svg class="pipe-step-check" viewBox="0 0 22 22"><circle cx="11" cy="11" r="10" fill="rgba(5,150,105,0.15)"/><path d="M7 11.5L9.5 14L15 8" stroke="var(--accent-green)" stroke-width="2" stroke-linecap="round"/></svg>' : ''}
                    ${st==='fail' ? '<svg class="pipe-step-check" viewBox="0 0 22 22"><circle cx="11" cy="11" r="10" fill="rgba(220,38,38,0.15)"/><path d="M8 8L14 14M14 8L8 14" stroke="var(--accent-red)" stroke-width="2" stroke-linecap="round"/></svg>' : ''}
                    ${st==='warn' ? '<svg class="pipe-step-check" viewBox="0 0 22 22"><circle cx="11" cy="11" r="10" fill="rgba(217,119,6,0.15)"/><path d="M11 7V12M11 14.5V15" stroke="var(--accent-orange)" stroke-width="2" stroke-linecap="round"/></svg>' : ''}
                    ${!isProc&&!isDone ? `<span class="pipe-step-badge pipe-badge-${st}">${STATUS_LABELS[st]||st}</span>` : ''}
                  </div>
                  ${isProc ? `<div class="pipe-step-progress"><div class="pipe-step-progress-fill" style="background:${a.color}"></div></div>` : ''}
                </div>`;
              }).join('')}</div></div>`;
          }).join('')}
        </div>
        <div class="pipe-tip">⚡ Agenti běží paralelně • ${U.formatTime(elapsed)}</div>
      </div>
    </div>`;
}
