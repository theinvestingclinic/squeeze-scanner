const API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://localhost:8000'
  : '';  // same origin in production

let allResults = [];
let currentTicker = null;
let latestMeta = {};

// ── Boot ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  loadResults();
  setInterval(() => {
    if (document.visibilityState === 'visible') loadResults();
  }, 300_000);

  document.getElementById('run-scan-btn').addEventListener('click', refreshResults);
  document.getElementById('close-detail').addEventListener('click', closeDetail);
  document.getElementById('search-input').addEventListener('input', renderTable);
  document.getElementById('min-score-filter').addEventListener('change', renderTable);
});

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadResults() {
  try {
    const res = await fetch(`${API}/api/scan?limit=50&min_score=0`);
    if (!res.ok) throw new Error(res.statusText);
    const data = await res.json();
    allResults = data.results || [];
    latestMeta = data;
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
  document.getElementById('stat-total').textContent = latestMeta.eligible_count ?? allResults.length;
  document.getElementById('stat-high').textContent = latestMeta.active_trigger_count ?? 0;
  document.getElementById('stat-neg-gamma').textContent = latestMeta.setup_watch_count ?? 0;
  document.getElementById('stat-avg').textContent = latestMeta.last_completed
    ? new Date(latestMeta.last_completed + 'Z').toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})
    : '—';
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
    tbody.innerHTML = `<tr><td colspan="11" class="empty-state">No active candidates meet this threshold. Quiet is a valid result.</td></tr>`;
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
      <td>${redditBadge(r)}</td>
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

function redditBadge(result) {
  if (!result.reddit_data_available) return `<span class="muted">Unavailable</span>`;
  const sat = result.reddit_saturation || 0;
  if (sat >= 0.8) return `<span class="reddit-hot">🔥 Crowded</span>`;
  if (sat >= 0.4) return `<span class="reddit-warm">⚠ Warm</span>`;
  return `<span class="reddit-safe">✓ Clear</span>`;
}

// ── Detail panel ──────────────────────────────────────────────────────────────

async function openDetail(ticker) {
  currentTicker = ticker;
  const data = await loadTickerDetail(ticker);
  if (!data) return;

  const state = data.signal_state === 'active_trigger' ? 'Active trigger'
    : data.signal_state === 'setup_watch' ? 'Setup watch' : 'Monitor';
  document.getElementById('detail-title').textContent = `$${ticker} — ${state} · ${data.score}/100`;

  // Gamma map
  const gamma = document.getElementById('gamma-data');
  gamma.innerHTML = [
    ['Current price', `$${fmt(data.price)}`],
    ['Call wall', data.call_wall ? `$${data.call_wall}` : 'N/A'],
    ['Put wall', data.put_wall ? `$${data.put_wall}` : 'N/A'],
    ['Zero gamma', data.zero_gamma ? `$${data.zero_gamma}` : 'N/A'],
    ['Net GEX proxy', data.net_gex ? formatGex(data.net_gex) : 'N/A'],
    ['Options-OI gamma proxy', data.is_negative_gamma ? 'Negative (amplification risk)' : 'Positive'],
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
    zones.insertAdjacentHTML('afterbegin', '<p style="font-size:11px;color:var(--muted);margin-bottom:8px">Price-volume clusters from the last 30 days. These are not institutional or dark-pool prints.</p>');
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

  const skipped = new Set(['total', 'setup_score', 'trigger_score', '_data_quality', '_eligibility']);
  bd.innerHTML = Object.entries(breakdown)
    .filter(([k, v]) => !skipped.has(k) && typeof v === 'number')
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

  const panel = document.getElementById('detail-panel');
  panel.style.display = 'block';
  panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function closeDetail() {
  document.getElementById('detail-panel').style.display = 'none';
  currentTicker = null;
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
