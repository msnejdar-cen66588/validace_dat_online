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

export async function startPipeline(sessionId: string): Promise<PipelineResult> {
    const res = await fetch(`${API_BASE}/api/pipeline/start/${sessionId}`, {
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

export function getWebSocketUrl(sessionId: string): string {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (apiUrl) {
        const wsUrl = apiUrl.replace(/^http/, 'ws');
        return `${wsUrl}/ws/pipeline/${sessionId}`;
    }
    const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
    return `ws://${host}:8000/ws/pipeline/${sessionId}`;
}
