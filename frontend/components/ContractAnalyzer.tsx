'use client';
import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import styles from './ContractAnalyzer.module.css';
import {
  uploadContract,
  queryContract,
  extractAllContractData,
  compareContracts,
  getContractPdfUrl,
  getContractPageImageUrl,
  API_BASE,
  type ContractUploadResponse,
  type ContractQueryResult,
  type ContractPreset,
  type ExtractAllResult,
  type ExtractAllField,
  type RedFlag,
  type CompareResult,
} from '@/lib/api';

interface QueryResultEntry {
  preset_id?: string;
  label: string;
  result: ContractQueryResult;
}

interface ContractAnalyzerProps {
  selectedModel: string;
}

// Processing steps for the loader
const PROCESSING_STEPS = [
  { key: 'uploading', icon: '📤', label: 'Nahrávání dokumentu', desc: 'Odesílání smlouvy na server' },
  { key: 'ocr', icon: '🔍', label: 'Čtení dokumentu', desc: 'AI rozpoznává text ze smlouvy' },
  { key: 'classifying', icon: '🤖', label: 'Klasifikace smlouvy', desc: 'Určování typu smlouvy a příprava předvoleb' },
  { key: 'ready', icon: '✅', label: 'Analýza dokončena', desc: 'Smlouva je připravena k dotazování' },
];

// Sub-component: renders page image and overlays highlights after image loads
function OriginalPageWithHighlights({ pageIndex, sessionId, highlights }: {
  pageIndex: number;
  sessionId: string;
  highlights: { page: number; text: string; y_ratio: number }[];
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [imageLoaded, setImageLoaded] = useState(false);
  const [imageHeight, setImageHeight] = useState(0);

  const handleImageLoad = (e: React.SyntheticEvent<HTMLImageElement>) => {
    const img = e.target as HTMLImageElement;
    setImageHeight(img.clientHeight);
    setImageLoaded(true);
  };

  // Update height on window resize
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver(() => {
      const img = containerRef.current?.querySelector('img');
      if (img) setImageHeight(img.clientHeight);
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div className={styles.originalPageContainer} data-page={pageIndex} ref={containerRef}>
      <img
        src={getContractPageImageUrl(sessionId, pageIndex)}
        alt={`Strana ${pageIndex + 1}`}
        className={styles.originalPageImage}
        onLoad={handleImageLoad}
        onError={(e) => {
          (e.target as HTMLImageElement).style.display = 'none';
        }}
      />
      {imageLoaded && imageHeight > 0 && highlights.map((hp, hIdx) => (
        <div
          key={hIdx}
          className={styles.originalHighlight}
          style={{
            top: `${hp.y_ratio * imageHeight}px`,
          }}
          title={hp.text}
        >
          <div className={styles.originalHighlightBar} />
          <div className={styles.originalHighlightText}>
            {hp.text.substring(0, 80)}{hp.text.length > 80 ? '...' : ''}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ContractAnalyzer({ selectedModel }: ContractAnalyzerProps) {
  const [step, setStep] = useState<'upload' | 'processing' | 'analysis'>('upload');
  const [files, setFiles] = useState<File[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [contractData, setContractData] = useState<ContractUploadResponse | null>(null);
  const [queryResults, setQueryResults] = useState<QueryResultEntry[]>([]);
  const [activeQuery, setActiveQuery] = useState<string | null>(null);
  const [queryInput, setQueryInput] = useState('');
  const [queryLoading, setQueryLoading] = useState(false);
  const [highlightTexts, setHighlightTexts] = useState<string[]>([]);
  const [highlightPositions, setHighlightPositions] = useState<{page: number; text: string; y_ratio: number}[]>([]);
  const [processingPhase, setProcessingPhase] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [viewMode, setViewMode] = useState<'text' | 'original' | 'pdf'>('text');
  const [panelWidth, setPanelWidth] = useState(380);
  const [isResizing, setIsResizing] = useState(false);
  
  // Extract All
  const [extractAllData, setExtractAllData] = useState<ExtractAllResult | null>(null);
  const [extractAllLoading, setExtractAllLoading] = useState(false);
  
  // Compare
  const [compareMode, setCompareMode] = useState(false);
  const [compareFiles, setCompareFiles] = useState<File[]>([]);
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);
  const [compareSessionB, setCompareSessionB] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const documentContentRef = useRef<HTMLDivElement>(null);
  const resizeRef = useRef<{ startX: number; startWidth: number } | null>(null);

  // Timer for processing loader
  // Resize handler
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!resizeRef.current) return;
      const delta = e.clientX - resizeRef.current.startX;
      const newWidth = Math.max(280, Math.min(700, resizeRef.current.startWidth + delta));
      setPanelWidth(newWidth);
    };
    const handleMouseUp = () => {
      resizeRef.current = null;
      setIsResizing(false);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    if (isResizing) {
      document.addEventListener('mousemove', handleMouseMove);
      document.addEventListener('mouseup', handleMouseUp);
    }
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isResizing]);

  const startResize = (e: React.MouseEvent) => {
    e.preventDefault();
    resizeRef.current = { startX: e.clientX, startWidth: panelWidth };
    setIsResizing(true);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };

  useEffect(() => {
    if (step !== 'processing') return;
    const start = Date.now();
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [step]);

  // ─── File Handling ───
  const handleFiles = useCallback((newFiles: FileList | File[]) => {
    const arr = Array.from(newFiles);
    const valid = arr.filter(f => {
      const ext = f.name.split('.').pop()?.toLowerCase();
      return ['pdf', 'jpg', 'jpeg', 'png', 'heic', 'heif', 'webp', 'tiff', 'bmp'].includes(ext || '');
    });
    setFiles(prev => [...prev, ...valid]);
    setError(null);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  // ─── Upload ───
  const handleUpload = async () => {
    if (files.length === 0) {
      setError('Nahrajte alespoň jednu smlouvu.');
      return;
    }

    setError(null);
    setStep('processing');
    setProcessingPhase(0);
    setElapsed(0);

    try {
      // Phase 1: Uploading
      setProcessingPhase(0);
      
      // Small delay to show uploading phase
      await new Promise(r => setTimeout(r, 500));
      
      // Phase 2: OCR
      setProcessingPhase(1);
      
      const result = await uploadContract(files, selectedModel);
      
      // Phase 3: Classifying
      setProcessingPhase(2);
      await new Promise(r => setTimeout(r, 600));
      
      // Phase 4: Ready
      setProcessingPhase(3);
      await new Promise(r => setTimeout(r, 400));

      setContractData(result);
      setStep('analysis');
    } catch (e: any) {
      setError(e.message || 'Chyba při nahrávání smlouvy.');
      setStep('upload');
    }
  };

  // ─── Query Handler ───
  const handleQuery = async (query: string, presetId?: string, presetLabel?: string) => {
    if (!contractData || !query.trim()) return;

    setQueryLoading(true);
    setActiveQuery(presetId || 'custom');

    try {
      const result = await queryContract(contractData.session_id, query, selectedModel);

      const entry: QueryResultEntry = {
        preset_id: presetId,
        label: presetLabel || query,
        result,
      };

      setQueryResults(prev => {
        if (presetId) {
          const existing = prev.findIndex(r => r.preset_id === presetId);
          if (existing >= 0) {
            const updated = [...prev];
            updated[existing] = entry;
            return updated;
          }
        }
        return [entry, ...prev];
      });

      // Set highlights
      const allHighlights = [
        ...result.highlights,
        ...result.citations.map(c => c.text),
      ];
      setHighlightTexts(allHighlights);

      // Store highlight positions for original view
      if (result.highlight_positions.length > 0) {
        setHighlightPositions(prev => [...prev, ...result.highlight_positions]);
      }

      // Auto-scroll to first highlight after DOM update
      const firstCitation = result.citations[0]?.text || result.highlights[0];
      const firstPosition = result.highlight_positions[0];
      
      // Give React time to re-render highlights, then scroll
      setTimeout(() => {
        if (viewMode === 'original' && firstPosition) {
          // Scroll to highlight on original page image
          scrollToOriginalHighlight(firstPosition.page, firstPosition.y_ratio);
        } else if (firstCitation) {
          scrollToHighlight(firstCitation);
        }
      }, 300);

    } catch (e: any) {
      setError(e.message || 'Chyba při dotazu.');
    } finally {
      setQueryLoading(false);
      setActiveQuery(null);
    }
  };

  const handlePresetClick = (preset: ContractPreset) => {
    handleQuery(preset.query, preset.id, preset.label);
  };

  const handleCustomQuery = (e: React.FormEvent) => {
    e.preventDefault();
    if (queryInput.trim()) {
      handleQuery(queryInput, undefined, queryInput);
      setQueryInput('');
    }
  };

  // ─── Highlight & Scroll ───
  const scrollToHighlight = (text: string) => {
    if (!text || !documentContentRef.current) return;

    const container = documentContentRef.current;
    const marks = container.querySelectorAll('mark');
    
    // Strategy 1: Match by first 20 chars of mark content
    for (const mark of marks) {
      if (mark.textContent) {
        const markText = mark.textContent.toLowerCase();
        const searchText = text.toLowerCase();
        
        if (searchText.includes(markText.substring(0, 15)) || markText.includes(searchText.substring(0, 15))) {
          mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
          mark.classList.add(styles.highlightActive);
          setTimeout(() => mark.classList.remove(styles.highlightActive), 4000);
          return;
        }
      }
    }
    
    // Strategy 2: If no mark found, try to find the text in the document itself
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let node;
    const searchLower = text.toLowerCase().substring(0, 30);
    while (node = walker.nextNode()) {
      if (node.textContent && node.textContent.toLowerCase().includes(searchLower)) {
        const parent = node.parentElement;
        if (parent) {
          parent.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        return;
      }
    }
  };

  const scrollToOriginalHighlight = (page: number, yRatio: number) => {
    if (!documentContentRef.current) return;
    
    const pageContainer = documentContentRef.current.querySelector(`[data-page="${page}"]`);
    if (pageContainer) {
      const rect = pageContainer.getBoundingClientRect();
      const containerRect = documentContentRef.current.getBoundingClientRect();
      const scrollTop = documentContentRef.current.scrollTop;
      const targetY = (pageContainer as HTMLElement).offsetTop + (rect.height * yRatio) - containerRect.height / 3;
      
      documentContentRef.current.scrollTo({
        top: targetY,
        behavior: 'smooth',
      });
    }
  };

  const handleCitationClick = (citationText: string, page: number) => {
    setHighlightTexts(prev => {
      if (!prev.includes(citationText)) return [...prev, citationText];
      return prev;
    });
    
    if (viewMode === 'original') {
      // Find the matching highlight position for this citation
      const pos = highlightPositions.find(p => p.text === citationText && p.page === page);
      if (pos) {
        scrollToOriginalHighlight(pos.page, pos.y_ratio);
      }
    } else {
      setTimeout(() => scrollToHighlight(citationText), 200);
    }
  };

  // ─── Render highlighted text ───
  const renderHighlightedText = useMemo(() => {
    if (!contractData) return null;

    return contractData.pages.map((page, pageIdx) => {
      let text = page.full_text;
      if (!text) return null;

      let segments: { text: string; highlighted: boolean }[] = [{ text, highlighted: false }];

      if (highlightTexts.length > 0) {
        for (const ht of highlightTexts) {
          if (!ht || ht.length < 2) continue;
          const newSegments: typeof segments = [];
          for (const seg of segments) {
            if (seg.highlighted) {
              newSegments.push(seg);
              continue;
            }
            const searchText = ht.substring(0, 60);
            const idx = seg.text.toLowerCase().indexOf(searchText.toLowerCase());
            if (idx >= 0) {
              if (idx > 0) {
                newSegments.push({ text: seg.text.substring(0, idx), highlighted: false });
              }
              newSegments.push({ text: seg.text.substring(idx, idx + searchText.length), highlighted: true });
              if (idx + searchText.length < seg.text.length) {
                newSegments.push({ text: seg.text.substring(idx + searchText.length), highlighted: false });
              }
            } else {
              newSegments.push(seg);
            }
          }
          segments = newSegments;
        }
      }

      return (
        <div key={pageIdx} id={`contract-page-${pageIdx}`}>
          {contractData.total_pages > 1 && (
            <span className={styles.pageMarker}>Strana {pageIdx + 1}</span>
          )}
          {segments.map((seg, segIdx) =>
            seg.highlighted ? (
              <mark key={segIdx} className={styles.highlight}>
                {seg.text}
              </mark>
            ) : (
              <span key={segIdx}>{seg.text}</span>
            )
          )}
        </div>
      );
    });
  }, [contractData, highlightTexts]);

  // ─── Reset ───
  // ─── Extract All Handler ───
  const handleExtractAll = async () => {
    if (!contractData) return;
    setExtractAllLoading(true);
    setError(null);
    try {
      const result = await extractAllContractData(contractData.session_id, selectedModel);
      setExtractAllData(result);
      
      // Set highlights from all extracted fields
      const allCitations = result.fields
        .filter(f => f.found && f.citation)
        .map(f => f.citation);
      setHighlightTexts(allCitations);
      
      // Set highlight positions
      const positions = result.fields
        .filter(f => f.found && f.y_ratio !== undefined)
        .map(f => ({ page: f.page - 1, text: f.citation, y_ratio: f.y_ratio! }));
      setHighlightPositions(positions);
    } catch (e: any) {
      setError(e.message || 'Chyba při extrakci.');
    } finally {
      setExtractAllLoading(false);
    }
  };

  // ─── Compare Handler ───
  const handleCompare = async () => {
    if (!contractData || compareFiles.length === 0) return;
    setCompareLoading(true);
    setError(null);
    try {
      // Upload second document
      const uploadResult = await uploadContract(compareFiles, selectedModel);
      setCompareSessionB(uploadResult.session_id);
      
      // Compare
      const result = await compareContracts(
        contractData.session_id, 
        uploadResult.session_id, 
        selectedModel
      );
      setCompareResult(result);
      setCompareMode(false); // Hide upload, show results
    } catch (e: any) {
      setError(e.message || 'Chyba při porovnávání.');
    } finally {
      setCompareLoading(false);
    }
  };

  // ─── CSV Export ───
  const exportCSV = () => {
    if (!extractAllData) return;
    const header = 'Údaj;Hodnota;Strana;Jistota;Nalezeno;Citace\n';
    const rows = extractAllData.fields.map(f =>
      `"${f.label}";"${f.value}";"${f.page}";"${Math.round(f.confidence * 100)}%";"${f.found ? 'Ano' : 'Ne'}";"${f.citation?.replace(/"/g, '""') || ''}"`
    ).join('\n');
    
    const bom = '\uFEFF'; // UTF-8 BOM for Excel
    const blob = new Blob([bom + header + rows], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${contractData?.filename || 'smlouva'}_extrakce.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleReset = () => {
    setStep('upload');
    setFiles([]);
    setContractData(null);
    setQueryResults([]);
    setHighlightTexts([]);
    setHighlightPositions([]);
    setError(null);
    setQueryInput('');
    setViewMode('text');
    setProcessingPhase(0);
    setElapsed(0);
    setExtractAllData(null);
    setCompareResult(null);
    setCompareMode(false);
    setCompareFiles([]);
    setCompareSessionB(null);
  };

  // ═══════════════════════════════════════════════════════════════════
  // RENDER: Upload Step (inside tab)
  // ═══════════════════════════════════════════════════════════════════
  if (step === 'upload') {
    return (
      <div className={styles.uploadSection}>
        <p className={styles.uploadSubtitle}>
          Nahrajte bankovní smlouvu — AI analyzuje obsah a najde klíčové informace
        </p>

        <div
          className={`${styles.dropZone} ${dragActive ? styles.dropZoneActive : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={() => fileInputRef.current?.click()}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,.pdf,application/pdf,image/jpeg,image/png,image/heic,image/heif,image/webp,image/tiff,image/bmp"
            onChange={(e) => e.target.files && handleFiles(e.target.files)}
            className={styles.fileInput}
          />
          <div className={styles.dropIcon}>
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
              <path d="M17 2H7C6.45 2 6 2.45 6 3V25C6 25.55 6.45 26 7 26H21C21.55 26 22 25.55 22 25V7L17 2Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M17 2V7H22" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M10 17H18M14 13V21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <p className={styles.dropText}>
            {dragActive ? 'Přetáhněte sem' : 'Přetáhněte smlouvu nebo klikněte pro výběr'}
          </p>
          <p className={styles.dropHint}>PDF, fotky (JPG, PNG, HEIC) • Podporuje i špatně vyfocené dokumenty</p>
        </div>

        {files.length > 0 && (
          <div className={styles.fileList}>
            {files.map((file, i) => (
              <div key={i} className={styles.fileChip}>
                <span className={styles.fileChipIcon}>
                  {file.name.toLowerCase().endsWith('.pdf') ? '📄' : '📷'}
                </span>
                <span>{file.name}</span>
                <button className={styles.fileChipRemove} onClick={(e) => { e.stopPropagation(); removeFile(i); }}>✕</button>
              </div>
            ))}
          </div>
        )}

        {error && <div className={styles.error}>{error}</div>}

        <div className={styles.uploadActions}>
          <button
            className="btn btn-primary"
            onClick={handleUpload}
            disabled={files.length === 0}
            style={{ padding: '14px 36px', fontSize: '15px' }}
          >
            Analyzovat smlouvu
          </button>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════
  // RENDER: Processing Step (fullscreen loader like ProcessingLoader)
  // ═══════════════════════════════════════════════════════════════════
  if (step === 'processing') {
    return (
      <div className={styles.loaderOverlay}>
        <div className={styles.loaderContent}>
          {/* Animated ring */}
          <div className={styles.ringContainer}>
            <div className={styles.ringOuter} />
            <svg className={styles.ringSvg} viewBox="0 0 160 160">
              <defs>
                <linearGradient id="contractLoaderGradient" x1="0%" y1="0%" x2="100%" y2="100%">
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
                <path d="M8 4H20L26 10V28H8C6.9 28 6 27.1 6 26V6C6 4.9 6.9 4 8 4Z" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M20 4V10H26" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M12 18H22M12 22H18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
            </div>
          </div>

          <h2 className={styles.loaderTitle}>
            Analyzuji smlouvu
            <span className={styles.loaderDots}>
              <span>.</span><span>.</span><span>.</span>
            </span>
          </h2>
          <p className={styles.loaderSubtitle}>
            AI čte dokument a připravuje inteligentní analýzu
          </p>

          {/* Step indicators */}
          <div className={styles.loaderSteps}>
            {PROCESSING_STEPS.map((s, idx) => {
              const isActive = idx === processingPhase;
              const isDone = idx < processingPhase;
              return (
                <div
                  key={s.key}
                  className={`${styles.loaderStepItem} ${isActive ? styles.loaderStepActive : ''} ${isDone ? styles.loaderStepDone : ''}`}
                >
                  <div className={styles.loaderStepIcon}>{s.icon}</div>
                  <div className={styles.loaderStepText}>
                    <span className={styles.loaderStepLabel}>{s.label}</span>
                    <span className={styles.loaderStepDesc}>{s.desc}</span>
                  </div>
                  {isActive && <div className={styles.loaderStepSpinner} />}
                  {isDone && (
                    <svg className={styles.loaderStepCheck} viewBox="0 0 20 20" fill="none">
                      <circle cx="10" cy="10" r="9" fill="rgba(5,150,105,0.15)" />
                      <path d="M6 10.5L8.5 13L14 7" stroke="var(--accent-green)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </div>
              );
            })}
          </div>

          <div className={styles.loaderTip}>
            <span>⏱️</span>
            Analýza obvykle trvá 15–45 sekund • {elapsed}s
          </div>
        </div>
      </div>
    );
  }

  // ═══════════════════════════════════════════════════════════════════
  // RENDER: Analysis Step (full-width new page)
  // ═══════════════════════════════════════════════════════════════════
  if (step === 'analysis' && contractData) {
    const classification = contractData.classification;

    return (
      <div className={styles.analysisPage}>
        {/* Top bar */}
        <div className={styles.analysisTopBar}>
          <button className={styles.backBtn} onClick={handleReset}>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path d="M10 12L6 8L10 4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Nová smlouva
          </button>
          <div className={styles.analysisTopBarInfo}>
            <span className={styles.analysisTopBarIcon}>{classification.icon}</span>
            <span className={styles.analysisTopBarTitle}>{classification.title}</span>
            <span className={styles.analysisTopBarConfidence}>
              {Math.round(classification.confidence * 100)}%
            </span>
          </div>
          <div className={styles.analysisTopBarFileName}>
            📄 {contractData.filename}
            <span className={styles.analysisTopBarPages}>
              ({contractData.total_pages} {contractData.total_pages === 1 ? 'strana' : contractData.total_pages < 5 ? 'strany' : 'stran'})
            </span>
          </div>
        </div>

        {/* Main content */}
        <div className={styles.analysisLayout} style={{ gridTemplateColumns: `${panelWidth}px 6px 1fr` }}>
          {/* ─── Left: Query Panel ─── */}
          <div className={styles.queryPanel}>
            {/* Contract Summary */}
            {classification.summary && (
              <div className={styles.contractInfoCard}>
                <div className={styles.contractSummary}>{classification.summary}</div>
                {classification.parties.length > 0 && (
                  <div className={styles.contractParties}>
                    {classification.parties.map((party, i) => (
                      <span key={i} className={styles.partyChip}>{party}</span>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Quick Presets */}
            <div className={styles.presetsCard}>
              <div className={styles.presetsTitle}>
                <span className={styles.presetsTitleIcon}>⚡</span>
                Rychlé předvolby
              </div>
              <div className={styles.presetsGrid}>
                {classification.presets.map((preset) => {
                  const hasResult = queryResults.some(r => r.preset_id === preset.id);
                  const isLoading = activeQuery === preset.id;
                  return (
                    <button
                      key={preset.id}
                      className={`${styles.presetBtn} ${hasResult ? styles.presetBtnActive : ''} ${isLoading ? styles.presetBtnLoading : ''}`}
                      onClick={() => handlePresetClick(preset)}
                      disabled={queryLoading}
                    >
                      {isLoading && <span className={styles.presetBtnSpinner} />}
                      {preset.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* ─── Action Buttons ─── */}
            <div className={styles.actionButtonsRow}>
              <button
                className={styles.extractAllBtn}
                onClick={handleExtractAll}
                disabled={extractAllLoading || queryLoading}
              >
                {extractAllLoading ? (
                  <><span className={styles.presetBtnSpinner} /> Extrahuji...</>
                ) : (
                  <>⚡ Extrahovat vše</>
                )}
              </button>
              <button
                className={styles.compareBtn}
                onClick={() => setCompareMode(!compareMode)}
                disabled={compareLoading}
              >
                🔀 Porovnat
              </button>
            </div>

            {/* ─── Compare Upload ─── */}
            {compareMode && (
              <div className={styles.compareCard}>
                <div className={styles.compareTitle}>📎 Nahrát druhý dokument k porovnání</div>
                <input
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,.heic,image/*"
                  multiple
                  onChange={(e) => setCompareFiles(Array.from(e.target.files || []))}
                  className={styles.compareFileInput}
                />
                {compareFiles.length > 0 && (
                  <button
                    className={styles.compareStartBtn}
                    onClick={handleCompare}
                    disabled={compareLoading}
                  >
                    {compareLoading ? (
                      <><span className={styles.presetBtnSpinner} /> Porovnávám...</>
                    ) : (
                      <>🔍 Porovnat dokumenty</>
                    )}
                  </button>
                )}
              </div>
            )}

            {/* ─── Extract All Results Table ─── */}
            {extractAllData && (
              <div className={styles.extractAllCard}>
                <div className={styles.extractAllHeader}>
                  <div className={styles.extractAllTitle}>
                    <span>📊</span>
                    Extrahovaná data ({extractAllData.fields.filter(f => f.found).length}/{extractAllData.fields.length})
                    {(extractAllData as any).stats && (
                      <span className={styles.extractAllStats}>
                        ✅ {(extractAllData as any).stats.verified} ověřeno
                      </span>
                    )}
                  </div>
                  <button className={styles.exportCsvBtn} onClick={exportCSV}>
                    📥 Export CSV
                  </button>
                </div>
                <div className={styles.extractAllTable}>
                  {extractAllData.fields.map((field, idx) => (
                    <div key={idx} className={`${styles.extractAllRow} ${!field.found ? styles.extractAllRowNotFound : ''}`}>
                      <div className={styles.extractAllLabel}>{field.label}</div>
                      <div className={styles.extractAllValue}>
                        {field.found ? field.value : '—'}
                      </div>
                      <div className={styles.extractAllMeta}>
                        {field.found && (
                          <>
                            {(field as any).verified && (
                              <span className={styles.verifiedBadge} title="Citace ověřena v textu">✓</span>
                            )}
                            <span className={`${styles.confidenceBadge} ${
                              field.confidence >= 0.9 ? styles.confidenceHigh :
                              field.confidence >= 0.6 ? styles.confidenceMedium :
                              styles.confidenceLow
                            }`}>
                              {Math.round(field.confidence * 100)}%
                            </span>
                            <span className={styles.extractAllPage}>str. {field.page}</span>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ─── Red Flags ─── */}
            {extractAllData && extractAllData.red_flags.length > 0 && (
              <div className={styles.redFlagsCard}>
                <div className={styles.redFlagsTitle}>
                  <span>⚠️</span>
                  Upozornění ({extractAllData.red_flags.length})
                </div>
                {extractAllData.red_flags.map((flag, idx) => (
                  <div key={idx} className={`${styles.redFlagItem} ${styles[`redFlag_${flag.severity}`]}`}>
                    <div className={styles.redFlagSeverity}>
                      {flag.severity === 'critical' ? '🔴' : flag.severity === 'high' ? '🟠' : flag.severity === 'medium' ? '🟡' : '🟢'}
                    </div>
                    <div className={styles.redFlagContent}>
                      <div className={styles.redFlagLabel}>{flag.title}</div>
                      <div className={styles.redFlagDesc}>{flag.description}</div>
                      {flag.page && <div className={styles.redFlagPage}>📍 Strana {flag.page}</div>}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* ─── Compare Results ─── */}
            {compareResult && (
              <div className={styles.compareResultCard}>
                <div className={styles.compareResultTitle}>
                  <span>🔀</span>
                  Výsledek porovnání
                </div>
                <div className={styles.compareResultSummary}>{compareResult.summary}</div>
                
                {compareResult.differences.length > 0 && (
                  <div className={styles.compareDiffSection}>
                    <div className={styles.compareDiffSectionTitle}>Změny ({compareResult.differences.length})</div>
                    {compareResult.differences.map((diff, idx) => (
                      <div key={idx} className={`${styles.compareDiffItem} ${styles[`severity_${diff.severity}`]}`}>
                        <div className={styles.compareDiffHeader}>
                          <span className={styles.compareDiffCategory}>{diff.category}</span>
                          <span className={`${styles.compareDiffSeverity} ${styles[`severity_${diff.severity}`]}`}>
                            {diff.severity === 'critical' ? '🔴 Kritické' : diff.severity === 'high' ? '🟠 Vysoké' : diff.severity === 'medium' ? '🟡 Střední' : '🟢 Nízké'}
                          </span>
                        </div>
                        <div className={styles.compareDiffTitle}>{diff.title}</div>
                        <div className={styles.compareDiffTexts}>
                          <div className={styles.compareDiffA}>
                            <span className={styles.compareDiffLabel}>A:</span> {diff.text_a}
                          </div>
                          {diff.text_b && (
                            <div className={styles.compareDiffB}>
                              <span className={styles.compareDiffLabel}>B:</span> {diff.text_b}
                            </div>
                          )}
                        </div>
                        <div className={styles.compareDiffDescription}>{diff.description}</div>
                      </div>
                    ))}
                  </div>
                )}

                {compareResult.added_in_b.length > 0 && (
                  <div className={styles.compareDiffSection}>
                    <div className={styles.compareDiffSectionTitle}>✅ Přidáno v B ({compareResult.added_in_b.length})</div>
                    {compareResult.added_in_b.map((item, idx) => (
                      <div key={idx} className={styles.compareDiffItemAdded}>
                        <div className={styles.compareDiffTitle}>{item.title}</div>
                        <div className={styles.compareDiffDesc}>{item.text}</div>
                      </div>
                    ))}
                  </div>
                )}

                {compareResult.missing_in_b.length > 0 && (
                  <div className={styles.compareDiffSection}>
                    <div className={styles.compareDiffSectionTitle}>❌ Chybí v B ({compareResult.missing_in_b.length})</div>
                    {compareResult.missing_in_b.map((item, idx) => (
                      <div key={idx} className={styles.compareDiffItemMissing}>
                        <div className={styles.compareDiffTitle}>{item.title}</div>
                        <div className={styles.compareDiffDesc}>{item.text}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Custom Query */}
            <div className={styles.queryCard}>
              <div className={styles.queryTitle}>
                <span>🔍</span>
                Vlastní dotaz
              </div>
              <form onSubmit={handleCustomQuery} className={styles.queryInputWrapper}>
                <input
                  type="text"
                  className={styles.queryInput}
                  placeholder="Co se píše v §3? / Najdi kupní cenu"
                  value={queryInput}
                  onChange={(e) => setQueryInput(e.target.value)}
                  disabled={queryLoading}
                />
                <button
                  type="submit"
                  className={styles.querySubmitBtn}
                  disabled={queryLoading || !queryInput.trim()}
                >
                  <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                    <path d="M16 2L9 9M16 2L11 16L9 9M16 2L2 7L9 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </button>
              </form>
            </div>

            {/* Loading */}
            {queryLoading && (
              <div className={styles.queryLoading}>
                <div className={styles.queryLoadingDots}>
                  <span className={styles.queryLoadingDot} />
                  <span className={styles.queryLoadingDot} />
                  <span className={styles.queryLoadingDot} />
                </div>
                AI hledá ve smlouvě...
              </div>
            )}

            {/* Results */}
            {queryResults.length > 0 && (
              <div className={styles.resultsCard}>
                <div className={styles.resultsTitle}>
                  <span>📋</span>
                  Nalezené informace ({queryResults.length})
                  <button
                    className={styles.clearResultsBtn}
                    onClick={() => { setQueryResults([]); setHighlightTexts([]); setHighlightPositions([]); }}
                    title="Smazat historii"
                  >
                    🗑️ Smazat
                  </button>
                </div>
                {queryResults.map((qr, idx) => (
                  <div key={idx} className={styles.resultItem}>
                    <div className={styles.resultLabel}>{qr.label}</div>
                    <div className={styles.resultAnswer}>{qr.result.answer}</div>
                    {!qr.result.found && (
                      <span className={styles.notFoundBadge}>⚠ Nenalezeno ve smlouvě</span>
                    )}
                    {qr.result.citations.map((citation, cIdx) => (
                      <div
                        key={cIdx}
                        className={styles.resultCitation}
                        onClick={() => handleCitationClick(citation.text, citation.page - 1)}
                      >
                        {`„${citation.text}"`}
                        <div className={styles.resultCitationPage}>
                          📍 Strana {citation.page} — klikněte pro zobrazení
                        </div>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            )}

            {error && <div className={styles.error}>{error}</div>}
          </div>

          {/* Resize Handle */}
          <div
            className={`${styles.resizeHandle} ${isResizing ? styles.resizeHandleActive : ''}`}
            onMouseDown={startResize}
          >
            <div className={styles.resizeGrip}>
              <span /><span /><span />
            </div>
          </div>

          {/* ─── Right: Document Viewer ─── */}
          <div className={styles.documentPanel}>
            <div className={styles.documentHeader}>
              {/* View mode toggle */}
              <div className={styles.viewToggle}>
                <button
                  className={`${styles.viewToggleBtn} ${viewMode === 'text' ? styles.viewToggleBtnActive : ''}`}
                  onClick={() => setViewMode('text')}
                >
                  📝 Přepis
                </button>
                <button
                  className={`${styles.viewToggleBtn} ${viewMode === 'original' ? styles.viewToggleBtnActive : ''}`}
                  onClick={() => setViewMode('original')}
                >
                  🖼️ Originál
                </button>
                {contractData.has_pdf && (
                  <button
                    className={`${styles.viewToggleBtn} ${viewMode === 'pdf' ? styles.viewToggleBtnActive : ''}`}
                    onClick={() => setViewMode('pdf')}
                  >
                    📄 Náhled PDF
                  </button>
                )}
              </div>
              <span className={styles.documentPageInfo}>
                {contractData.total_pages} {contractData.total_pages === 1 ? 'strana' : contractData.total_pages < 5 ? 'strany' : 'stran'}
              </span>
            </div>

            <div className={styles.documentContent} ref={documentContentRef}>
              {viewMode === 'text' ? (
                <div className={styles.documentText}>
                  {renderHighlightedText}
                </div>
              ) : viewMode === 'original' ? (
                <div className={styles.originalPages}>
                  {Array.from({ length: contractData.total_pages }, (_, i) => {
                    const pageHighlights = highlightPositions.filter(h => h.page === i);
                    return (
                      <div key={i} className={styles.originalPageWrapper}>
                        {contractData.total_pages > 1 && (
                          <div className={styles.originalPageLabel}>Strana {i + 1}</div>
                        )}
                        <OriginalPageWithHighlights
                          pageIndex={i}
                          sessionId={contractData.session_id}
                          highlights={pageHighlights}
                        />
                      </div>
                    );
                  })}
                  {highlightPositions.length === 0 && queryResults.length > 0 && (
                    <div className={styles.originalNoHighlights}>
                      💡 Klikněte na citaci vlevo pro zobrazení zvýraznění
                    </div>
                  )}
                </div>
              ) : (
                <iframe
                  src={getContractPdfUrl(contractData.session_id)}
                  className={styles.pdfViewer}
                  title="Contract PDF"
                />
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
