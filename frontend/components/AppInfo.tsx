'use client';
import { useState } from 'react';
import styles from './AppInfo.module.css';

interface AgentInfo {
    name: string;
    icon: string;
    color: string;
    description: string;
    inputs: string;
    outputs: string;
    thresholds?: string;
    prompt: string;
}

const AGENTS: AgentInfo[] = [
    {
        name: 'Strazce',
        icon: '🛡️',
        color: '#2870ED',
        description: 'Agent 1 – Kontrola úplnosti fotodokumentace (BR-G4). Klasifikuje každou fotku do 17 kategorií (EXTERIER_PREDNI, INTERIER_KUCHYN atd.), ověřuje přítomnost povinných pohledů a aktuálnost EXIF metadat (max 90 dní). Rozlišuje podkroví vs. plné patro pomocí pravidel pro širokoúhlý objektiv.',
        inputs: 'Seznam obrázků (JPEG bytes). EXIF metadata (datum, GPS, model zařízení) pro validaci stáří.',
        outputs: 'classifications[] → pro každou fotku seznam kategorií a popis. summary → počty ext/int, has_cislo_popisne, has_front/rear/side, interior_rooms_found[], vedlejsi_stavba_visible. image_metadata{} s GPS a daty.',
        thresholds: 'FAIL: exteriér < 2 fotek, chybí přední pohled, interiér < 3 fotek. WARN: chybí ČP, chybí zadní/boční, chybí místnosti (kuchyň/koupelna/obývák), vedlejší stavba nezdokumentována, EXIF starší 90 dní. SUCCESS: vše splněno.',
        prompt: `Jsi expert na validaci fotografické dokumentace nemovitostí typu Rodinný dům (RD) pro účely bankovního ocenění.

POVINNÁ FOTODOKUMENTACE:
1) Aktuální barevné fotografie:
   a) EXTERIÉR — pohled na dům ze všech světových stran (přední, zadní, boční).
      Na alespoň jedné fotce musí být viditelné číslo popisné (CP).
   b) INTERIÉR — fotografie všech místností
   c) VEDLEJŠÍ STAVBY — POUZE pokud na pozemku existují.

KATEGORIE PRO KLASIFIKACI:
EXTERIER_PREDNI, EXTERIER_ZADNI, EXTERIER_BOCNI, EXTERIER_DETAIL,
EXTERIER_CISLO_POPISNE, INTERIER_KUCHYN, INTERIER_OBYVAK, INTERIER_LOZNICE,
INTERIER_KOUPELNA, INTERIER_CHODBA, INTERIER_SKLEP, INTERIER_PODKROVI,
INTERIER_OSTATNI, VEDLEJSI_STAVBA, OKOLI, PUDORYS

POZN.: INTERIER_PODKROVI — klasifikuj POUZE pokud na fotce vidíš skutečně
šikmé/zkosené stropy sledující tvar střechy. POZOR: širokoúhlý objektiv
deformuje okraje fotky → to NENÍ podkroví!

Odpověz POUZE validním JSON.`,
    },
    {
        name: 'ForenzniAnalytik',
        icon: '🔬',
        color: '#dc2626',
        description: 'Agent 2 – Detekce manipulace fotografií (BR-G5). AI analýza generování, retušování, klonování + Google Cloud Vision Web Detection pro odhalení fotek stažených z internetu (sreality.cz, bezrealitky.cz atd.). Fotka nalezená na blocked domain = automatický score 1.0.',
        inputs: 'Obrázky + EXIF metadata. Google Cloud Vision (service account credentials) pro web detection.',
        outputs: 'photos[] → manipulation_score (0.0–1.0), confidence, is_ai_generated, is_downloaded_from_internet, findings[], risk_level. overall → avg/max score, flagged_count.',
        thresholds: 'FAIL: manipulation_score ≥ 0.7 AND confidence ≥ 0.6, nebo fotka nalezena na blocked domains → score=1.0. WARN: score ≥ 0.4. SUCCESS: vše pod prahem.',
        prompt: `Jsi forenzní expert na analýzu fotografií nemovitostí. Detekuj manipulace, AI úpravy, retuše.

ANALYZUJ NA:
1. AI Generování: podivné textury, nereálné odrazy
2. Retuše a Úpravy: klonování, healing, content-aware fill
3. Lokální Artefakty: skoky v kompresi, nekonzistentní šum
4. Metadata Nesoulad: osvětlení vs. čas pořízení
5. Manipulace Perspektivy: nereálné úhly
6. Původ Fotografie: vodoznaky, loga portálů (zejména sreality.cz)

risk_level: "low" (<0.3), "medium" (0.3-0.6), "high" (0.6-0.8), "critical" (>0.8)

Odpověz POUZE validním JSON.`,
    },
    {
        name: 'Historik',
        icon: '📅',
        color: '#92400e',
        description: 'Agent 3 – Výpočet efektivního věku a přiřazení kategorie (BR-G6). Plně deterministický (bez AI volání). Rekonstrukce má vždy přednost. Referenční rok: 2026.',
        inputs: 'year_built (rok výstavby), year_reconstructed (rok rekonstrukce).',
        outputs: 'effective_age, age_source ("rekonstrukce"|"výstavba"), category (1–5), category_description, reference_year.',
        thresholds: 'Kat.1: 0–5 let. Kat.2: 6–15 let. Kat.3: 16–30 let. Kat.4: 31–50 let. Kat.5: 50+ let (+ varování). FAIL pouze pokud chybí oba roky.',
        prompt: `Plně deterministický agent – nepotřebuje AI/LLM volání.

VZOREC:
- Pokud existuje rok rekonstrukce: efektivní_věk = 2026 - rok_rekonstrukce
- Pokud ne: efektivní_věk = 2026 - rok_výstavby
- Rekonstrukce má VŽDY přednost.

KATEGORIE (1-5) dle efektivního věku:
- Kat. 1: 0-5 let (novostavba / čerstvá rekonstrukce)
- Kat. 2: 6-15 let (moderní)
- Kat. 3: 16-30 let (starší, ale udržovaný)
- Kat. 4: 31-50 let (starší, vyžaduje pozornost)
- Kat. 5: 50+ let (starý, potenciální rizika)`,
    },
    {
        name: 'Inspektor',
        icon: '🔍',
        color: '#059669',
        description: 'Agent 4 – Vizuální inspekce technického stavu (ANO/NE). Verdikt MUSÍ vycházet z kombinace EXTERIÉRU i INTERIÉRU – nikdy jen jedno! Finální verdikt = horší z obou hodnocení. Hledá: probíhající rekonstrukce, opadlou omítku >15%, statické trhliny, vlhkost/plísně, celkovou neobyvatelnost.',
        inputs: 'Všechny nahrané obrázky (JPEG bytes).',
        outputs: 'verdikt ("ANO"|"NE"), duvod (formát: "Exteriér: [hodnocení]. Interiér: [hodnocení]. [Závěr].")',
        thresholds: 'FAIL (NE): probíhající rekonstrukce, omítka >15% chybí, diagonální trhliny, viditelná vlhkost/plísně, poškozená střecha. SUCCESS (ANO): funkční a kompletní dům, i zastaralý.',
        prompt: `Jsi specializovaný inspektor nemovitostí. Rozhodneš, zda je RD způsobilý pro online ocenění.

KLÍČOVÉ PRAVIDLO – KOMBINACE EXTERIÉRU A INTERIÉRU:
Verdikt MUSÍ vycházet z hodnocení OBOU pohledů. Finální verdikt = horší z obou.

Rozhodovací kritéria (NE):
1. Probíhající rekonstrukce (chybějící podlahy, odhalené cihly, lešení)
2. Stav fasády (omítka opadaná > 15 %)
3. Statické vady (trhliny v nosném zdivu, zejména diagonální)
4. Vlhkost a plísně (mapy vlhkosti, solné výkvěty, plísně)
5. Celková neobyvatelnost (poškozená střecha, vybitá okna)

Kritéria (ANO):
- Starý, esteticky zastaralý, ale kompletní a funkční.
- Čistý, suchý a bez prasklin – PLATÍ PRO OBOJÍ SOUČASNĚ.

V důvodu VŽDY: "Exteriér: [hodnocení]. Interiér: [hodnocení]. [Závěr]."
VRAŤ POUZE VALIDNÍ JSON: {"verdikt": "ANO"|"NE", "duvod": "..."}`,
    },
    {
        name: 'PorovnavacDokumentu',
        icon: '📋',
        color: '#7c3aed',
        description: 'Agent 5 – Porovnání dat z formuláře (PDF/manuální) s fotodokumentací. Nejdůležitější: počet podlaží (3-bodový test podkroví, detekce změny materiálu fasády vs. nového podlaží). Profesionální odhad podlahové plochy (m²) z exteriéru. Automatická korekce AI verdiktu dle skutečných match/mismatch. Využívá Strážce klasifikace.',
        inputs: 'property_data (JSON z formuláře), až 10 fotek s klasifikačními štítky ze Strážce.',
        outputs: 'verdict ("SHODA"|"ČÁSTEČNÁ_SHODA"|"NESHODA"), confidence, checks[] (podlaží, plocha, střecha, stav, podsklepení, vytápění, podkroví).',
        thresholds: 'SUCCESS: všechny checks match=true → "SHODA". WARN: 1+ neshoda → "ČÁSTEČNÁ_SHODA". FAIL: 0 shod → "NESHODA". Backend přepisuje AI verdikt dle skutečných match/mismatch.',
        prompt: `Jsi expertní odhadce nemovitostí. Křížově ověř údaje z dotazníku klienta s fotodokumentací.

POČET PODLAŽÍ – NEJDŮLEŽITĚJŠÍ KONTROLA:
⚠️ ZMĚNA MATERIÁLU FASÁDY ≠ NOVÉ PODLAŽÍ!
✅ Rozlišující znak podlaží: viditelná STROPNÍ/PODLAŽNÍ LINIE
❌ Pouhá změna materiálu, barvy nebo textury fasády NENÍ důkazem!

DETEKCE PODKROVÍ – PŘÍSNÝ 3-BODOVÝ TEST:
✅ Podmínka 1: Šikmé stropy na interiérových fotkách
✅ Podmínka 2: Sedlová/mansardová/valbová střecha z exteriéru
✅ Podmínka 3: Střešní okna (velux) nebo vikýře viditelné z exteriéru

ODHAD PODLAHOVÉ PLOCHY:
A) Odhadni půdorysné rozměry z exteriéru (okno ~1,5m, dveře ~0,9m)
B) Hrubá zastavěná plocha 1NP
C) Odpočítej 20 % na zdi = čistá plocha
D) Vynásob počtem plných NP
E) Podkroví = cca 60 % čisté plochy přízemí
F) Sečti → porovnej s deklarací (tolerance ±25 %)

STAV DOMU = horší z hodnocení exteriéru a interiéru.

Vrať JSON: {verdict, confidence, overall_summary, checks[], warnings[], recommendations[]}`,
    },
    {
        name: 'KatastralniAnalytik',
        icon: '🏛️',
        color: '#0891b2',
        description: 'Agent 6 – Analýza LV + ortofoto. Parsuje PDF Listu vlastnictví (vlastní lv_parser), AI analýza právních rizik. Geocoduje adresu → stáhne ortofoto z ČÚZK WMS (1024×1024px) + katastrální hranice → flood-fill zvýraznění parcel (cyan) + žluté hranice → AI detekce nezakreslených staveb. Přeskočí, pokud LV nebylo nahráno.',
        inputs: 'lv_pdf_path (PDF soubor), selected_parcels[] (vybrané parcely z UI), property_address. Vyžaduje MAPY_CZ_API_KEY.',
        outputs: 'risks[] (severity, category, description, recommendation). ortofoto_url + ortofoto_annotated_url (s bounding boxy). buildings_detected[]. access_assessment.',
        thresholds: 'FAIL: 1+ vysoké riziko (zástavní právo / VB užívání / zákaz zcizení). WARN: 1+ střední riziko (ostatní VB, exekuce, plomby, nezajištěný přístup). Nezakreslená stavba >45m² → střední.',
        prompt: `PROMPT 1 – Právní analýza LV:
Tato 3 rizika MUSÍ BÝT VYSOKÉ: Zástavní práva, Věcné břemeno užívání, Zákazy zcizení.
Všechna ostatní MUSÍ BÝT STŘEDNÍ: exekuce, insolvence, plomby, spoluvlastnictví, BPEJ/ZPF.

Přístup: ZAJIŠTĚNÝ pokud přístupová parcela je komunikace OR ve vlastnictví obce/státu
OR je VB přístupu OR spoluvlastnictví vlastníka.

---
PROMPT 2 – Ortofoto (detekce nezakreslených staveb):
Hledej STAVBY na pozemcích, které NEJSOU zakresleny v katastru:
1. Vedlejší stavba >45m² → RIZIKO STŘEDNÍ
2. Přístavba k hlavní stavbě >16m² → RIZIKO STŘEDNÍ
Pro každou stavbu uveď bounding box v procentech obrázku.`,
    },
    {
        name: 'GeoValidator',
        icon: '📍',
        color: '#ea580c',
        description: 'Agent 7 – GPS validace + vizuální porovnání s panoramou Mapy.cz. Hierarchie: (1) Geocoding adresy přes Mapy.cz API, (2) Haversine vzdálenost EXIF GPS vs. adresa, (3) Stažení panoramy 800×450px, (4) AI výběr nejlepší exteriérové fotky (nejprve ze Strážce klasifikací, pak vlastní AI), (5) Vizuální porovnání fotek, (6) Kontrola stáří fotek (max 90 dní), (7) AI odhad ročního období z vizuálních indicií (jen pokud <4 fotek má EXIF datum).',
        inputs: 'images + EXIF GPS/datum, property_address, Strážce classifications[]. Vyžaduje MAPY_CZ_API_KEY.',
        outputs: 'photo_results[] (distance_m, photo_address, status). visual_comparison (match_verdict, confidence, comparison_text). panorama_url. season_estimation.',
        thresholds: 'GPS WARN: >500m od adresy. GPS FAIL: >2000m. Stáří fotek FAIL: >90 dní. Roční období WARN: odhadnutá sezóna nesedí s aktuálním měsícem (±3 měsíce).',
        prompt: `PROMPT 1 – Vizuální porovnání s panoramou:
Porovnej nahrané foto klientem s panoramou z Mapy.cz.
match_verdict: "shoda" | "možná_shoda" | "neshoda"

PROMPT 2 – Výběr přední fotky:
Vyber fotku NEJLÉPE ukazující PŘEDNÍ FASÁDU / POHLED Z ULICE.
NIKDY nevyber interiérovou fotku ani detail.

PROMPT 3 – Odhad ročního období (fallback bez EXIF):
Posuzuj: vegetaci, sníh, světlo, trávu, oblečení lidí, stav zahrady, bazén.
Vrať: estimated_season, confidence, reasoning, freshness_concern.`,
    },
    {
        name: 'Strateg',
        icon: '🎯',
        color: '#4f46e5',
        description: 'Agent 8 (finální) – Agregace výsledků všech předchozích agentů. Deterministický semafor: Strážce FAIL → VRÁTIT KLIENTOVI. Inspektor FAIL nebo jakýkoliv FAIL nebo 3+ varování → SUPERVISED. 1–2 varování → SUPERVISED. Vše OK → ONLINE. Generuje lidsky čitelný report přes AI.',
        inputs: 'Výsledky všech 7 předchozích agentů. Vždy spustí jako poslední.',
        outputs: 'semaphore ("ONLINE"|"SUPERVISED"|"VRÁTIT KLIENTOVI"), semaphore_color, semaphore_reason, final_category (1–5), human_report.',
        thresholds: 'GREEN (ONLINE): 0 varování + 0 selhání. ORANGE (SUPERVISED): 1+ varování NEBO jakýkoliv fail (kromě Strážce). RED (VRÁTIT KLIENTOVI): Strážce FAIL (neúplná/neaktuální fotodok.).',
        prompt: `Jsi senior analytik nemovitostí. Napiš stručný, čitelný report česky, profesionálně.
Nepoužívej technický žargon. Nepiš o "agentech" – piš o kontrolách a zjištěních.

STRUKTURA REPORTU:
1. Shrnutí (2-3 věty)
2. Fotodokumentace (kompletnost, kvalita)
3. Stav nemovitosti (technický stav, vady)
4. Věk a kategorizace (efektivní věk, kategorie)
5. Ověření autentičnosti (manipulace fotek, GPS)
6. Porovnání dokumentů (shoda/neshoda dat z formuláře)
7. Doporučení (další krok)

Piš stručně – každá sekce max 2-3 věty.

---
SEMAFOR (deterministická logika):
• Strážce FAIL (neaktuální EXIF) → VRÁTIT KLIENTOVI
• Strážce FAIL (neúplné fotky) → VRÁTIT KLIENTOVI
• Inspektor FAIL / has_fail / warns ≥ 3 → SUPERVISED
• warns 1–2 → SUPERVISED
• vše OK → ONLINE`,
    },
];

const TECH_STACK = [
    {
        category: 'Frontend',
        items: [
            'Next.js 16 (App Router)',
            'React 19 + TypeScript',
            'CSS Modules (Vanilla CSS)',
            'WebSocket (real-time streaming výsledků)',
            'jsPDF (client-side PDF report)',
        ]
    },
    {
        category: 'Backend',
        items: [
            'Python 3.13 + FastAPI + Uvicorn',
            'WebSocket streaming (ping/pong keepalive)',
            'Pillow + piexif (zpracování obrázků, EXIF extrakce)',
            'httpx (async HTTP pro API volání)',
            'pypdf + pdfplumber (parsování PDF dokumentů)',
            'lv_parser (vlastní parser Listu vlastnictví)',
            'Apify REST API (scraping realitních portálů)',
        ]
    },
    {
        category: 'AI / LLM',
        items: [
            'Google Gemini 3.1 Flash / Pro (primární model)',
            'OpenAI GPT-5.4 / GPT-5.4 mini / GPT-4.1 / o4-mini',
            'Unified LLMClient (Gemini + OpenAI-compatible endpoint)',
            'Multimodální prompty (text + obrázky – JPEG bytes)',
            'Structured JSON output (response_format: json_object)',
            'Exponential backoff retry (429 rate limit protection)',
            'Google Cloud Vision – web detection (stažení fotek z internetu)',
        ]
    },
    {
        category: 'Datové zdroje',
        items: [
            'ČÚZK WMS – ortofoto + katastrální mapa (hranice_parcel, parcelni_cisla)',
            'ČÚZK Nahlížení – List vlastnictví (parsovaný PDF)',
            'Mapy.cz API v1 – geocoding, reverse geocoding, panorama (800×450)',
            'Apify actor (martas_kristof~cz-reality-scraper) – sreality.cz + bezrealitky.cz',
            'Nominatim / OpenStreetMap – geocoding pro Odhadce',
            'Google Cloud Vision – web detection (blocked domains)',
        ]
    },
    {
        category: 'Hosting & CI/CD',
        items: [
            'Vercel – frontend (Next.js, automatický deploy z GitHub)',
            'Render.com free tier – backend (512 MB RAM, 0.1 CPU)',
            'GitHub – zdrojový kód + CI/CD (push → auto deploy)',
        ]
    },
];



export default function AppInfo({ onClose }: { onClose: () => void }) {
    const [expandedAgent, setExpandedAgent] = useState<string | null>(null);

    return (
        <div className={styles.overlay} onClick={onClose}>
            <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
                {/* Header */}
                <div className={styles.modalHeader}>
                    <div>
                        <h2 className={styles.modalTitle}>O aplikaci</h2>
                        <p className={styles.modalSubtitle}>Kontrola vstupních dat pro online ocenění RD</p>
                    </div>
                    <button className={styles.closeBtn} onClick={onClose}>✕</button>
                </div>

                <div className={styles.modalBody}>
                    {/* Architecture overview */}
                    <section className={styles.section}>
                        <h3 className={styles.sectionTitle}>
                            <span className={styles.sectionIcon}>⚙️</span>
                            Architektura
                        </h3>
                        <p className={styles.sectionDesc}>
                            Aplikace implementuje <strong>multi-agentní pipeline</strong> — sérii 8 specializovaných AI agentů,
                            kteří postupně analyzují fotografickou dokumentaci a podkladové dokumenty rodinného domu.
                            Každý agent má specifický prompt a roli. Agenti běží <strong>sekvenčně</strong> (kvůli
                            paměťovým limitům free-tier hostingu) a výsledky streamují přes <strong>WebSocket</strong> v reálném čase.
                            Podporuje volbu LLM modelu (Gemini 3.1 Flash/Pro, GPT-5.4, GPT-4.1, o4-mini) přes unified LLMClient.
                        </p>
                        <div className={styles.techGrid}>
                            {TECH_STACK.map((cat) => (
                                <div key={cat.category} className={styles.techCard}>
                                    <div className={styles.techCategory}>{cat.category}</div>
                                    <ul className={styles.techList}>
                                        {cat.items.map((item) => (
                                            <li key={item}>{item}</li>
                                        ))}
                                    </ul>
                                </div>
                            ))}
                        </div>
                    </section>

                    {/* Agents */}
                    <section className={styles.section}>
                        <h3 className={styles.sectionTitle}>
                            <span className={styles.sectionIcon}>🤖</span>
                            Agenti a jejich prompty
                        </h3>
                        <p className={styles.sectionDesc}>
                            Kliknutím na agenta zobrazíte jeho plný system prompt. Prompty lze upravit v souborech
                            <code>backend/agents/*.py</code>.
                        </p>
                        <div className={styles.agentList}>
                            {AGENTS.map((agent) => (
                                <div key={agent.name} className={styles.agentItem}>
                                    <button
                                        className={styles.agentHeader}
                                        onClick={() => setExpandedAgent(expandedAgent === agent.name ? null : agent.name)}
                                        style={{ borderLeftColor: agent.color }}
                                    >
                                        <div className={styles.agentMeta}>
                                            <span className={styles.agentIcon}>{agent.icon}</span>
                                            <div>
                                                <div className={styles.agentName}>{agent.name}</div>
                                                <div className={styles.agentDesc}>{agent.description}</div>
                                            </div>
                                        </div>
                                        <span className={styles.agentChevron}>
                                            {expandedAgent === agent.name ? '▲' : '▼'}
                                        </span>
                                    </button>
                                    {expandedAgent === agent.name && (
                                        <div className={styles.agentPrompt}>
                                            <div className={styles.promptLabel}>System Prompt:</div>
                                            <pre className={styles.promptCode}>{agent.prompt}</pre>
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    </section>

                    {/* Pipeline flow */}
                    <section className={styles.section}>
                        <h3 className={styles.sectionTitle}>
                            <span className={styles.sectionIcon}>🔄</span>
                            Pipeline
                        </h3>
                        <div className={styles.pipelineFlow}>
                            {AGENTS.map((agent, i) => (
                                <div key={agent.name} className={styles.pipelineStep}>
                                    <div className={styles.pipelineNum} style={{ background: agent.color }}>{i + 1}</div>
                                    <span>{agent.icon} {agent.name}</span>
                                    {i < AGENTS.length - 1 && <span className={styles.pipelineArrow}>→</span>}
                                </div>
                            ))}
                        </div>
                    </section>
                </div>
            </div>
        </div>
    );
}
