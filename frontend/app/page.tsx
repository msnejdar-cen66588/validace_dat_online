'use client';
import { useState, useRef, useCallback } from 'react';
import styles from './page.module.css';
import { uploadFiles, startPipeline, parsePdf, parseLv, uploadBatch, startBatch, uploadBjFiles, startBjPipeline, parseBjPdf, getBjPipelineResults, type UploadResponse, type PipelineResult, type PropertyData, type LVData, type BatchCase, type ApartmentPropertyData, type BjUploadResponse, BJ_DATA_LABELS } from '@/lib/api';
import PipelineCanvas from '@/components/PipelineCanvas';
import ResultsDashboard from '@/components/ResultsDashboard';
import ProcessingLoader from '@/components/ProcessingLoader';
import AppInfo from '@/components/AppInfo';
import BatchDashboard from '@/components/BatchDashboard';
import ContractAnalyzer from '@/components/ContractAnalyzer';
import { useWebSocket } from '@/hooks/useWebSocket';
import { useBatchWebSocket } from '@/hooks/useBatchWebSocket';

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
  const [step, setStep] = useState<'upload' | 'processing' | 'pipeline' | 'results' | 'batch-select' | 'batch'>('upload');
  const [processingPhase, setProcessingPhase] = useState<'uploading' | 'compressing' | 'starting' | 'ready'>('uploading');
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
  const [selectedModel, setSelectedModel] = useState<string>("gemini-3-flash-preview");
  const [modelSelectorOpen, setModelSelectorOpen] = useState(false);
  const [pipelineStarted, setPipelineStarted] = useState(false);
  const lvInputRef = useRef<HTMLInputElement>(null);

  // Batch mode state
  const [mode, setMode] = useState<'single' | 'batch' | 'contract' | 'bj'>('single');
  const [batchId, setBatchId] = useState<string | null>(null);
  const [batchCases, setBatchCases] = useState<BatchCase[]>([]);
  const [batchUploading, setBatchUploading] = useState(false);
  const batchInputRef = useRef<HTMLInputElement>(null);
  const [selectedBatchCaseIds, setSelectedBatchCaseIds] = useState<Set<string>>(new Set());

  // BJ (apartment) state
  const [bjFiles, setBjFiles] = useState<File[]>([]);
  const [bjPdfFile, setBjPdfFile] = useState<File | null>(null);
  const [bjExtractedData, setBjExtractedData] = useState<ApartmentPropertyData | null>(null);
  const [bjFloorAreaDocs, setBjFloorAreaDocs] = useState<File[]>([]);
  const [bjLvFile, setBjLvFile] = useState<File | null>(null);
  const [bjDragActive, setBjDragActive] = useState(false);
  const [bjPdfParsing, setBjPdfParsing] = useState(false);
  const bjFileInputRef = useRef<HTMLInputElement>(null);
  const bjPdfInputRef = useRef<HTMLInputElement>(null);
  const bjFloorDocInputRef = useRef<HTMLInputElement>(null);
  const bjLvInputRef = useRef<HTMLInputElement>(null);

  const ws = useWebSocket(sessionId, mode === 'bj' ? 'bj' : 'rd');
  const batchWs = useBatchWebSocket(batchId);

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
    setProcessingPhase('uploading');
    setStep('processing');

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

      setProcessingPhase('compressing');

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

      setProcessingPhase('starting');

      // Brief pause to show the "starting agents" phase
      await new Promise(resolve => setTimeout(resolve, 1200));

      setProcessingPhase('ready');
      await new Promise(resolve => setTimeout(resolve, 800));

      setStep('pipeline');
    } catch (e: any) {
      setError(e.message || 'Chyba při nahrávání');
      setStep('upload');
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

  // Batch upload handler — only uploads files and shows selection screen
  const handleBatchUpload = async (fileList: FileList) => {
    const filesArr = Array.from(fileList);
    if (filesArr.length === 0) return;
    setBatchUploading(true);
    setError(null);
    try {
      const result = await uploadBatch(filesArr, selectedModel);
      setBatchId(result.batch_id);
      setBatchCases(result.cases);
      // Select all cases by default
      setSelectedBatchCaseIds(new Set(result.cases.map(c => c.case_id)));
      setStep('batch-select');
    } catch (e: any) {
      setError(e.message || 'Chyba při hromadném nahrávání');
      setStep('upload');
    } finally {
      setBatchUploading(false);
    }
  };

  // Start batch processing with selected cases
  const handleStartBatch = async () => {
    if (!batchId) return;
    setError(null);
    try {
      const selectedIds = Array.from(selectedBatchCaseIds);
      await startBatch(batchId, selectedIds.length < batchCases.length ? selectedIds : undefined);
      setStep('batch');
    } catch (e: any) {
      setError(e.message || 'Chyba při spouštění hromadné kontroly');
    }
  };

  // ── BJ Handlers ──
  const handleBjFiles = useCallback((newFiles: FileList | File[]) => {
    const arr = Array.from(newFiles);
    setBjFiles(prev => [...prev, ...arr]);
    setError(null);
  }, []);

  const handleBjDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setBjDragActive(false);
    handleBjFiles(e.dataTransfer.files);
  }, [handleBjFiles]);

  const processBjPdf = useCallback(async (file: File) => {
    setBjPdfFile(file);
    setBjPdfParsing(true);
    setError(null);
    try {
      const data = await parseBjPdf(file);
      if (data) {
        setBjExtractedData({ ...data });
      } else {
        setError('PDF bytu bylo zpracováno, ale nepodařilo se extrahovat údaje.');
      }
    } catch {
      setError('Chyba při zpracování PDF bytu.');
    } finally {
      setBjPdfParsing(false);
    }
  }, []);

  const handleBjUpload = async () => {
    if (bjFiles.length === 0) {
      setError('Nahrajte alespoň 4 fotografie bytu.');
      return;
    }

    setUploading(true);
    setError(null);
    setProcessingPhase('uploading');
    setStep('processing');

    try {
      const addressVal = bjExtractedData?.adresa || undefined;
      setProcessingPhase('compressing');

      const result = await uploadBjFiles(
        bjFiles,
        addressVal,
        bjPdfFile || undefined,
        bjExtractedData || undefined,
        bjLvFile || undefined,
        bjFloorAreaDocs.length > 0 ? bjFloorAreaDocs : undefined,
      );
      setUploadData(result as any);
      setSessionId(result.session_id);

      if (result.property_data) {
        setBjExtractedData(result.property_data);
      }

      setProcessingPhase('starting');
      await new Promise(resolve => setTimeout(resolve, 1200));
      setProcessingPhase('ready');
      await new Promise(resolve => setTimeout(resolve, 800));
      setStep('pipeline');
    } catch (e: any) {
      setError(e.message || 'Chyba při nahrávání');
      setStep('upload');
    } finally {
      setUploading(false);
    }
  };

  const handleStartBjPipeline = async () => {
    if (!sessionId) return;
    startBjPipeline(sessionId, selectedModel)
      .then(() => {
        // Robust fallback: poll for results in case WebSocket doesn't deliver
        let pollCount = 0;
        const maxPolls = 30; // 30 × 10s = 5 minutes max
        const pollInterval = setInterval(async () => {
          pollCount++;
          if (pollCount >= maxPolls || ws.pipelineResult || pipelineResult) {
            clearInterval(pollInterval);
            return;
          }
          try {
            const result = await getBjPipelineResults(sessionId);
            if (result && (result as any).completed && (result as any).semaphore) {
              console.log('[BJ] Got result via HTTP polling fallback');
              setPipelineResult(result);
              clearInterval(pollInterval);
            }
          } catch {
            // Not ready yet
          }
        }, 10000);
      })
      .catch((e: any) => {
        setError(e.message || 'Chyba při spuštění BJ pipeline');
      });
  };

  const MODEL_PROVIDERS = [
    {
      id: 'google',
      name: 'Google',
      icon: '🔵',
      models: [
        { id: 'gemini-3-flash-preview', name: 'Gemini 3.1 Flash', desc: 'Rychlý a cenově efektivní' },
        { id: 'gemini-3.1-pro-preview', name: 'Gemini 3.1 Pro', desc: 'Vlajkový model pro reasoning' },
      ],
    },
    {
      id: 'openai',
      name: 'OpenAI',
      icon: '🟢',
      models: [
        { id: 'gpt-5.4', name: 'GPT-5.4', desc: 'Nejnovější vlajkový model OpenAI' },
        { id: 'gpt-5.4-mini', name: 'GPT-5.4 mini', desc: 'Rychlý a cenově efektivní' },
        { id: 'gpt-4.1', name: 'GPT-4.1', desc: 'Vyvážený výkon a cena' },
        { id: 'o4-mini', name: 'o4-mini', desc: 'Reasoning model pro analytiku' },
      ],
    },
  ];

  const getModelDisplayName = (modelId: string) => {
    for (const provider of MODEL_PROVIDERS) {
      const model = provider.models.find(m => m.id === modelId);
      if (model) return `${provider.icon} ${model.name}`;
    }
    return modelId;
  };

  const renderModelSelection = () => (
    <div className={styles.modelSwitcher}>
      {/* Compact collapsed bar */}
      <button
        className={styles.modelSwitcherToggle}
        onClick={() => setModelSelectorOpen(!modelSelectorOpen)}
      >
        <div className={styles.modelSwitcherToggleLeft}>
          <span className={styles.modelSwitcherBadge}>AI</span>
          <span className={styles.modelSwitcherToggleValue}>Vyber LLM</span>
        </div>
        <span className={`${styles.modelSwitcherChevron} ${modelSelectorOpen ? styles.modelSwitcherChevronOpen : ''}`}>
          ▾
        </span>
      </button>

      {/* Expandable model list */}
      {modelSelectorOpen && (
        <div className={styles.modelSelectorPanel}>
          {MODEL_PROVIDERS.map(provider => (
            <div key={provider.id} className={styles.modelProviderGroup}>
              <div className={styles.modelProviderHeader}>
                <span className={styles.modelProviderIcon}>{provider.icon}</span>
                {provider.name}
              </div>
              <div className={styles.modelProviderModels}>
                {provider.models.map(model => (
                  <button
                    key={model.id}
                    onClick={() => { setSelectedModel(model.id); setModelSelectorOpen(false); }}
                    className={`${styles.modelOption} ${selectedModel === model.id ? styles.modelOptionActive : ''}`}
                  >
                    <span className={styles.modelName}>{model.name}</span>
                    <span className={styles.modelDesc}>{model.desc}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
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
              <p className={styles.logoSubtitle}>
                {mode === 'bj' ? 'Online ocenění bytových jednotek' : 'Online ocenění rodinných domů'}
              </p>
            </div>
          </div>
          <div className={styles.steps}>
            <div className={`${styles.step} ${step === 'upload' ? styles.stepActive : ''} ${step !== 'upload' ? styles.stepDone : ''}`}>
              <span className={styles.stepNum}>1</span>Nahrání
            </div>
            <div className={styles.stepLine} />
            <div
              className={`${styles.step} ${(step === 'processing' || step === 'pipeline' || step === 'batch-select' || step === 'batch') ? styles.stepActive : ''} ${step === 'results' ? styles.stepDone : ''}`}>
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
              {mode === 'contract' ? (
                <h2 className={styles.sectionTitle}>
                  <span className={styles.titleGradient}>Analýza smluv</span>
                  <span className={styles.titleSub}>AI agent pro extrakci dat</span>
                </h2>
              ) : mode === 'bj' ? (
                <h2 className={styles.sectionTitle}>
                  <span className={styles.titleGradient}>Nahrajte podklady</span>
                  <span className={styles.titleSub}>bytové jednotky</span>
                </h2>
              ) : (
                <h2 className={styles.sectionTitle}>
                  <span className={styles.titleGradient}>Nahrajte fotografie</span>
                  <span className={styles.titleSub}>rodinných domů</span>
                </h2>
              )}

              {/* Mode Toggle */}
              <div className={styles.modeToggle}>
                <button className={`${styles.modeBtn} ${mode === 'single' ? styles.modeBtnActive : ''}`} onClick={() => setMode('single')}>
                  📋 Jednotlivé ocenění
                </button>
                <button className={`${styles.modeBtn} ${mode === 'batch' ? styles.modeBtnActive : ''}`} onClick={() => setMode('batch')}>
                  📁 Hromadná kontrola
                </button>
                <button className={`${styles.modeBtn} ${mode === 'bj' ? styles.modeBtnActive : ''}`} onClick={() => setMode('bj')}>
                  🏢 Bytová jednotka
                </button>
                <button className={`${styles.modeBtn} ${mode === 'contract' ? styles.modeBtnActive : ''}`} onClick={() => setMode('contract')}>
                  📄 Analýza smluv
                </button>
              </div>

              {/* AI Model Selection */}
              {renderModelSelection()}

            {/* Single mode content */}
            {mode === 'single' && (<div>
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
          </div>)}

          {/* Batch Upload Mode */}
          {mode === 'batch' && (
            <div className={styles.batchUploadZone}>
              {batchUploading ? (
                <div className={styles.folderDropZone} style={{ pointerEvents: 'none', opacity: 0.7 }}>
                  <div style={{
                    width: '36px',
                    height: '36px',
                    border: '3px solid rgba(40, 112, 237, 0.15)',
                    borderTopColor: '#2870ED',
                    borderRadius: '50%',
                    animation: 'spin 0.8s linear infinite',
                    margin: '0 auto 12px',
                  }} />
                  <p className={styles.folderDropText}>Nahrávám a třídím soubory...</p>
                  <p className={styles.folderDropHint}>Toto může chvíli trvat u větších složek</p>
                  <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
                </div>
              ) : (
                <div className={styles.folderDropZone} onClick={() => batchInputRef.current?.click()}>
                  <input ref={batchInputRef} type="file" {...{webkitdirectory: 'true', directory: 'true'} as any} multiple onChange={(e) => e.target.files && handleBatchUpload(e.target.files)} className={styles.fileInput} />
                  <div className={styles.folderDropIcon}>📁</div>
                  <p className={styles.folderDropText}>Vyberte složku s podklady</p>
                  <p className={styles.folderDropHint}>Složka s podsložkami (1, 2, 3...) — každá obsahuje fotky + PDF formulář + LV</p>
                </div>
              )}
              {error && <div className={styles.error}>{error}</div>}
            </div>
          )}

          {/* BJ (Bytová jednotka) Mode */}
          {mode === 'bj' && (<div>
            {/* BJ Photo Drop Zone */}
            <div
              className={`${styles.dropZone} ${bjDragActive ? styles.dropZoneActive : ''} ${bjFiles.length > 0 ? styles.dropZoneHasFiles : ''}`}
              onDragOver={(e) => { e.preventDefault(); setBjDragActive(true); }}
              onDragLeave={() => setBjDragActive(false)}
              onDrop={handleBjDrop}
              onClick={() => bjFileInputRef.current?.click()}
            >
              <input
                ref={bjFileInputRef}
                type="file"
                multiple
                accept=".jpg,.jpeg,.png,.heic,.heif,.webp,.tiff,.bmp"
                onChange={(e) => e.target.files && handleBjFiles(e.target.files)}
                className={styles.fileInput}
              />
              <div className={styles.dropIcon}>
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
                  <path d="M24 32V16M24 16L18 22M24 16L30 22" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                  <path d="M8 32V36C8 38.2 9.8 40 12 40H36C38.2 40 40 38.2 40 36V32" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>
              <p className={styles.dropText}>
                {bjDragActive ? 'Přetáhněte sem' : 'Přetáhněte fotky bytu nebo klikněte pro výběr'}
              </p>
              <p className={styles.dropHint}>Min. 4 fotky (max. stáří 1 měsíc): exteriér domu, vstup, interiér všech místností</p>
            </div>

            {/* BJ File list */}
            {bjFiles.length > 0 && (
              <div className={styles.fileList}>
                <div className={styles.fileListHeader}>
                  <span>📸 {bjFiles.length} {bjFiles.length === 1 ? 'fotografie' : 'fotografií'}</span>
                  <button className={styles.clearBtn} onClick={() => setBjFiles([])}>
                    Vymazat vše
                  </button>
                </div>
                <div className={styles.fileGrid}>
                  {bjFiles.map((f, i) => (
                    <div key={i} className={styles.fileItem}>
                      <div className={styles.fileThumb}>
                        <img src={URL.createObjectURL(f)} alt={f.name} />
                      </div>
                      <div className={styles.fileInfo}>
                        <span className={styles.fileName}>{f.name}</span>
                        <span className={styles.fileSize}>{(f.size / 1024 / 1024).toFixed(1)} MB</span>
                      </div>
                      <button className={styles.fileRemove} onClick={(e) => { e.stopPropagation(); setBjFiles(prev => prev.filter((_, idx) => idx !== i)); }}>✕</button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* BJ PDF Upload */}
            <div className={styles.pdfSection}>
              <div className={styles.sectionLabel}>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <path d="M3 1H8.5L11 3.5V13H3V1Z" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M8 1V4H11" stroke="currentColor" strokeWidth="1.5" />
                </svg>
                PDF formulář ocenění bytu
              </div>
              {!bjPdfFile ? (
                <div
                  className={styles.pdfDropzone}
                  onClick={() => bjPdfInputRef.current?.click()}
                >
                  <input
                    ref={bjPdfInputRef}
                    type="file"
                    accept=".pdf"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) processBjPdf(file);
                    }}
                    style={{ display: 'none' }}
                  />
                  <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                    <path d="M14 4V18M8 12L14 18L20 12" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" />
                  </svg>
                  <span>Klikněte nebo přetáhněte PDF „Zadané údaje pro on-line ocenění bytu"</span>
                </div>
              ) : (
                <div className={styles.pdfFileDisplay}>
                  <div className={styles.pdfFileName}>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                      <path d="M11.5 4L5.5 10L2.5 7" stroke="#10b981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                    {bjPdfFile.name}
                    <button
                      className={styles.pdfRemove}
                      onClick={() => { setBjPdfFile(null); setBjExtractedData(null); }}
                    >
                      ✕
                    </button>
                  </div>
                  {bjPdfParsing && <span className={styles.spinner} />}
                </div>
              )}
            </div>

            {/* BJ Extracted Data */}
            {bjExtractedData && (
              <div className={styles.extractedData}>
                <div className={styles.extractedDataTitle}>
                  <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                    <path d="M11.5 4L5.5 10L2.5 7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  Extrahované údaje z PDF – bytová jednotka
                </div>
                <div className={styles.extractedGrid}>
                  {(Object.keys(BJ_DATA_LABELS) as (keyof typeof BJ_DATA_LABELS)[]).map((key) => {
                    const label = BJ_DATA_LABELS[key];
                    const value = (bjExtractedData as any)[key];
                    return (
                      <div key={key} className={styles.extractedField}>
                        <label className={styles.extractedLabel}>{label}</label>
                        <input
                          type="text"
                          className="input-field"
                          value={value || ''}
                          placeholder="nenalezeno"
                          onChange={(e) => setBjExtractedData(prev => prev ? { ...prev, [key]: e.target.value || null } : prev)}
                          style={{ fontSize: '13px', padding: '6px 8px' }}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Floor Area Document Upload – multiple files */}
            <div className={styles.pdfSection} onClick={(e) => e.stopPropagation()}>
              <div className={styles.sectionLabel}>
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                  <rect x="2" y="2" width="10" height="10" rx="1" stroke="currentColor" strokeWidth="1.5" />
                  <path d="M5 5H9M5 7H9M5 9H7" stroke="currentColor" strokeWidth="1" strokeLinecap="round" />
                </svg>
                Dokumenty potvrzující podlahovou plochu
              </div>

              <input
                ref={bjFloorDocInputRef}
                type="file"
                multiple
                accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.heif,.tiff,.bmp,.doc,.docx"
                onChange={(e) => {
                  const fileList = e.target.files;
                  console.log('[FloorAreaDocs] onChange fired, files:', fileList?.length);
                  if (fileList && fileList.length > 0) {
                    const newFiles = Array.from(fileList);
                    console.log('[FloorAreaDocs] Adding files:', newFiles.map(f => f.name));
                    setBjFloorAreaDocs(prev => {
                      const updated = [...prev, ...newFiles];
                      console.log('[FloorAreaDocs] Updated count:', updated.length);
                      return updated;
                    });
                  }
                  e.target.value = '';
                }}
                style={{ display: 'none' }}
              />
              <div
                className={styles.pdfDropzone}
                onClick={(e) => {
                  e.stopPropagation();
                  e.preventDefault();
                  console.log('[FloorAreaDocs] Dropzone clicked, triggering file input');
                  bjFloorDocInputRef.current?.click();
                }}
                onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const droppedFiles = e.dataTransfer.files;
                  if (droppedFiles && droppedFiles.length > 0) {
                    console.log('[FloorAreaDocs] Dropped files:', droppedFiles.length);
                    setBjFloorAreaDocs(prev => [...prev, ...Array.from(droppedFiles)]);
                  }
                }}
              >
                <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
                  <path d="M14 4V18M8 12L14 18L20 12" stroke="var(--text-muted)" strokeWidth="2" strokeLinecap="round" />
                </svg>
                <span>Klikněte nebo přetáhněte dokumenty (PDF/obrázek)</span>
              </div>

              {bjFloorAreaDocs.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginTop: '8px' }}>
                  <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--accent-green)', marginBottom: '2px' }}>
                    📎 {bjFloorAreaDocs.length} {bjFloorAreaDocs.length === 1 ? 'dokument nahrán' : 'dokumenty nahrány'}
                  </div>
                  {bjFloorAreaDocs.map((doc, i) => (
                    <div key={`floor-doc-${i}-${doc.name}`} className={styles.pdfFileDisplay}>
                      <div className={styles.pdfFileName}>
                        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
                          <path d="M11.5 4L5.5 10L2.5 7" stroke="#10b981" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                        {doc.name}
                        <span style={{ color: 'var(--text-muted)', fontSize: '11px', marginLeft: '4px' }}>({(doc.size / 1024 / 1024).toFixed(1)} MB)</span>
                        <button
                          className={styles.pdfRemove}
                          onClick={(e) => {
                            e.stopPropagation();
                            e.preventDefault();
                            setBjFloorAreaDocs(prev => prev.filter((_, idx) => idx !== i));
                          }}
                        >✕</button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '6px', padding: '0 4px', lineHeight: '1.5' }}>
                Akceptovatelné podklady: nabývací titul (kupní smlouva), prohlášení vlastníka, vyúčtování služeb, evidenční list SVJ/BD, odhad nemovitosti
              </div>
            </div>

            {/* BJ LV Upload */}
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
              {!bjLvFile ? (
                <div className={styles.pdfDropzone} onClick={() => bjLvInputRef.current?.click()}>
                  <input
                    ref={bjLvInputRef}
                    type="file"
                    accept=".pdf"
                    onChange={(e) => {
                      const file = e.target.files?.[0];
                      if (file) setBjLvFile(file);
                    }}
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
                    {bjLvFile.name}
                    <button className={styles.pdfRemove} onClick={() => setBjLvFile(null)}>✕</button>
                  </div>
                </div>
              )}
            </div>

            {error && <div className={styles.error}>{error}</div>}

            <button
              className="btn btn-primary"
              onClick={handleBjUpload}
              disabled={uploading || bjFiles.length === 0}
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
                  Nahrát a zpracovat ({bjFiles.length} {bjFiles.length === 1 ? 'soubor' : 'souborů'})
                </>
              )}
            </button>
          </div>)}

          {/* Contract Analysis Mode */}
          {mode === 'contract' && (
            <ContractAnalyzer selectedModel={selectedModel} />
          )}
          </div>
        </section>
      )}

      {/* Processing Loader */}
      {step === 'processing' && (
        <ProcessingLoader phase={processingPhase} />
      )}

      {/* Pipeline Step */}
      {step === 'pipeline' && sessionId && (
        <PipelineCanvas
          sessionId={sessionId}
          agentStatuses={ws.agentStatuses}
          agentLogs={ws.agentLogs}
          isRunning={ws.isRunning}
          onStart={mode === 'bj' ? handleStartBjPipeline : handleStartPipeline}
          onEdit={handleEdit}
          uploadData={uploadData}
        />
      )}

      {/* Results Step */}
      {step === 'results' && finalResult && (
        <ResultsDashboard
          result={finalResult}
          onEdit={handleEdit}
          valuationSteps={ws.valuationSteps}
          valuationResult={ws.valuationResult}
          isValuating={ws.isValuating}
          onReset={() => {
            setStep('upload');
            setFiles([]);
            setSessionId(null);
            setUploadData(null);
            setPipelineResult(null);
            setPdfFile(null);
            setExtractedData(null);
            setManualData({ ...EMPTY_PROPERTY_DATA });
            // Reset BJ state
            setBjFiles([]);
            setBjPdfFile(null);
            setBjExtractedData(null);
            setBjFloorAreaDocs([]);
            setBjLvFile(null);
          }}
        />
        )}

      {/* Batch Case Selection */}
      {step === 'batch-select' && batchId && (
        <section style={{ maxWidth: '900px', margin: '0 auto', padding: '24px' }}>
          <div style={{
            background: 'var(--surface-card)',
            borderRadius: '16px',
            border: '1px solid var(--border-subtle)',
            padding: '28px 32px',
          }}>
            <h2 style={{
              fontSize: '20px',
              fontWeight: 700,
              color: 'var(--text-primary)',
              marginBottom: '4px',
              display: 'flex',
              alignItems: 'center',
              gap: '10px',
            }}>
              <span style={{ fontSize: '22px' }}>📁</span>
              Hromadná kontrola — výběr případů
            </h2>
            <p style={{
              fontSize: '13px',
              color: 'var(--text-muted)',
              marginBottom: '20px',
            }}>
              Nalezeno {batchCases.length} {batchCases.length === 1 ? 'případ' : batchCases.length < 5 ? 'případy' : 'případů'}
              &nbsp;• Vyberte, které chcete analyzovat
            </p>

            {/* Select all / deselect all */}
            <div style={{
              display: 'flex',
              gap: '12px',
              marginBottom: '16px',
            }}>
              <button
                onClick={() => setSelectedBatchCaseIds(new Set(batchCases.map(c => c.case_id)))}
                style={{
                  padding: '6px 14px',
                  fontSize: '12px',
                  fontWeight: 600,
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '8px',
                  background: selectedBatchCaseIds.size === batchCases.length
                    ? 'rgba(40,112,237,0.08)'
                    : 'var(--surface-card)',
                  color: selectedBatchCaseIds.size === batchCases.length
                    ? '#2870ED'
                    : 'var(--text-secondary)',
                  cursor: 'pointer',
                }}
              >
                ✓ Vybrat vše
              </button>
              <button
                onClick={() => setSelectedBatchCaseIds(new Set())}
                style={{
                  padding: '6px 14px',
                  fontSize: '12px',
                  fontWeight: 600,
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '8px',
                  background: 'var(--surface-card)',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                }}
              >
                Odznačit vše
              </button>
            </div>

            {/* Case list with checkboxes */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '24px' }}>
              {batchCases.map((c) => {
                const isSelected = selectedBatchCaseIds.has(c.case_id);
                return (
                  <label
                    key={c.case_id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '14px',
                      padding: '12px 16px',
                      background: isSelected ? 'rgba(40,112,237,0.04)' : '#F8FAFC',
                      border: isSelected
                        ? '1px solid rgba(40,112,237,0.3)'
                        : '1px solid var(--border-subtle, #e2e8f0)',
                      borderRadius: '10px',
                      cursor: 'pointer',
                      transition: 'all 0.15s',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => {
                        setSelectedBatchCaseIds(prev => {
                          const next = new Set(prev);
                          if (next.has(c.case_id)) next.delete(c.case_id);
                          else next.add(c.case_id);
                          return next;
                        });
                      }}
                      style={{ accentColor: '#2870ED', width: '16px', height: '16px' }}
                    />
                    <span style={{
                      fontWeight: 700,
                      fontSize: '14px',
                      color: 'var(--text-primary)',
                      minWidth: '80px',
                    }}>
                      REV {c.rev_id}
                    </span>
                    {c.file_counts && (
                      <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                        📷 {c.file_counts.images} fotek • 📄 {c.file_counts.pdfs} PDF
                      </span>
                    )}
                  </label>
                );
              })}
            </div>

            {error && <div className={styles.error}>{error}</div>}

            <div style={{ display: 'flex', gap: '12px' }}>
              <button
                onClick={() => {
                  setStep('upload');
                  setBatchId(null);
                  setBatchCases([]);
                  setError(null);
                }}
                style={{
                  flex: '0 0 auto',
                  padding: '14px 24px',
                  fontSize: '14px',
                  fontWeight: 600,
                  border: '1px solid var(--border-subtle)',
                  borderRadius: '10px',
                  background: 'var(--surface-card)',
                  color: 'var(--text-secondary)',
                  cursor: 'pointer',
                }}
              >
                ← Zpět
              </button>
              <button
                className="btn btn-primary"
                onClick={handleStartBatch}
                disabled={selectedBatchCaseIds.size === 0}
                style={{
                  flex: 1,
                  justifyContent: 'center',
                  padding: '14px',
                  fontSize: '15px',
                }}
              >
                <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
                  <path d="M6 3L14 9L6 15V3Z" fill="currentColor" />
                </svg>
                Spustit hromadnou kontrolu ({selectedBatchCaseIds.size} {selectedBatchCaseIds.size === 1 ? 'případ' : selectedBatchCaseIds.size < 5 ? 'případy' : 'případů'})
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Batch Dashboard */}
      {step === 'batch' && batchId && (
        <BatchDashboard
          batchId={batchId}
          cases={batchWs.cases.length > 0 ? batchWs.cases : batchCases}
          currentIndex={batchWs.currentIndex}
          estimatedRemaining={batchWs.estimatedRemaining}
          batchComplete={batchWs.batchComplete}
          batchTotalTime={batchWs.batchTotalTime}
          semaphoreSummary={batchWs.semaphoreSummary}
          isRunning={batchWs.isRunning}
          onReset={() => {
            setStep('upload');
            setBatchId(null);
            setBatchCases([]);
            setError(null);
          }}
        />
      )}
      </div>
    </main>
  );
}
