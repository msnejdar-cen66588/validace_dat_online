/* API client + WebSocket manager */
const API_BASE = window.location.origin;

const Api = {
  async upload(files, pdfFile, extractedData, lvFile, selectedParcels, model) {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    if (pdfFile) fd.append('pdf_file', pdfFile);
    if (extractedData) fd.append('extracted_data', JSON.stringify(extractedData));
    if (lvFile) fd.append('lv_file', lvFile);
    if (selectedParcels?.length) fd.append('selected_parcels', JSON.stringify(selectedParcels));
    if (model) fd.append('model', model);
    const r = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async uploadBj(files, pdfFile, extractedData, floorDocs, lvFile, model) {
    const fd = new FormData();
    files.forEach(f => fd.append('files', f));
    if (pdfFile) fd.append('pdf_file', pdfFile);
    if (extractedData) fd.append('property_data_json', JSON.stringify(extractedData));
    if (floorDocs) floorDocs.forEach(f => fd.append('floor_area_docs', f));
    if (lvFile) fd.append('lv_pdf_file', lvFile);
    if (model) fd.append('model', model);
    const r = await fetch(`${API_BASE}/api/bj/upload`, { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async parsePdf(file) {
    const fd = new FormData();
    fd.append('pdf_file', file);
    const r = await fetch(`${API_BASE}/api/parse-pdf`, { method: 'POST', body: fd });
    if (!r.ok) return null;
    const data = await r.json();
    return data.property_data || null;
  },

  async parseBjPdf(file) {
    const fd = new FormData();
    fd.append('pdf_file', file);
    const r = await fetch(`${API_BASE}/api/bj/parse-pdf`, { method: 'POST', body: fd });
    if (!r.ok) return null;
    const data = await r.json();
    return data.property_data || null;
  },

  async parseLv(file) {
    const fd = new FormData();
    fd.append('lv_file', file);
    const r = await fetch(`${API_BASE}/api/parse-lv`, { method: 'POST', body: fd });
    if (!r.ok) return null;
    const data = await r.json();
    return data.lv_data || null;
  },

  async startPipeline(sessionId, model) {
    const r = await fetch(`${API_BASE}/api/pipeline/start/${sessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    if (!r.ok) throw new Error('Pipeline start failed');
    return r.json();
  },

  async getPipelineResult(sessionId) {
    const r = await fetch(`${API_BASE}/api/pipeline/results/${sessionId}`);
    if (!r.ok) throw new Error('Result fetch failed');
    return r.json();
  },

  async startBjPipeline(sessionId, model) {
    const r = await fetch(`${API_BASE}/api/bj/pipeline/start/${sessionId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model }),
    });
    if (!r.ok) throw new Error('BJ Pipeline start failed');
    return r.json();
  },

  async getConfig() {
    try {
      const r = await fetch(`${API_BASE}/api/config`);
      return r.json();
    } catch { return { enable_maps: true, enable_valuation: true, enable_external: true }; }
  },

  async uploadBatch(files) {
    const fd = new FormData();
    for (const f of files) fd.append('files', f);
    const r = await fetch(`${API_BASE}/api/batch/upload`, { method: 'POST', body: fd });
    if (!r.ok) { const t = await r.text(); throw new Error(t || 'Batch upload failed'); }
    return r.json();
  },

  async startBatch(batchId, caseIds, model) {
    const r = await fetch(`${API_BASE}/api/batch/start/${batchId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected_case_ids: [...caseIds], model }),
    });
    if (!r.ok) throw new Error('Batch start failed');
    return r.json();
  },

  async uploadBatchBj(files) {
    const fd = new FormData();
    for (const f of files) fd.append('files', f);
    const r = await fetch(`${API_BASE}/api/batch-bj/upload`, { method: 'POST', body: fd });
    if (!r.ok) { const t = await r.text(); throw new Error(t || 'BJ Batch upload failed'); }
    return r.json();
  },

  async startBatchBj(batchId, caseIds, model) {
    const r = await fetch(`${API_BASE}/api/batch-bj/start/${batchId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ selected_case_ids: [...caseIds], model }),
    });
    if (!r.ok) throw new Error('BJ Batch start failed');
    return r.json();
  },
};

/* WebSocket manager with polling fallback */
class WsManager {
  constructor(sessionId, type) {
    this.sessionId = sessionId;
    this.type = type; // 'pipeline' | 'bj' | 'batch' | 'batch-bj'
    this.ws = null;
    this.handlers = {};
    this.agentStatuses = {};
    this.agentLogs = {};
    this.isRunning = false;
  }

  on(event, handler) { this.handlers[event] = handler; return this; }
  _emit(event, data) { if (this.handlers[event]) this.handlers[event](data); }

  connect() {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const pathMap = { pipeline: 'ws/pipeline', bj: 'ws/bj/pipeline', batch: 'ws/batch', 'batch-bj': 'ws/batch-bj' };
    const path = pathMap[this.type] || 'ws/pipeline';
    const url = `${proto}//${location.host}/${path}/${this.sessionId}`;
    try {
      this.ws = new WebSocket(url);
      this.ws.onmessage = (e) => this._onMessage(JSON.parse(e.data));
      this.ws.onclose = () => setTimeout(() => this._emit('close'), 1000);
      this.ws.onerror = () => {};
    } catch { /* polling fallback would go here */ }
    return this;
  }

  _onMessage(msg) {
    if (msg.type === 'agent_status') {
      this.agentStatuses[msg.agent] = msg.status;
      this._emit('status', msg);
    } else if (msg.type === 'agent_log') {
      if (!this.agentLogs[msg.agent]) this.agentLogs[msg.agent] = [];
      this.agentLogs[msg.agent].push(msg);
      this._emit('log', msg);
    } else if (msg.type === 'pipeline_start') {
      this.isRunning = true;
      this._emit('pipeline_start', msg);
    } else if (msg.type === 'pipeline_complete') {
      this.isRunning = false;
      this._emit('pipeline_complete', msg);
    } else if (msg.type === 'valuation_step') {
      this._emit('valuation_step', msg);
    } else if (msg.type === 'valuation_complete') {
      this._emit('valuation_complete', msg);
    } else if (msg.type === 'batch_start') {
      // Initialize cases from batch_start
      if (msg.rev_ids) {
        this.batchCases = msg.rev_ids.map((rid, i) => ({
          case_id: msg.case_ids?.[i] || `${msg.batch_id}_${rid}`,
          rev_id: rid, status: 'pending', session_id: '', semaphore: '', semaphore_color: 'gray',
        }));
      }
      this._emit('batch_start', msg);
    } else if (msg.type === 'batch_case_preparing') {
      this._updateBatchCase(msg.index, { status: 'preparing', rev_id: msg.rev_id });
      this._emit('batch_case_update', { cases: this.batchCases, current_index: msg.index, phase: 'preparing' });
    } else if (msg.type === 'batch_case_start') {
      this._updateBatchCase(msg.index, { status: 'processing', rev_id: msg.rev_id });
      // Reset agent statuses for the new case
      this.agentStatuses = {};
      this.agentLogs = {};
      this._emit('batch_case_update', { cases: this.batchCases, current_index: msg.index, phase: 'processing' });
    } else if (msg.type === 'batch_case_complete') {
      this._updateBatchCase(msg.index, {
        status: 'complete', session_id: msg.session_id,
        semaphore: msg.semaphore, semaphore_color: msg.semaphore_color,
        total_time: msg.total_time, address: msg.address,
      });
      this._emit('batch_case_update', { cases: this.batchCases, current_index: msg.index, phase: 'complete' });
    } else if (msg.type === 'batch_complete') {
      this._emit('batch_complete', msg);
    }
    this._emit('message', msg);
  }

  _updateBatchCase(index, data) {
    if (!this.batchCases) this.batchCases = [];
    while (this.batchCases.length <= index) {
      this.batchCases.push({ case_id: '', rev_id: '', status: 'pending', session_id: '' });
    }
    Object.assign(this.batchCases[index], data);
  }

  close() { if (this.ws) this.ws.close(); }
}
