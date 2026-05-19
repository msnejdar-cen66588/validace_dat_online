/* Main App – state management and view routing */
(function() {
  const appEl = document.getElementById('app');
  let ws = null;
  let pipelineTimer = null;

  // Global state
  const S = {
    step: 'upload', // upload | processing | pipeline | results | batch-select | batch
    mode: 'single', // single | bj | batch-rd | batch-bj
    selectedModel: 'gemini',
    modelOpen: false,
    // Upload
    files: [], pdfFile: null, extractedData: null, dataSource: 'pdf',
    manualData: { ...EMPTY_PROPERTY_DATA },
    lvFile: null, lvData: null, selectedParcels: [],
    // BJ
    bjFiles: [], bjPdfFile: null, bjExtractedData: null, bjFloorAreaDocs: [], bjLvFile: null, bjPdfParsing: false,
    // Pipeline
    sessionId: null, uploadData: null, error: null, uploading: false,
    agentStatuses: {}, agentLogs: {}, pipelineStarted: false, elapsed: 0,
    // Results
    finalResult: null,
    // Batch
    batchId: null, batchCases: [], selectedBatchCaseIds: new Set(),
    batchWs: { cases: [], currentIndex: -1, batchComplete: false, semaphoreSummary: null },
    // Info
    showInfo: false,
    // Feature flags
    config: { enable_maps: true, enable_valuation: true, enable_external: true },
  };

  // Load config
  Api.getConfig().then(c => { S.config = c; });

  function render() {
    appEl.innerHTML = '';
    // Header
    const stepIdx = { upload: 0, processing: 1, pipeline: 2, results: 3, 'batch-select': 1, batch: 2 }[S.step] || 0;
    const header = `<header class="header"><div class="header-content">
      <div class="logo"><div class="logo-icon"><svg width="20" height="20" viewBox="0 0 24 24" fill="none"><path d="M4 21V9L12 3L20 9V21H14V14H10V21H4Z" stroke="white" stroke-width="2"/></svg></div>
        <div><div class="logo-title">Kontrola vstupních dat</div><div class="logo-subtitle">AI validační systém</div></div></div>
      <div class="steps">
        ${['Nahrání','Zpracování','Analýza','Výsledky'].map((s, i) => {
          const cls = i === stepIdx ? 'step-active' : i < stepIdx ? 'step-done' : '';
          return `<div class="step ${cls}"><div class="step-num">${i < stepIdx ? '✓' : i+1}</div><span>${s}</span></div>${i<3?'<div class="step-line"></div>':''}`;
        }).join('')}
      </div>
      <button class="info-btn" id="info-btn">?</button>
    </div></header>`;

    const content = document.createElement('div');
    appEl.innerHTML = header;
    appEl.appendChild(content);

    // Info button
    document.getElementById('info-btn').onclick = () => { S.showInfo = true; renderInfo(); };

    // Route to current step
    if (S.step === 'upload') renderUploadView(content);
    else if (S.step === 'processing') renderProcessingLoader(content, S.processingPhase || 'uploading');
    else if (S.step === 'pipeline') renderPipelineView(content);
    else if (S.step === 'results') renderResultsView(content);
    else if (S.step === 'batch-select') renderBatchSelectView(content);
    else if (S.step === 'batch') renderBatchView(content);
  }

  function renderInfo() {
    const infoDiv = document.createElement('div');
    document.body.appendChild(infoDiv);
    renderAppInfo(infoDiv, () => { S.showInfo = false; infoDiv.remove(); });
  }

  function renderUploadView(el) {
    // Pass S directly so mutations in upload.js propagate back
    S.onModeChange = (m) => { S.mode = m; render(); };
    S.onModelChange = (m) => { S.selectedModel = m; render(); };
    S.onFilesChange = (f) => { S.files = Array.from(f); render(); };
    S.onBjFilesChange = (f) => { S.bjFiles = Array.from(f); render(); };
    S.onError = (e) => { S.error = e; render(); };
    S.onUpload = () => handleUpload();
    S.onBatchUpload = (files) => handleBatchUpload(files);
    S.onBatchBjUpload = (files) => handleBatchBjUpload(files);
    renderUpload(el, S);
  }

  function renderPipelineView(el) {
    renderPipelineCanvas(el, {
      mode: S.mode,
      agentStatuses: S.agentStatuses,
      agentLogs: S.agentLogs,
      started: S.pipelineStarted,
      elapsed: S.elapsed,
      uploadData: S.uploadData,
      onStart: () => handleStartPipeline(),
      onEdit: () => handleEdit(),
    });
  }

  function renderResultsView(el) {
    renderResultsDashboard(el, {
      result: S.finalResult,
      onReset: () => handleReset(),
      onEdit: () => handleEdit(),
      isBatchMode: !!S.batchId,
      onBackToBatch: () => { S.step = 'batch'; render(); },
    });
  }

  function renderBatchSelectView(el) {
    renderBatchSelect(el, {
      batchCases: S.batchCases,
      selectedIds: S.selectedBatchCaseIds,
      onStart: () => handleStartBatch(),
      onBack: () => { S.step = 'upload'; render(); },
    });
  }

  function renderBatchView(el) {
    const isBj = S.mode === 'batch-bj';
    renderBatchDashboard(el, {
      batchId: S.batchId,
      batchType: isBj ? 'bj' : 'rd',
      cases: S.batchWs.cases.length > 0 ? S.batchWs.cases : S.batchCases,
      currentIndex: S.batchWs.currentIndex,
      batchComplete: S.batchWs.batchComplete,
      semaphoreSummary: S.batchWs.semaphoreSummary,
      elapsed: S.batchElapsed || 0,
      agentStatuses: S.batchAgentStatuses || {},
      agentLogs: S.batchAgentLogs || {},
      phase: S.batchPhase || '',
      onReset: () => handleReset(),
      onViewResult: (id) => handleViewBatchResult(id),
    });
  }

  // ── Handlers ───────────────────────────────────────

  async function handleUpload() {
    // Client-side validation
    const requiredFiles = S.mode === 'bj' ? S.bjFiles : S.files;
    if (requiredFiles.length === 0) {
      S.error = S.mode === 'bj'
        ? 'Nahrajte prosím fotografie bytu před odesláním.'
        : 'Nahrajte prosím fotografie nemovitosti před odesláním.';
      render();
      return;
    }

    S.uploading = true; S.error = null;
    S.processingPhase = 'uploading';
    S.step = 'processing';
    render();

    try {
      let data;
      if (S.mode === 'bj') {
        data = await Api.uploadBj(S.bjFiles, S.bjPdfFile, S.bjExtractedData, S.bjFloorAreaDocs, S.bjLvFile, S.selectedModel);
      } else {
        const propData = S.dataSource === 'pdf' ? S.extractedData : S.manualData;
        data = await Api.upload(S.files, S.pdfFile, propData, S.lvFile, S.selectedParcels, S.selectedModel);
      }
      S.uploadData = data;
      S.sessionId = data.session_id;
      S.uploading = false;
      S.step = 'pipeline';
      S.pipelineStarted = false;
      S.agentStatuses = {};
      S.agentLogs = {};
      S.elapsed = 0;
      render();
    } catch (e) {
      S.uploading = false;
      // Parse API error messages
      let msg = e.message || 'Neznámá chyba';
      try {
        const parsed = JSON.parse(msg);
        if (parsed.detail) {
          msg = Array.isArray(parsed.detail)
            ? parsed.detail.map(d => d.msg || d).join(', ')
            : String(parsed.detail);
        }
      } catch (_) { /* not JSON, use as-is */ }
      S.error = msg;
      S.step = 'upload';
      render();
    }
  }

  async function handleStartPipeline() {
    S.pipelineStarted = true;
    S.elapsed = 0;
    const startTime = Date.now();
    pipelineTimer = setInterval(() => {
      S.elapsed = Math.floor((Date.now() - startTime) / 1000);
      // Re-render pipeline only
      const content = appEl.querySelector('.pipe-time, .pipe-counter');
      if (content) {
        const timeEl = appEl.querySelector('.pipe-time');
        const counterEl = appEl.querySelector('.pipe-counter');
        if (timeEl) timeEl.textContent = U.formatTime(S.elapsed);
      }
    }, 1000);

    // Connect WebSocket
    const wsType = S.mode === 'bj' ? 'bj' : 'pipeline';
    ws = new WsManager(S.sessionId, wsType);
    ws.on('status', () => { S.agentStatuses = { ...ws.agentStatuses }; renderPipelineView(appEl.lastElementChild); });
    ws.on('log', () => { S.agentLogs = { ...ws.agentLogs }; });
    ws.on('pipeline_complete', (msg) => {
      clearInterval(pipelineTimer);
      S.finalResult = msg.result;
      setTimeout(() => { S.step = 'results'; render(); }, 1500);
    });
    ws.connect();

    try {
      if (S.mode === 'bj') {
        await Api.startBjPipeline(S.sessionId, S.selectedModel);
      } else {
        await Api.startPipeline(S.sessionId, S.selectedModel);
      }
    } catch (e) {
      S.error = e.message;
      clearInterval(pipelineTimer);
      S.step = 'upload';
      render();
    }
    render();
  }

  async function handleBatchUpload(files) {
    S.uploading = true; S.error = null;
    render();
    try {
      const data = await Api.uploadBatch(files);
      S.batchId = data.batch_id;
      S.batchCases = data.cases || [];
      S.selectedBatchCaseIds = new Set(S.batchCases.map(c => c.case_id));
      S.uploading = false;
      S.mode = 'batch-rd';
      S.step = 'batch-select';
      render();
    } catch (e) {
      S.uploading = false;
      let msg = e.message || 'Neznámá chyba';
      try { const p = JSON.parse(msg); if (p.detail) msg = p.detail; } catch (_) {}
      S.error = msg;
      render();
    }
  }

  async function handleBatchBjUpload(files) {
    S.uploading = true; S.error = null;
    render();
    try {
      const data = await Api.uploadBatchBj(files);
      S.batchId = data.batch_id;
      S.batchCases = data.cases || [];
      S.selectedBatchCaseIds = new Set(S.batchCases.map(c => c.case_id));
      S.uploading = false;
      S.mode = 'batch-bj';
      S.step = 'batch-select';
      render();
    } catch (e) {
      S.uploading = false;
      let msg = e.message || 'Neznámá chyba';
      try { const p = JSON.parse(msg); if (p.detail) msg = p.detail; } catch (_) {}
      S.error = msg;
      render();
    }
  }

  async function handleStartBatch() {
    S.step = 'batch';
    S.batchWs = { cases: [], currentIndex: 0, batchComplete: false, semaphoreSummary: null };
    S.batchElapsed = 0;
    S.batchAgentStatuses = {};
    S.batchAgentLogs = {};
    S.batchPhase = '';
    render();

    // Start elapsed timer
    const batchStartTime = Date.now();
    if (pipelineTimer) clearInterval(pipelineTimer);
    pipelineTimer = setInterval(() => {
      S.batchElapsed = Math.floor((Date.now() - batchStartTime) / 1000);
      // Update just the timer element if it exists
      const timerEl = appEl.querySelector('.batch-timer');
      if (timerEl) timerEl.textContent = U.formatTime(S.batchElapsed);
    }, 1000);

    // Connect batch WebSocket — use batch-bj type if in BJ mode
    const isBj = S.mode === 'batch-bj';
    ws = new WsManager(S.batchId, isBj ? 'batch-bj' : 'batch');

    ws.on('batch_case_update', (msg) => {
      S.batchWs.cases = msg.cases || S.batchWs.cases;
      S.batchWs.currentIndex = msg.current_index ?? S.batchWs.currentIndex;
      S.batchPhase = msg.phase || '';
      renderBatchView(appEl.lastElementChild);
    });

    // Forward agent status/log for live feedback on current case
    ws.on('status', (msg) => {
      S.batchAgentStatuses = { ...ws.agentStatuses };
      renderBatchView(appEl.lastElementChild);
    });
    ws.on('log', (msg) => {
      S.batchAgentLogs = { ...ws.agentLogs };
      renderBatchView(appEl.lastElementChild);
    });

    ws.on('batch_complete', (msg) => {
      S.batchWs.batchComplete = true;
      S.batchWs.semaphoreSummary = msg.semaphore_summary;
      clearInterval(pipelineTimer);
      renderBatchView(appEl.lastElementChild);
    });
    ws.connect();

    try {
      if (isBj) {
        await Api.startBatchBj(S.batchId, S.selectedBatchCaseIds, S.selectedModel);
      } else {
        await Api.startBatch(S.batchId, S.selectedBatchCaseIds, S.selectedModel);
      }
    } catch (e) { S.error = e.message; clearInterval(pipelineTimer); S.step = 'upload'; render(); }
  }

  function handleEdit() {
    if (ws) ws.close();
    clearInterval(pipelineTimer);
    S.step = 'upload';
    render();
  }

  function handleReset() {
    if (ws) ws.close();
    clearInterval(pipelineTimer);
    Object.assign(S, {
      step: 'upload', files: [], pdfFile: null, extractedData: null, dataSource: 'pdf',
      manualData: { ...EMPTY_PROPERTY_DATA }, lvFile: null, lvData: null, selectedParcels: [],
      bjFiles: [], bjPdfFile: null, bjExtractedData: null, bjFloorAreaDocs: [], bjLvFile: null,
      sessionId: null, uploadData: null, error: null, uploading: false,
      agentStatuses: {}, agentLogs: {}, pipelineStarted: false, elapsed: 0,
      finalResult: null, batchId: null, batchCases: [], selectedBatchCaseIds: new Set(),
      batchWs: { cases: [], currentIndex: -1, batchComplete: false, semaphoreSummary: null },
      batchElapsed: 0, batchAgentStatuses: {}, batchAgentLogs: {}, batchPhase: '',
    });
    render();
  }

  async function handleViewBatchResult(sessionId) {
    try {
      const data = await Api.getPipelineResult(sessionId);
      if (data.completed) {
        S.finalResult = data;
        S.step = 'results';
        render();
      } else {
        alert('Výsledek pro tento případ ještě není plně dostupný.');
      }
    } catch (e) {
      alert('Nepodařilo se načíst detail výsledku.');
      console.error(e);
    }
  }

  // Initial render
  render();
})();
