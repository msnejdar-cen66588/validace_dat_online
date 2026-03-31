'use client';
import { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import styles from './ContractAnalyzer.module.css';
import {
  uploadContract,
  queryContract,
  getContractPdfUrl,
  getContractPageImageUrl,
  API_BASE,
  type ContractUploadResponse,
  type ContractQueryResult,
  type ContractPreset,
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

  const fileInputRef = useRef<HTMLInputElement>(null);
  const documentContentRef = useRef<HTMLDivElement>(null);

  // Timer for processing loader
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
        return [...prev, entry];
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

      // Scroll to first highlight
      if (result.highlight_positions.length > 0) {
        scrollToHighlight(result.citations[0]?.text || result.highlights[0]);
      }
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

    setTimeout(() => {
      const container = documentContentRef.current;
      if (!container) return;

      const marks = container.querySelectorAll('mark');
      for (const mark of marks) {
        if (mark.textContent && text.toLowerCase().includes(mark.textContent.toLowerCase().substring(0, 20))) {
          mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
          mark.classList.add(styles.highlightActive);
          setTimeout(() => mark.classList.remove(styles.highlightActive), 3000);
          break;
        }
      }
    }, 100);
  };

  const handleCitationClick = (citationText: string, page: number) => {
    setHighlightTexts(prev => {
      if (!prev.includes(citationText)) return [...prev, citationText];
      return prev;
    });
    scrollToHighlight(citationText);
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
        <div className={styles.analysisLayout}>
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
                        <div className={styles.originalPageContainer}>
                          <img
                            src={getContractPageImageUrl(contractData.session_id, i)}
                            alt={`Strana ${i + 1}`}
                            className={styles.originalPageImage}
                            onError={(e) => {
                              (e.target as HTMLImageElement).style.display = 'none';
                            }}
                          />
                          {/* Highlight overlays */}
                          {pageHighlights.map((hp, hIdx) => (
                            <div
                              key={hIdx}
                              className={styles.originalHighlight}
                              style={{
                                top: `${hp.y_ratio * 100}%`,
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
