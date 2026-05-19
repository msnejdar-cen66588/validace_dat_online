/* AppInfo modal – project overview */
function renderAppInfo(container, onClose) {
  container.innerHTML = `
    <div class="info-overlay" id="info-overlay">
      <div class="info-modal">
        <div class="info-header">
          <h2>ℹ️ O aplikaci</h2>
          <button class="info-close" id="info-close-btn">✕</button>
        </div>
        <div class="info-body">

          <h3>AI Validační Pipeline</h3>
          <p>Automatizovaná kontrola vstupních dat pro online ocenění nemovitostí České spořitelny. Systém zpracovává <strong>rodinné domy (RD)</strong> i <strong>bytové jednotky (BJ)</strong> – jednotlivě i hromadně.</p>

          <h4>🏗️ Režimy zpracování</h4>
          <ul>
            <li><strong>Jednotlivě RD</strong> – nahrání fotek, formuláře a LV jednoho rodinného domu</li>
            <li><strong>Jednotlivě BJ</strong> – nahrání fotek, formuláře, LV a dokumentů k podlahové ploše bytu</li>
            <li><strong>Hromadně RD</strong> – dávkové zpracování více RD případů ze složek</li>
            <li><strong>Hromadně BJ</strong> – dávkové zpracování více BJ případů ze složek</li>
          </ul>

          <h4>🤖 AI Agenti – RD Pipeline (8 agentů, 3 vlny)</h4>
          <ul>
            <li><strong>Vlna A – Fotografie</strong>
              <ul>
                <li>🛡️ <strong>Strážce</strong> – kontrola úplnosti fotodokumentace (BR-G4)</li>
                <li>🔬 <strong>Forenzní analytik</strong> – detekce manipulace a úprav fotografií</li>
                <li>📜 <strong>Historik</strong> – určení věku a kategorizace nemovitosti</li>
                <li>🔍 <strong>Inspektor</strong> – hodnocení technického stavu objektu</li>
              </ul>
            </li>
            <li><strong>Vlna B – Dokumenty & lokace</strong>
              <ul>
                <li>📄 <strong>DocComparator</strong> – porovnání dat z formuláře vs. fotky</li>
                <li>🏛️ <strong>Katastrální analýza</strong> – analýza listu vlastnictví a ortofoto</li>
                <li>📍 <strong>GeoValidator</strong> – ověření GPS lokace + panorama z Mapy.cz</li>
              </ul>
            </li>
            <li><strong>Vlna C – Verdikt</strong>
              <ul>
                <li>🎯 <strong>Stratég</strong> – agregace výsledků, semafor (ZELENÁ / ORANŽOVÁ / ČERVENÁ)</li>
              </ul>
            </li>
          </ul>

          <h4>🏢 AI Agenti – BJ Pipeline</h4>
          <p>Stejná struktura s BJ-specifickými variantami: Strážce BJ, Inspektor BJ, DocComparator BJ (včetně ověření podlahové plochy) a Stratég BJ.</p>

          <h4>📊 Semafor – výsledek validace</h4>
          <ul>
            <li>🟢 <strong>ZELENÁ</strong> – plně online ocenění, bez námitek</li>
            <li>🟠 <strong>ORANŽOVÁ</strong> – vyžaduje dohled odhadce</li>
            <li>🔴 <strong>ČERVENÁ</strong> – vrátit klientovi, závažné problémy</li>
          </ul>

          <h4>📄 PDF Report</h4>
          <p>Automaticky generovaný profesionální protokol o validaci: semafor, porovnání fotky s panoramou, tabulka formulář vs. AI zjištění, přehled agentů.</p>

          <h4>⚙️ Technologie</h4>
          <p>
            Backend: Python / FastAPI / Uvicorn<br>
            Frontend: Vanilla HTML/CSS/JS (SPA)<br>
            AI: Google Gemini / OpenAI kompatibilní<br>
            Mapy: Mapy.cz API (geocoding, panorama, ortofoto)
          </p>

          <h4>📌 Verze</h4>
          <p>Enterprise Local Edition v3.0 – jednoportová Python aplikace. Jednotlivé i hromadné zpracování RD a BJ s real-time WebSocket feedbackem.</p>
        </div>
      </div>
    </div>`;
  container.querySelector('#info-close-btn').onclick = onClose;
  container.querySelector('#info-overlay').onclick = (e) => { if (e.target.id === 'info-overlay') onClose(); };
}
