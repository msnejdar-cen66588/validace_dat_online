/* Upload component – handles file upload, PDF parsing, mode switching */

const DATA_LABELS = {
  rok_dokonceni:'Rok dokončení', stav_rodinneho_domu:'Stav RD', pocet_nadz_podlazi:'Nadzemní podlaží',
  podsklepeni:'Podsklepení', celkova_podlahova_plocha:'Podlahová plocha', plocha_pozemku:'Plocha pozemku',
  typ_strechy:'Typ střechy', typ_vytapeni:'Typ vytápění', podkrovi:'Podkroví',
  podkrovi_obytne:'Obytné podkroví', vyuziti_podkrovi_procent:'Využití podkroví (%)', adresa:'Adresa',
};

const BJ_DATA_LABELS = {
  rok_dokonceni_budovy:'Rok dokončení budovy', rok_rekonstrukce:'Rok rekonstrukce',
  konstrukce:'Konstrukce', stav_budovy:'Stav budovy', vytah:'Výtah',
  podlazi_jednotky:'Podlaží jednotky', pocet_nadz_podlazi:'Počet nadzemních podlaží',
  pocet_podz_podlazi:'Počet podzemních podlaží', typ_strechy:'Typ střechy',
  obytne_podkrovi:'Obytné podkroví', zatepleni:'Zateplení', typ_oken:'Typ oken',
  ohrev_vody:'Ohřev vody', vetrani:'Větrání', rekuperace:'Rekuperace',
  solarni_panely:'Solární panely', typ_jednotky:'Typ jednotky',
  pocet_garazi:'Počet garáží/stání', typ_vytapeni:'Typ vytápění',
  plocha_bytu:'Plocha bytu', plocha_terasy:'Plocha terasy',
  plocha_balkonu:'Plocha balkonu', plocha_sklepa:'Plocha sklepa/skladu',
  plocha_zahrady:'Plocha zahrady', stav_bytu:'Stav bytu', adresa:'Adresa',
};

const EMPTY_PROPERTY_DATA = {
  rok_dokonceni:'', stav_rodinneho_domu:'', pocet_nadz_podlazi:'', podsklepeni:'',
  celkova_podlahova_plocha:'', plocha_pozemku:'', typ_strechy:'', typ_vytapeni:'',
  podkrovi:'', podkrovi_obytne:'', vyuziti_podkrovi_procent:'', adresa:'',
};

const MODEL_OPTIONS = [
  { provider:'Google', icon:'✦', models:[
    { value:'gemini', name:'Gemini 3.1 Flash', desc:'Rychlý a efektivní' },
    { value:'gemini-3.1-pro', name:'Gemini 3.1 Pro', desc:'Nejpřesnější' },
  ]},
  { provider:'OpenAI', icon:'🤖', models:[
    { value:'čs', name:'čs', desc:'Česká spořitelna (OpenAI)' },
  ]},
];

function renderUpload(container, state) {
  const { mode, files, pdfFile, extractedData, dataSource, manualData, lvFile, lvData,
    selectedParcels, selectedModel, error, uploading, modelOpen,
    // BJ state
    bjFiles, bjPdfFile, bjExtractedData, bjFloorAreaDocs, bjLvFile, bjPdfParsing,
    // Handlers
    onModeChange, onFilesChange, onUpload, onModelChange, onError } = state;

  const modelInfo = MODEL_OPTIONS.flatMap(p => p.models).find(m => m.value === selectedModel) || { name: selectedModel };

  let html = `<section class="upload-section"><div class="upload-container">
    <div class="section-title"><span class="title-gradient">Kontrola vstupních dat</span><span class="title-sub">Nahrajte fotografie a dokumenty pro AI validaci</span></div>`;

  // Mode switcher
  html += `<div class="mode-switcher">
    <button class="mode-btn ${mode==='single'?'active':''}" data-mode="single">🏠 Rodinný dům</button>
    <button class="mode-btn ${mode==='bj'?'active':''}" data-mode="bj">🏢 Bytová jednotka</button>
    <button class="mode-btn ${mode==='batch-rd'?'active':''}" data-mode="batch-rd">📁 Hromadně RD</button>
    <button class="mode-btn ${mode==='batch-bj'?'active':''}" data-mode="batch-bj">🏢 Hromadně BJ</button>
  </div>`;

  // Model switcher
  html += `<div class="model-switcher">
    <button class="model-toggle" id="model-toggle"><div class="model-toggle-left"><div class="model-badge">AI</div><div><div class="model-toggle-label">Model</div><div class="model-toggle-value">${modelInfo.name}</div></div></div><span class="model-chevron ${modelOpen?'open':''}">▾</span></button>
    ${modelOpen ? `<div class="model-panel">${MODEL_OPTIONS.map(p => `
      <div class="model-provider-group"><div class="model-provider-header"><span>${p.icon}</span> ${p.provider}</div>
        <div class="model-provider-models">${p.models.map(m => `
          <button class="model-option ${m.value===selectedModel?'active':''}" data-model="${m.value}"><span class="model-name">${m.name}</span><span class="model-desc">${m.desc}</span></button>
        `).join('')}</div></div>`).join('')}</div>` : ''}
  </div>`;

  // Single mode upload
  if (mode === 'single') {
    // Drop zone
    html += `<div class="drop-zone ${files.length>0?'has-files':''}" id="drop-zone">
      <input type="file" multiple accept=".jpg,.jpeg,.png,.heic,.heif,.webp,.tiff,.bmp" class="file-input" id="file-input">
      <div class="drop-icon"><svg width="48" height="48" viewBox="0 0 48 48" fill="none"><path d="M24 32V16M24 16L18 22M24 16L30 22" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><path d="M8 32V36C8 38.2 9.8 40 12 40H36C38.2 40 40 38.2 40 36V32" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg></div>
      <p class="drop-text">Přetáhněte fotky nebo klikněte pro výběr</p>
      <p class="drop-hint">Min. 9 fotografií: 4× exteriér, 5× interiér (všechny místnosti)</p>
    </div>`;

    // File list
    if (files.length > 0) {
      html += `<div class="file-list"><div class="file-list-header"><span>📸 ${files.length} fotografií</span><button class="clear-btn" id="clear-files">Vymazat vše</button></div>
        <div class="file-grid">${files.map((f, i) => `<div class="file-item"><div class="file-thumb"><img src="${URL.createObjectURL(f)}" alt="${f.name}"></div><div class="file-info"><span class="file-name">${f.name}</span><span class="file-size">${U.formatSize(f.size)}</span></div><button class="file-remove" data-idx="${i}">✕</button></div>`).join('')}</div></div>`;
    }

    // PDF Section with data source toggle
    html += `<div class="pdf-section">
      <div class="section-label"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 1H8.5L11 3.5V13H3V1Z" stroke="currentColor" stroke-width="1.5"/><path d="M8 1V4H11" stroke="currentColor" stroke-width="1.5"/></svg> Údaje o nemovitosti</div>
      <div class="data-source-toggle"><button class="toggle-tab ${dataSource==='pdf'?'active':''}" data-source="pdf">📄 Z PDF formuláře</button><button class="toggle-tab ${dataSource==='manual'?'active':''}" data-source="manual">✏️ Ruční zadání</button></div>`;

    if (dataSource === 'pdf') {
      if (!pdfFile) {
        html += `<div class="pdf-dropzone" id="pdf-dropzone"><input type="file" accept=".pdf" class="file-input" id="pdf-input"><svg width="28" height="28" viewBox="0 0 28 28" fill="none"><path d="M14 4V18M8 12L14 18L20 12" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round"/></svg><span>Klikněte nebo přetáhněte PDF formulář</span></div>`;
      } else {
        html += `<div class="pdf-file-display"><div class="pdf-file-name"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M11.5 4L5.5 10L2.5 7" stroke="#10b981" stroke-width="2" stroke-linecap="round"/></svg> ${pdfFile.name} <button class="pdf-remove" id="pdf-remove">✕</button></div></div>`;
      }
      // Extracted data
      if (extractedData) {
        html += `<div class="extracted-data"><div class="extracted-title"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M11.5 4L5.5 10L2.5 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg> Extrahované údaje z PDF <span style="font-size:11px;color:var(--text-muted);margin-left:8px;font-weight:400">— můžete upravit</span></div>
          <div class="extracted-grid">${Object.entries(DATA_LABELS).map(([key, label]) => {
            const isYN = ['podsklepeni','podkrovi','podkrovi_obytne'].includes(key);
            const val = extractedData[key] || '';
            return `<div class="extracted-item"><span class="extracted-label">${label}</span>
              ${isYN ? `<select class="input-field extracted-input" data-key="${key}"><option value="">nenalezeno</option><option value="ANO" ${val==='ANO'?'selected':''}>ANO</option><option value="NE" ${val==='NE'?'selected':''}>NE</option></select>`
                : `<input type="text" class="input-field extracted-input" data-key="${key}" value="${val}" placeholder="nenalezeno">`}
            </div>`;
          }).join('')}</div></div>`;
      }
    } else {
      // Manual input form
      html += `<div class="manual-form"><div class="manual-grid">${Object.entries(DATA_LABELS).map(([key, label]) => {
        const isYN = ['podsklepeni','podkrovi','podkrovi_obytne'].includes(key);
        const isFull = ['typ_vytapeni','adresa'].includes(key);
        const val = manualData[key] || '';
        return `<div class="input-group ${isFull?'manual-full':''}"><label class="input-label">${label}</label>
          ${isYN ? `<select class="input-field manual-input" data-key="${key}"><option value="">Vyberte...</option><option value="ANO" ${val==='ANO'?'selected':''}>ANO</option><option value="NE" ${val==='NE'?'selected':''}>NE</option></select>`
            : `<input type="text" class="input-field manual-input" data-key="${key}" value="${val}" placeholder="...">`}
        </div>`;
      }).join('')}</div></div>`;
    }
    html += `</div>`; // end pdf-section

    // LV Section
    html += `<div class="pdf-section"><div class="section-label"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 3H12V12H2V3Z" stroke="currentColor" stroke-width="1.5"/><path d="M4 1V4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M10 1V4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg> List vlastnictví (PDF) — volitelné</div>`;
    if (!lvFile) {
      html += `<div class="pdf-dropzone" id="lv-dropzone"><input type="file" accept=".pdf" class="file-input" id="lv-input"><svg width="28" height="28" viewBox="0 0 28 28" fill="none"><path d="M14 4V18M8 12L14 18L20 12" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round"/></svg><span>Klikněte nebo přetáhněte PDF s LV</span></div>`;
    } else {
      html += `<div class="pdf-file-display"><div class="pdf-file-name"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M11.5 4L5.5 10L2.5 7" stroke="#10b981" stroke-width="2" stroke-linecap="round"/></svg> ${lvFile.name} <button class="pdf-remove" id="lv-remove">✕</button></div></div>`;
    }
    html += `</div>`;

    // Error + submit button
    if (error) html += `<div class="error">${error}</div>`;
    html += `<button class="btn btn-primary upload-btn" id="upload-btn" ${uploading||files.length===0?'disabled':''} style="width:100%;justify-content:center;padding:16px;font-size:16px">
      ${uploading ? '<span class="spinner"></span> Zpracovávám...' : `<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 4V16M4 10H16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg> Nahrát a zpracovat (${files.length} souborů)`}
    </button>`;
  }

  // BJ mode
  if (mode === 'bj') {
    html += `<div class="drop-zone ${bjFiles.length>0?'has-files':''}" id="bj-drop-zone">
      <input type="file" multiple accept=".jpg,.jpeg,.png,.heic,.heif,.webp,.tiff,.bmp" class="file-input" id="bj-file-input">
      <div class="drop-icon"><svg width="48" height="48" viewBox="0 0 48 48" fill="none"><path d="M24 32V16M24 16L18 22M24 16L30 22" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/><path d="M8 32V36C8 38.2 9.8 40 12 40H36C38.2 40 40 38.2 40 36V32" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg></div>
      <p class="drop-text">Přetáhněte fotky bytu nebo klikněte</p>
      <p class="drop-hint">Min. 4 fotky: exteriér domu, vstup, interiér místností</p>
    </div>`;
    if (bjFiles.length > 0) {
      html += `<div class="file-list"><div class="file-list-header"><span>📸 ${bjFiles.length} fotografií</span><button class="clear-btn" id="bj-clear-files">Vymazat vše</button></div>
        <div class="file-grid">${bjFiles.map((f, i) => `<div class="file-item"><div class="file-thumb"><img src="${URL.createObjectURL(f)}" alt="${f.name}"></div><div class="file-info"><span class="file-name">${f.name}</span><span class="file-size">${U.formatSize(f.size)}</span></div><button class="file-remove bj-file-remove" data-idx="${i}">✕</button></div>`).join('')}</div></div>`;
    }
    // BJ PDF
    html += `<div class="pdf-section"><div class="section-label"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M3 1H8.5L11 3.5V13H3V1Z" stroke="currentColor" stroke-width="1.5"/><path d="M8 1V4H11" stroke="currentColor" stroke-width="1.5"/></svg> PDF formulář ocenění bytu</div>`;
    if (!bjPdfFile) {
      html += `<div class="pdf-dropzone" id="bj-pdf-dropzone"><input type="file" accept=".pdf" class="file-input" id="bj-pdf-input"><svg width="28" height="28" viewBox="0 0 28 28" fill="none"><path d="M14 4V18M8 12L14 18L20 12" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round"/></svg><span>Klikněte nebo přetáhněte PDF „Zadané údaje pro on-line ocenění bytu"</span></div>`;
    } else {
      html += `<div class="pdf-file-display"><div class="pdf-file-name"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M11.5 4L5.5 10L2.5 7" stroke="#10b981" stroke-width="2" stroke-linecap="round"/></svg> ${bjPdfFile.name} <button class="pdf-remove" id="bj-pdf-remove">✕</button></div>${bjPdfParsing?'<span class="spinner"></span>':''}</div>`;
    }
    html += `</div>`;

    // BJ Extracted Data
    if (bjExtractedData) {
      html += `<div class="extracted-data"><div class="extracted-title"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M11.5 4L5.5 10L2.5 7" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg> Extrahované údaje z PDF – bytová jednotka</div>
        <div class="extracted-grid">${Object.entries(BJ_DATA_LABELS).map(([key, label]) => {
          const val = bjExtractedData[key] || '';
          return `<div class="extracted-item"><span class="extracted-label">${label}</span>
            <input type="text" class="input-field bj-extracted-input" data-key="${key}" value="${val}" placeholder="nenalezeno" style="font-size:13px;padding:6px 8px">
          </div>`;
        }).join('')}</div></div>`;
    }

    // Floor Area Documents
    html += `<div class="pdf-section" id="floor-doc-section"><div class="section-label"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><rect x="2" y="2" width="10" height="10" rx="1" stroke="currentColor" stroke-width="1.5"/><path d="M5 5H9M5 7H9M5 9H7" stroke="currentColor" stroke-width="1" stroke-linecap="round"/></svg> Dokumenty potvrzující podlahovou plochu</div>
      <input type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.tiff,.bmp,.doc,.docx" class="file-input" id="bj-floor-input">
      <div class="pdf-dropzone" id="bj-floor-dropzone"><svg width="28" height="28" viewBox="0 0 28 28" fill="none"><path d="M14 4V18M8 12L14 18L20 12" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round"/></svg><span>Klikněte nebo přetáhněte dokumenty (PDF/obrázek)</span></div>`;
    if (bjFloorAreaDocs.length > 0) {
      html += `<div style="margin-top:8px"><div style="font-size:12px;font-weight:600;color:var(--accent-green);margin-bottom:4px">📎 ${bjFloorAreaDocs.length} ${bjFloorAreaDocs.length === 1 ? 'dokument nahrán' : 'dokumenty nahrány'}</div>`;
      bjFloorAreaDocs.forEach((doc, i) => {
        html += `<div class="pdf-file-display" style="margin-bottom:4px"><div class="pdf-file-name"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M11.5 4L5.5 10L2.5 7" stroke="#10b981" stroke-width="2" stroke-linecap="round"/></svg> ${doc.name} <span style="color:var(--text-muted);font-size:11px;margin-left:4px">(${U.formatSize(doc.size)})</span><button class="pdf-remove bj-floor-remove" data-idx="${i}">✕</button></div></div>`;
      });
      html += `</div>`;
    }
    html += `<div style="font-size:11px;color:var(--text-muted);margin-top:6px;padding:0 4px;line-height:1.5">Akceptovatelné podklady: nabývací titul (kupní smlouva), prohlášení vlastníka, vyúčtování služeb, evidenční list SVJ/BD, odhad nemovitosti</div></div>`;

    // BJ LV Upload
    html += `<div class="pdf-section"><div class="section-label"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M2 3H12V12H2V3Z" stroke="currentColor" stroke-width="1.5"/><path d="M4 1V4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="M10 1V4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg> List vlastnictví (PDF) — volitelné</div>`;
    if (!bjLvFile) {
      html += `<div class="pdf-dropzone" id="bj-lv-dropzone"><input type="file" accept=".pdf" class="file-input" id="bj-lv-input"><svg width="28" height="28" viewBox="0 0 28 28" fill="none"><path d="M14 4V18M8 12L14 18L20 12" stroke="var(--text-muted)" stroke-width="2" stroke-linecap="round"/></svg><span>Klikněte nebo přetáhněte PDF s Listem vlastnictví</span></div>`;
    } else {
      html += `<div class="pdf-file-display"><div class="pdf-file-name"><svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M11.5 4L5.5 10L2.5 7" stroke="#10b981" stroke-width="2" stroke-linecap="round"/></svg> ${bjLvFile.name} <button class="pdf-remove" id="bj-lv-remove">✕</button></div></div>`;
    }
    html += `</div>`;

    if (error) html += `<div class="error">${error}</div>`;
    html += `<button class="btn btn-primary upload-btn" id="bj-upload-btn" ${uploading||bjFiles.length===0?'disabled':''} style="width:100%;justify-content:center;padding:16px;font-size:16px">
      ${uploading ? '<span class="spinner"></span> Zpracovávám...' : `<svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M10 4V16M4 10H16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg> Nahrát BJ (${bjFiles.length} souborů)`}
    </button>`;
  }

  // Batch RD mode
  if (mode === 'batch-rd') {
    if (uploading) {
      html += `<div class="batch-upload-zone"><div class="folder-drop-zone" style="pointer-events:none;opacity:0.7">
        <div class="folder-drop-icon"><span class="spinner" style="width:40px;height:40px;border-width:3px"></span></div>
        <p class="drop-text">Nahrávám soubory na server...</p>
        <p class="drop-hint">Prosím čekejte, zpracovávají se složky</p>
      </div></div>`;
    } else {
      html += `<div class="batch-upload-zone">
        <div class="folder-drop-zone" id="batch-drop-zone">
          <input type="file" webkitdirectory directory multiple class="file-input" id="batch-input">
          <div class="folder-drop-icon">📁</div>
          <p class="drop-text">Vyberte složku s podklady (Rodinné domy)</p>
          <p class="drop-hint">Složka s podsložkami (1, 2, 3...) — každá obsahuje fotky + PDF</p>
        </div>
      </div>`;
    }
    if (error) html += `<div class="error">${error}</div>`;
  }

  // Batch BJ mode
  if (mode === 'batch-bj') {
    if (uploading) {
      html += `<div class="batch-upload-zone"><div class="folder-drop-zone" style="pointer-events:none;opacity:0.7">
        <div class="folder-drop-icon"><span class="spinner" style="width:40px;height:40px;border-width:3px"></span></div>
        <p class="drop-text">Nahrávám soubory na server...</p>
        <p class="drop-hint">Prosím čekejte, zpracovávají se složky BJ</p>
      </div></div>`;
    } else {
      html += `<div class="batch-upload-zone">
        <div class="folder-drop-zone" id="batch-bj-drop-zone">
          <input type="file" webkitdirectory directory multiple class="file-input" id="batch-bj-input">
          <div class="folder-drop-icon">🏢</div>
          <p class="drop-text">Vyberte složku s podklady (Bytové jednotky)</p>
          <p class="drop-hint">Složka s podsložkami — každá obsahuje fotky bytu + PDF formulář BJ</p>
        </div>
      </div>`;
    }
    if (error) html += `<div class="error">${error}</div>`;
  }

  html += `</div></section>`;
  container.innerHTML = html;
  _bindUploadEvents(container, state);
}

function _bindUploadEvents(container, state) {
  // Mode buttons
  container.querySelectorAll('.mode-btn').forEach(b => b.onclick = () => state.onModeChange(b.dataset.mode));

  // Model toggle
  const mt = container.querySelector('#model-toggle');
  if (mt) mt.onclick = () => { state.modelOpen = !state.modelOpen; renderUpload(container, state); };
  container.querySelectorAll('.model-option').forEach(b => b.onclick = () => { state.onModelChange(b.dataset.model); state.modelOpen = false; renderUpload(container, state); });

  // Data source toggle
  container.querySelectorAll('.toggle-tab').forEach(b => b.onclick = () => { state.dataSource = b.dataset.source; renderUpload(container, state); });

  // File drop zone (single)
  const dz = container.querySelector('#drop-zone');
  const fi = container.querySelector('#file-input');
  if (dz && fi) {
    dz.onclick = () => fi.click();
    dz.ondragover = (e) => { e.preventDefault(); dz.classList.add('drop-zone-active'); };
    dz.ondragleave = () => dz.classList.remove('drop-zone-active');
    dz.ondrop = (e) => { e.preventDefault(); dz.classList.remove('drop-zone-active'); state.onFilesChange([...state.files, ...e.dataTransfer.files]); };
    fi.onchange = () => { if (fi.files.length) state.onFilesChange([...state.files, ...fi.files]); };
  }
  const clearBtn = container.querySelector('#clear-files');
  if (clearBtn) clearBtn.onclick = () => state.onFilesChange([]);
  container.querySelectorAll('.file-remove:not(.bj-file-remove)').forEach(b => b.onclick = (e) => {
    e.stopPropagation();
    const idx = parseInt(b.dataset.idx);
    state.onFilesChange(state.files.filter((_, i) => i !== idx));
  });

  // PDF input
  const pdfDz = container.querySelector('#pdf-dropzone');
  const pdfIn = container.querySelector('#pdf-input');
  if (pdfDz && pdfIn) {
    pdfDz.onclick = () => pdfIn.click();
    pdfIn.onchange = async () => {
      const file = pdfIn.files[0];
      if (!file) return;
      state.pdfFile = file;
      try {
        const data = await Api.parsePdf(file);
        if (data) state.extractedData = data;
        else state.onError('PDF zpracováno, ale nepodařilo se extrahovat údaje.');
      } catch (e) { state.onError('Chyba při parsování PDF: ' + (e.message || 'neznámá chyba')); }
      renderUpload(container, state);
    };
  }
  const pdfRm = container.querySelector('#pdf-remove');
  if (pdfRm) pdfRm.onclick = () => { state.pdfFile = null; state.extractedData = null; renderUpload(container, state); };

  // Extracted data editing
  container.querySelectorAll('.extracted-input').forEach(inp => {
    inp.onchange = () => { if (state.extractedData) state.extractedData[inp.dataset.key] = inp.value; };
    inp.oninput = () => { if (state.extractedData) state.extractedData[inp.dataset.key] = inp.value; };
  });
  container.querySelectorAll('.manual-input').forEach(inp => {
    inp.onchange = () => { state.manualData[inp.dataset.key] = inp.value; };
    inp.oninput = () => { state.manualData[inp.dataset.key] = inp.value; };
  });

  // LV input
  const lvDz = container.querySelector('#lv-dropzone');
  const lvIn = container.querySelector('#lv-input');
  if (lvDz && lvIn) {
    lvDz.onclick = () => lvIn.click();
    lvIn.onchange = async () => {
      const file = lvIn.files[0];
      if (!file) return;
      state.lvFile = file;
      try {
        const data = await Api.parseLv(file);
        state.lvData = data;
      } catch (e) { state.onError('Chyba LV: ' + e.message); }
      renderUpload(container, state);
    };
  }
  const lvRm = container.querySelector('#lv-remove');
  if (lvRm) lvRm.onclick = () => { state.lvFile = null; state.lvData = null; renderUpload(container, state); };

  // Upload button
  const uploadBtn = container.querySelector('#upload-btn');
  if (uploadBtn) uploadBtn.onclick = () => state.onUpload();

  // BJ events
  const bjDz = container.querySelector('#bj-drop-zone');
  const bjFi = container.querySelector('#bj-file-input');
  if (bjDz && bjFi) {
    bjDz.onclick = () => bjFi.click();
    bjDz.ondragover = (e) => { e.preventDefault(); bjDz.classList.add('drop-zone-active'); };
    bjDz.ondragleave = () => bjDz.classList.remove('drop-zone-active');
    bjDz.ondrop = (e) => {
      e.preventDefault();
      bjDz.classList.remove('drop-zone-active');
      if (e.dataTransfer.files.length) {
        if (state.onBjFilesChange) state.onBjFilesChange([...state.bjFiles, ...e.dataTransfer.files]);
        else { state.bjFiles = [...state.bjFiles, ...e.dataTransfer.files]; renderUpload(container, state); }
      }
    };
    bjFi.onchange = () => {
      if (bjFi.files.length) {
        if (state.onBjFilesChange) state.onBjFilesChange([...state.bjFiles, ...bjFi.files]);
        else { state.bjFiles = [...state.bjFiles, ...bjFi.files]; renderUpload(container, state); }
      }
    };
  }
  const bjClear = container.querySelector('#bj-clear-files');
  if (bjClear) bjClear.onclick = () => {
    if (state.onBjFilesChange) state.onBjFilesChange([]);
    else { state.bjFiles = []; renderUpload(container, state); }
  };
  container.querySelectorAll('.bj-file-remove').forEach(b => b.onclick = (e) => {
    e.stopPropagation();
    const newFiles = state.bjFiles.filter((_, i) => i !== parseInt(b.dataset.idx));
    if (state.onBjFilesChange) state.onBjFilesChange(newFiles);
    else { state.bjFiles = newFiles; renderUpload(container, state); }
  });

  // BJ PDF
  const bjPdfDz = container.querySelector('#bj-pdf-dropzone');
  const bjPdfIn = container.querySelector('#bj-pdf-input');
  if (bjPdfDz && bjPdfIn) {
    bjPdfDz.onclick = () => bjPdfIn.click();
    bjPdfIn.onchange = async () => {
      const file = bjPdfIn.files[0];
      if (!file) return;
      state.bjPdfFile = file;
      state.bjPdfParsing = true;
      renderUpload(container, state);
      try {
        const data = await Api.parseBjPdf(file);
        if (data) state.bjExtractedData = data;
        else state.onError('PDF zpracováno, ale nepodařilo se extrahovat údaje.');
      } catch (e) { state.onError('BJ PDF: ' + (e.message || 'chyba')); }
      state.bjPdfParsing = false;
      renderUpload(container, state);
    };
  }
  const bjPdfRm = container.querySelector('#bj-pdf-remove');
  if (bjPdfRm) bjPdfRm.onclick = () => { state.bjPdfFile = null; state.bjExtractedData = null; renderUpload(container, state); };

  // BJ extracted data editing
  container.querySelectorAll('.bj-extracted-input').forEach(inp => {
    inp.onchange = () => { if (state.bjExtractedData) state.bjExtractedData[inp.dataset.key] = inp.value || null; };
    inp.oninput = () => { if (state.bjExtractedData) state.bjExtractedData[inp.dataset.key] = inp.value || null; };
  });

  // BJ Floor Area Docs
  const floorDz = container.querySelector('#bj-floor-dropzone');
  const floorIn = container.querySelector('#bj-floor-input');
  if (floorDz && floorIn) {
    floorDz.onclick = (e) => { e.stopPropagation(); e.preventDefault(); floorIn.click(); };
    floorDz.ondragover = (e) => { e.preventDefault(); e.stopPropagation(); };
    floorDz.ondrop = (e) => {
      e.preventDefault(); e.stopPropagation();
      if (e.dataTransfer.files.length) {
        state.bjFloorAreaDocs = [...state.bjFloorAreaDocs, ...Array.from(e.dataTransfer.files)];
        renderUpload(container, state);
      }
    };
    floorIn.onchange = () => {
      if (floorIn.files.length) {
        state.bjFloorAreaDocs = [...state.bjFloorAreaDocs, ...Array.from(floorIn.files)];
        floorIn.value = '';
        renderUpload(container, state);
      }
    };
  }
  container.querySelectorAll('.bj-floor-remove').forEach(b => b.onclick = (e) => {
    e.stopPropagation(); e.preventDefault();
    state.bjFloorAreaDocs = state.bjFloorAreaDocs.filter((_, i) => i !== parseInt(b.dataset.idx));
    renderUpload(container, state);
  });

  // BJ LV
  const bjLvDz = container.querySelector('#bj-lv-dropzone');
  const bjLvIn = container.querySelector('#bj-lv-input');
  if (bjLvDz && bjLvIn) {
    bjLvDz.onclick = () => bjLvIn.click();
    bjLvIn.onchange = () => {
      const file = bjLvIn.files[0];
      if (file) { state.bjLvFile = file; renderUpload(container, state); }
    };
  }
  const bjLvRm = container.querySelector('#bj-lv-remove');
  if (bjLvRm) bjLvRm.onclick = () => { state.bjLvFile = null; renderUpload(container, state); };

  const bjUploadBtn = container.querySelector('#bj-upload-btn');
  if (bjUploadBtn) bjUploadBtn.onclick = () => state.onUpload();

  // Batch RD
  const batchDz = container.querySelector('#batch-drop-zone');
  const batchIn = container.querySelector('#batch-input');
  if (batchDz && batchIn) {
    batchDz.onclick = () => batchIn.click();
    batchIn.onchange = () => { if (batchIn.files.length) state.onBatchUpload(batchIn.files); };
  }

  // Batch BJ
  const batchBjDz = container.querySelector('#batch-bj-drop-zone');
  const batchBjIn = container.querySelector('#batch-bj-input');
  if (batchBjDz && batchBjIn) {
    batchBjDz.onclick = () => batchBjIn.click();
    batchBjIn.onchange = () => { if (batchBjIn.files.length && state.onBatchBjUpload) state.onBatchBjUpload(batchBjIn.files); };
  }
}
