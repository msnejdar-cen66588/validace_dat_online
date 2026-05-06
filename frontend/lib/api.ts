/**
 * API client for the backend FastAPI service.
 */

export const API_BASE = process.env.NEXT_PUBLIC_API_URL
    || (typeof window !== 'undefined'
        ? `http://${window.location.hostname}:8000`
        : 'http://localhost:8000');

export async function parsePdf(pdfFile: File): Promise<PropertyData | null> {
    const formData = new FormData();
    formData.append('pdf_file', pdfFile);
    const res = await fetch(`${API_BASE}/api/parse-pdf`, {
        method: 'POST',
        body: formData,
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.property_data || null;
}

export async function parseLv(lvFile: File): Promise<LVData | null> {
    const formData = new FormData();
    formData.append('lv_file', lvFile);
    const res = await fetch(`${API_BASE}/api/parse-lv`, {
        method: 'POST',
        body: formData,
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.lv_data || null;
}

export interface ImageMetadata {
    gps_latitude: number | null;
    gps_longitude: number | null;
    capture_date: string | null;
    device_model: string | null;
    original_format: string | null;
    original_size_bytes: number;
}

export interface ProcessedImage {
    id: string;
    original_filename: string;
    processed_path: string;
    width: number;
    height: number;
    size_bytes: number;
    metadata: ImageMetadata;
}

export interface PropertyData {
    stavba_dokoncena: string | null;
    stav_rodinneho_domu: string | null;
    pocet_podlazi: string | null;
    typ_strechy: string | null;
    podsklepeni: string | null;
    celkova_podlahova_plocha: string | null;
    plocha_pozemku: string | null;
    typ_vytapeni: string | null;
    adresa: string | null;
    podkrovi: string | null;
    podkrovi_obytne: string | null;
    vyuziti_podkrovi_procent: string | null;
}

export interface LVParcel {
    parcel_number: string;
    area_m2: number;
    land_type: string;
    land_use: string;
    protection: string;
    selected: boolean;
}

export interface LVEncumbrance {
    type: string;
    description: string;
    beneficiary: string;
    parcels: string[];
    amount: string;
    document: string;
}

export interface LVData {
    kat_uzemi_kod: string;
    kat_uzemi_nazev: string;
    lv_number: string;
    okres: string;
    obec: string;
    owners: { name: string; address: string; identifier: string; share: string }[];
    parcels: LVParcel[];
    buildings: { part_of: string; on_parcel: string }[];
    rights_in_favor: string;
    encumbrances: LVEncumbrance[];
    notes: string;
    seals: string;
}

export interface UploadResponse {
    session_id: string;
    files_uploaded: number;
    files_processed: number;
    images: ProcessedImage[];
    property_data: PropertyData | null;
    lv_data: LVData | null;
}

export interface AgentLog {
    timestamp: number;
    message: string;
    level: string;
}

export interface AgentResultData {
    status: string;
    category: number | null;
    score: number | null;
    summary: string;
    details: Record<string, any>;
    warnings: string[];
    errors: string[];
}

export interface AgentState {
    name: string;
    description: string;
    system_prompt: string;
    status: string;
    logs: AgentLog[];
    result: AgentResultData | null;
    elapsed_time: number;
}

export interface PipelineResult {
    pipeline_id: string;
    session_id: string;
    total_time: number;
    semaphore: string;
    semaphore_color: string;
    final_category: number | null;
    agents: Record<string, AgentState>;
    property_data?: PropertyData;
    property_address?: string;
    pipeline_type?: 'rd' | 'bj';
}

export async function uploadFiles(
    files: File[],
    yearBuilt?: number,
    yearReconstructed?: number,
    propertyAddress?: string,
    pdfFile?: File,
    propertyData?: PropertyData,
    lvPdfFile?: File,
    selectedParcels?: string[],
): Promise<UploadResponse> {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    if (yearBuilt) formData.append('year_built', yearBuilt.toString());
    if (yearReconstructed) formData.append('year_reconstructed', yearReconstructed.toString());
    if (propertyAddress) formData.append('property_address', propertyAddress);
    if (pdfFile) formData.append('pdf_file', pdfFile);
    if (propertyData) formData.append('property_data_json', JSON.stringify(propertyData));
    if (lvPdfFile) formData.append('lv_pdf_file', lvPdfFile);
    if (selectedParcels) formData.append('selected_parcels_json', JSON.stringify(selectedParcels));

    const res = await fetch(`${API_BASE}/api/upload`, {
        method: 'POST',
        body: formData,
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(err.detail || 'Upload failed');
    }

    return res.json();
}

export async function startPipeline(sessionId: string, model: string = "gemini"): Promise<PipelineResult> {
    const res = await fetch(`${API_BASE}/api/pipeline/start/${sessionId}?model=${model}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Pipeline start failed' }));
        throw new Error(err.detail || 'Pipeline start failed');
    }

    return res.json();
}

export async function getPipelineResults(sessionId: string): Promise<PipelineResult> {
    const res = await fetch(`${API_BASE}/api/pipeline/results/${sessionId}`);
    if (!res.ok) throw new Error('Results not found');
    return res.json();
}

export async function updateAgentPrompt(
    sessionId: string,
    agentName: string,
    systemPrompt: string,
): Promise<void> {
    await fetch(`${API_BASE}/api/agent/prompt/${sessionId}/${agentName}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ system_prompt: systemPrompt }),
    });
}

export async function generateValuation(sessionId: string, model: string = "gemini"): Promise<PipelineResult> {
    const res = await fetch(`${API_BASE}/api/pipeline/valuation/${sessionId}?model=${model}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Valuation generation failed' }));
        throw new Error(err.detail || 'Valuation generation failed');
    }

    return res.json();
}

export function getWebSocketUrl(sessionId: string): string {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (apiUrl) {
        const wsUrl = apiUrl.replace(/^http/, 'ws');
        return `${wsUrl}/ws/pipeline/${sessionId}`;
    }
    const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
    return `ws://${host}:8000/ws/pipeline/${sessionId}`;
}


// ── Batch Processing ─────────────────────────────────────────────────────

export interface BatchCase {
    case_id: string;
    rev_id: string;
    session_id: string;
    status: string;
    address: string;
    semaphore?: string;
    semaphore_color?: string;
    total_time?: number;
    file_counts?: { images: number; pdfs: number };
}

export interface BatchUploadResponse {
    batch_id: string;
    total_cases: number;
    cases: BatchCase[];
}

export interface BatchStatus {
    batch_id: string;
    status: string;
    model: string;
    total_cases: number;
    completed_cases: number;
    current_case_index: number;
    estimated_remaining: number | null;
    total_time: number | null;
    cases: BatchCase[];
}

export async function uploadBatch(files: File[], model: string): Promise<BatchUploadResponse> {
    const formData = new FormData();
    files.forEach(file => {
        formData.append('files', file);
    });
    formData.append('model', model);

    const res = await fetch(`${API_BASE}/api/batch/upload`, {
        method: 'POST',
        body: formData,
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Batch upload failed' }));
        throw new Error(err.detail || 'Batch upload failed');
    }

    return res.json();
}

export async function startBatch(batchId: string, selectedCaseIds?: string[]): Promise<void> {
    const res = await fetch(`${API_BASE}/api/batch/start/${batchId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(selectedCaseIds ? { selected_case_ids: selectedCaseIds } : {}),
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Batch start failed' }));
        throw new Error(err.detail || 'Batch start failed');
    }
}

export async function getBatchStatus(batchId: string): Promise<BatchStatus> {
    const res = await fetch(`${API_BASE}/api/batch/status/${batchId}`);
    if (!res.ok) throw new Error('Batch not found');
    return res.json();
}

export async function getBatchCaseResult(batchId: string, caseId: string): Promise<PipelineResult> {
    const res = await fetch(`${API_BASE}/api/batch/case-result/${batchId}/${caseId}`);
    if (!res.ok) throw new Error('Case result not available');
    return res.json();
}

export function getBatchWebSocketUrl(batchId: string): string {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (apiUrl) {
        const wsUrl = apiUrl.replace(/^http/, 'ws');
        return `${wsUrl}/ws/batch/${batchId}`;
    }
    const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
    return `ws://${host}:8000/ws/batch/${batchId}`;
}


// ── Contract Analysis ────────────────────────────────────────────────────

export interface ContractPreset {
    id: string;
    label: string;
    query: string;
}

export interface ContractClassification {
    contract_type: string;
    confidence: number;
    title: string;
    summary: string;
    parties: string[];
    icon: string;
    label: string;
    presets: ContractPreset[];
}

export interface ContractPage {
    page_number: number;
    full_text: string;
    blocks: {
        text: string;
        page: number;
        x: number;
        y: number;
        width: number;
        height: number;
        confidence: number;
    }[];
    has_image: boolean;
    width: number;
    height: number;
}

export interface ContractUploadResponse {
    session_id: string;
    filename: string;
    total_pages: number;
    full_text: string;
    pages: ContractPage[];
    classification: ContractClassification;
    has_pdf: boolean;
    page_image_urls: string[];
}

export interface ContractQueryResult {
    answer: string;
    found: boolean;
    citations: {
        text: string;
        page: number;
        context: string;
    }[];
    highlights: string[];
    highlight_positions: {
        page: number;
        text: string;
        y_ratio: number;
        context: string;
    }[];
}

export async function uploadContract(files: File[], model: string = "gpt-5.4-mini"): Promise<ContractUploadResponse> {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    formData.append('model', model);

    const res = await fetch(`${API_BASE}/api/contract/upload`, {
        method: 'POST',
        body: formData,
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(err.detail || 'Nahrávání smlouvy selhalo');
    }

    return res.json();
}

export async function queryContract(sessionId: string, query: string, model?: string): Promise<ContractQueryResult> {
    const res = await fetch(`${API_BASE}/api/contract/query/${sessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, model }),
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Query failed' }));
        throw new Error(err.detail || 'Dotaz selhal');
    }

    return res.json();
}

export function getContractPdfUrl(sessionId: string): string {
    return `${API_BASE}/api/contract/pdf/${sessionId}`;
}

export function getContractPageImageUrl(sessionId: string, pageNum: number): string {
    return `${API_BASE}/api/contract/page-image/${sessionId}/${pageNum}`;
}

// ─── Extract All ───
export interface ExtractAllField {
    id: string;
    label: string;
    value: string;
    page: number;
    found: boolean;
    confidence: number;
    citation: string;
    y_ratio?: number;
}

export interface RedFlag {
    severity: 'low' | 'medium' | 'high' | 'critical';
    title: string;
    description: string;
    page?: number;
}

export interface ExtractAllResult {
    fields: ExtractAllField[];
    summary: string;
    red_flags: RedFlag[];
}

export async function extractAllContractData(sessionId: string, model?: string): Promise<ExtractAllResult> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90000); // 90s timeout
    
    try {
        const res = await fetch(`${API_BASE}/api/contract/extract-all/${sessionId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ model }),
            signal: controller.signal,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: 'Extract failed' }));
            throw new Error(err.detail || 'Extrakce selhala');
        }

        return res.json();
    } catch (e: any) {
        if (e.name === 'AbortError') {
            throw new Error('Extrakce trvala příliš dlouho (>90s). Zkuste menší dokument.');
        }
        throw e;
    } finally {
        clearTimeout(timeout);
    }
}

// ─── Compare Contracts ───
export interface ContractDifference {
    category: string;
    title: string;
    severity: 'low' | 'medium' | 'high' | 'critical';
    text_a: string;
    text_b: string | null;
    description: string;
}

export interface CompareResult {
    summary: string;
    are_same_type: boolean;
    type_a: string;
    type_b: string;
    differences: ContractDifference[];
    added_in_b: { title: string; text: string; severity: string }[];
    missing_in_b: { title: string; text: string; severity: string }[];
}

export async function compareContracts(sessionA: string, sessionB: string, model?: string): Promise<CompareResult> {
    const res = await fetch(`${API_BASE}/api/contract/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_a: sessionA, session_b: sessionB, model }),
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Compare failed' }));
        throw new Error(err.detail || 'Porovnání selhalo');
    }

    return res.json();
}


// ── Bytová jednotka (BJ) Pipeline ────────────────────────────────────────

export interface ApartmentPropertyData {
    // Žadatel
    jmeno_prijmeni: string | null;
    kupni_cena: string | null;
    // Oceňovaný byt
    list_vlastnictvi: string | null;
    katastral_uzemi: string | null;
    ulice: string | null;
    cislo_popisne_bytu: string | null;
    obec: string | null;
    psc: string | null;
    // Informace o budově
    rok_dokonceni_budovy: string | null;
    rok_rekonstrukce: string | null;
    konstrukce: string | null;
    stav_budovy: string | null;
    vytah: string | null;
    podlazi_jednotky: string | null;
    pocet_nadz_podlazi: string | null;
    pocet_podz_podlazi: string | null;
    typ_strechy: string | null;
    obytne_podkrovi: string | null;
    zatepleni: string | null;
    typ_oken: string | null;
    ohrev_vody: string | null;
    vetrani: string | null;
    rekuperace: string | null;
    solarni_panely: string | null;
    // Byt
    typ_jednotky: string | null;
    pocet_garazi: string | null;
    typ_vytapeni: string | null;
    plocha_bytu: string | null;
    plocha_terasy: string | null;
    plocha_balkonu: string | null;
    plocha_sklepa: string | null;
    plocha_zahrady: string | null;
    stav_bytu: string | null;
    // Derived
    adresa: string | null;
}

/** Human-readable labels for BJ property data fields */
export const BJ_DATA_LABELS: Record<string, string> = {
    rok_dokonceni_budovy: "Rok dokončení budovy",
    rok_rekonstrukce: "Rok rekonstrukce",
    konstrukce: "Konstrukce",
    stav_budovy: "Stav budovy",
    vytah: "Výtah",
    podlazi_jednotky: "Podlaží jednotky",
    pocet_nadz_podlazi: "Počet nadzemních podlaží",
    pocet_podz_podlazi: "Počet podzemních podlaží",
    typ_strechy: "Typ střechy",
    obytne_podkrovi: "Obytné podkroví",
    zatepleni: "Zateplení",
    typ_oken: "Typ oken",
    ohrev_vody: "Ohřev vody",
    vetrani: "Větrání",
    rekuperace: "Rekuperace",
    solarni_panely: "Solární panely",
    typ_jednotky: "Typ jednotky",
    pocet_garazi: "Počet garáží/stání",
    typ_vytapeni: "Typ vytápění",
    plocha_bytu: "Plocha bytu",
    plocha_terasy: "Plocha terasy",
    plocha_balkonu: "Plocha balkonu",
    plocha_sklepa: "Plocha sklepa/skladu",
    plocha_zahrady: "Plocha zahrady",
    stav_bytu: "Stav bytu",
    adresa: "Adresa",
};

export interface BjUploadResponse {
    session_id: string;
    files_uploaded: number;
    files_processed: number;
    images: ProcessedImage[];
    property_data: ApartmentPropertyData | null;
    lv_data: LVData | null;
}

export async function parseBjPdf(pdfFile: File): Promise<ApartmentPropertyData | null> {
    const formData = new FormData();
    formData.append('pdf_file', pdfFile);
    const res = await fetch(`${API_BASE}/api/bj/parse-pdf`, {
        method: 'POST',
        body: formData,
    });
    if (!res.ok) return null;
    const data = await res.json();
    return data.property_data || null;
}

export async function uploadBjFiles(
    files: File[],
    propertyAddress?: string,
    pdfFile?: File,
    propertyData?: ApartmentPropertyData,
    lvPdfFile?: File,
    floorAreaDocs?: File[],
    selectedParcels?: string[],
): Promise<BjUploadResponse> {
    const formData = new FormData();
    files.forEach(file => formData.append('files', file));
    if (propertyAddress) formData.append('property_address', propertyAddress);
    if (pdfFile) formData.append('pdf_file', pdfFile);
    if (propertyData) formData.append('property_data_json', JSON.stringify(propertyData));
    if (lvPdfFile) formData.append('lv_pdf_file', lvPdfFile);
    if (floorAreaDocs) floorAreaDocs.forEach(doc => formData.append('floor_area_docs', doc));
    if (selectedParcels) formData.append('selected_parcels_json', JSON.stringify(selectedParcels));

    const res = await fetch(`${API_BASE}/api/bj/upload`, {
        method: 'POST',
        body: formData,
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(err.detail || 'Upload failed');
    }

    return res.json();
}

export async function startBjPipeline(sessionId: string, model: string = "gemini"): Promise<PipelineResult> {
    const res = await fetch(`${API_BASE}/api/bj/pipeline/start/${sessionId}?model=${model}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'BJ Pipeline start failed' }));
        throw new Error(err.detail || 'BJ Pipeline start failed');
    }

    return res.json();
}

export async function getBjPipelineResults(sessionId: string): Promise<PipelineResult> {
    const res = await fetch(`${API_BASE}/api/bj/pipeline/results/${sessionId}`);
    if (!res.ok) throw new Error('BJ results not found');
    return res.json();
}

export function getBjWebSocketUrl(sessionId: string): string {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (apiUrl) {
        const wsUrl = apiUrl.replace(/^http/, 'ws');
        return `${wsUrl}/ws/bj/pipeline/${sessionId}`;
    }
    const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
    return `ws://${host}:8000/ws/bj/pipeline/${sessionId}`;
}
