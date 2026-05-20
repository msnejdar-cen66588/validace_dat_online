/* ResultsDashboard – displays pipeline results with semaphore verdict */
const AGENT_META = {
  Strazce:{icon:'🛡️',label:'Fotodokumentace',color:'#3b82f6'},
  ForenzniAnalytik:{icon:'🔬',label:'Autenticita fotek',color:'#8b5cf6'},
  Historik:{icon:'📜',label:'Věk nemovitosti',color:'#06b6d4'},
  Inspektor:{icon:'🔍',label:'Technický stav',color:'#f59e0b'},
  GeoValidator:{icon:'📍',label:'Ověření lokace',color:'#ec4899'},
  GDPRValidator:{icon:'👤',label:'GDPR kontrola',color:'#dc2626'},
  PorovnavacDokumentu:{icon:'📄',label:'PDF vs Fotky',color:'#f97316'},
  KatastralniAnalytik:{icon:'🏛️',label:'Katastr & LV',color:'#7c3aed'},
  Strateg:{icon:'🎯',label:'Závěrečné hodnocení',color:'#10b981'},
  StrazceBJ:{icon:'🛡️',label:'Fotodokumentace bytu',color:'#3b82f6'},
  InspektorBJ:{icon:'🔍',label:'Technický stav bytu',color:'#f59e0b'},
  PorovnavacDokumentuBJ:{icon:'📄',label:'PDF vs Fotky (BJ)',color:'#f97316'},
  StrategBJ:{icon:'🎯',label:'Závěrečné hodnocení',color:'#10b981'},
};

function renderResultsDashboard(container, state) {
  const { result, onReset, onEdit, isBatchMode, onBackToBatch } = state;
  const sem = result.semaphore || 'UNKNOWN';
  const semColor = result.semaphore_color || 'gray';
  const agents = result.agents || {};
  const isBJ = result.pipeline_type === 'bj' || !!agents['StrategBJ'];
  const strategist = agents[isBJ ? 'StrategBJ' : 'Strateg'];
  const humanReport = strategist?.result?.details?.human_report || strategist?.result?.summary || '';

  const semLabel = semColor === 'green' ? 'Proces může pokračovat online'
    : semColor === 'orange' ? 'Vyžaduje dohled pracovníka' : 'Vrátit klientovi k doplnění';
  const semIcon = semColor === 'green' ? '✅' : semColor === 'orange' ? '⚠️' : '🔴';

  const agentList = isBJ
    ? ['StrazceBJ','InspektorBJ','ForenzniAnalytik','Historik','GeoValidator','GDPRValidator','PorovnavacDokumentuBJ','KatastralniAnalytik']
    : ['Strazce','Inspektor','ForenzniAnalytik','Historik','GeoValidator','GDPRValidator','PorovnavacDokumentu','KatastralniAnalytik'];

  const getStatusBadge = (status) => {
    if (status === 'success') return { text: 'Bez nálezu', cls: 'badge-success' };
    if (status === 'warn') return { text: 'Varování', cls: 'badge-warn' };
    if (status === 'fail') return { text: 'Problém', cls: 'badge-fail' };
    return { text: '–', cls: '' };
  };

  let html = `<section class="res-section"><div class="res-container">`;

  // Verdict header
  html += `<div class="res-verdict res-verdict-${semColor}">
    <div class="res-verdict-left"><span class="res-verdict-icon">${semIcon}</span><div><h2 class="res-verdict-title">${sem}</h2><p class="res-verdict-sub">${semLabel}</p></div></div>
  </div>`;

  // Meta strip + PDF download
  const pdfUrl = isBJ
    ? `${API_BASE}/api/bj/pipeline/report/${result.session_id}`
    : `${API_BASE}/api/pipeline/report/${result.session_id}`;

  html += `<div class="res-meta">
    <span>Doba analýzy: ${result.total_time?.toFixed(1)}s</span><span>•</span><span>Pipeline: ${result.pipeline_id}</span>
    <a href="${pdfUrl}" class="btn-pdf-download" target="_blank" title="Stáhnout PDF protokol">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
      Stáhnout PDF
    </a>
  </div>`;

  // Human report from Stratég
  if (humanReport) {
    html += `<div class="res-card"><div class="res-card-header"><h3>🎯 Závěrečná zpráva Stratéga</h3></div>
      <div class="res-card-body"><div class="res-report">${humanReport.replace(/\n/g, '<br>')}</div></div></div>`;
  }

  // Agent cards
  agentList.forEach(name => {
    const agent = agents[name];
    if (!agent) return;
    const meta = AGENT_META[name] || { icon: '🤖', label: name, color: '#666' };
    const status = agent.result?.status || 'idle';
    const badge = getStatusBadge(status);
    const summary = agent.result?.summary || '';
    const errors = agent.result?.errors || [];
    const warnings = agent.result?.warnings || [];
    const details = agent.result?.details || {};

    let extraHtml = '';

    // 1. Tagged photos (Strazce)
    if ((name === 'Strazce' || name === 'StrazceBJ') && details.classifications && details.classifications.length > 0) {
      // Build defect map from Inspektor/InspektorBJ photo_defects
      const inspektorKey = name === 'StrazceBJ' ? 'InspektorBJ' : 'Inspektor';
      const inspektorDefects = (agents[inspektorKey]?.result?.details?.photo_defects || []);
      const defectMap = {};
      inspektorDefects.forEach(pd => { defectMap[pd.photo_id] = pd.defects || []; });

      const DEFECT_LABELS = {
        PRASKLINA: '⚠️ Prasklina', VLHKOST: '💧 Vlhkost', PLISEN: '🦠 Plíseň',
        REKONSTRUKCE: '🔨 Rekonstrukce', POSKOZENA_OMITKA: '🧱 Poš. omítka',
        PORUSENA_STRECHA: '🏚️ Poš. střecha', VYBYDLENOST: '⛔ Vybydlenost',
      };

      extraHtml += `<div class="res-photos" style="display:flex;gap:10px;overflow-x:auto;padding:10px 0;margin-top:10px;">`;
      details.classifications.forEach((cls, idx) => {
        const photoId = cls.photo_id || cls.filename;
        const url = `/uploads/${result.session_id}/${photoId}.jpg`;
        const cats = (cls.categories || []);
        const defects = defectMap[photoId] || [];
        const hasDefect = defects.length > 0;
        const borderColor = hasDefect ? '#ef4444' : '#e2e8f0';
        const catLabel = cats.map(c => c.replace(/^(EXTERIER_|INTERIER_)/, '')).join(', ') || 'Neznámé';
        const firstCat = cats.length > 0 ? cats[0].replace(/^(EXTERIER_|INTERIER_)/, '') : 'Neznámé';
        const moreCount = cats.length > 1 ? cats.length - 1 : 0;
        const modalId = `photo-modal-${name}-${idx}`;
        const allTagsHtml = [
          ...cats.map(c => `<span style="display:inline-block;background:#eff6ff;color:#1d4ed8;border:1px solid #bfdbfe;border-radius:4px;font-size:11px;padding:2px 7px;margin:2px;">${c.replace(/^(EXTERIER_|INTERIER_)/, '')}</span>`),
          ...defects.map(d => `<span style="display:inline-block;background:#fef2f2;color:#dc2626;border:1px solid #fca5a5;border-radius:4px;font-size:11px;padding:2px 7px;margin:2px;">${DEFECT_LABELS[d] || d}</span>`)
        ].join('');
        extraHtml += `
        <div style="flex-shrink:0;width:130px;border-radius:8px;overflow:hidden;border:2px solid ${borderColor};background:#fff;cursor:pointer;" onclick="document.getElementById('${modalId}').style.display='flex'">
          <img src="${url}" style="width:100%;height:90px;object-fit:cover;" onerror="this.style.display='none'">
          <div style="font-size:11px;padding:5px 4px;color:#1e293b;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${firstCat}${moreCount > 0 ? ` <span style="color:#6366f1;">+${moreCount}</span>` : ''}</div>
          ${hasDefect ? `<div style="padding:0 4px 4px;"><span style="font-size:10px;color:#dc2626;">⚠️ ${defects.length} vada${defects.length > 1 ? 'y' : ''}</span></div>` : ''}
        </div>
        <div id="${modalId}" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.7);z-index:9999;align-items:center;justify-content:center;" onclick="this.style.display='none'">
          <div style="background:#fff;border-radius:12px;max-width:600px;width:90%;padding:20px;position:relative;" onclick="event.stopPropagation()">
            <button onclick="document.getElementById('${modalId}').style.display='none'" style="position:absolute;top:12px;right:12px;background:#f1f5f9;border:none;border-radius:6px;padding:4px 10px;cursor:pointer;font-size:14px;">✕</button>
            <img src="${url}" style="width:100%;max-height:350px;object-fit:contain;border-radius:8px;margin-bottom:12px;" onerror="this.style.display='none'">
            <div style="font-size:12px;color:#64748b;margin-bottom:6px;">${cls.description || ''}</div>
            <div style="display:flex;flex-wrap:wrap;gap:4px;">${allTagsHtml}</div>
          </div>
        </div>`;
      });
      extraHtml += `</div>`;
    }

    // 2. DocComparator Table & Floor Area
    if (name === 'PorovnavacDokumentu' || name === 'PorovnavacDokumentuBJ') {
       // Prepare floor area data for inline expansion
       const far = (details.floor_area_results || []).find(f => f.is_acceptable && f.extracted_floor_area_m2 != null) || (details.floor_area_results || [])[0] || null;
       const floorAreaFields = ['plocha bytu', 'podlahová plocha', 'plocha jednotky', 'dokument podlahové plochy', 'započitatelná plocha'];

       if (details.checks && details.checks.length > 0) {
         extraHtml += `<div style="overflow-x:auto;margin-top:10px;"><table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #e2e8f0;">
           <tr style="background:#f8fafc;border-bottom:2px solid #e2e8f0;"><th style="padding:10px;text-align:left;color:#475569;">Položka</th><th style="padding:10px;text-align:left;color:#475569;">Od klienta</th><th style="padding:10px;text-align:left;color:#475569;">Zjištěno AI</th><th style="padding:10px;text-align:center;color:#475569;">Stav</th></tr>`;
         details.checks.forEach((c, ci) => {
           const isMatch = c.match === 'YES' || c.match === true;
           const color = isMatch ? '#166534' : '#991b1b';
           const bg = isMatch ? '#f0fdf4' : '#fef2f2';
           const icon = isMatch ? '✓' : '✗';
           const fieldLower = (c.field || '').toLowerCase();
           const isFloorAreaRow = floorAreaFields.some(f => fieldLower.includes(f));
           const hasExpandable = isFloorAreaRow && far && far.extracted_floor_area_m2 != null;
           const rowId = `doc-check-row-${ci}`;

           // Determine what to show in "Zjištěno AI" for floor area rows
           let aiValue = c.observed || c.observed_value || '–';
           if (hasExpandable && (fieldLower.includes('plocha bytu') || fieldLower.includes('podlahová plocha') || fieldLower.includes('plocha jednotky'))) {
             // Override visual estimate with document-based value
             const docArea = far.zapocitatalna_plocha_m2 || far.extracted_floor_area_m2;
             aiValue = `${docArea} m² (z dokumentu: ${far.document_type || 'příloha'})`;
           }

           extraHtml += `<tr style="border-bottom:1px solid #e2e8f0;background:${bg};${hasExpandable ? 'cursor:pointer;' : ''}" ${hasExpandable ? `onclick="document.getElementById('${rowId}').style.display = document.getElementById('${rowId}').style.display === 'none' ? 'table-row' : 'none'"` : ''}>
             <td style="padding:10px;font-weight:600;color:#1e293b;">${c.field}${hasExpandable ? ' <span style="font-size:10px;color:#6366f1;margin-left:4px;">▼ detail</span>' : ''}</td>
             <td style="padding:10px;color:#334155;">${c.declared || c.form_value || '–'}</td>
             <td style="padding:10px;color:#334155;">${aiValue}</td>
             <td style="padding:10px;text-align:center;color:${color};font-weight:bold;font-size:14px;">${icon}</td>
           </tr>`;

           // Expandable detail row for floor area
           if (hasExpandable) {
             const comp = far.area_components || {};
             const rooms = far.room_breakdown || [];
             let detailHtml = `<div style="padding:14px;background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;margin:4px 0;">`;
             detailHtml += `<h4 style="margin:0 0 10px 0;font-size:13px;color:#166534;font-weight:700;">📐 Výpočet podlahové plochy z dokumentu</h4>`;
             detailHtml += `<div style="font-size:12px;color:#15803d;line-height:1.8;">`;
             detailHtml += `<b>Typ dokumentu:</b> ${far.document_type || 'Neznámý'}<br>`;
             detailHtml += `<b>Celková plocha dle dokumentu:</b> ${far.extracted_floor_area_m2} m²<br>`;

             // Room-by-room breakdown table
             if (rooms.length > 0) {
               detailHtml += `<div style="margin:8px 0;padding:10px;background:#fff;border:1px solid #d1fae5;border-radius:6px;">`;
               detailHtml += `<b style="color:#065f46;">Rozpis místností z dokumentu:</b>`;
               detailHtml += `<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:6px;">`;
               rooms.forEach(r => {
                 detailHtml += `<tr style="border-bottom:1px solid #e5e7eb;"><td style="padding:4px 8px;color:#1e293b;">${r.name}</td><td style="padding:4px 8px;text-align:right;font-weight:600;color:#1e293b;">${r.area_m2} m²</td></tr>`;
               });
               // Sum row
               const roomSum = far.room_sum_m2 || rooms.reduce((sum, r) => sum + (r.area_m2 || 0), 0);
               detailHtml += `<tr style="border-top:2px solid #065f46;"><td style="padding:6px 8px;font-weight:700;color:#065f46;">Součet místností</td><td style="padding:6px 8px;text-align:right;font-weight:700;color:#065f46;">${typeof roomSum === 'number' ? roomSum.toFixed(2) : roomSum} m²</td></tr>`;
               detailHtml += `</table></div>`;
             }

             // Verification result
             if (far.verification_result) {
               const isOk = far.verification_result.toUpperCase().startsWith('OK') || far.verification_result.toUpperCase().startsWith('SHODA') || far.verification_result.toUpperCase().includes('ODPOVÍDÁ');
               const vrColor = isOk ? '#166534' : '#991b1b';
               const vrBg = isOk ? '#f0fdf4' : '#fef2f2';
               const vrBorder = isOk ? '#bbf7d0' : '#fecaca';
               const vrIcon = isOk ? '✅' : '⚠️';
               detailHtml += `<div style="margin:8px 0;padding:10px;background:${vrBg};border:1px solid ${vrBorder};border-radius:6px;font-size:12px;color:${vrColor};font-weight:600;">
                 ${vrIcon} Ověření výpočtu: ${far.verification_result}
               </div>`;
             }

             // Area components breakdown (vedlejší plochy)
             if (comp.balkon_m2 || comp.terasa_m2 || comp.sklep_m2) {
               detailHtml += `<div style="margin:8px 0;padding:10px;background:#fff;border:1px solid #d1fae5;border-radius:6px;">`;
               detailHtml += `<b style="color:#065f46;">Vedlejší plochy (koeficient 0.5):</b><br>`;
               if (comp.balkon_m2) detailHtml += `&nbsp;&nbsp;🌿 Balkón/lodžie: <b>${comp.balkon_m2} m²</b> × 0.5 = ${(comp.balkon_m2 * 0.5).toFixed(2)} m²<br>`;
               if (comp.terasa_m2) detailHtml += `&nbsp;&nbsp;☀️ Terasa: <b>${comp.terasa_m2} m²</b> × 0.5 = ${(comp.terasa_m2 * 0.5).toFixed(2)} m²<br>`;
               if (comp.sklep_m2) detailHtml += `&nbsp;&nbsp;📦 Sklep/komora: <b>${comp.sklep_m2} m²</b> × 0.5 = ${(comp.sklep_m2 * 0.5).toFixed(2)} m²<br>`;
               if (comp.garaz_m2) detailHtml += `&nbsp;&nbsp;🚗 Garáž: <b>${comp.garaz_m2} m²</b> × 0.0 (nezapočítává se)<br>`;
               if (comp.zahrada_m2) detailHtml += `&nbsp;&nbsp;🌳 Zahrada: <b>${comp.zahrada_m2} m²</b> × 0.0 (nezapočítává se)<br>`;
               detailHtml += `</div>`;
             }

             // Calculation formula
             if (far.zapocitatalna_vypocet) {
               detailHtml += `<div style="margin:8px 0;padding:10px;background:#ecfdf5;border:1px solid #a7f3d0;border-radius:6px;font-family:monospace;font-size:12px;color:#065f46;white-space:pre-wrap;word-break:break-word;">`;
               detailHtml += `<b>Postup výpočtu:</b>\n${far.zapocitatalna_vypocet}`;
               detailHtml += `</div>`;
             }

             // Final result
             if (far.zapocitatalna_plocha_m2 != null) {
               detailHtml += `<div style="margin:8px 0;padding:12px;background:#065f46;color:#fff;border-radius:8px;font-size:14px;font-weight:700;text-align:center;">`;
               detailHtml += `Započitatelná plocha: ${far.zapocitatalna_plocha_m2} m²`;
               detailHtml += `</div>`;
             }

             // Confidence + notes
             if (far.confidence != null) detailHtml += `<b>Spolehlivost:</b> ${Math.round(far.confidence * 100)}%<br>`;
             if (far.notes) detailHtml += `<b>Poznámky:</b> ${far.notes}<br>`;

             detailHtml += `</div></div>`;

             extraHtml += `<tr id="${rowId}" style="display:none;"><td colspan="4" style="padding:0 10px 10px 10px;">${detailHtml}</td></tr>`;
           }

           // Note row (for non-floor-area checks with useful notes)
           if (c.note && !isFloorAreaRow) {
             extraHtml += `<tr style="display:none;" class="check-note-${ci}"><td colspan="4" style="padding:6px 10px 10px 10px;font-size:12px;color:#64748b;background:#f8fafc;">💡 ${c.note}</td></tr>`;
           }
         });
         extraHtml += `</table></div>`;
       }
    }

    // 3. GeoValidator – panorama vs front photo visual comparison
    if (name === 'GeoValidator') {
       const vc = details.visual_comparison;
       const panoUrl = details.panorama_url || (vc && vc.panorama_url) || null;
       const frontId = details.front_photo_id;
       const frontUrl = frontId ? `/uploads/${result.session_id}/${frontId}.jpg` : null;

       if (vc || panoUrl) {
         const conf = vc ? Math.round((vc.confidence || 0) * 100) : null;
         const verdict = vc ? vc.match_verdict : null;
         const verdictLabel = verdict === 'shoda' ? '✅ Shoda' : verdict === 'možná_shoda' ? '⚠️ Možná shoda' : verdict === 'neshoda' ? '❌ Neshoda' : '–';
         const verdictColor = verdict === 'shoda' ? '#166534' : verdict === 'možná_shoda' ? '#92400e' : '#991b1b';

         extraHtml += `<div style="margin:10px 0;padding:14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;">
           <h4 style="margin:0 0 10px 0;font-size:14px;color:#334155;display:flex;align-items:center;gap:6px;">
             📷 Porovnání fotky domu s panoramou (Mapy.cz)
           </h4>`;

         // Side-by-side images
         if (frontUrl || panoUrl) {
           extraHtml += `<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px;">`;
           if (frontUrl) {
             extraHtml += `<div>
               <div style="font-size:11px;font-weight:700;color:#475569;margin-bottom:4px;text-transform:uppercase;">Nahrané foto klientem</div>
               <img src="${frontUrl}" style="width:100%;border-radius:8px;border:1px solid #e2e8f0;aspect-ratio:16/10;object-fit:cover;" onerror="this.parentElement.innerHTML='<div style=\\'padding:20px;color:#94a3b8;font-size:12px;text-align:center;\\'>Foto není k dispozici</div>'">
             </div>`;
           }
           if (panoUrl) {
             extraHtml += `<div>
               <div style="font-size:11px;font-weight:700;color:#475569;margin-bottom:4px;text-transform:uppercase;">Panorama z Mapy.cz</div>
               <img src="${panoUrl}" style="width:100%;border-radius:8px;border:1px solid #e2e8f0;aspect-ratio:16/10;object-fit:cover;" onerror="this.parentElement.innerHTML='<div style=\\'padding:20px;color:#94a3b8;font-size:12px;text-align:center;\\'>Panorama není k dispozici</div>'">
             </div>`;
           }
           extraHtml += `</div>`;
         }

         // Verdict + comparison text
         if (vc) {
           extraHtml += `<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
             <span style="font-size:15px;font-weight:700;color:${verdictColor};">${verdictLabel}</span>
             ${conf !== null ? `<span style="font-size:12px;color:#64748b;background:#e2e8f0;padding:2px 8px;border-radius:99px;">Jistota: ${conf}%</span>` : ''}
           </div>`;

           if (vc.comparison_text) {
             extraHtml += `<p style="font-size:13px;color:#334155;margin:6px 0;line-height:1.5;">${vc.comparison_text}</p>`;
           }

           // Matching / differing features
           const matching = vc.matching_features || [];
           const differing = vc.differing_features || [];
           if (matching.length > 0 || differing.length > 0) {
             extraHtml += `<div style="display:flex;gap:16px;margin-top:8px;flex-wrap:wrap;">`;
             if (matching.length > 0) {
               extraHtml += `<div style="flex:1;min-width:140px;">
                 <div style="font-size:11px;font-weight:700;color:#166534;margin-bottom:4px;">Shodné znaky</div>
                 ${matching.map(f => `<span style="display:inline-block;font-size:11px;background:#dcfce7;color:#166534;padding:2px 8px;border-radius:99px;margin:2px 4px 2px 0;">${f}</span>`).join('')}
               </div>`;
             }
             if (differing.length > 0) {
               extraHtml += `<div style="flex:1;min-width:140px;">
                 <div style="font-size:11px;font-weight:700;color:#92400e;margin-bottom:4px;">Rozdíly</div>
                 ${differing.map(f => `<span style="display:inline-block;font-size:11px;background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:99px;margin:2px 4px 2px 0;">${f}</span>`).join('')}
               </div>`;
             }
             extraHtml += `</div>`;
           }

           if (vc.notes) {
             extraHtml += `<p style="font-size:12px;color:#64748b;margin:8px 0 0;font-style:italic;">📝 ${vc.notes}</p>`;
           }
         }

         extraHtml += `</div>`;
       }
    }

    // 4. KatastralniAnalytik
    if (name === 'KatastralniAnalytik') {
       if (details.ortofoto_url || details.ortofoto_annotated_url) {
         const url = details.ortofoto_annotated_url || details.ortofoto_url;
         extraHtml += `<div style="margin:12px 0;">
           <img src="${url}" style="width:100%;max-width:500px;border-radius:8px;border:1px solid #e2e8f0;" onerror="this.style.display='none'">
         </div>`;
       }
       if (details.lv_data) {
         extraHtml += `<div style="font-size:13px;font-weight:600;color:#475569;margin-bottom:8px;">LV ${details.lv_data.lv_number} · k.ú. ${details.lv_data.kat_uzemi_nazev}</div>`;
       }
       if (details.risks && details.risks.length > 0) {
         extraHtml += `<div style="display:flex;flex-direction:column;gap:8px;margin-top:12px;">`;
         details.risks.forEach(r => {
           const rcol = r.severity === 'vysoké' ? '#ef4444' : r.severity === 'střední' ? '#f59e0b' : '#22c55e';
           extraHtml += `<div style="padding:10px 12px;border-left:4px solid ${rcol};background:#f8fafc;font-size:13px;border-radius:0 8px 8px 0;border-top:1px solid #e2e8f0;border-right:1px solid #e2e8f0;border-bottom:1px solid #e2e8f0;">
             <span style="font-size:11px;font-weight:700;color:${rcol};text-transform:uppercase;margin-right:6px;">${r.severity}</span>
             <span style="color:#334155;">${r.description}</span>
           </div>`;
         });
         extraHtml += `</div>`;
       }
    }

    // Agent card HTML
    html += `<div class="res-agent-card expanded">
      <div class="res-agent-header" onclick="this.parentElement.classList.toggle('expanded')">
        <div class="res-agent-info"><span class="res-agent-icon" style="background:${meta.color}22;color:${meta.color}">${meta.icon}</span><span class="res-agent-label">${meta.label}</span></div>
        <span class="res-badge ${badge.cls}">${badge.text}</span>
      </div>
      <div class="res-agent-body">
        <p style="margin-bottom:8px;color:#334155;">${summary.replace(/\n/g, '<br>')}</p>
        ${extraHtml}
        ${errors.length ? `<div class="res-errors" style="margin-top:12px;">${errors.map(e => `<div class="res-error-item">❌ ${e}</div>`).join('')}</div>` : ''}
        ${warnings.length ? `<div class="res-warnings" style="margin-top:12px;">${warnings.map(w => `<div class="res-warning-item">⚠️ ${w}</div>`).join('')}</div>` : ''}
      </div>
    </div>`;
  });

  // Actions
  if (isBatchMode) {
    html += `<div class="res-actions">
      <a href="${pdfUrl}" class="btn btn-pdf" id="res-pdf-btn" target="_blank"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Stáhnout PDF protokol</a>
      <button class="btn btn-primary" id="res-batch-back-btn">← Zpět na Hromadné zpracování</button>
    </div>`;
  } else {
    html += `<div class="res-actions">
      <button class="btn btn-secondary" id="res-edit-btn"><svg width="16" height="16" viewBox="0 0 16 16" fill="none"><path d="M10 2L13 5L5 13H2V10L10 2Z" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg> Upravit vstup</button>
      <a href="${pdfUrl}" class="btn btn-pdf" id="res-pdf-btn" target="_blank"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> Stáhnout PDF protokol</a>
      <button class="btn btn-primary" id="res-reset-btn">Nová kontrola</button>
    </div>`;
  }

  html += `</div></section>`;
  container.innerHTML = html;

  const editBtn = container.querySelector('#res-edit-btn');
  const resetBtn = container.querySelector('#res-reset-btn');
  const batchBackBtn = container.querySelector('#res-batch-back-btn');
  if (editBtn) editBtn.onclick = onEdit;
  if (resetBtn) resetBtn.onclick = onReset;
  if (batchBackBtn) batchBackBtn.onclick = onBackToBatch;
}
