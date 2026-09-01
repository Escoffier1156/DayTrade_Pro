import { api } from './api';
import type { Target, TradeLog } from './types';
import { TargetChart } from './chart';

// DOM Elements
const timeDisplay = document.getElementById('header-time')!;
const watchlistGrid = document.getElementById('watchlist-grid')!;
const logBody = document.getElementById('trade-log-body')!;
const chartContainer = document.getElementById('main-chart')!;
const chartTitle = document.getElementById('chart-title')!;
const statsHeader = document.getElementById('stats-header-row')!;
const statsBody = document.getElementById('stats-body')!;
const headerRlz = document.getElementById('header-rlz')!;
const headerUnrlz = document.getElementById('header-unrlz')!;
const panelUnrlz = document.getElementById('panel-unrlz')!;
const contextMenu = document.getElementById('context-menu')!;
const cmTp = document.getElementById('cm-tp')!;
const cmSl = document.getElementById('cm-sl')!;
const cmCancelTp = document.getElementById('cm-cancel-tp')!;

// State
let targetsData: Target[] = [];
let historyData: TradeLog[] = [];
let selectedSymbol: string | null = null;
let mainChart: TargetChart | null = null;
let contextMenuTarget: string | null = null;

// Hide context menu on global click
document.addEventListener('click', () => {
  contextMenu.style.display = 'none';
});

async function handleManualAction(action: 'TP' | 'SL' | 'CANCEL_TP') {
  if (!contextMenuTarget) return;
  
  let msg = '';
  if (action === 'TP') msg = `【${contextMenuTarget}】の利確を実行しますか？`;
  else if (action === 'SL') msg = `【${contextMenuTarget}】の損切を実行しますか？`;
  else if (action === 'CANCEL_TP') msg = `【${contextMenuTarget}】の利確を取り消してOPENに戻しますか？`;
  
  if (!confirm(msg)) return;
  
  try {
    const res = await fetch('/api/action?k=l5cL0jRp9Yzcj_dRutcc43zNmZG0oOFb', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker: contextMenuTarget, action })
    });
    if (res.ok) {
      alert('リクエストを送信しました！(数秒後に反映されます)');
    } else {
      alert('エラーが発生しました。');
    }
  } catch (e) {
    alert('通信エラー: ' + e);
  }
}

cmTp.addEventListener('click', () => handleManualAction('TP'));
cmSl.addEventListener('click', () => handleManualAction('SL'));
cmCancelTp.addEventListener('click', () => handleManualAction('CANCEL_TP'));

const btnNotifyReport = document.getElementById('btn-notify-report');
const reportModal = document.getElementById('report-modal');
const previewText = document.getElementById('report-preview-text');
const btnCancelReport = document.getElementById('btn-cancel-report');
const btnConfirmReport = document.getElementById('btn-confirm-report');

if (btnNotifyReport && reportModal && previewText && btnCancelReport && btnConfirmReport) {
  btnNotifyReport.addEventListener('click', async () => {
    try {
      const res = await fetch('/api/preview_report?k=l5cL0jRp9Yzcj_dRutcc43zNmZG0oOFb');
      if (res.ok) {
        const data = await res.json();
        previewText.textContent = data.text || 'No text';
        reportModal.style.display = 'flex';
      } else {
        alert('プレビューの取得に失敗しました。');
      }
    } catch (e) {
      alert('通信エラー: ' + e);
    }
  });

  btnCancelReport.addEventListener('click', () => {
    reportModal.style.display = 'none';
  });

  btnConfirmReport.addEventListener('click', async () => {
    reportModal.style.display = 'none';
    try {
      const res = await fetch('/api/report?k=l5cL0jRp9Yzcj_dRutcc43zNmZG0oOFb', { method: 'POST' });
      if (res.ok) {
        alert('レポート通知リクエストを送信しました！(数秒後にSlackに投稿されます)');
      } else {
        alert('エラーが発生しました。');
      }
    } catch (e) {
      alert('通信エラー: ' + e);
    }
  });
}

function formatYen(num: number): string {
  return new Intl.NumberFormat('ja-JP').format(num);
}

function calculateTPProgress(entry: number, current: number, tp: number): number {
  if (current >= tp) return 100;
  if (current <= entry) return 0;
  return ((current - entry) / (tp - entry)) * 100;
}

function calculateSLRisk(entry: number, current: number, sl: number): number {
  if (current <= sl) return 100; // 100% risk reached
  if (current >= entry) return 0;
  return ((entry - current) / (entry - sl)) * 100;
}

// Clock
const JPHolidays = [
  "2026-01-01", "2026-01-12", "2026-02-11", "2026-02-23", "2026-03-20",
  "2026-04-29", "2026-05-03", "2026-05-04", "2026-05-05", "2026-05-06",
  "2026-07-20", "2026-08-11", "2026-09-21", "2026-09-22", "2026-09-23",
  "2026-10-12", "2026-11-03", "2026-11-23", "2026-12-31",
  "2027-01-01", "2027-01-02", "2027-01-03", "2027-01-11"
];

function isMarketClosedDay(date: Date) {
  if (date.getDay() === 0 || date.getDay() === 6) return true;
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, '0');
  const dd = String(date.getDate()).padStart(2, '0');
  return JPHolidays.includes(`${yyyy}-${mm}-${dd}`);
}

function updateTime() {
  const now = new Date();
  timeDisplay.textContent = now.toLocaleTimeString('ja-JP', { hour12: false });
  
  const hm = now.getHours() * 100 + now.getMinutes();
  const isClosedDay = isMarketClosedDay(now);
  const badge = document.getElementById('live-badge');
  const overlay = document.getElementById('market-closed-overlay');
  
  if (overlay) {
    if (isClosedDay) {
      overlay.style.display = 'flex';
    } else {
      overlay.style.display = 'none';
    }
  }
  
  if (badge) {
    if (isClosedDay || hm >= 1530 || hm < 900) {
      badge.textContent = 'MARKET CLOSED';
      badge.style.background = '#4b5563'; // gray
      badge.style.color = 'white';
    } else {
      badge.textContent = 'LIVE SIM';
      badge.style.background = 'var(--text-amber)';
      badge.style.color = 'black';
    }
  }
}

setInterval(updateTime, 1000);

function renderWatchlist() {
  watchlistGrid.innerHTML = '';
  targetsData.forEach(target => {
    const card = document.createElement('div');
    const isActive = selectedSymbol === target.code;
    card.className = `watchlist-card ${isActive ? 'active' : ''}`;
    
    const pctChange = ((target.latest_price / target.entry_price) - 1) * 100;
    const isUp = pctChange >= 0;
    const colorClass = isUp ? 'text-green' : 'text-red';
    const sign = isUp ? '+' : '';
    
    const tpProgress = calculateTPProgress(target.entry_price, target.latest_price, target.target);
    const slRisk = calculateSLRisk(target.entry_price, target.latest_price, target.stop);

    card.innerHTML = `
      <div class="card-top">
        <span class="code">${target.code} ${target.name || ''}</span>
        <span class="status ${target.status === 'OPEN' ? 'text-amber' : (target.status === 'HIT_TP' ? 'text-green' : 'text-red')}">${target.status}</span>
      </div>
      <div class="card-price ${colorClass}">
        ${formatYen(target.latest_price)} <span class="pct">${sign}${pctChange.toFixed(2)}%</span>
      </div>
      <div style="font-size: 10px; color: #9ca3af; margin-bottom: 8px;">
        Position Size: &yen;${formatYen(target.entry_price * target.shares)} (${target.shares} shares)
      </div>
      
      <div class="progress-section">
        <div class="progress-bar-container">
          <div class="progress-label">TP <span class="text-green">${tpProgress.toFixed(0)}%</span></div>
          <div class="progress-track">
            <div class="progress-fill tp-fill" style="width: ${tpProgress}%"></div>
          </div>
        </div>
        <div class="progress-bar-container">
          <div class="progress-label">SL <span class="text-red">${slRisk.toFixed(0)}%</span></div>
          <div class="progress-track">
            <div class="progress-fill sl-fill" style="width: ${slRisk}%"></div>
          </div>
        </div>
      </div>
    `;

    card.addEventListener('click', () => {
      selectedSymbol = target.code;
      renderWatchlist(); // re-render to update active class
      updateMainChart();
    });

    card.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      contextMenuTarget = target.code;
      contextMenu.style.display = 'block';
      contextMenu.style.left = `${e.pageX}px`;
      contextMenu.style.top = `${e.pageY}px`;
    });

    watchlistGrid.appendChild(card);
  });
}

function updateMainChart() {
  if (!mainChart) {
    mainChart = new TargetChart(chartContainer);
  }
  
  if (!selectedSymbol && targetsData.length > 0) {
    selectedSymbol = targetsData[0].code;
  }
  
  const target = targetsData.find(t => t.code === selectedSymbol);
  if (target) {
    chartTitle.textContent = `GP - ${target.code} ${target.name}`;
    
    // Reset chart to clear old lines, then redraw
    mainChart.remove();
    mainChart = new TargetChart(chartContainer);
    
    mainChart.addPriceLines(target);
    mainChart.setData(target);
  } else {
    chartTitle.textContent = `GP - CHART (NO SELECTION)`;
  }
}

function renderHistory() {
  logBody.innerHTML = '';
  // Sort reverse chronologically by date and time
  const sorted = [...historyData].sort((a, b) => {
    const dateA = a.date || '';
    const dateB = b.date || '';
    if (dateA !== dateB) return dateA > dateB ? -1 : 1;
    return a.time > b.time ? -1 : 1;
  });

  // Group by date
  const grouped: Record<string, TradeLog[]> = {};
  sorted.forEach(log => {
    const d = log.date || 'Unknown';
    if (!grouped[d]) grouped[d] = [];
    grouped[d].push(log);
  });

  const todayStr = new Date().toLocaleDateString('sv-SE'); // YYYY-MM-DD in local time
  let todayTotalPnl = 0;
  
  if (grouped[todayStr]) {
    todayTotalPnl = grouped[todayStr].reduce((sum, log) => sum + log.pnl, 0);
  }

  for (const [date, logs] of Object.entries(grouped)) {
    let datePnl = 0;
    logs.forEach(l => datePnl += l.pnl);
    
    // Create header row
    const headerTr = document.createElement('tr');
    headerTr.className = 'date-group-header';
    const pnlColor = datePnl >= 0 ? 'text-green' : 'text-red';
    const pnlSign = datePnl >= 0 ? '+' : '';
    
    const isToday = date === todayStr;
    const isExpanded = isToday; // Today starts expanded, others collapsed
    
    headerTr.innerHTML = `
      <td colspan="5" style="text-align: left; cursor: pointer; padding-left: 8px;">
        <span class="accordion-icon" style="display: inline-block; width: 12px;">${isExpanded ? '▼' : '▶'}</span> 
        <span style="font-weight: bold; color: #cbd5e1;">${date}</span>
      </td>
      <td class="${pnlColor}" style="font-weight: bold;">${pnlSign}${formatYen(datePnl)}</td>
    `;
    
    logBody.appendChild(headerTr);
    
    const rowElements: HTMLTableRowElement[] = [];
    
    logs.forEach(log => {
      const isWin = log.pnl >= 0;
      const colorClass = isWin ? 'text-green' : 'text-red';
      const sign = isWin ? '+' : '';
      
      const tr = document.createElement('tr');
      tr.className = `trade-row`;
      if (!isExpanded) tr.style.display = 'none';
      
      tr.innerHTML = `
        <td>${log.time}</td>
        <td class="text-amber">${log.ticker}</td>
        <td>${log.side}</td>
        <td>${formatYen(log.qty)}</td>
        <td>${formatYen(log.price)}</td>
        <td class="${colorClass}">${sign}${formatYen(log.pnl)}</td>
      `;
      logBody.appendChild(tr);
      rowElements.push(tr);
    });
    
    // Accordion toggle
    headerTr.addEventListener('click', () => {
      const currentlyHidden = rowElements[0]?.style.display === 'none';
      const icon = headerTr.querySelector('.accordion-icon');
      if (currentlyHidden) {
        rowElements.forEach(r => r.style.display = '');
        if (icon) icon.textContent = '▼';
      } else {
        rowElements.forEach(r => r.style.display = 'none');
        if (icon) icon.textContent = '▶';
      }
    });
  }

  // Update header RLZ for TODAY only
  const pnlColor = todayTotalPnl >= 0 ? 'text-green' : 'text-red';
  const pnlSign = todayTotalPnl >= 0 ? '+' : '';
  const rlzPct = ((todayTotalPnl / 10000000) * 100).toFixed(2);
  
  headerRlz.innerHTML = `TODAY RLZ <span class="${pnlColor}">${pnlSign}&yen;${formatYen(todayTotalPnl)} (${pnlSign}${rlzPct}%)</span>`;
  headerRlz.className = pnlColor;
}

function updateUnrealizedPnL() {
  let unrlz = 0;
  targetsData.forEach(t => {
    if (t.status === 'OPEN') {
      const diff = t.latest_price - t.entry_price;
      unrlz += diff * t.shares;
    }
  });
  
  const pnlColor = unrlz >= 0 ? 'text-green' : 'text-red';
  const pnlSign = unrlz >= 0 ? '+' : '';
  const unrlzPct = ((unrlz / 10000000) * 100).toFixed(2);
  const formatted = `${pnlSign}&yen;${formatYen(unrlz)} (${pnlSign}${unrlzPct}%)`;
  
  headerUnrlz.innerHTML = `UNRLZ <span class="${pnlColor}">${formatted}</span>`;
  headerUnrlz.className = pnlColor;
  
  panelUnrlz.innerHTML = `UNREALIZED P&L: <span class="${pnlColor}">${formatted}</span>`;
}

function renderStats() {
  // Clear headers except first
  while (statsHeader.children.length > 1) {
    statsHeader.removeChild(statsHeader.lastChild!);
  }
  
  targetsData.forEach(t => {
    const th = document.createElement('th');
    const pctChange = ((t.latest_price / t.entry_price) - 1) * 100;
    const isUp = pctChange >= 0;
    const colorClass = isUp ? 'text-green' : 'text-red';
    const sign = isUp ? '+' : '';
    th.innerHTML = `${t.code} ${t.name || ''} &lt;Equity&gt; <span class="${colorClass}">${formatYen(t.latest_price)} ${sign}${pctChange.toFixed(2)}%</span>`;
    statsHeader.appendChild(th);
  });

  const rows = [
    { label: 'Current Price', key: 'latest_price' },
    { label: 'Take Profit (TP)', key: 'target' },
    { label: 'Entry Price', key: 'entry_price' },
    { label: 'Stop Loss (SL)', key: 'stop' },
    { label: 'Lot Size', key: 'shares' },
    { label: 'Status', key: 'status' }
  ];

  statsBody.innerHTML = '';
  rows.forEach(r => {
    const tr = document.createElement('tr');
    tr.innerHTML = `<th class="stats-label">${r.label}</th>`;
    targetsData.forEach(t => {
      const td = document.createElement('td');
      let val = (t as any)[r.key];
      
      if (val === undefined || val === null) {
        td.textContent = '-';
      } else if (r.key === 'status') {
        const color = val === 'OPEN' ? 'text-amber' : (val === 'HIT_TP' ? 'text-green' : 'text-red');
        td.innerHTML = `<span class="${color}">${val}</span>`;
      } else if (typeof val === 'number') {
        if (r.key === 'volume' || r.key === 'trades' || r.key === 'shares') {
          td.textContent = new Intl.NumberFormat('ja-JP').format(val);
        } else {
          td.textContent = formatYen(val);
        }
      } else {
        td.textContent = val.toString();
      }
      tr.appendChild(td);
    });
    statsBody.appendChild(tr);
  });
}

// --- Resize Handlers ---
const watchlistPanel = document.querySelector('.panel-watchlist') as HTMLElement;
const handleY = document.querySelector('.resize-handle-y') as HTMLElement;
let isResizingY = false;

if (handleY && watchlistPanel) {
  handleY.addEventListener('mousedown', (e) => {
    isResizingY = true;
    document.body.style.cursor = 'ns-resize';
    e.preventDefault();
  });
}

const logPanel = document.querySelector('.panel-log') as HTMLElement;
const handleX = document.querySelector('.resize-handle-x') as HTMLElement;
let isResizingX = false;

if (handleX && logPanel) {
  handleX.addEventListener('mousedown', (e) => {
    isResizingX = true;
    document.body.style.cursor = 'ew-resize';
    e.preventDefault();
  });
}

document.addEventListener('mousemove', (e) => {
  if (isResizingY) {
    const newHeight = e.clientY - watchlistPanel.getBoundingClientRect().top;
    watchlistPanel.style.height = `${Math.max(80, newHeight)}px`;
  }
  if (isResizingX) {
    const newWidth = logPanel.getBoundingClientRect().right - e.clientX;
    logPanel.style.width = `${Math.max(150, newWidth)}px`;
  }
});

document.addEventListener('mouseup', () => {
  if (isResizingY || isResizingX) {
    isResizingY = false;
    isResizingX = false;
    document.body.style.cursor = 'default';
  }
});

// --- Initialization ---
async function sync() {
  try {
    const [targetsRes, historyRes] = await Promise.all([
      api.getTargets(),
      api.getHistory()
    ]);
    
    targetsData = targetsRes.targets || [];
    historyData = historyRes || [];
    
    // Set default selection if none
    if (!selectedSymbol && targetsData.length > 0) {
      selectedSymbol = targetsData[0].code;
    }
    
    renderWatchlist();
    updateMainChart();
    renderHistory();
    renderStats();
    updateUnrealizedPnL();
    
  } catch (err) {
    console.error("Failed to sync data:", err);
  }
}

sync();
setInterval(sync, 15000);
