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
        description: 'Agent 1 – Kontrola úplnosti fotodokumentace (BR-G4). Klasifikuje každou fotku do kategorií, ověřuje přítomnost povinných pohledů (exteriér ze všech stran, interiér všech místností, vedlejší stavby) a aktuálnost fotek. Minimální počet fotek: 5 (ideálně ~9).',
        inputs: 'Seznam obrázků (JPEG bytes, max 3000 tokenů). Žádná jiná data z formuláře.',
        outputs: 'classifications[] → pro každou fotku seznam kategorií a popis. summary → počty ext/int, has_cislo_popisne, has_front/rear/side, interior_rooms_found[], vedlejsi_stavba_visible.',
        thresholds: 'FAIL: exteriér < 2 fotek, chybí přední pohled, interiér < 3 fotek. WARN: chybí ČP, chybí zadní/boční, chybí místnosti (kuchyň/koupelna/obývák), vedlejší stavba bez fotky. SUCCESS: vše splněno.',
        prompt: `Jsi expert na validaci fotografické dokumentace nemovitostí typu Rodinný dům (RD) pro účely bankovního ocenění.

POVINNÁ FOTODOKUMENTACE:
1) Aktuální barevné fotografie:
   a) EXTERIÉR — pohled na dům ze všech světových stran (přední, zadní, boční), pokud je to možné.
      Na alespoň jedné fotce musí být viditelné číslo popisné (CP).
   b) INTERIÉR — fotografie všech místností:
      - kuchyň, obývací pokoj, ložnice, koupelna, WC, chodba, schodiště, sklep, podkroví a další
   c) VEDLEJŠÍ STAVBY — garáž, stodola, dílna, kůlna apod.
      Vedlejší stavby se fotí POUZE pokud na pozemku existují.

KATEGORIE PRO KLASIFIKACI:
- EXTERIER_PREDNI: Přední pohled na dům (fasáda, vchod), ideálně s číslem popisným
- EXTERIER_ZADNI: Zadní pohled na dům (ze zahrady/dvora)
- EXTERIER_BOCNI: Boční pohled na dům
- EXTERIER_DETAIL: Detail exteriéru (střecha, okna, fasáda zblízka, sokl)
- EXTERIER_CISLO_POPISNE: Fotografie s viditelným číslem popisným na domě
- INTERIER_KUCHYN: Kuchyň nebo kuchyňský kout
- INTERIER_OBYVAK: Obývací pokoj
- INTERIER_LOZNICE: Ložnice / dětský pokoj
- INTERIER_KOUPELNA: Koupelna / WC
- INTERIER_CHODBA: Chodba, schodiště, vstupní hala
- INTERIER_SKLEP: Sklep, suterén
- INTERIER_PODKROVI: Podkroví, půdní prostor
- INTERIER_OSTATNI: Jiné interiérové prostory
- VEDLEJSI_STAVBA: Vedlejší stavba — garáž, stodola, dílna, kůlna
- OKOLI: Zahrada, příjezdová cesta, okolí domu
- PUDORYS: Půdorys, technický výkres

Odpověz POUZE validním JSON.`,
    },
    {
        name: 'ForenzniAnalytik',
        icon: '🔬',
        color: '#dc2626',
        description: 'Agent 2 – Detekce manipulace fotografií (BR-G5). Analýza AI generování, retušování, klonování, nekonzistentního šumu, stažení z internetu (Google Cloud Vision web detection), nesouladu EXIF metadat.',
        inputs: 'Obrázky + EXIF metadata (datum, GPS, model zařízení). Volitelně Google Cloud Vision web detection přes service account credentials.',
        outputs: 'photos[] → pro každou fotku: manipulation_score (0.0–1.0), confidence (0.0–1.0), is_ai_generated, is_downloaded_from_internet, findings[], risk_level (low/medium/high/critical). overall → avg/max score, flagged_count, summary.',
        thresholds: 'FAIL: manipulation_score ≥ 0.7 AND confidence ≥ 0.6 (konfigurovatelné v config.py), nebo fotka nalezena na blocked domains (sreality.cz apod.) → score=1.0 automaticky. WARN: score ≥ 0.4. SUCCESS: vše pod prahem.',
        prompt: `Jsi forenzní expert na analýzu fotografií nemovitostí. Tvým úkolem je detekovat jakékoliv manipulace, AI úpravy, retuše nebo nesrovnalosti.

ANALYZUJ KAŽDOU FOTOGRAFII NA:
1. AI Generování: podivné textury, nereálné odrazy, anomálie v detailech
2. Retuše a Úpravy: klonování, healing, content-aware fill
3. Lokální Artefakty: skoky v kompresi, nekonzistentní šum, blur/sharpen anomálie
4. Metadata Nesoulad: nesoulad mezi vizuálním obsahem a metadaty
5. Manipulace Perspektivy: zkreslení, nereálné úhly
6. Původ Fotografie: vodoznaky, loga portálů (zejména sreality.cz)

PRO KAŽDOU FOTOGRAFII VRAŤ:
- manipulation_score: 0.0-1.0
- confidence: 0.0-1.0
- findings: seznam nalezených problémů
- risk_level: "low" (<0.3) | "medium" (0.3-0.6) | "high" (0.6-0.8) | "critical" (>0.8)

Odpověz POUZE validním JSON.`,
    },
    {
        name: 'Historik',
        icon: '📅',
        color: '#92400e',
        description: 'Agent 3 – Výpočet efektivního věku a přiřazení kategorie (BR-G6). Čistě deterministický (bez AI). Rekonstrukce má vždy přednost před rokem výstavby.',
        inputs: 'year_built (rok výstavby), year_reconstructed (rok rekonstrukce) z kontextu pipeline.',
        outputs: 'effective_age (číslo v letech), age_source ("rekonstrukce"|"výstavba"), category (1–5), category_description, reference_year (2026).',
        thresholds: 'Kat.1: 0–5 let. Kat.2: 6–15 let. Kat.3: 16–30 let. Kat.4: 31–50 let. Kat.5: 50+ let (+ automatické varování). FAIL pouze pokud chybí oba roky.',
        prompt: `Jsi expert na hodnocení stáří nemovitostí. Tvým úkolem je:

1. Vypočítat EFEKTIVNÍ VĚK nemovitosti podle vzorce:
   - Pokud existuje rok rekonstrukce: efektivní_věk = 2026 - rok_rekonstrukce
   - Pokud ne: efektivní_věk = 2026 - rok_výstavby
   - Rekonstrukce má VŽDY přednost.

2. Přiřadit PRIMÁRNÍ KATEGORII (1-5) dle efektivního věku:
   - Kat. 1: 0-5 let (novostavba / čerstvá rekonstrukce)
   - Kat. 2: 6-15 let (moderní)
   - Kat. 3: 16-30 let (starší, ale udržovaný)
   - Kat. 4: 31-50 let (starší, vyžaduje pozornost)
   - Kat. 5: 50+ let (starý, potenciální rizika)

POZN.: Tento agent je plně deterministický – nepotřebuje AI/LLM volání.`,
    },
    {
        name: 'Inspektor',
        icon: '🔍',
        color: '#059669',
        description: 'Agent 4 – Vizuální inspekce technického stavu (ANO/NE pro online ocenění). Hledá blokovací vady: probíhající rekonstrukce, opadlá omítka >15%, statické trhliny v nosném zdivu, vlhkost/plísně, celková neobyvatelnost. Zastaralé vybavení nevadí, pokud je stavba v pořádku.',
        inputs: 'Všechny nahrané obrázky (JPEG bytes, max 1000 tokenů odpovědi).',
        outputs: 'verdikt ("ANO"|"NE"), duvod (2 věty, česky, konkrétní nález).',
        thresholds: 'FAIL (verdikt=NE): probíhající rekonstrukce, omítka >15% chybí, diagonální trhliny v nosném zdivu, viditelná vlhkost/plísně, poškozená střecha / vybydlenost. SUCCESS (verdikt=ANO): funkční a kompletní dům, i zastaralý.',
        prompt: `Jsi specializovaný inspektor nemovitostí. Tvým úkolem je na základě vizuální analýzy fotografií rozhodnout, zda je rodinný dům (RD) způsobilý pro automatizované online ocenění.

Základní princip: Hledáš dům, který je obyvatelný a funkční. Nevadí zastaralé vybavení, pokud je stavba v dobrém technickém stavu.

Rozhodovací kritéria (Kdy zvolit NE):
1. Probíhající rekonstrukce: chybějící podlahy, odhalené cihly, vytrhané rozvody, lešení
2. Stav fasády: omítka opadaná na více než 15 % viditelné plochy
3. Statické vady (Kritické): trhliny a praskliny v nosném zdivu (zejména diagonální nad okny/dveřmi)
4. Vlhkost a plísně: mapy vlhkosti, solné výkvěty, plísně v rozích
5. Celková neobyvatelnost: poškozená střecha, vybitá okna, vybydlenost

Odpovídej maximálně ve dvou větách v důvodu.
VRAŤ POUZE VALIDNÍ JSON: {"verdikt": "ANO"|"NE", "duvod": "..."}`,
    },
    {
        name: 'PorovnavacDokumentu',
        icon: '📋',
        color: '#7c3aed',
        description: 'Agent 5 – Porovnání dat z formuláře (JSON) s fotodokumentací. Nejdůležitější kontrola: počet podlaží (rozlišuje 2NP vs. podkroví vs. půda). Detailní analýza vikýřů, střešních oken, šikmých stropů. Automatická korekce AI verdiktu dle skutečných výsledků kontrol (check[]). Přeskočí, pokud nejsou data z formuláře.',
        inputs: 'property_data (JSON z formuláře: stav, podlaží, střecha, podsklepení, plocha, vytápění, rok). Až 10 fotek (JPEG bytes).',
        outputs: 'verdict ("SHODA"|"ČÁSTEČNÁ_SHODA"|"NESHODA"), confidence (0.0–1.0), checks[] → pro každou kontrolu: field, declared, observed, match (bool), note. warnings[], recommendations[].',
        thresholds: 'SUCCESS: všechny checks match=true → verdict="SHODA". WARN: 1+ neshodnout → "ČÁSTEČNÁ_SHODA". FAIL: 0 shod → "NESHODA". Automatická korekce: kód přepíše AI verdikt dle počtu match/mismatch.',
        prompt: `Jsi expert na validaci nemovitostí. Porovnej údaje z formuláře ocenění rodinného domu s přiloženou fotodokumentací.

NEJDŮLEŽITĚJŠÍ KONTROLA – POČET PODLAŽÍ:
- 1NP (přízemí) = vždy se počítá
- 2NP (patro) = plné svislé stěny
- Podkroví (obytné) = střešní okna, vikýře → POČÍTÁ SE jako podlaží
- Půda (neobytná) = bez oken, neupravená → NEPOČÍTÁ SE
- Suterén/sklep = podzemní podlaží

JAK POZNAT Z FOTEK:
- Počítej řady oken nad sebou na exteriéru
- Okna ve střeše (vikýře, Velux) = obytné podkroví
- Šikmé stropy na interiéru = podkroví

Kontroluj: plochu (shoda ±20%), typ střechy, stav, podsklepení, typ vytápění.

Vrať JSON: {"verdict": ..., "confidence": ..., "overall_summary": ..., "checks": [...], "warnings": [...], "recommendations": [...]}`,
    },
    {
        name: 'GeoValidator',
        icon: '📍',
        color: '#ea580c',
        description: 'Agent 6 – GPS validace + vizuální porovnání s panoramou Mapy.cz. Hierarchie: (1) Geocoding adresy přes Mapy.cz API, (2) Haversine vzdálenost EXIF GPS vs. adresa, (3) Stažení panoramy z Mapy.cz Static API (800×450 px), (4) AI výběr nejlepší exteriérové fotky (nejprve ze Strazce klasifikací, potom vlastní AI volání), (5) Vizuální porovnání fotek, (6) Kontrola stáří fotek (max 90 dní), (7) AI odhad ročního období z vizuálních indicií (jen pokud <4 fotek mají EXIF datum).',
        inputs: 'images + EXIF GPS/datum, property_address, Strazce classifications[] (pro výběr ext. fotky). Vyžaduje API klíče: MAPY_CZ_API_KEY.',
        outputs: 'photo_results[] → pro každou fotku distance_m, photo_address (reverse geocode), status (ok/warn/fail). visual_comparison → match_verdict ("shoda"|"možná_shoda"|"neshoda"), confidence, comparison_text. panorama_url. season_estimation → estimated_season, confidence, reasoning, freshness_concern.',
        thresholds: 'GPS WARN: >500m od adresy. GPS FAIL: >2000m. Stáří fotek FAIL: >90 dní od EXIF data. Roční období WARN: odhadnutá sezóna nesedí s aktuálním měsícem (±3 měsíce).',
        prompt: `Jsi expert na vizuální porovnávání nemovitostí.

Dostáváš DVĚ fotografie:
1. Nahrané foto – fotka RD dodaná klientem (pohled z ulice / přední fasáda)
2. Panorama z Mapy.cz – automaticky stažená panorama ze souřadnic nemovitosti

TVŮJ ÚKOL: Porovnej obě fotky a popiš, co vidíš.

STRUKTURA ODPOVĚDI (JSON):
- match_verdict: "shoda" | "možná_shoda" | "neshoda"
- confidence: 0.0-1.0
- comparison_text: podrobný popis (3-5 vět)
- matching_features: ["barva fasády", "tvar střechy", ...]
- differing_features: ["jiný úhel pohledu", ...]
- notes: roční období, rekonstrukce, jiný úhel...

PRAVIDLA:
- Jiný dům nebo jiná lokace → "neshoda"
- Barva, tvar, střecha shodné → "shoda"
- Podobné ale nejistota → "možná_shoda"`,
    },
    {
        name: 'KatastralniAnalytik',
        icon: '🏛️',
        color: '#0891b2',
        description: 'Agent 7 – Analýza LV + ortofoto. Parsuje PDF Listu vlastnictví (vlastní lv_parser), AI analýza právních rizik (zástavní práva, věcná břemena, zákazy zcizení, exekuce, přístup). Geocoduje adresu → stáhne ortofoto z ČÚZK WMS (satellite 1024×1024px) + katastrální hranice → flood-fill zvýraznění parcel (cyan) + žluté hranice → AI detekce nezakreslených staveb s bounding boxy. Přeskočí, pokud LV nebylo nahráno.',
        inputs: 'lv_pdf_path (PDF soubor), selected_parcels[] (vybrané parcely z UI), property_address. Vyžaduje MAPY_CZ_API_KEY pro geocoding.',
        outputs: 'risks[] → každé riziko má severity ("vysoké"|"střední"), category, description, recommendation. overall_risk_level. access_assessment (zajištěný/nezajištěný/nelze posoudit). ortofoto_url + ortofoto_annotated_url (s barevnými boxy nad nezakreslenými stavbami). buildings_detected[] s bbox souřadnicemi.',
        thresholds: 'FAIL: 1+ vysoké riziko (zástavní právo / VB užívání / zákaz zcizení / nezajištěný přístup). WARN: 1+ střední riziko. SUCCESS: žádné riziko. Nezakreslená vedlejší stavba >45m² → střední. Přístavba >16m² → střední.',
        prompt: `PROMPT 1 – Právní analýza LV:
Jsi expert na právní analýzu listu vlastnictví pro účely bankovních hypotečních úvěrů.

Tato 3 rizika MUSÍ BÝT VYSOKÉ: Zástavní práva, Věcné břemeno užívání, Zákazy zcizení.
Všechna ostatní MUSÍ BÝT STŘEDNÍ: exekuce, insolvence, plomby, spoluvlastnictví, BPEJ/ZPF.

Přístup: ZAJIŠTĚNÝ pokud přístupová parcela je komunikace OR ve vlastnictví obce/státu OR je VB přístupu OR spoluvlastnictví vlastníka.

---
PROMPT 2 – Ortofoto (detekce nezakreslených staveb):
Jsi expert na analýzu leteckých/satelitních snímků pro účely bankovních ocenění.

Hledej STAVBY na pozemcích, které NEJSOU zakresleny v katastru:
1. Vedlejší stavba >45m² → RIZIKO STŘEDNÍ
2. Přístavba k hlavní stavbě >16m² → RIZIKO STŘEDNÍ

Pro každou detekovanou stavbu uveď bounding box v procentech obrázku (bbox_x, bbox_y, bbox_w, bbox_h).`,
    },
    {
        name: 'Odhadce',
        icon: '💰',
        color: '#10b981',
        description: 'Agent 8 – Tržní ocenění NHZP porovnávací metodou. Hierarchie: (1) Geocoding adresy přes Nominatim (OpenStreetMap), (2) Progressivní vyhledávání inzerátů sreality.cz (2→5→10→15→30 km, fallback celá ČR), (3) AI výběr 3 nejpodobnějších vzorků + přiřazení K1–K8 koeficientů, (4) BACKEND vždy přepočítá NHZP z koeficientů (nedůvěřuje AI aritmetice), (5) Sanity checks → zastropování max cenou vzorků ×1.15 a absolutní strop 25M. Koeficienty jsou sanitizovány do přísných rozsahů. To AI jsou odesílány i fotky oceňované nemovitosti (pro K4/K5).',
        inputs: 'property_data (adresa, plocha, stav, střecha, vytápění), images[] (pro vizuální analýzu stavu). Volitelně valuation_overrides (manuální přepsání z UI).',
        outputs: 'odhad_czk (NHZP v Kč), duvod (komentář k trhu), vzorky[] → pro každý vzorek: cena_czk, velikost, adresa, jc (Kč/m²), io (index odlišnosti), upravena_jc, koeficienty {k1..k8}, zdroj_url, obrazek_url (proxy).',
        thresholds: 'K1=0.85 vždy (rozsah 0.80–0.90). K2–K3=0.90–1.10. K4=0.85–1.15. K5=0.80–1.20. K6:0.90–1.10. K7–K8=0.95–1.05. NHZP cap: min(max_sample×1.15, 25M). Frontend: NHZP capped at 1.5× AI odhad AND max_sample×1.15.',
        prompt: `Jsi soudní znalec a bankovní odhadce nemovitostí s 20letou praxí v ČR.
Provádíš ocenění POROVNÁVACÍ METODOU (NHZP).

POSTUP:
KROK 1 – Vyber přesně 3 NEJPODOBNĚJŠÍ vzorky (velikost > stav > lokalita).
KROK 2 – Ke každému přiřaď K1–K8:
• K = 1.00 → shodná vlastnost
• K < 1.00 → vzorek LEPŠÍ (snížíme upravenou JC)
• K > 1.00 → vzorek HORŠÍ (navýšíme upravenou JC)

POVINNÉ ROZSAHY:
• K1 (Redukce pramene) = VŽDY 0.85 (inzerce o ~15% nad prodejní cenou)
• K2 (Velikost): 0.90–1.10
• K3 (Poloha): 0.90–1.10
• K4 (Provedení/vybavení): 0.85–1.15
• K5 (Celkový stav): 0.80–1.20
• K6 (Vliv pozemku): 0.90–1.10
• K7 (Úvaha znalce): 0.95–1.05
• K8 (Energ. náročnost): 0.95–1.05

KROK 3 – VÝPOČET:
JC_i = cena_i / plocha_i
IO_i = K1 × K2 × K3 × K4 × K5 × K6 × K7 × K8
Upravena_JC_i = JC_i × IO_i
NHZP = průměr(Upravena_JC) × plocha_oceňovaného

Vrať JSON: {nhzp_czk, duvod, plocha_ocenovaneho, vzorky[{id, jc, io, upravena_jc, koeficienty, oduvodneni_koeficientu}]}`,
    },
    {
        name: 'Strateg',
        icon: '🎯',
        color: '#4f46e5',
        description: 'Agent 9 (finální) – Agregace výsledků všech předchozích agentů a stanovení semaforu. Prioritní přehled: Strazce FAIL (neúplné/neaktuální fotkyt) → červená. Inspektor FAIL (špatný stav) → červená. Jakýkoliv FAIL nebo 3+ varování → červená. 1–2 varování → oranžová. Vše OK → zelená. Generuje lidsky čitelný report přes AI (Gemini/GPT).',
        inputs: 'Výsledky všech 8 předchozích agentů (agent_results{}). Vždy spustí jako poslední.',
        outputs: 'semaphore ("ONLINE"|"SUPERVISED"|"VRÁTIT KLIENTOVI"), semaphore_color ("green"|"orange"|"red"), semaphore_reason, final_category (1–5), total_warnings, human_report (čitelný text generovaný AI).',
        thresholds: 'GREEN (ONLINE): 0 varování + 0 selhání. ORANGE (SUPERVISED): 1–2 varování. RED (VRÁTIT KLIENTOVI): Strazce FAIL OR Inspektor FAIL OR jakýkoliv FAIL OR 3+ varování. Inspektor FAIL přepíše kategorii na 5.',
        prompt: `Jsi senior analytik nemovitostí. Napiš stručný, čitelný report česky, profesionálně.
Nepoužívej technický žargon. Nepiš o "agentech" – piš o kontrolách a zjištěních.

STRUKTURA REPORTU:
1. Shrnutí (2-3 věty – celkový verdikt, nejdůležitější zjištění)
2. Fotodokumentace (kompletnost, kvalita)
3. Stav nemovitosti (technický stav, nalezené vady)
4. Věk a kategorizace (efektivní věk, přiřazená kategorie)
5. Ověření autentičnosti (manipulace fotek, GPS ověření lokace)
6. Porovnání dokumentů (shoda/neshoda dat z formuláře s fotodokumentací)
7. Doporučení (co doporučuješ jako další krok)

Piš stručně – každá sekce max 2-3 věty. Pokud je vše v pořádku, řekni "bez nálezu".
Vrať POUZE text reportu, bez markdownu ani JSON.

---
SEMAFOR PRAVIDLA (deterministická logika, nelze ovlivnit promptem):
• Strazce FAIL → VRÁTIT KLIENTOVI (neúplná/neaktuální fotodok.)
• Inspektor FAIL → VRÁTIT KLIENTOVI (špatný tech. stav)
• has_fail OR warns ≥ 3 → VRÁTIT KLIENTOVI
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
            'pypdf (parsování PDF dokumentů)',
            'lv_parser (vlastní parser Listu vlastnictví)',
        ]
    },
    {
        category: 'AI / LLM',
        items: [
            'GPT-4o (primární model – OpenAI kompatibilní endpoint)',
            'Google Gemini 2.0 Flash (fallback / alternativa)',
            'Multimodální prompty (text + obrázky – JPEG bytes)',
            'Structured JSON output (response_format: json_object)',
            'Temperature 0.3 pro výpočty (Odhadce), 0.7 pro analytiku',
        ]
    },
    {
        category: 'Datové zdroje',
        items: [
            'ČÚZK WMS – ortofoto (https://ags.cuzk.gov.cz) + katastrální mapa (hranice_parcel, parcelni_cisla)',
            'ČÚZK Nahlížení – List vlastnictví (parsovaný PDF)',
            'Mapy.cz API v1 – geocoding, reverse geocoding, panorama (800×450)',
            'Sreality.cz (neoficiální) – inzeráty RD (GPS filtr, oblast filtr)',
            'Nominatim / OpenStreetMap – geocoding pro Odhadce',
            'Google Cloud Vision – web detection (stažení fotek z internetu)',
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

', 'WebSocket streaming', 'Pillow (image processing)', 'httpx (async HTTP)'] },
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
