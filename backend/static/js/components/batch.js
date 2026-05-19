/* BatchDashboard */
function renderBatchDashboard(container, state) {
  const { batchId, batchType, cases, currentIndex, batchComplete, semaphoreSummary,
          elapsed, agentStatuses, agentLogs, phase, onReset, onViewResult } = state;
  const total = cases.length;
  const done = cases.filter(c => c.status === 'complete' || c.status === 'fail').length;
  const typeLabel = batchType === 'bj' ? '🏢 Hromadná kontrola – BJ' : '📁 Hromadná kontrola – RD';

  // Build active agent info for the current case
  const activeAgents = Object.entries(agentStatuses || {}).filter(([, s]) => s === 'processing');
  const doneAgents = Object.entries(agentStatuses || {}).filter(([, s]) => ['success', 'fail', 'warn'].includes(s));
  let agentInfoHtml = '';
  if (!batchComplete && activeAgents.length > 0) {
    agentInfoHtml = activeAgents.map(([name]) => {
      const logs = (agentLogs || {})[name] || [];
      const lastMsg = logs.length > 0 ? logs[logs.length - 1].message || '' : 'Analyzuji...';
      return `<div class="batch-agent-activity">
        <span class="pipe-running-dot"></span>
        <strong>${name}</strong>: <span class="batch-agent-msg">${lastMsg.substring(0, 80)}</span>
      </div>`;
    }).join('');
  }

  let html = `<section class="batch-section"><div class="batch-container">
    <div class="batch-header"><h2>${typeLabel}</h2>
      <div class="batch-progress-info">
        <span>${done}/${total} případů</span>
        <span class="batch-timer">${typeof U !== 'undefined' ? U.formatTime(elapsed || 0) : '0:00'}</span>
        ${batchComplete ? '<span class="batch-done-badge">✓ Dokončeno</span>' : '<span class="batch-running-badge"><span class="pipe-running-dot"></span> Probíhá</span>'}
      </div>
    </div>
    <div class="batch-progress-bar"><div class="batch-progress-fill" style="width:${total>0?(done/total)*100:0}%"></div></div>`;

  // Current case agent activity panel
  if (!batchComplete && currentIndex >= 0 && currentIndex < total) {
    const currentCase = cases[currentIndex];
    const phaseLabel = phase === 'preparing' ? '📦 Příprava podkladů...'
                     : phase === 'processing' ? '🤖 AI agenti pracují...'
                     : currentCase?.status === 'processing' ? '🤖 AI agenti pracují...'
                     : currentCase?.status === 'preparing' ? '📦 Příprava podkladů...'
                     : '';
    if (phaseLabel) {
      html += `<div class="batch-current-info">
        <div class="batch-current-header">
          <span class="batch-current-label">REV ${currentCase?.rev_id || '?'}</span>
          <span class="batch-current-phase">${phaseLabel}</span>
          <span class="batch-agents-done">${doneAgents.length} agentů hotovo</span>
        </div>
        ${agentInfoHtml ? `<div class="batch-agent-panel">${agentInfoHtml}</div>` : ''}
      </div>`;
    }
  }

  // Semaphore summary
  if (batchComplete && semaphoreSummary) {
    html += `<div class="batch-summary">
      ${semaphoreSummary.green ? `<div class="semaphore green">✅ ${semaphoreSummary.green}× ZELENÁ</div>` : ''}
      ${semaphoreSummary.orange ? `<div class="semaphore orange">⚠️ ${semaphoreSummary.orange}× ORANŽOVÁ</div>` : ''}
      ${semaphoreSummary.red ? `<div class="semaphore red">🔴 ${semaphoreSummary.red}× ČERVENÁ</div>` : ''}
      ${semaphoreSummary.error ? `<div class="semaphore red">❌ ${semaphoreSummary.error}× CHYBA</div>` : ''}
    </div>`;
  }

  // Case list
  html += `<div class="batch-cases">`;
  cases.forEach((c, i) => {
    const isCurrent = i === currentIndex && !batchComplete;
    const isDone = c.status === 'complete' || c.status === 'fail';
    const isPreparing = c.status === 'preparing';
    const isProcessing = c.status === 'processing';
    const color = c.semaphore_color || 'gray';

    let statusBadge = '';
    if (isDone) {
      statusBadge = `<span class="res-badge ${color==='green'?'badge-success':color==='orange'?'badge-warn':'badge-fail'}">${c.semaphore || c.status}</span>`;
      if (c.total_time) statusBadge += `<span style="font-size:11px;color:var(--text-muted);margin-left:6px">${c.total_time.toFixed(1)}s</span>`;
    } else if (isPreparing) {
      statusBadge = '<span style="font-size:11px;color:var(--text-muted)">📦 Příprava...</span>';
    } else if (isProcessing) {
      statusBadge = '<div class="pipe-step-spinner" style="width:14px;height:14px"></div>';
    }

    html += `<div class="batch-case ${isCurrent?'batch-case-active':''} ${isDone?'batch-case-done':''}">
      <div class="batch-case-header">
        <span class="batch-case-rev">REV ${c.rev_id || c.case_id}</span>
        <div style="flex:1"></div>
        ${statusBadge}
      </div>`;
    if (isDone && c.session_id) {
        const pdfUrl = `${window.API_BASE || ''}/api/pipeline/report/${c.session_id}`;
        html += `<div class="batch-case-actions" style="display:flex;gap:8px;margin-top:10px;justify-content:flex-end;">
          <a href="${pdfUrl}" target="_blank" class="btn btn-secondary" style="padding:4px 10px;font-size:12px;display:flex;align-items:center;gap:4px;">📄 Stáhnout PDF</a>
          <button class="btn btn-secondary btn-batch-detail" data-session="${c.session_id}" style="padding:4px 10px;font-size:12px;">🔍 Detail</button>
        </div>`;
    }
    html += `</div>`;
  });
  html += `</div>`;

  if (batchComplete) {
    html += `<div class="batch-actions"><button class="btn btn-primary" id="batch-reset-btn">← Nová kontrola</button></div>`;
  }
  html += `</div></section>`;
  container.innerHTML = html;

  const resetBtn = container.querySelector('#batch-reset-btn');
  if (resetBtn) resetBtn.onclick = onReset;

  container.querySelectorAll('.btn-batch-detail').forEach(btn => {
    btn.onclick = () => { if (onViewResult) onViewResult(btn.dataset.session); };
  });
}

/* Batch case selection */
function renderBatchSelect(container, state) {
  const { batchCases, selectedIds, onStart, onBack } = state;
  let html = `<section class="batch-section"><div class="batch-container">
    <h2 style="display:flex;align-items:center;gap:10px;margin-bottom:4px"><span style="font-size:22px">📁</span> Hromadná kontrola — výběr případů</h2>
    <p style="font-size:13px;color:var(--text-muted);margin-bottom:20px">Nalezeno ${batchCases.length} případů • Vyberte, které chcete analyzovat</p>
    <div style="display:flex;gap:12px;margin-bottom:16px">
      <button class="btn btn-secondary" id="batch-sel-all" style="padding:6px 14px;font-size:12px">✓ Vybrat vše</button>
      <button class="btn btn-secondary" id="batch-sel-none" style="padding:6px 14px;font-size:12px">Odznačit vše</button>
    </div>
    <div class="batch-select-list">`;
  batchCases.forEach(c => {
    const sel = selectedIds.has(c.case_id);
    html += `<label class="batch-select-item ${sel?'selected':''}">
      <input type="checkbox" ${sel?'checked':''} data-id="${c.case_id}" style="accent-color:#2870ED;width:16px;height:16px">
      <span style="font-weight:700;min-width:80px">REV ${c.rev_id}</span>
      ${c.file_counts ? `<span style="font-size:12px;color:var(--text-muted)">📷 ${c.file_counts.images} fotek • 📄 ${c.file_counts.pdfs} PDF</span>` : ''}
    </label>`;
  });
  html += `</div>
    <div style="display:flex;gap:12px;margin-top:24px">
      <button class="btn btn-secondary" id="batch-back-btn">← Zpět</button>
      <button class="btn btn-primary" id="batch-go-btn" ${selectedIds.size===0?'disabled':''} style="flex:1">
        <svg width="18" height="18" viewBox="0 0 18 18" fill="none"><path d="M6 3L14 9L6 15V3Z" fill="currentColor"/></svg>
        Spustit kontrolu (${selectedIds.size} případů)
      </button>
    </div>
  </div></section>`;
  container.innerHTML = html;

  container.querySelector('#batch-sel-all').onclick = () => { batchCases.forEach(c => selectedIds.add(c.case_id)); renderBatchSelect(container, state); };
  container.querySelector('#batch-sel-none').onclick = () => { selectedIds.clear(); renderBatchSelect(container, state); };
  container.querySelector('#batch-back-btn').onclick = onBack;
  container.querySelector('#batch-go-btn').onclick = () => onStart();
  container.querySelectorAll('input[type=checkbox]').forEach(cb => {
    cb.onchange = () => {
      const id = cb.dataset.id;
      if (cb.checked) selectedIds.add(id); else selectedIds.delete(id);
      renderBatchSelect(container, state);
    };
  });
}
