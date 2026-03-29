const state = {
  selectedOpportunityId: null,
  payloads: {},
};

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
});

const percent = new Intl.NumberFormat("en-US", {
  style: "percent",
  maximumFractionDigits: 2,
});

const byId = (id) => document.getElementById(id);

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`${url} failed`);
  }
  return response.json();
}

function formatMoney(value) {
  return money.format(Number(value || 0));
}

function formatPercent(value) {
  return percent.format(Number(value || 0));
}

function formatDate(value) {
  if (!value) return "N/A";
  return new Date(value).toLocaleString();
}

function statusClass(status) {
  return status === "approved" ? "approved" : status === "blocked" ? "blocked" : "watch";
}

function renderOverview() {
  const overview = state.payloads.health ? state.payloads.overview : null;
  const analytics = state.payloads.analytics || {};
  const claude = state.payloads.health?.claude || {};
  if (!overview) return;

  const cards = [
    ["Bankroll", formatMoney(overview.bankroll), `Mode ${overview.mode}${state.payloads.health?.using_demo_data ? " • demo data" : ""}`],
    ["Realized PnL", formatMoney(overview.realized_pnl), "Closed and booked"],
    ["Unrealized PnL", formatMoney(overview.unrealized_pnl), "Open exposure"],
    ["Active Positions", `${overview.active_positions}`, `${overview.concurrent_positions} concurrent`],
    ["Blocked Trades", `${overview.blocked_trades}`, "Deterministic filters"],
    ["Max Drawdown", formatPercent(analytics.max_drawdown || 0), "New entries block at 8%"],
  ];

  byId("overview-grid").innerHTML = cards
    .map(
      ([label, value, foot]) => `
        <article class="metric-card">
          <div class="metric-label">${label}</div>
          <div class="metric-value">${value}</div>
          <div class="metric-foot">${foot}</div>
        </article>
      `
    )
    .join("");

  byId("mode-chip").textContent = `Mode: ${overview.mode} • Claude: ${claude.state || "idle"}`;
}

function renderOpportunities() {
  const opportunities = state.payloads.opportunities || [];
  if (!state.selectedOpportunityId && opportunities[0]) {
    state.selectedOpportunityId = opportunities[0].opportunity_id;
  }

  byId("opportunity-feed").innerHTML =
    opportunities.length === 0
      ? `<div class="empty">No opportunities found yet.</div>`
      : opportunities
          .map(
            (opportunity) => `
            <article class="feed-item ${state.selectedOpportunityId === opportunity.opportunity_id ? "active" : ""}" data-opportunity-id="${opportunity.opportunity_id}">
              <div class="feed-row">
                <div>
                  <div class="feed-title">${opportunity.question}</div>
                  <div class="feed-subtitle">${opportunity.strategy_type} • ${opportunity.category}</div>
                </div>
                <div class="badge ${statusClass(opportunity.status)}">${opportunity.status}</div>
              </div>
              <div class="pill-row" style="margin-top:0.9rem;">
                <span class="pill">Net edge ${formatPercent(opportunity.net_edge)}</span>
                <span class="pill">Fill ${formatPercent(opportunity.fill_confidence)}</span>
                <span class="pill">Liquidity ${formatPercent(opportunity.liquidity_score)}</span>
              </div>
            </article>
          `
          )
          .join("");

  byId("scan-timestamp").textContent = state.payloads.health?.last_scan_at
    ? `Last scan ${formatDate(state.payloads.health.last_scan_at)}`
    : "Waiting for scan";

  document.querySelectorAll("[data-opportunity-id]").forEach((node) => {
    node.addEventListener("click", () => {
      state.selectedOpportunityId = node.dataset.opportunityId;
      renderOpportunities();
      renderMarketDetail();
    });
  });
}

function renderMarketDetail() {
  const opportunities = state.payloads.opportunities || [];
  const markets = state.payloads.markets || [];
  const selected = opportunities.find((item) => item.opportunity_id === state.selectedOpportunityId) || opportunities[0];
  if (!selected) {
    byId("market-detail").innerHTML = `<div class="empty">Select an opportunity to inspect execution context.</div>`;
    return;
  }

  const market = markets.find((item) => item.market_id === selected.market_id) || {};
  const risk = selected.risk || { reasons: [], blocked_by: [], metrics: {}, sizing: {} };
  const analytics = state.payloads.analytics || {};
  byId("market-detail").innerHTML = `
    <div class="stack">
      <div class="detail-block">
        <strong>${selected.question}</strong>
        <p class="detail-copy">${selected.rationale}</p>
      </div>

      <div class="detail-grid">
        <div class="detail-block">
          <div class="eyebrow">Pricing</div>
          <div class="detail-row"><span>YES</span><strong>${formatPercent(market.yes_price || 0)}</strong></div>
          <div class="detail-row"><span>NO</span><strong>${formatPercent(market.no_price || 0)}</strong></div>
          <div class="detail-row"><span>Net edge</span><strong>${formatPercent(selected.net_edge)}</strong></div>
        </div>
        <div class="detail-block">
          <div class="eyebrow">Execution</div>
          <div class="detail-row"><span>Capital at risk</span><strong>${formatMoney(selected.capital_at_risk)}</strong></div>
          <div class="detail-row"><span>Expected profit</span><strong>${formatMoney(selected.expected_profit)}</strong></div>
          <div class="detail-row"><span>Sizing cap</span><strong>${formatPercent(risk.sizing?.capped_fraction || 0)}</strong></div>
        </div>
        <div class="detail-block">
          <div class="eyebrow">Risk verdict</div>
          <div class="detail-row"><span>Approved</span><strong>${risk.approved ? "Yes" : "No"}</strong></div>
          <div class="detail-row"><span>Blocks</span><strong>${(risk.blocked_by || []).join(", ") || "None"}</strong></div>
          <p class="detail-copy">${(risk.reasons || []).join(" ")}</p>
        </div>
        <div class="detail-block">
          <div class="eyebrow">Equity trend</div>
          ${drawSparkline(analytics.equity_curve || [10000])}
        </div>
      </div>
    </div>
  `;

  const executeButton = byId("execute-button");
  executeButton.disabled = !risk.approved;
  executeButton.textContent = risk.approved ? "Paper Execute" : "Blocked";
}

function renderRisk() {
  const risk = state.payloads.risk || {};
  const exposures = Object.entries(risk.category_exposure || {});
  byId("risk-panel").innerHTML = `
    <div class="stack">
      <div class="detail-block">
        <div class="detail-row"><span>Kill switch</span><strong>${risk.kill_switch ? "ACTIVE" : "clear"}</strong></div>
        <div class="detail-row"><span>Daily loss</span><strong>${formatMoney(risk.daily_loss)}</strong></div>
        <div class="detail-row"><span>Drawdown</span><strong>${formatPercent(risk.drawdown_fraction || 0)}</strong></div>
      </div>
      <div class="detail-block">
        <div class="eyebrow">Category exposure</div>
        ${
          exposures.length
            ? exposures.map(([category, value]) => `<div class="detail-row"><span>${category}</span><strong>${formatMoney(value)}</strong></div>`).join("")
            : `<p class="detail-copy">No active category exposure.</p>`
        }
      </div>
      <div class="detail-block">
        <div class="eyebrow">Recent warnings</div>
        ${
          (risk.open_risk_checks || []).length
            ? risk.open_risk_checks.map((item) => `<p class="detail-copy">${item}</p>`).join("")
            : `<p class="detail-copy">No recent risk alerts.</p>`
        }
      </div>
    </div>
  `;
}

function renderAgent() {
  const agent = state.payloads.agent || { notes: [], summary: "", claude: {} };
  const claude = agent.claude || {};
  byId("agent-panel").innerHTML = `
    <div class="stack">
      <div class="detail-block">
        <div class="eyebrow">Claude status</div>
        <div class="detail-row"><span>State</span><strong>${claude.state || "unknown"}</strong></div>
        <div class="detail-row"><span>Model</span><strong>${claude.model || "N/A"}</strong></div>
        <p class="detail-copy">${claude.message || "No Claude status yet."}</p>
        ${claude.error?.body ? `<p class="detail-copy">API detail: ${claude.error.body}</p>` : ""}
        ${claude.error?.message ? `<p class="detail-copy">Transport detail: ${claude.error.message}</p>` : ""}
      </div>
      <div class="detail-block">
        <div class="eyebrow">Daily recap</div>
        <p class="detail-copy">${agent.summary || "No summary yet."}</p>
      </div>
      ${
        (agent.notes || []).length
          ? agent.notes
              .map(
                (note) => `
                <div class="timeline-item">
                  <div class="feed-row">
                    <strong>${note.title}</strong>
                    <span class="muted">${formatDate(note.created_at)}</span>
                  </div>
                  <p class="detail-copy" style="margin-top:0.55rem;">${note.body}</p>
                </div>
              `
              )
              .join("")
          : `<div class="empty">Claude insights will appear here after scanning.</div>`
      }
    </div>
  `;
}

function renderSettings() {
  const settings = state.payloads.settings || {};
  const claude = settings.claude || {};
  byId("settings-panel").innerHTML = `
    <div class="stack">
      <div class="detail-block">
        <div class="setting-line"><span>Live trading enabled</span><strong>${settings.app?.enable_live_trading ? "Yes" : "No"}</strong></div>
        <div class="setting-line"><span>Research mode</span><strong>${settings.app?.enable_research_mode ? "On" : "Off"}</strong></div>
        <div class="setting-line"><span>Demo data active</span><strong>${settings.using_demo_data ? "Yes" : "No"}</strong></div>
        <div class="setting-line"><span>Refresh</span><strong>${settings.scanner?.refresh_seconds || 0}s</strong></div>
        <div class="setting-line"><span>Min net edge</span><strong>${formatPercent(settings.risk?.min_net_edge || 0)}</strong></div>
      </div>
      <div class="detail-block">
        <div class="eyebrow">App mode</div>
        <div class="setting-line"><span>Current mode</span><strong>${settings.current_mode || settings.app?.mode || "unknown"}</strong></div>
        <select class="mode-select" id="app-mode-select">
          ${(settings.available_modes || []).map((mode) => `<option value="${mode}" ${mode === (settings.current_mode || settings.app?.mode) ? "selected" : ""}>${mode}</option>`).join("")}
        </select>
        <button class="action-button" id="save-mode-button" style="margin-top:0.8rem;">Apply mode</button>
        ${
          settings.current_mode === "live" && settings.app?.enable_live_trading !== true
            ? `<p class="detail-copy" style="margin-top:0.7rem;">Live mode is selected, but live execution is still blocked until ENABLE_LIVE_TRADING=true.</p>`
            : ""
        }
      </div>
      <div class="detail-block">
        <div class="eyebrow">Presets</div>
        <div class="pill-row">${(settings.preset_files || []).map((preset) => `<span class="pill">${preset}</span>`).join("")}</div>
      </div>
      <div class="detail-block">
        <div class="eyebrow">Claude</div>
        <div class="setting-line"><span>API key</span><strong>${settings.secrets?.claude_key_present ? "Configured" : "Missing"}</strong></div>
        <div class="setting-line"><span>Default flag</span><strong>${settings.secrets?.claude_agent_default ? "Enabled" : "Disabled"}</strong></div>
        <div class="setting-line"><span>Runtime toggle</span><strong>${claude.operator_enabled ? "Enabled" : "Disabled"}</strong></div>
        <div class="setting-line"><span>Status</span><strong>${claude.state || "unknown"}</strong></div>
        <div class="setting-line"><span>Model</span><strong>${claude.model || "N/A"}</strong></div>
        <p class="detail-copy">${claude.message || ""}</p>
        <button class="action-button" id="toggle-claude-button" style="margin-top:0.8rem;">${claude.operator_enabled ? "Disable Claude" : "Enable Claude"}</button>
        ${
          settings.using_demo_data
            ? `<p class="detail-copy" style="margin-top:0.7rem;">Demo/bootstrap data is active, so Claude remains runtime-blocked even if the toggle is on.</p>`
            : ""
        }
      </div>
      <div class="detail-block">
        <div class="eyebrow">Platform secrets</div>
        <div class="setting-line"><span>Polymarket relayer</span><strong>${settings.secrets?.polymarket_relayer_key_present ? "Configured" : "Missing"}</strong></div>
      </div>
    </div>
  `;

  const saveModeButton = byId("save-mode-button");
  if (saveModeButton) {
    saveModeButton.addEventListener("click", applyAppMode);
  }
  const toggleClaudeButton = byId("toggle-claude-button");
  if (toggleClaudeButton) {
    toggleClaudeButton.addEventListener("click", toggleClaudeAgent);
  }
}

function renderOrders() {
  const orders = state.payloads.orders || [];
  byId("orders-table").innerHTML = `
    <div class="table">
      ${
        orders.length
          ? orders
              .map(
                (order) => `
                  <div class="table-row">
                    <div class="table-main">
                      <strong>${order.order_id}</strong>
                      <span class="table-sub">${order.market_id} • ${order.status}</span>
                    </div>
                    <div class="table-main">
                      <strong>${order.mode}</strong>
                      <span class="table-sub">${formatDate(order.created_at)}</span>
                    </div>
                    <div class="table-main">
                      <strong>${order.message || "No message"}</strong>
                    </div>
                  </div>
                `
              )
              .join("")
          : `<div class="empty">No orders yet. Approved opportunities can be paper-executed from the detail panel.</div>`
      }
    </div>
  `;
}

function renderPositions() {
  const positions = state.payloads.positions || [];
  byId("positions-panel").innerHTML = `
    <div class="positions-list">
      ${
        positions.length
          ? positions
              .map(
                (position) => `
                <div class="mini-card">
                  <div class="feed-row">
                    <strong>${position.question}</strong>
                    <span class="badge ${position.state === "closed" ? "watch" : "approved"}">${position.state}</span>
                  </div>
                  <div class="detail-row" style="margin-top:0.7rem;"><span>Size</span><strong>${Number(position.size).toFixed(2)}</strong></div>
                  <div class="detail-row"><span>Entry cost</span><strong>${formatMoney(position.entry_cost)}</strong></div>
                  <div class="detail-row"><span>Unrealized</span><strong>${formatMoney(position.unrealized_pnl)}</strong></div>
                </div>
              `
              )
              .join("")
          : `<div class="empty">No open positions.</div>`
      }
    </div>
  `;
}

function drawSparkline(values) {
  if (!values.length) return `<div class="empty">No equity points.</div>`;
  const width = 280;
  const height = 70;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = max - min || 1;
  const points = values
    .map((value, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((value - min) / spread) * (height - 10) - 5;
      return `${x},${y}`;
    })
    .join(" ");
  return `
    <svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">
      <polyline fill="none" stroke="rgba(97,231,206,0.95)" stroke-width="3" points="${points}" />
    </svg>
  `;
}

async function loadDashboard() {
  const [health, opportunities, markets, positions, orders, risk, analytics, agent, settings] = await Promise.all([
    fetchJson("/health"),
    fetchJson("/opportunities"),
    fetchJson("/markets"),
    fetchJson("/positions"),
    fetchJson("/orders"),
    fetchJson("/risk"),
    fetchJson("/analytics"),
    fetchJson("/agent/summary"),
    fetchJson("/settings"),
  ]);

  state.payloads = {
    health,
    opportunities,
    markets,
    positions,
    orders,
    risk,
    analytics,
    agent,
    settings,
    overview: {
      bankroll: risk.bankroll,
      realized_pnl: analytics.realized_pnl,
      unrealized_pnl: analytics.unrealized_pnl,
      active_positions: positions.length,
      blocked_trades: opportunities.filter((item) => item.status === "blocked").length,
      concurrent_positions: positions.length,
      mode: health.mode,
    },
  };

  renderOverview();
  renderOpportunities();
  renderMarketDetail();
  renderRisk();
  renderAgent();
  renderSettings();
  renderOrders();
  renderPositions();
}

async function executeSelected() {
  const selected = (state.payloads.opportunities || []).find((item) => item.opportunity_id === state.selectedOpportunityId);
  if (!selected || !selected.risk?.approved) return;
  await fetchJson(`/opportunities/${selected.opportunity_id}/execute`, { method: "POST" });
  await loadDashboard();
}

async function toggleKillSwitch() {
  const active = !(state.payloads.health?.kill_switch);
  await fetchJson("/kill-switch", { method: "POST", body: JSON.stringify({ active }) });
  await loadDashboard();
}

async function refreshScan() {
  await fetchJson("/scan", { method: "POST" });
  await loadDashboard();
}

async function applyAppMode() {
  const select = byId("app-mode-select");
  if (!select) return;
  await fetchJson("/settings/app-mode", { method: "POST", body: JSON.stringify({ mode: select.value }) });
  await loadDashboard();
}

async function toggleClaudeAgent() {
  const enabled = !(state.payloads.settings?.claude?.operator_enabled);
  await fetchJson("/settings/claude-agent", { method: "POST", body: JSON.stringify({ enabled }) });
  await loadDashboard();
}

byId("refresh-button").addEventListener("click", refreshScan);
byId("execute-button").addEventListener("click", executeSelected);
byId("kill-switch-button").addEventListener("click", toggleKillSwitch);

loadDashboard().catch((error) => {
  console.error(error);
});

setInterval(() => {
  loadDashboard().catch((error) => console.error(error));
}, 15000);
