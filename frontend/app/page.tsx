'use client';
import { useState, useRef, useCallback } from 'react';
import styles from './page.module.css';
import { uploadFiles, startPipeline, parsePdf, parseLv, type UploadResponse, type PipelineResult, type PropertyData, type LVData } from '@/lib/api';
import PipelineCanvas from '@/components/PipelineCanvas';
import ResultsDashboard from '@/components/ResultsDashboard';
import AppInfo from '@/components/AppInfo';
import { useWebSocket } from '@/hooks/useWebSocket';

const EMPTY_PROPERTY_DATA: PropertyData = {
  stavba_dokoncena: null,
  stav_rodinneho_domu: null,
  pocet_podlazi: null,
  typ_strechy: null,
  podsklepeni: null,
  celkova_podlahova_plocha: null,
  plocha_pozemku: null,
  typ_vytapeni: null,
  adresa: null,
  podkrovi: null,
  podkrovi_obytne: null,
  vyuziti_podkrovi_procent: null,
};

const DATA_LABELS: Record<keyof PropertyData, string> = {
  stavba_dokoncena: 'Stavba dokončena',
  stav_rodinneho_domu: 'Stav rodinného domu',
  pocet_podlazi: 'Počet podlaží',
  typ_strechy: 'Typ střechy',
  podsklepeni: 'Podsklepení',
  celkova_podlahova_plocha: 'Celková podlahová plocha',
  plocha_pozemku: 'Plocha pozemku',
  typ_vytapeni: 'Typ vytápění',
  adresa: 'Adresa',
  podkrovi: 'Podkroví',
  podkrovi_obytne: 'Obytné podkroví',
  vyuziti_podkrovi_procent: 'Využití podkroví (%)',
};

export default function Home() {
  const [step, setStep] = useState<'upload' | 'pipeline' | 'results'>('upload');
  const [files, setFiles] = useState<File[]>([]);
  const [yearBuilt, setYearBuilt] = useState('');
  const [yearReconstructed, setYearReconstructed] = useState('');
  const [propertyAddress, setPropertyAddress] = useState('');
  const [uploading, setUploading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [uploadData, setUploadData] = useState<UploadResponse | null>(null);
  const [pipelineResult, setPipelineResult] = useState<PipelineResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pdfInputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [showAppInfo, setShowAppInfo] = useState(false);

  // PDF state
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const [pdfDragActive, setPdfDragActive] = useState(false);
  const [extractedData, setExtractedData] = useState<PropertyData | null>(null);
  const [pdfParsing, setPdfParsing] = useState(false);
  const [dataSource, setDataSource] = useState<'pdf' | 'manual'>('pdf');

  // Manual form state
  const [manualData, setManualData] = useState<PropertyData>({ ...EMPTY_PROPERTY_DATA });

  // LV (List Vlastnictví) state
  const [lvFile, setLvFile] = useState<File | null>(null);
  const [lvData, setLvData] = useState<LVData | null>(null);
  const [lvParsing, setLvParsing] = useState(false);
  const [selectedParcels, setSelectedParcels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("gemini");
  const [pipelineStarted, setPipelineStarted] = useState(false);
  const lvInputRef = useRef<HTMLInputElement>(null);

  const ws = useWebSocket(sessionId);

  const handleFiles = useCallback((newFiles: FileList | File[]) => {
    const arr = Array.from(newFiles);
    setFiles(prev => [...prev, ...arr]);
    setError(null);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const processPdf = useCallback(async (file: File) => {
    setPdfFile(file);
    setPdfParsing(true);
    setError(null);
    try {
      const data = await parsePdf(file);
      if (data) {
        setExtractedData({ ...data });
      } else {
        setError('PDF bylo zpracováno, ale nepodařilo se extrahovat údaje.');
      }
    } catch {
      setError('Chyba při zpracování PDF.');
    } finally {
      setPdfParsing(false);
    }
  }, []);

  const handlePdfDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setPdfDragActive(false);
    const droppedFiles = Array.from(e.dataTransfer.files);
    const pdf = droppedFiles.find(f => f.name.toLowerCase().endsWith('.pdf'));
    if (pdf) processPdf(pdf);
  }, [processPdf]);

  const handlePdfSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && file.name.toLowerCase().endsWith('.pdf')) {
      processPdf(file);
    }
  }, [processPdf]);

  const updateManualField = (field: keyof PropertyData, value: string) => {
    setManualData(prev => ({ ...prev, [field]: value || null }));
  };

  const updateExtractedField = (field: keyof PropertyData, value: string) => {
    setExtractedData(prev => prev ? { ...prev, [field]: value || null } : prev);
  };

  const processLv = useCallback(async (file: File) => {
    setLvFile(file);
    setLvParsing(true);
    try {
      const data = await parseLv(file);
      if (data) {
        setLvData(data);
        // All parcels selected by default
        setSelectedParcels(data.parcels.map(p => p.parcel_number));
      }
    } catch {
      setError('Chyba při zpracování LV.');
    } finally {
      setLvParsing(false);
    }
  }, []);

  const handleLvSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file && file.name.toLowerCase().endsWith('.pdf')) {
      processLv(file);
    }
  }, [processLv]);

  const toggleParcel = (parcelNumber: string) => {
    setSelectedParcels(prev =>
      prev.includes(parcelNumber)
        ? prev.filter(p => p !== parcelNumber)
        : [...prev, parcelNumber]
    );
  };

  const handleUpload = async () => {
    if (files.length === 0) {
      setError('Nahrajte alespoň jednu fotografii.');
      return;
    }

    setUploading(true);
    setError(null);

    try {
      // Determine property data source
      const effectivePdf = dataSource === 'pdf' ? pdfFile || undefined : undefined;
      const effectiveManualData = dataSource === 'manual' ? manualData : undefined;

      // Use extractedData (possibly user-edited) or manual data
      const effectiveData = extractedData || (dataSource === 'manual' ? manualData : null);
      const yearBuiltVal = effectiveData?.stavba_dokoncena ? parseInt(effectiveData.stavba_dokoncena) : undefined;
      const addressVal = effectiveData?.adresa || undefined;

      // If PDF was parsed and user edited the data, send user-edited version
      const finalPropertyData = dataSource === 'pdf' && extractedData ? extractedData : effectiveManualData;

      const result = await uploadFiles(
        files,
        yearBuiltVal,
        undefined,
        addressVal,
        effectivePdf,
        finalPropertyData,
        lvFile || undefined,
        selectedParcels.length > 0 ? selectedParcels : undefined,
      );
      setUploadData(result);
      setSessionId(result.session_id);

      // Store extracted data from server response
      if (result.property_data) {
        setExtractedData(result.property_data);
      }

      setStep('pipeline');
    } catch (e: any) {
      setError(e.message || 'Chyba při nahrávání');
    } finally {
      setUploading(false);
    }
  };

  const handleStartPipeline = async () => {
    if (!sessionId) return;
    // Fire-and-forget: let WebSocket drive the UI updates in real-time
    startPipeline(sessionId, selectedModel)
      .then((result) => {
        // Fallback: if WS didn't deliver the result, use HTTP response (but only if it's the full result with agents)
        if (!ws.pipelineResult && result.agents) {
          setPipelineResult(result);
        }
      })
      .catch((e: any) => {
        setError(e.message || 'Chyba při spuštění pipeline');
      });
  };

  const removeFile = (index: number) => {
    setFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleEdit = () => {
    // Go back to upload step, keep files and property data
    setStep('upload');
    setSessionId(null);
    setUploadData(null);
    setPipelineResult(null);
    setError(null);
  };

  // Use WS pipeline result when available
  const finalResult = ws.pipelineResult || pipelineResult;

  if (finalResult && finalResult.semaphore && finalResult.semaphore !== 'UNKNOWN' && step !== 'results') {
    setStep('results');
    setPipelineResult(finalResult);
  }

  const renderModelSelection = () => (
    <div className={styles.modelSwitcher}>
      <h3 className={styles.modelSwitcherTitle}>
        <span className={styles.modelSwitcherBadge}>AI</span>
        Výběr AI modelu
      </h3>
      <div className={styles.modelGrid}>
        <button
          onClick={() => setSelectedModel("gemini")}
          className={`${styles.modelOption} ${selectedModel === "gemini" ? styles.modelOptionActive : ""}`}
        >
          <span className={styles.modelName}>Google Gemini</span>
          <span className={styles.modelDesc}>Výchozí stabilní model s multimodální vizí</span>
        </button>
        <button
          onClick={() => setSelectedModel("gpt-5")}
          className={`${styles.modelOption} ${selectedModel !== "gemini" ? styles.modelOptionActive : ""}`}
        >
          <span className={styles.modelName}>OpenAI GPT-5</span>
          <span className={styles.modelDesc}>Experimentální model přes podnikovou gateway</span>
        </button>
      </div>
    </div>
  );

  return (
    <main className={styles.main}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerContent}>
          <div className={styles.logo}>
            <div className={styles.logoIcon}>
              <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                <rect x="3" y="6" width="22" height="16" rx="2" stroke="url(#hgrad1)" strokeWidth="2" fill="none" />
                <path d="M3 10H25" stroke="url(#hgrad1)" strokeWidth="1.5" />
                <path d="M8 15H16" stroke="url(#hgrad2)" strokeWidth="1.5" strokeLinecap="round" />
                <path d="M8 18H12" stroke="url(#hgrad2)" strokeWidth="1.5" strokeLinecap="round" opacity="0.5" />
                <circle cx="21" cy="17" r="2.5" stroke="url(#hgrad2)" strokeWidth="1.5" fill="none" />
                <defs>
                  <linearGradient id="hgrad1" x1="3" y1="6" x2="25" y2="22">
                    <stop stopColor="#4a9eff" /><stop offset="1" stopColor="#1e6fd9" />
                  </linearGradient>
                  <linearGradient id="hgrad2" x1="8" y1="15" x2="22" y2="18">
                    <stop stopColor="#8fa3bf" /><stop offset="1" stopColor="#4a9eff" />
                  </linearGradient>
                </defs>
              </svg>
            </div>
            <div>
              <h1 className={styles.logoTitle}>Kontrola vstupních dat</h1>
              <p className={styles.logoSubtitle}>Online ocenění rodinných domů</p>
            </div>
          </div>
          <div className={styles.steps}>
            <div className={`${styles.step} ${step === 'upload' ? styles.stepActive : ''} ${step !== 'upload' ? styles.stepDone : ''}`}>
              <span className={styles.stepNum}>1</span>Nahrání
            </div>
            <div className={styles.stepLine} />
            <div className={`${styles.step} ${step === 'pipeline' ? styles.stepActive : ''} ${step === 'results' ? styles.stepDone : ''}`}>
              <span className={styles.stepNum}>2</span>Analýza
            </div>
            <div className={styles.stepLine} />
            <div className={`${styles.step} ${step === 'results' ? styles.stepActive : ''}`}>
              <span className={styles.stepNum}>3</span>Výsledky
            </div>
            <div className={styles.stepLine} />
            <button
              className={styles.infoBtn}
              onClick={() => setShowAppInfo(true)}
              title="O aplikaci"
            >
              ℹ
            </button>
          </div>
        </div>
      </header>

      {showAppInfo && <AppInfo onClose={() => setShowAppInfo(false)} />}

      <div className={styles.container}>
        {/* Upload Step */}
        {step === 'upload' && (
          <section className={styles.uploadSection}>
            <div className={styles.uploadContainer}>
              <h2 className={styles.sectionTitle}>
                <span className={styles.titleGradient}>Nahrajte fotografie</span>
                <span className={styles.titleSub}>rodinného domu</span>
              </h2>

              {/* AI Model Selection */}
              {renderModelSelection()}

            {/* Photo Drop Zone */}
            <div
              className={`${styles.dropZone} ${dragActive ? styles.dropZoneActive : ''} ${files.length > 0 ? styles.dropZoneHasFiles : ''}`}
              onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
              onDragLeave={() => setDragActive(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".jpg,.jpeg,.png,.heic,.heif,.webp,.tiff,.bmp"
                onChange={(e) => e.target.files && handleFiles(e.target.files)}
                className={styles.fileInput}
              />
              <div className={styles.dropIcon}>
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                  <path d="M24 32V16M24 16L18 22M24 16L30 22" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M8 32V36C8 38.2 9.8 40 12 40H36C38.2 40 40 38.2 40 36V32" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <p className={styles.dropText}>
                {dragActive ? 'Přetáhněte sem' : 'Přetáhněte fotky nebo klikněte pro výběr'}
              </p>
              <p className={styles.dropHint}>JPG, PNG, HEIC, WebP • Jakákoliv velikost – automatická komprese na max 2 MB</p>
            </div>

            {/* File List */}
            {files.length > 0 && (
              <div className={styles.fileList}>
                <div className={styles.fileListHeader}>
                  <span>{files.length} {files.length === 1 ? 'soubor' : files.length < 5 ? 'soubory' : 'souborů'}</span>
                  <button className={styles.clearBtn} onClick={() => setFiles([])}>Vymazat vše</button>
                </div>
                <div className={styles.fileGrid}>
                  {files.map((file, i) => (
                    <div key={i} className={styles.fileItem}>
                      <div className={styles.fileThumb}>
                        <img src={URL.createObjectURL(file)} alt={file.name} />
                      </div>
                      <div className={styles.fileInfo}>
                        <span className={styles.fileName}>{file.name}</span>
                        <span className={styles.fileSize}>{(file.size / 1024 / 1024).toFixed(1)} MB</span>
                      </div>
                      <button className={styles.fileRemove} onClick={(e) => { e.stopPropagation(); removeFile(i); }}>
                        ✕
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* PDF / Manual Data Section */}
            <div className={styles.pdfSection}>
              <h3 className={styles.pdfSectionTitle}>
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                  <path d="M11 1H4C3.45 1 3 1.45 3 2V16C3 16.55 3.45 17 4 17H14C14.55 17 15 16.55 15 16V5L11 1Z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M11 1V5H15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Údaje o nemovitosti
              </h3>

              {/* Toggle: PDF vs Manual */}
              <div className={styles.dataSourceToggle}>
                <button
                  className={`${styles.toggleTab} ${dataSource === 'pdf' ? styles.toggleTabActive : ''}`}
                  onClick={() => setDataSource('pdf')}
                >
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M8.5 1H3.5C3.22 1 3 1.22 3 1.5V12.5C3 12.78 3.22 13 3.5 13H10.5C10.78 13 11 12.78 11 12.5V3.5L8.5 1Z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Z PDF formuláře
                </button>
                <button
                  className={`${styles.toggleTab} ${dataSource === 'manual' ? styles.toggleTabActive : ''}`}
                  onClick={() => setDataSource('manual')}
                >
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M10 1.5L12.5 4L4.5 12H2V9.5L10 1.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Zadat ručně
                </button>
              </div>

              {/* PDF Upload */}
              {dataSource === 'pdf' && (
                <>
                  {!pdfFile ? (
                    <div
                      className={`${styles.pdfDropZone} ${pdfDragActive ? styles.pdfDropZoneActive : ''}`}
                      onDragOver={(e) => { e.preventDefault(); setPdfDragActive(true); }}
                      onDragLeave={() => setPdfDragActive(false)}
                      onDrop={handlePdfDrop}
                      onClick={() => pdfInputRef.current?.click()}
                    >
                      <input
                        ref={pdfInputRef}
                        type="file"
                        accept=".pdf"
                        onChange={handlePdfSelect}
                        className={styles.fileInput}
                      />
                      <div className={styles.pdfDropIcon}>
                        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                          <path d="M14 2H6C5.45 2 5 2.45 5 3V21C5 21.55 5.45 22 6 22H18C18.55 22 19 21.55 19 21V7L14 2Z" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                          <path d="M14 2V7H19" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                          <path d="M9 15H15M12 12V18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </div>
                      <p className={styles.pdfDropText}>
                        {pdfDragActive ? 'Přetáhněte PDF sem' : 'Nahrajte PDF formulář ocenění'}
                      </p>
                      <p className={styles.pdfDropHint}>Formulář „Ocenění rodinného domu" • PDF formát</p>
                    </div>
                  ) : (
                    <div className={styles.pdfFileInfo}>
                      <div className={styles.pdfFileName}>
                        <div className={styles.pdfFileIcon}>
                          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                            <path d="M10 1H4C3.45 1 3 1.45 3 2V14C3 14.55 3.45 15 4 15H12C12.55 15 13 14.55 13 14V4L10 1Z" stroke="currentColor" strokeWidth="1.5" fill="none" />
                          </svg>
                        </div>
                        <span>{pdfFile.name}</span>
                        {pdfParsing && <span className={styles.spinner} style={{ width: '14px', height: '14px', borderWidth: '2px' }} />}
                        {pdfParsing && <span style={{ fontSize: '12px', color: 'var(--accent-blue)' }}>Extrahuji údaje...</span>}
                      </div>
                      <button className={styles.pdfRemoveBtn} onClick={() => { setPdfFile(null); setExtractedData(null); }}>✕</button>
                    </div>
                  )}
                </>
              )}

              {/* Manual Form */}
              {dataSource === 'manual' && (
                <div className={styles.manualForm}>
                  <div className={styles.manualFormGrid}>
                    <div className={styles.inputGroup}>
                      <label className={styles.inputLabel}>Stavba dokončena (rok)</label>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="např. 1980"
                        value={manualData.stavba_dokoncena || ''}
                        onChange={(e) => updateManualField('stavba_dokoncena', e.target.value)}
                      />
                    </div>
                    <div className={styles.inputGroup}>
                      <label className={styles.inputLabel}>Stav rodinného domu</label>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="např. dobře udržovaný"
                        value={manualData.stav_rodinneho_domu || ''}
                        onChange={(e) => updateManualField('stav_rodinneho_domu', e.target.value)}
                      />
                    </div>
                    <div className={styles.inputGroup}>
                      <label className={styles.inputLabel}>Počet podlaží</label>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="např. 2"
                        value={manualData.pocet_podlazi || ''}
                        onChange={(e) => updateManualField('pocet_podlazi', e.target.value)}
                      />
                    </div>
                    <div className={styles.inputGroup}>
                      <label className={styles.inputLabel}>Typ střechy</label>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="např. sedlová"
                        value={manualData.typ_strechy || ''}
                        onChange={(e) => updateManualField('typ_strechy', e.target.value)}
                      />
                    </div>
                    <div className={styles.inputGroup}>
                      <label className={styles.inputLabel}>Podsklepení</label>
                      <select
                        className="input-field"
                        value={manualData.podsklepeni || ''}
                        onChange={(e) => updateManualField('podsklepeni', e.target.value)}
                      >
                        <option value="">Vyberte...</option>
                        <option value="ANO">ANO</option>
                        <option value="NE">NE</option>
                      </select>
                    </div>
                    <div className={styles.inputGroup}>
                      <label className={styles.inputLabel}>Celková podlahová plocha</label>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="např. 175 m²"
                        value={manualData.celkova_podlahova_plocha || ''}
                        onChange={(e) => updateManualField('celkova_podlahova_plocha', e.target.value)}
                      />
                    </div>
                    <div className={`${styles.inputGroup} ${styles.manualFormFull}`}>
                      <label className={styles.inputLabel}>Typ vytápění</label>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="např. lokální - Plynový standardní kotel"
                        value={manualData.typ_vytapeni || ''}
                        onChange={(e) => updateManualField('typ_vytapeni', e.target.value)}
                      />
                    </div>
                    <div className={styles.inputGroup}>
                      <label className={styles.inputLabel}>Podkroví</label>
                      <select
                        className="input-field"
                        value={manualData.podkrovi || ''}
                        onChange={(e) => updateManualField('podkrovi', e.target.value)}
                      >
                        <option value="">Vyberte...</option>
                        <option value="ANO">ANO</option>
                        <option value="NE">NE</option>
                      </select>
                    </div>
                    <div className={styles.inputGroup}>
                      <label className={styles.inputLabel}>Obytné podkroví</label>
                      <select
                        className="input-field"
                        value={manualData.podkrovi_obytne || ''}
                        onChange={(e) => updateManualField('podkrovi_obytne', e.target.value)}
                      >
                        <option value="">Vyberte...</option>
                        <option value="ANO">ANO</option>
                        <option value="NE">NE</option>
                      </select>
                    </div>
                    <div className={styles.inputGroup}>
                      <label className={styles.inputLabel}>Využití podkroví (%)</label>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="např. 80 %"
                        value={manualData.vyuziti_podkrovi_procent || ''}
                        onChange={(e) => updateManualField('vyuziti_podkrovi_procent', e.target.value)}
                      />
                    </div>
                    <div className={`${styles.inputGroup} ${styles.manualFormFull}`}>
                      <label className={styles.inputLabel}>Adresa nemovitosti</label>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="např. Květná 1740, 68001 Boskovice"
                        value={manualData.adresa || ''}
                        onChange={(e) => updateManualField('adresa', e.target.value)}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Extracted Data Display — EDITABLE after PDF parsing */}
              {extractedData && (
                <div className={styles.extractedData}>
                  <div className={styles.extractedDataTitle}>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M11.5 4L5.5 10L2.5 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    Extrahované údaje z PDF
                    <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: '8px', fontWeight: 400 }}>— můžete upravit</span>
                  </div>
                  <div className={styles.extractedGrid}>
                    {(Object.keys(DATA_LABELS) as (keyof PropertyData)[]).map(key => {
                      // Use select for ANO/NE fields
                      const isYesNo = key === 'podsklepeni' || key === 'podkrovi' || key === 'podkrovi_obytne';
                      return (
                        <div key={key} className={styles.extractedItem}>
                          <span className={styles.extractedLabel}>{DATA_LABELS[key]}</span>
                          {isYesNo ? (
                            <select
                              className="input-field"
                              value={extractedData[key] || ''}
                              onChange={(e) => updateExtractedField(key, e.target.value)}
                              style={{ fontSize: '13px', padding: '6px 8px' }}
                            >
                              <option value="">nenalezeno</option>
                              <option value="ANO">ANO</option>
                              <option value="NE">NE</option>
                            </select>
                          ) : (
                            <input
                              type="text"
                              className="input-field"
                              value={extractedData[key] || ''}
                              placeholder="nenalezeno"
                              onChange={(e) => updateExtractedField(key, e.target.value)}
                              style={{ fontSize: '13px', padding: '6px 8px' }}
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* ── LV (List Vlastnictví) Upload ── */}
              <div className={styles.pdfSection}>
                <div className={styles.sectionLabel}>
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M2 3H12V12H2V3Z" stroke="currentColor" strokeWidth="1.5" />
                    <path d="M4 1V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    <path d="M10 1V4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    <path d="M4 7H10M4 10H7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
                  </svg>
                  List vlastnictví (PDF) — volitelné
                </div>

                {!lvFile ? (
                  <div
                    className={styles.pdfDropzone}
                    onClick={() => lvInputRef.current?.click()}
                  >
                    <input
                      ref={lvInputRef}
                      type="file"
                      accept=".pdf"
                      onChange={handleLvSelect}
                      style={{ display: 'none' }}
                    />
                    <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                      <path d="M14 4V18M8 12L14 18L20 12" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    <span>Klikněte nebo přetáhněte PDF s Listem vlastnictví</span>
                  </div>
                ) : (
                  <div className={styles.pdfFileDisplay}>
                    <div className={styles.pdfFileName}>
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                        <path d="M11.5 4L5.5 10L2.5 7" stroke="#10b981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      {lvFile.name}
                      <button
                        className={styles.pdfRemove}
                        onClick={() => { setLvFile(null); setLvData(null); setSelectedParcels([]); }}
                      >
                        ✕
                      </button>
                    </div>
                    {lvParsing && <span className={styles.spinner} />}
                  </div>
                )}

                {/* LV Parsed Data — Parcel Checkboxes */}
                {lvData && (
                  <div className={styles.extractedData} style={{ marginTop: '12px' }}>
                    <div className={styles.extractedDataTitle}>
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                        <path d="M11.5 4L5.5 10L2.5 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                      LV {lvData.lv_number} — k.ú. {lvData.kat_uzemi_nazev} ({lvData.kat_uzemi_kod})
                    </div>

                    {lvData.owners.length > 0 && (
                      <div style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '8px', padding: '0 4px' }}>
                        {lvData.owners.map((o, i) => (
                          <span key={i}>{o.name} ({o.share}){i < lvData.owners.length - 1 ? ', ' : ''}</span>
                        ))}
                      </div>
                    )}

                    <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '10px', padding: '0 4px' }}>
                      <strong>Funkční celek — vyberte parcely pro validaci:</strong>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                      {lvData.parcels.map(p => (
                        <label
                          key={p.parcel_number}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '10px',
                            padding: '8px 12px',
                            background: selectedParcels.includes(p.parcel_number)
                              ? '#E8F0FE'
                              : '#F8FAFC',
                            border: selectedParcels.includes(p.parcel_number)
                              ? '1px solid rgba(40,112,237,0.3)'
                              : '1px solid #E2E8F0',
                            borderRadius: '8px',
                            cursor: 'pointer',
                            fontSize: '13px',
                            transition: 'all 0.15s',
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={selectedParcels.includes(p.parcel_number)}
                            onChange={() => toggleParcel(p.parcel_number)}
                            style={{ accentColor: '#2870ED' }}
                          />
                          <span style={{ fontWeight: 600, minWidth: '65px' }}>p.č. {p.parcel_number}</span>
                          <span style={{ color: 'var(--text-muted)' }}>{p.area_m2} m²</span>
                          <span style={{ color: 'var(--text-secondary)' }}>{p.land_type}</span>
                          {p.land_use && <span style={{ color: 'var(--text-muted)', fontSize: '11px' }}>({p.land_use})</span>}
                        </label>
                      ))}
                    </div>

                    {lvData.buildings.length > 0 && (
                      <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--text-muted)', padding: '0 4px' }}>
                        <strong>Stavby:</strong> {lvData.buildings.map(b => b.part_of).join('; ')}
                      </div>
                    )}

                    {lvData.encumbrances.length > 0 && (
                      <div style={{ marginTop: '6px', fontSize: '12px', color: 'var(--accent-orange)', padding: '0 4px' }}>
                        ⚠ {lvData.encumbrances.length} záznam(ů) v sekci C (zástavní práva, věcná břemena, ...)
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            {error && <div className={styles.error}>{error}</div>}

            <button
              className="btn btn-primary"
              onClick={handleUpload}
              disabled={uploading || files.length === 0}
              style={{ width: '100%', justifyContent: 'center', padding: '16px', fontSize: '16px' }}
            >
              {uploading ? (
                <>
                  <span className={styles.spinner} />
                  Zpracovávám...
                </>
              ) : (
                <>
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                    <path d="M10 4V16M4 10H16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  Nahrát a zpracovat ({files.length} {files.length === 1 ? 'soubor' : 'souborů'})
                </>
              )}
            </button>
          </div>
        </section>
      )}

      {/* Pipeline Step */}
      {step === 'pipeline' && sessionId && (
        <PipelineCanvas
          sessionId={sessionId}
          agentStatuses={ws.agentStatuses}
          agentLogs={ws.agentLogs}
          isRunning={ws.isRunning}
          onStart={handleStartPipeline}
          onEdit={handleEdit}
          uploadData={uploadData}
        />
      )}

      {/* Results Step */}
      {step === 'results' && finalResult && (
        <ResultsDashboard
          result={finalResult}
          onEdit={handleEdit}
          onReset={() => {
            setStep('upload');
            setFiles([]);
            setSessionId(null);
            setUploadData(null);
            setPipelineResult(null);
            setPdfFile(null);
            setExtractedData(null);
            setManualData({ ...EMPTY_PROPERTY_DATA });
          }}
        />
        )}
      </div>
    </main>
  );
}
