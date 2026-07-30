const API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000'
  : '';  // same origin in production

let allResults = [];
let currentTicker = null;

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadResults();
  setInterval(loadResults, 60_000); // refresh every 60s

  document.getElementById('run-scan-btn').addEventListener('click', refreshResults);
  document.getElementById('close-detail').addEventListener('click', closeDetail);
  document.getElementById('search-input').addEventListener('input', renderTable);
  document.getElementById('min-score-filter').addEventListener('change', renderTable);
});

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadResults() {
  try {
    const res = await fetch(`${API}/api/scan?limit=100&min_score=0`);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    allResults = data.results || [];
    renderStats();
    renderTable();
    updateLastScanTime();
  } catch (e) {
    showTableError('Could not load scan results. Is the backend running?');
  }
}

async function refreshResults() {
  const btn = document.getElementById('run-scan-btn');
  btn.textContent = 'Refreshing…';
  btn.disabled = true;
  try {
    await loadResults();
  } finally {
    btn.textContent = 'Refresh Results';
    btn.disabled = false;
  }
}

async function loadTickerDetail(ticker) {
  try {
    const res = await fetch(`${API}/api/ticker/${ticker}`);
    if (!res.ok) throw new Error(res.statusText);
    return await res.json();
  } catch {
    return allResults.find(r => r.ticker === ticker) || null;
  }
}

// ── Rendering ─────────────────────────────────────────────────────────────────

function renderStats() {
  const total = allResults.length;
  const highConviction = allResults.filter(r => r.score >= 75).length;
  const negGamma = allResults.filter(r => r.is_negative_gamma).length;
  const avg = total > 0
    ? (allResults.reduce((s, r) => s + r.score, 0) / total).toFixed(1)
    : '—';

  document.getElementById('stat-total').textContent = total;
  document.getElementById('stat-high').textContent = highConviction;
  document.getElementById('stat-neg-gamma').textContent = negGamma;
  document.getElementById('stat-avg').textContent = avg;
}

function renderTable() {
  const query = document.getElementById('search-input').value.trim().toUpperCase();
  const minScore = parseFloat(document.getElementById('min-score-filter').value) || 0;

  const filtered = allResults.filter(r => {
    if (r.score < minScore) return false;
    if (query && !r.ticker.includes(query)) return false;
    return true;
  });

  document.getElementById('result-count').textContent = `${filtered.length} results`;

  const tbody = document.getElementById('scanner-body');
  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="empty-state">No results match your filters.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(r => `
    <tr onclick="openDetail('${r.ticker}')">
      <td><strong>${r.ticker}</strong></td>
      <td>${scorePill(r.score)}</td>
      <td>$${fmt(r.price)}</td>
      <td>${r.short_interest_pct > 0 ? r.short_interest_pct + '%' : '<span class="muted">N/A</span>'}</td>
      <td>${r.float_shares_m > 0 ? r.float_shares_m + 'M' : '<span class="muted">—</span>'}</td>
      <td>${r.call_volume_ratio > 0 ? r.call_volume_ratio + 'x' : '<span class="muted">—</span>'}</td>
      <td>${r.is_negative_gamma
        ? '<span class="gamma-neg">⚡ Negative</span>'
        : '<span class="gamma-pos">Positive</span>'
      }</td>
      <td>${r.iv_percentile > 0 ? r.iv_percentile + '%' : '—'}</td>
      <td>${r.relative_volume > 0 ? r.relative_volume + 'x' : '—'}</td>
      <td>${redditBadge(r.reddit_saturation)}</td>
      <td><button class="btn-sm">Details →</button></td>
    </tr>
  `).join('');
}

function scorePill(score) {
  let cls = 'score-low';
  if (score >= 75) cls = 'score-hot';
  else if (score >= 60) cls = 'score-high';
  else if (score >= 40) cls = 'score-mid';
  return `<span class="score-pill ${cls}">${score}</span>`;
}

function redditBadge(sat) {
  if (sat >= 0.8) return `<span class="reddit-hot">🔥 Crowded</span>`;
  if (sat >= 0.4) return `<span class="reddit-warm">⚠ Warm</span>`;
  return `<span class="reddit-safe">✓ Clear</span>`;
}

// ── Detail panel ──────────────────────────────────────────────────────────────

async function openDetail(ticker) {
  currentTicker = ticker;
  const data = await loadTickerDetail(ticker);
  if (!data) return;

  document.getElementById('detail-title').textContent = `$${ticker} — Score ${data.score}/100`;

  // Gamma map
  const gamma = document.getElementById('gamma-data');
  gamma.innerHTML = [
    ['Current price', `$${fmt(data.price)}`],
    ['Call wall', data.call_wall ? `$${data.call_wall}` : 'N/A'],
    ['Put wall', data.put_wall ? `$${data.put_wall}` : 'N/A'],
    ['Zero gamma', data.zero_gamma ? `$${data.zero_gamma}` : 'N/A'],
    ['Net GEX', data.net_gex ? formatGex(data.net_gex) : 'N/A'],
    ['Gamma env.', data.is_negative_gamma ? '⚡ Negative (squeeze fuel)' : 'Positive (stabilising)'],
  ].map(([k, v]) => `<div class="kv-row"><span class="kv-label">${k}</span><span class="kv-value">${v}</span></div>`).join('');

  // Volume zones
  const zones = document.getElementById('zones-data');
  const zoneList = data.volume_zones || [];
  if (zoneList.length > 0) {
    zones.innerHTML = zoneList.map(z => `
      <div class="zone-card">
        <span class="zone-range">$${z.low} – $${z.high}</span>
        <span class="zone-pct">${z.volume_pct}% of 30d vol</span>
      </div>
    `).join('');
    zones.insertAdjacentHTML('afterbegin', '<p style="font-size:11px;color:var(--muted);margin-bottom:8px">High-volume accumulation zones (30-day volume profile). Upgrade to Unusual Whales API for actual dark pool prints.</p>');
  } else {
    zones.innerHTML = `<p class="muted" style="font-size:12px;color:var(--muted)">No significant zones detected.</p>`;
  }

  // Score breakdown
  const bd = document.getElementById('breakdown-data');
  const breakdown = data.score_breakdown || {};
  const maxPts = {
    short_interest: 20, float: 10, price_trend: 10,
    call_volume: 15, gamma: 12, call_oi_buildup: 10, iv_expansion: 8,
    level_break: 8, relative_volume: 7,
    reddit_danger: 15, already_squeezed: 10,
  };
  const labels = {
    short_interest: 'Short interest', float: 'Float size', price_trend: 'Price trend',
    call_volume: 'Call volume', gamma: 'Gamma', call_oi_buildup: 'Call OI buildup',
    iv_expansion: 'IV expansion', level_break: 'Level break', relative_volume: 'Rel volume',
    reddit_danger: 'Reddit danger', already_squeezed: 'Already squeezed',
  };

  bd.innerHTML = Object.entries(breakdown)
    .filter(([k]) => k !== 'total')
    .map(([key, pts]) => {
      const max = maxPts[key] || 10;
      const pct = Math.min(Math.abs(pts) / max * 100, 100);
      const isNeg = pts < 0;
      return `
        <div class="breakdown-bar-row">
          <span class="breakdown-label">${labels[key] || key}</span>
          <div class="breakdown-bar-bg">
            <div class="breakdown-bar-fill ${isNeg ? 'negative' : ''}" style="width:${pct}%"></div>
          </div>
          <span class="breakdown-pts" style="color:${isNeg ? 'var(--red)' : 'var(--text)'}">${pts > 0 ? '+' : ''}${pts}</span>
        </div>
      `;
    }).join('');

  // Alert preview
  document.getElementById('alert-preview').textContent = buildAlertPreview(data);

  const panel = document.getElementById('detail-panel');
  panel.style.display = 'block';
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeDetail() {
  document.getElementById('detail-panel').style.display = 'none';
  currentTicker = null;
}

function buildAlertPreview(d) {
  const trigger = d.price ? `$${(d.price * 1.03).toFixed(2)}` : 'N/A';
  const risk = d.price ? `$${(d.price * 0.95).toFixed(2)}` : 'N/A';
  const gammaLine = d.is_negative_gamma ? 'Negative above price (squeeze fuel)' : 'Positive';
  const zones = d.volume_zones || [];
  const zoneText = zones.length > 0
    ? `\nVolume zone: $${zones[0].low} – $${zones[0].high}`
    : '';

  return `🔥 Squeeze Radar Alert

$${d.ticker} score: ${d.score}/100

Short interest: ${d.short_interest_pct || '?'}% float
Float: ${d.float_shares_m || '?'}M shares
Call volume: ${d.call_volume_ratio || '?'}x normal
Gamma: ${gammaLine}
Call wall: ${d.call_wall ? '$' + d.call_wall : 'N/A'}
Put wall: ${d.put_wall ? '$' + d.put_wall : 'N/A'}
Zero gamma: ${d.zero_gamma ? '$' + d.zero_gamma : 'N/A'}${zoneText}

Trigger: break above ${trigger} with volume
Risk: failed breakout under ${risk}`;
}

// ── Utilities ──────────────────────────────────────────────────────────────────

function fmt(n) {
  if (!n) return '—';
  return parseFloat(n).toFixed(2);
}

function formatGex(gex) {
  const abs = Math.abs(gex);
  const sign = gex < 0 ? '-' : '+';
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
  if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function updateLastScanTime() {
  if (allResults.length > 0 && allResults[0].scanned_at) {
    const d = new Date(allResults[0].scanned_at + 'Z');
    document.getElementById('last-scan-time').textContent =
      `Last scan: ${d.toLocaleTimeString()}`;
  }
}

function showTableError(msg) {
  document.getElementById('scanner-body').innerHTML =
    `<tr><td colspan="11" class="empty-state" style="color:var(--red)">${msg}</td></tr>`;
}
