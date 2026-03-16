'use client';
import { useState } from 'react';
import styles from './AppInfo.module.css';

interface AgentInfo {
    name: string;
    icon: string;
    color: string;
    description: string;
    prompt: string;
}

const AGENTS: AgentInfo[] = [
    {
        name: 'Strazce',
        icon: '🛡️',
        color: '#2870ED',
        description: 'Kontrola úplnosti a aktuálnosti fotek — ověřuje, zda sada obsahuje exteriér ze všech stran, interiér všech místností a zda fotky nejsou archivní nebo AI generované.',
        prompt: `Jsi expert na validaci fotografické dokumentace pro účely bankovního online ocenění rodinného domu (RD).

Tvůj úkol je:
1. Klasifikovat každou fotografii do kategorií.
2. Ověřit ÚPLNOST sady (dostatečný počet, kategorie, zadní/boční pohled).
3. Posoudit AKTUÁLNOST fotografií – jsou to skutečné aktuální fotografie dané nemovitosti?

KATEGORIE:
- EXTERIER_PREDNI, EXTERIER_ZADNI, EXTERIER_BOCNI, EXTERIER_DETAIL
- INTERIER_KUCHYN, INTERIER_OBYVAK, INTERIER_LOZNICE, INTERIER_KOUPELNA
- INTERIER_OSTATNI, OKOLÍ

AKTUÁLNOST – nastav are_photos_current = false pokud:
- Fotografie vypadají jako AI-generované
- Jsou evidentně staré (historický nábytek, nízké rozlišení)
- Jsou to záběry z jiné nemovitosti nebo katalogové fotografie`,
    },
    {
        name: 'ForenzniAnalytik',
        icon: '🔬',
        color: '#dc2626',
        description: 'Detekce manipulace fotografií — analýza EXIF dat (datum, GPS, zařízení), detekce AI generovaných obrázků, kontrola úprav a nekonzistencí.',
        prompt: `Jsi forenzní expert na analýzu digitálních fotografií. Tvým úkolem je analyzovat přiložené fotky a detekovat:
1. Manipulace a úpravy (Photoshop, filtry, ořez)
2. AI generované nebo syntetické obrázky
3. Nekonzistentní metadata (EXIF) — rozdílné fotoaparáty, podezřelá data
4. Stopy po klonování nebo retušování
5. Nepřirozené osvětlení nebo stíny`,
    },
    {
        name: 'Inspektor',
        icon: '🔍',
        color: '#059669',
        description: 'Rozhodnutí o způsobilosti k online ocenění — hodnotí technický stav: fasáda, statika (praskliny), vlhkost, celková obyvatelnost a rozestavěnost.',
        prompt: `Jsi specializovaný inspektor nemovitostí. Tvým úkolem je rozhodnout, zda je dům způsobilý pro automatizované online ocenění.

KRITÉRIA PRO "NE":
1. Probíhající rekonstrukce (chybějící podlahy, rozvody, lešení)
2. Opadaná omítka (> 15 % plochy)
3. Statické vady (trhliny v nosném zdivu)
4. Vlhkost a plísně
5. Celková neobyvatelnost (poškozená střecha, vybydlenost)

Nevadí, že je vybavení zastaralé (retro), pokud je funkční a stavba je stavebně v pořádku.`,
    },
    {
        name: 'PorovnavacDokumentu',
        icon: '📋',
        color: '#7c3aed',
        description: 'Porovnání dat z formuláře s fotkami — kontrola počtu podlaží, plochy, střechy a stavu. Pečlivě ověřuje podkroví a suterény.',
        prompt: `Jsi expert na validaci nemovitostí. Tvým úkolem je porovnat údaje z formuláře ocenění RD s přiloženou fotodokumentací.

POČET PODLAŽÍ — NEJDŮLEŽITĚJŠÍ KONTROLA:
- 1NP (přízemí) = vždy se počítá.
- 2NP (patro) = plné svislé stěny.
- Podkroví (obytné) = střešní okna, vikýře → POČÍTÁ se jako podlaží.
- Půda (neobytná) = bez oken, neupravená → NEPOČÍTÁ se.
- Suterén/sklep = podzemní podlaží.

JAK POZNAT Z FOTEK:
- Počítej řady oken nad sebou na exteriéru.
- Okna ve střeše (střešní okna, vikýře) = podkroví.
- Šikmé stropy na interiéru = podkroví.

Kontroluj také plochu (shoda ±20 %), typ střechy a celkový stav.`,
    },
    {
        name: 'GeoValidator',
        icon: '📍',
        color: '#ea580c',
        description: 'Ověření lokality — porovnání GPS z EXIF s adresou a vizuální porovnání nahrané uliční fotky s panoramatem z Mapy.cz.',
        prompt: `Jsi expert na geolokační validaci.
ÚKOLY:
1. Extrahuj GPS souřadnice z EXIF dat a porovnej s adresou (tolerance 500m/2km).
2. Vizuálně porovnej nahrané uliční foto s panoramatem z Mapy.cz na daných souřadnicích.
3. Posuď shodu barvy fasády, tvaru střechy, počtu oken a okolí.
4. Odhadni roční období z vegetace, pokud chybí EXIF data.`,
    },
    {
        name: 'KatastralniAnalytik',
        icon: '🏛️',
        color: '#0891b2',
        description: 'Katastrální analýza — data z ČÚZK (LV), ortofoto s katastrální mapou a AI detekce nezakreslených staveb nebo přístaveb.',
        prompt: `Jsi expert na katastr a ortofoto.
1. LV ANALÝZA: Identifikuj zástavní práva, věcná břemena, exekuce a insolvence. Posuď právní zajištění přístupu k nemovitosti.
2. DETEKCE STAVEB: Porovnej ortofoto s katastrální mapou a hledej nezakreslené stavby.
   - Vedlejší stavba > 45 m² nezkreslená → RIZIKO
   - Přístavba k domu > 16 m² nezkreslená → RIZIKO`,
    },
    {
        name: 'Odhadce',
        icon: '💰',
        color: '#10b981',
        description: 'Tržní ocenění nemovitosti — výpočet ceny porovnávací metodou pomocí reálných inzerátů ze sreality.cz, GPS filtrace a AI výběru nejpodobnějších vzorků.',
        prompt: `Jsi expertní bankovní odhadce. Na základě parametrů domu vyber ze seznamu kandidátů (sreality.cz) 3–5 nejpodobnějších vzorků.

Vybírej dle:
- Velikost objektu (m²) — co nejbližší.
- Stav nemovitosti — podobný stupeň opotřebení.
- Poloha — přednost bližším vzorkům (okruh 2–30 km).

Ke každému vzorku přiřaď korekční koeficienty K1–K8 (poloha, stav, velikost atd.) a urči výslednou tržní cenu.`,
    },
    {
        name: 'Strateg',
        icon: '🎯',
        color: '#4f46e5',
        description: 'Finální verdikt — agregace výsledků, stanovení semaforu (ONLINE / SUPERVISED / VRÁTIT KLIENTOVI) s konkrétním zdůvodněním.',
        prompt: `Jsi hlavní strateg. Tvým úkolem je stanovit finální verdikt:
        
1. VRÁTIT KLIENTOVI (Červená):
   - Neúplné nebo neaktuální (archívní/AI) fotky (Strazce FAIL).
   - Špatný technický stav/rozestavěnost (Inspektor FAIL).
   - Detekována kritická manipulace (ForenzniAnalytik FAIL).
   - Příliš mnoho rizik (3+ varování).
2. SUPERVISED (Oranžová):
   - Nalezeny neshody vyžadující kontrolu (1-2 varování).
3. ONLINE (Zelená):
   - Vše v pořádku, shoda v datech.`,
    },
];

const TECH_STACK = [
    { category: 'Frontend', items: ['Next.js 15 (App Router)', 'React 19', 'TypeScript', 'CSS Modules', 'WebSocket (real-time)'] },
    { category: 'Backend', items: ['Python 3.14 + FastAPI', 'WebSocket streaming', 'Pillow (image processing)', 'httpx (async HTTP)'] },
    { category: 'AI / ML', items: ['Google Gemini 2.0 Flash', 'Multi-modal prompty (text + obrázky)', 'Structured JSON output'] },
    { category: 'Data Sources', items: ['ČÚZK WMS (ortofoto + katastrální mapa)', 'ČÚZK Nahlížení do KN (LV data)', 'Mapy.cz API (geocoding + panorama)'] },
    { category: 'Hosting', items: ['Vercel (frontend)', 'Render.com (backend)', 'GitHub (CI/CD)'] },
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
                            Aplikace implementuje <strong>multi-agentní pipeline</strong> — sérii specializovaných AI agentů,
                            kteří postupně analyzují fotografickou dokumentaci a podkladové dokumenty rodinného domu.
                            Každý agent má specifický prompt a roli. Agenti běží <strong>sekvenčně</strong> (kvůli
                            paměťovým limitům free-tier hostingu) a výsledky streamují přes <strong>WebSocket</strong> v reálném čase.
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
