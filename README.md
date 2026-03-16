# Online Validace a Ocenění Rodinných Domů

Tato aplikace slouží k automatizované kontrole vstupních dat a online ocenění rodinných domů (RD). Využívá multi-agentní architekturu postavenou na modelu **Google Gemini 2.0 Flash** k analýze fotografií, dokumentů a tržních dat.

## Hlavní funkce

*   **🛡️ Strazce (Guardian):** Validace úplnosti a aktuálnosti fotodokumentace. Detekuje, zda nechybí klíčové pohledy (zadní/boční) a zda fotky nejsou archivní nebo AI generované.
*   **🔍 Inspektor:** Technická inspekce stavu nemovitosti. Rozhoduje o způsobilosti pro online ocenění na základě statiky, vlhkosti a rozestavěnosti.
*   **🔬 Forenzní Analytik:** Detekce manipulace s fotografiemi a analýza EXIF metadat.
*   **🏛️ Katastrální Analytik:** Integrace s ČÚZK – analýza Listu vlastnictví (LV), kontrola exekucí a detekce nezakreslených staveb na ortofoto mapě.
*   **📍 GeoValidator:** Ověření lokality pomocí GPS a porovnání s panoramatem Mapy.cz.
*   **📋 Porovnávač Dokumentů:** Kontrola shody mezi daty z PDF formuláře a reálným stavem na fotkách (zejména počet podlaží).
*   **💰 Odhadce:** Automatizované ocenění porovnávací metodou. Načítá reálné inzeráty ze `sreality.cz` v okruhu 2–30 km a pomocí AI vybírá nejpodobnější vzorky pro výpočet ceny.
*   **🎯 Strateg:** Finální vyhodnocení a stanovení semaforu (ONLINE / SUPERVISED / VRÁTIT KLIENTOVI).

## Technický stack

*   **Frontend:** Next.js 15 (App Router), TypeScript, React 19.
*   **Backend:** Python 3.14, FastAPI, WebSocket pro real-time streamování výsledků.
*   **AI:** Google Gemini 2.0 Flash (Multimodální analýza).
*   **Data:** API Sreality.cz, Mapy.cz, ČÚZK WMS/KN.

## Jak to funguje

1.  **Nahrání:** Uživatel nahraje fotografie RD, PDF formulář ocenění a volitelně List vlastnictví.
2.  **Analýza:** Spustí se sekvenční pipeline agentů. Každý agent provede svou část kontroly a streamuje logy a výsledky uživateli.
3.  **Výsledek:** Strateg agreguje všechna zjištění, určí tržní cenu (pokud je dům způsobilý) a vygeneruje závěrečný report.

Důraz je kladen na bezpečnost bankovního procesu – pokud fotky nejsou aktuální nebo dům vykazuje statické vady, proces je okamžitě zastaven s požadavkem na fyzickou prohlídku odhadcem.
