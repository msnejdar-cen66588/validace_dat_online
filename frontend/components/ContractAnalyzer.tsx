'use client';
import { useState, useRef, useCallback, useMemo } from 'react';
import styles from './ContractAnalyzer.module.css';
import {
  uploadContract,
  queryContract,
  getContractPdfUrl,
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
  const [activeHighlightPage, setActiveHighlightPage] = useState<number | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const documentContentRef = useRef<HTMLDivElement>(null);

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

    try {
      const result = await uploadContract(files, selectedModel);
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

      // Add to results (replace if same preset)
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

      // Scroll to first highlight
      if (result.highlight_positions.length > 0) {
        setActiveHighlightPage(result.highlight_positions[0].page);
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

    // Find the highlighted span
    setTimeout(() => {
      const container = documentContentRef.current;
      if (!container) return;

      const marks = container.querySelectorAll('mark');
      for (const mark of marks) {
        if (mark.textContent && text.toLowerCase().includes(mark.textContent.toLowerCase().substring(0, 20))) {
          mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
          mark.classList.add(styles.active);
          setTimeout(() => mark.classList.remove(styles.active), 3000);
          break;
        }
      }
    }, 100);
  };

  const handleCitationClick = (citationText: string, page: number) => {
    setActiveHighlightPage(page);
    // Add this citation to highlights
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

      // Create highlighted version
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
            // Try to find the highlight text (case insensitive, first 40 chars for matching)
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
    setActiveHighlightPage(null);
    setError(null);
    setQueryInput('');
  };

  // ═══════════════════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════════════════

  // ─── Upload Step ───
  if (step === 'upload') {
    return (
      <div className={styles.container}>
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
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                <path d="M9 2V16M3 9H15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
              </svg>
              Analyzovat smlouvu
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ─── Processing Step ───
  if (step === 'processing') {
    return (
      <div className={styles.container}>
        <div className={styles.processingOverlay}>
          <div className={styles.processingSpinner} />
          <h3 className={styles.processingTitle}>Analyzuji smlouvu...</h3>
          <p className={styles.processingSubtitle}>
            AI čte dokument, rozpoznává typ smlouvy a připravuje předvolby
          </p>
        </div>
      </div>
    );
  }

  // ─── Analysis Step ───
  if (step === 'analysis' && contractData) {
    const classification = contractData.classification;

    return (
      <div className={styles.container}>
        <button className={styles.backBtn} onClick={handleReset}>
          ← Nová smlouva
        </button>

        <div className={styles.analysisLayout}>
          {/* ─── Left: Query Panel ─── */}
          <div className={styles.queryPanel}>
            {/* Contract Type Info */}
            <div className={styles.contractInfoCard}>
              <div className={styles.contractType}>
                <div className={styles.contractTypeIcon}>{classification.icon}</div>
                <div>
                  <div className={styles.contractTypeName}>{classification.title}</div>
                  <div className={styles.contractTypeConfidence}>
                    <span className={`${styles.confidenceDot} ${classification.confidence < 0.7 ? styles.confidenceDotMedium : ''}`} />
                    {Math.round(classification.confidence * 100)}% jistota
                  </div>
                </div>
              </div>
              {classification.summary && (
                <div className={styles.contractSummary}>{classification.summary}</div>
              )}
              {classification.parties.length > 0 && (
                <div className={styles.contractParties}>
                  {classification.parties.map((party, i) => (
                    <span key={i} className={styles.partyChip}>{party}</span>
                  ))}
                </div>
              )}
            </div>

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
                      className={`${styles.presetBtn} ${hasResult ? styles.active : ''} ${isLoading ? styles.loading : ''}`}
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
                Vlastní dotaz nad smlouvou
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
                        {"„"}{citation.text}{"“"}
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
              <div className={styles.documentTitle}>
                <span className={styles.documentTitleIcon}>📄</span>
                {contractData.filename}
              </div>
              <span className={styles.documentPageInfo}>
                {contractData.total_pages} {contractData.total_pages === 1 ? 'strana' : contractData.total_pages < 5 ? 'strany' : 'stran'}
              </span>
            </div>

            <div className={styles.documentContent} ref={documentContentRef}>
              <div className={styles.documentText}>
                {renderHighlightedText}
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
