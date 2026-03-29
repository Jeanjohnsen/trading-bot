const WORKSPACE_LAYOUT_STORAGE_KEY = "poly-arb-workspace-layout-v2";
const PANEL_KEYS = ["feed", "detail", "risk", "agent", "orders", "settings", "positions"];
const SIZE_OPTIONS = ["compact", "standard", "tall"];
const COLUMN_META = {
  1: { title: "Left Column", note: "Best for high-volume or tall panels" },
  2: { title: "Middle Column", note: "Good for detail-heavy views" },
  3: { title: "Right Column", note: "Best for stacked support views" },
};
const PANEL_META = {
  feed: { title: "Opportunity Feed", eyebrow: "Ranked Feed", defaultColumn: 1, defaultOrder: 0, defaultSize: "tall" },
  detail: { title: "Market Detail", eyebrow: "Execution View", defaultColumn: 2, defaultOrder: 0, defaultSize: "tall" },
  risk: { title: "Risk Panel", eyebrow: "Risk Controls", defaultColumn: 3, defaultOrder: 0, defaultSize: "compact" },
  agent: { title: "Claude Insights", eyebrow: "Agent Layer", defaultColumn: 3, defaultOrder: 1, defaultSize: "standard" },
  orders: { title: "Trade Blotter", eyebrow: "Execution History", defaultColumn: 2, defaultOrder: 1, defaultSize: "standard" },
  settings: { title: "Settings", eyebrow: "System Config", defaultColumn: 3, defaultOrder: 2, defaultSize: "standard" },
  positions: { title: "Positions", eyebrow: "Portfolio", defaultColumn: 3, defaultOrder: 3, defaultSize: "compact" },
};

function buildDefaultLayoutConfig() {
  return PANEL_KEYS.reduce((accumulator, panelKey) => {
    const meta = PANEL_META[panelKey];
    accumulator[panelKey] = {
      column: meta.defaultColumn,
      order: meta.defaultOrder,
      size: meta.defaultSize,
    };
    return accumulator;
  }, {});
}

function normalizeLayoutConfig(config) {
  const base = buildDefaultLayoutConfig();
  const normalized = {};

  PANEL_KEYS.forEach((panelKey) => {
    const source = config?.[panelKey] || base[panelKey];
    const column = [1, 2, 3].includes(Number(source?.column)) ? Number(source.column) : base[panelKey].column;
    const order = Number.isFinite(Number(source?.order)) ? Number(source.order) : base[panelKey].order;
    const size = SIZE_OPTIONS.includes(source?.size) ? source.size : base[panelKey].size;
    normalized[panelKey] = { column, order, size };
  });

  [1, 2, 3].forEach((column) => {
    PANEL_KEYS.filter((panelKey) => normalized[panelKey].column === column)
      .sort((left, right) => normalized[left].order - normalized[right].order || PANEL_KEYS.indexOf(left) - PANEL_KEYS.indexOf(right))
      .forEach((panelKey, index) => {
        normalized[panelKey].order = index;
      });
  });

  return normalized;
}

function loadLayoutConfig() {
  try {
    const raw = window.localStorage.getItem(WORKSPACE_LAYOUT_STORAGE_KEY);
    if (!raw) return buildDefaultLayoutConfig();
    const parsed = JSON.parse(raw);
    return normalizeLayoutConfig(parsed);
  } catch (error) {
    return buildDefaultLayoutConfig();
  }
}

const state = {
  selectedOpportunityId: null,
  payloads: {},
  feedFilter: "all",
  pendingAppMode: null,
  modeMenuOpen: false,
  layoutEditorOpen: false,
  layoutConfig: loadLayoutConfig(),
  draggedLayoutPanel: null,
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

function persistLayoutConfig() {
  try {
    window.localStorage.setItem(WORKSPACE_LAYOUT_STORAGE_KEY, JSON.stringify(state.layoutConfig));
  } catch (error) {
    console.warn("failed to persist workspace layout", error);
  }
}

function getColumnPanels(column) {
  return PANEL_KEYS.filter((panelKey) => state.layoutConfig[panelKey].column === column).sort(
    (left, right) => state.layoutConfig[left].order - state.layoutConfig[right].order
  );
}

function applyWorkspaceLayout() {
  const workspace = byId("workspace-columns");
  if (!workspace) return;
  const columns = Array.from(workspace.querySelectorAll("[data-workspace-column]"));

  PANEL_KEYS.forEach((panelKey) => {
    const panel = document.querySelector(`[data-panel-key="${panelKey}"]`);
    if (!panel) return;
    panel.classList.remove("panel-size-compact", "panel-size-standard", "panel-size-tall");
    panel.classList.add(`panel-size-${state.layoutConfig[panelKey].size}`);
  });

  columns.forEach((columnNode) => {
    const column = Number(columnNode.dataset.workspaceColumn);
    getColumnPanels(column).forEach((panelKey) => {
      const panel = document.querySelector(`[data-panel-key="${panelKey}"]`);
      if (panel) {
        columnNode.appendChild(panel);
      }
    });
  });
}

function updateLayoutConfig(mutator) {
  const next = normalizeLayoutConfig(mutator(JSON.parse(JSON.stringify(state.layoutConfig))));
  state.layoutConfig = next;
  persistLayoutConfig();
  applyWorkspaceLayout();
  renderLayoutEditor();
}

function setPanelColumn(panelKey, column) {
  if (!PANEL_META[panelKey] || !COLUMN_META[column]) return;
  if (state.layoutConfig[panelKey]?.column === column) return;
  updateLayoutConfig((draft) => {
    draft[panelKey].column = column;
    draft[panelKey].order = getColumnPanels(column).length;
    return draft;
  });
}

function setPanelSize(panelKey, size) {
  if (!PANEL_META[panelKey] || !SIZE_OPTIONS.includes(size)) return;
  updateLayoutConfig((draft) => {
    draft[panelKey].size = size;
    return draft;
  });
}

function movePanelWithinColumn(panelKey, direction) {
  const panel = state.layoutConfig[panelKey];
  if (!panel) return;
  const columnPanels = getColumnPanels(panel.column);
  const index = columnPanels.indexOf(panelKey);
  const targetIndex = direction === "up" ? index - 1 : index + 1;
  if (targetIndex < 0 || targetIndex >= columnPanels.length) return;

  updateLayoutConfig((draft) => {
    const targetKey = columnPanels[targetIndex];
    [draft[panelKey].order, draft[targetKey].order] = [draft[targetKey].order, draft[panelKey].order];
    return draft;
  });
}

function renderLayoutEditor() {
  const overlay = byId("layout-overlay");
  const grid = byId("layout-editor-grid");
  if (!overlay || !grid) return;

  overlay.hidden = !state.layoutEditorOpen;
  document.body.classList.toggle("layout-editor-open", state.layoutEditorOpen);

  if (!state.layoutEditorOpen) {
    return;
  }

  grid.innerHTML = Object.entries(COLUMN_META)
    .map(([column, meta]) => {
      const panels = getColumnPanels(Number(column));
      return `
        <div class="layout-editor-column" data-layout-drop-column="${column}">
          <div class="layout-column-copy">
            <p class="eyebrow">Column ${column}</p>
            <div class="layout-column-name">${meta.title} • ${meta.note}</div>
          </div>
          <div class="layout-editor-stack">
            ${panels
              .map((panelKey, index) => {
                const panel = PANEL_META[panelKey];
                const size = state.layoutConfig[panelKey].size;
                return `
                  <div class="layout-control-card" draggable="true" data-layout-panel-card="${panelKey}">
                    <div class="layout-control-top">
                      <div class="layout-panel-copy">
                        <strong>${panel.title}</strong>
                        <span class="table-sub">${panel.eyebrow}</span>
                      </div>
                      <span class="layout-control-badge">${size}</span>
                    </div>
                    <div class="layout-control-group">
                      <div class="layout-control-label">Column</div>
                      <div class="layout-button-row">
                        ${Object.entries(COLUMN_META)
                          .map(
                            ([targetColumn, targetMeta]) => `
                              <button class="layout-pill-button ${Number(targetColumn) === Number(column) ? "active" : ""}" type="button" data-layout-column="${targetColumn}" data-panel-key="${panelKey}">
                                ${targetMeta.title.replace(" Column", "")}
                              </button>
                            `
                          )
                          .join("")}
                      </div>
                    </div>
                    <div class="layout-control-group">
                      <div class="layout-control-label">Height</div>
                      <div class="layout-button-row">
                        ${SIZE_OPTIONS.map(
                          (option) => `
                            <button class="layout-pill-button ${option === size ? "active" : ""}" type="button" data-layout-size="${option}" data-panel-key="${panelKey}">
                              ${option}
                            </button>
                          `
                        ).join("")}
                      </div>
                    </div>
                    <div class="layout-control-group">
                      <div class="layout-control-label">Stack Order</div>
                      <div class="layout-button-row">
                        <button class="layout-icon-button" type="button" data-layout-move="up" data-panel-key="${panelKey}" ${index === 0 ? "disabled" : ""}>↑</button>
                        <button class="layout-icon-button" type="button" data-layout-move="down" data-panel-key="${panelKey}" ${index === panels.length - 1 ? "disabled" : ""}>↓</button>
                      </div>
                    </div>
                  </div>
                `;
              })
              .join("")}
          </div>
        </div>
      `;
    })
    .join("");

  document.querySelectorAll("[data-layout-column]").forEach((node) => {
    node.addEventListener("click", () => {
      setPanelColumn(node.dataset.panelKey, Number(node.dataset.layoutColumn));
    });
  });

  document.querySelectorAll("[data-layout-size]").forEach((node) => {
    node.addEventListener("click", () => {
      setPanelSize(node.dataset.panelKey, node.dataset.layoutSize);
    });
  });

  document.querySelectorAll("[data-layout-move]").forEach((node) => {
    node.addEventListener("click", () => {
      movePanelWithinColumn(node.dataset.panelKey, node.dataset.layoutMove);
    });
  });

  document.querySelectorAll("[data-layout-panel-card]").forEach((node) => {
    node.addEventListener("dragstart", (event) => {
      state.draggedLayoutPanel = node.dataset.layoutPanelCard;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", node.dataset.layoutPanelCard);
      node.classList.add("dragging");
    });

    node.addEventListener("dragend", () => {
      state.draggedLayoutPanel = null;
      document.querySelectorAll("[data-layout-drop-column]").forEach((columnNode) => columnNode.classList.remove("is-drop-target"));
      document.querySelectorAll("[data-layout-panel-card]").forEach((card) => card.classList.remove("dragging"));
    });
  });

  document.querySelectorAll("[data-layout-drop-column]").forEach((node) => {
    node.addEventListener("dragover", (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      node.classList.add("is-drop-target");
    });

    node.addEventListener("dragleave", (event) => {
      if (!node.contains(event.relatedTarget)) {
        node.classList.remove("is-drop-target");
      }
    });

    node.addEventListener("drop", (event) => {
      event.preventDefault();
      node.classList.remove("is-drop-target");
      const panelKey = event.dataTransfer.getData("text/plain") || state.draggedLayoutPanel;
      if (panelKey) {
        setPanelColumn(panelKey, Number(node.dataset.layoutDropColumn));
      }
    });
  });
}

function openLayoutEditor() {
  state.layoutEditorOpen = true;
  renderLayoutEditor();
}

function closeLayoutEditor() {
  state.layoutEditorOpen = false;
  state.draggedLayoutPanel = null;
  renderLayoutEditor();
}

function resetLayoutEditor() {
  state.layoutConfig = buildDefaultLayoutConfig();
  state.draggedLayoutPanel = null;
  persistLayoutConfig();
  applyWorkspaceLayout();
  renderLayoutEditor();
}

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

function formatBankrollSource(source) {
  if (source === "venue_synced") return "Venue-synced";
  if (source === "venue_unavailable") return "Venue unavailable";
  return "Simulated";
}

function formatShortAddress(value) {
  if (!value || value.length < 12) return value || "N/A";
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}

function getAccountBundle() {
  return state.payloads.risk?.account || state.payloads.settings?.account || state.payloads.health?.account || {};
}

function formatTradeSizeSource(source) {
  if (source === "manual") return "Manual override";
  if (source === "global") return "Global fixed size";
  return "Auto Kelly";
}

function isTradeSizeOptionActive(activeMode, activeFraction, mode, fraction = null) {
  if (mode === "auto") return activeMode === "auto";
  return activeMode === "fixed" && Math.abs(Number(activeFraction || 0) - Number(fraction || 0)) < 0.0001;
}

function renderTradeSizeButtons(buttonType, activeMode, activeFraction, presets, opportunityId = "") {
  const autoActive = isTradeSizeOptionActive(activeMode, activeFraction, "auto");
  const autoAttrs =
    buttonType === "global"
      ? `data-global-trade-size="auto"`
      : `data-opportunity-trade-size="auto" data-opportunity-id="${opportunityId}"`;
  const presetButtons = (presets || []).map((fraction) => {
    const active = isTradeSizeOptionActive(activeMode, activeFraction, "fixed", fraction);
    const attrs =
      buttonType === "global"
        ? `data-global-trade-size="fixed" data-trade-size-fraction="${fraction}"`
        : `data-opportunity-trade-size="fixed" data-trade-size-fraction="${fraction}" data-opportunity-id="${opportunityId}"`;
    return `<button class="layout-pill-button ${active ? "active" : ""}" type="button" ${attrs}>${formatPercent(fraction)}</button>`;
  });
  return `
    <div class="layout-button-row trade-size-button-row">
      <button class="layout-pill-button ${autoActive ? "active" : ""}" type="button" ${autoAttrs}>Auto</button>
      ${presetButtons.join("")}
    </div>
  `;
}

function renderRuntimeToggleButtons(toggleKey, enabled) {
  return `
    <div class="runtime-toggle-row">
      <button class="action-button ${enabled ? "" : "secondary"}" type="button" data-runtime-toggle="${toggleKey}" data-runtime-enabled="true">On</button>
      <button class="action-button ${enabled ? "secondary" : ""}" type="button" data-runtime-toggle="${toggleKey}" data-runtime-enabled="false">Off</button>
    </div>
  `;
}

function statusClass(status) {
  if (status === "approved" || status === "executable") return "approved";
  if (status === "watch" || status === "watch_only") return "watch";
  if (status === "executing") return "approved";
  return "blocked";
}

function humanizeRiskKey(value) {
  return String(value || "unknown")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function getOpportunityDisplayState(opportunity) {
  const status = opportunity.status || "watch";
  const blockedBy = opportunity.risk?.blocked_by || [];
  const nonAtomicBlockers = blockedBy.filter((item) => item !== "atomic_execution_pending");

  if (status === "approved") {
    return {
      filter: "executable",
      badge: "Executable now",
      tone: "approved",
      reason: "Deterministic checks passed",
      sortRank: 0,
    };
  }

  if (status === "executing") {
    return {
      filter: "executable",
      badge: "Executing",
      tone: "approved",
      reason: "Order routing in progress",
      sortRank: 0,
    };
  }

  if (blockedBy.includes("atomic_execution_pending") && nonAtomicBlockers.length === 0) {
    return {
      filter: "watch_only",
      badge: "Watch only",
      tone: "watch",
      reason: "Atomic execution pending",
      sortRank: 1,
    };
  }

  if (status === "watch") {
    return {
      filter: "watch_only",
      badge: "Watch only",
      tone: "watch",
      reason: "Not promoted to execution",
      sortRank: 1,
    };
  }

  return {
    filter: "safety_blocked",
    badge: "Blocked by safety",
    tone: "blocked",
    reason: humanizeRiskKey(nonAtomicBlockers[0] || blockedBy[0] || "risk_filter"),
    sortRank: 2,
  };
}

function renderOverview() {
  const overview = state.payloads.health ? state.payloads.overview : null;
  const analytics = state.payloads.analytics || {};
  const claude = state.payloads.health?.claude || {};
  const account = getAccountBundle();
  const activeAccount = account.active || {};
  const venueAccount = account.venue || {};
  if (!overview) return;

  const cards = [
    {
      label: "Bankroll",
      value: formatMoney(activeAccount.active_bankroll ?? overview.bankroll),
      foot: `${formatBankrollSource(activeAccount.source)}${state.payloads.health?.using_demo_data ? " • demo data" : ""} • Equity ${formatMoney(activeAccount.total_equity ?? overview.bankroll)}`,
      indicator:
        overview.mode === "paper" || overview.mode === "backtest"
          ? venueAccount.synced
            ? `Polymarket live cash ${formatMoney(venueAccount.available_cash)}`
            : "Polymarket live cash unavailable"
          : "",
    },
    { label: "Realized PnL", value: formatMoney(overview.realized_pnl), foot: "Closed and booked" },
    { label: "Unrealized PnL", value: formatMoney(overview.unrealized_pnl), foot: "Open exposure" },
    {
      label: "Active Positions",
      value: `${overview.active_positions}`,
      foot: activeAccount.positions_value
        ? `${activeAccount.source === "venue_synced" ? "Venue positions" : "Open value"} ${formatMoney(activeAccount.positions_value)}`
        : `${overview.concurrent_positions} concurrent`,
    },
    { label: "Blocked Trades", value: `${overview.blocked_trades}`, foot: "Deterministic filters" },
    { label: "Max Drawdown", value: formatPercent(analytics.max_drawdown || 0), foot: "New entries block at 8%" },
  ];

  byId("overview-grid").innerHTML = cards
    .map(
      (card) => `
        <article class="metric-card">
          <div class="metric-label">${card.label}</div>
          <div class="metric-value">${card.value}</div>
          <div class="metric-foot">${card.foot}</div>
          ${card.indicator ? `<div class="metric-indicator">${card.indicator}</div>` : ""}
        </article>
      `
    )
    .join("");

  byId("mode-chip").textContent = `Mode: ${overview.mode} • ${formatBankrollSource(activeAccount.source)} • Claude: ${claude.state || "idle"}`;
}

function renderOpportunities() {
  const opportunities = (state.payloads.opportunities || [])
    .map((opportunity) => ({
      ...opportunity,
      displayState: getOpportunityDisplayState(opportunity),
    }))
    .sort(
      (left, right) =>
        left.displayState.sortRank - right.displayState.sortRank ||
        Number(right.net_edge || 0) - Number(left.net_edge || 0) ||
        Number(right.fill_confidence || 0) - Number(left.fill_confidence || 0)
    );

  const counts = {
    executable: opportunities.filter((item) => item.displayState.filter === "executable").length,
    watch_only: opportunities.filter((item) => item.displayState.filter === "watch_only").length,
    safety_blocked: opportunities.filter((item) => item.displayState.filter === "safety_blocked").length,
  };

  const visibleOpportunities =
    state.feedFilter === "all" ? opportunities : opportunities.filter((item) => item.displayState.filter === state.feedFilter);

  if (!visibleOpportunities.find((item) => item.opportunity_id === state.selectedOpportunityId)) {
    state.selectedOpportunityId = visibleOpportunities[0]?.opportunity_id || null;
  }

  byId("opportunity-feed").innerHTML =
    visibleOpportunities.length === 0
        ? `<div class="empty">No opportunities found yet.</div>`
        : `
          <div class="feed-toolbar">
            <div class="feed-filter-row">
              <button class="layout-pill-button ${state.feedFilter === "all" ? "active" : ""}" type="button" data-feed-filter="all">All ${opportunities.length}</button>
              <button class="layout-pill-button ${state.feedFilter === "executable" ? "active" : ""}" type="button" data-feed-filter="executable">Executable ${counts.executable}</button>
              <button class="layout-pill-button ${state.feedFilter === "watch_only" ? "active" : ""}" type="button" data-feed-filter="watch_only">Watch only ${counts.watch_only}</button>
              <button class="layout-pill-button ${state.feedFilter === "safety_blocked" ? "active" : ""}" type="button" data-feed-filter="safety_blocked">Safety blocked ${counts.safety_blocked}</button>
            </div>
            <div class="panel-meta">Executable signals are ranked first. Watch-only signals stay visible, but safety blocks are called out separately.</div>
          </div>
          ${visibleOpportunities
            .map(
              (opportunity) => `
             <article class="feed-item ${state.selectedOpportunityId === opportunity.opportunity_id ? "active" : ""}" data-opportunity-id="${opportunity.opportunity_id}">
                <div class="feed-row">
                  <div>
                    <div class="feed-title">${opportunity.question}</div>
                    <div class="feed-subtitle">${opportunity.strategy_type} • ${opportunity.category}</div>
                    <div class="feed-context">${opportunity.displayState.reason}</div>
                  </div>
                 <div class="badge ${statusClass(opportunity.displayState.tone)}">${opportunity.displayState.badge}</div>
                </div>
               <div class="pill-row" style="margin-top:0.9rem;">
                 <span class="pill pill-accent">${opportunity.displayState.reason}</span>
                  <span class="pill">Net edge ${formatPercent(opportunity.net_edge)}</span>
                  <span class="pill">Fill ${formatPercent(opportunity.fill_confidence)}</span>
                  <span class="pill">Liquidity ${formatPercent(opportunity.liquidity_score)}</span>
                </div>
              </article>
            `
            )
            .join("")}
        `;

  byId("scan-timestamp").textContent = state.payloads.health?.last_scan_at
    ? `Last scan ${formatDate(state.payloads.health.last_scan_at)}`
    : "Waiting for scan";

  document.querySelectorAll("[data-feed-filter]").forEach((node) => {
    node.addEventListener("click", () => {
      state.feedFilter = node.dataset.feedFilter;
      renderOpportunities();
      renderMarketDetail();
    });
  });
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
  const displayState = getOpportunityDisplayState(selected);
  const analytics = state.payloads.analytics || {};
  const activeAccount = getAccountBundle().active || {};
  const tradeSizing = state.payloads.settings?.trade_sizing || {};
  const tradeNotional = Number(risk.sizing?.notional || 0);
  const activeBankroll = Number(activeAccount.active_bankroll || 0);
  const balanceUsage = activeBankroll > 0 ? tradeNotional / activeBankroll : 0;
  const baseOpportunitySize = Number(selected.capital_at_risk || 0);
  const opportunityCoverage = baseOpportunitySize > 0 ? tradeNotional / baseOpportunitySize : 0;
  const scaledExpectedProfit =
    baseOpportunitySize > 0
      ? Number(selected.expected_profit || 0) * opportunityCoverage
      : tradeNotional * Number(selected.net_edge || 0);
  const bankrollDescriptor = formatBankrollSource(activeAccount.source);
  const tradeSizeSource = risk.sizing?.size_source || "auto";
  const requestedFraction = Number(risk.sizing?.requested_fraction || risk.sizing?.capped_fraction || 0);
  const cappedFraction = Number(risk.sizing?.capped_fraction || 0);
  const estimatedAiCost = Number(risk.sizing?.estimated_ai_cost || 0);
  const estimatedProfitAfterAi = Number(
    risk.sizing?.estimated_profit_after_ai_cost ?? scaledExpectedProfit - estimatedAiCost
  );
  const isCrossMarket = selected.strategy_type === "cross_market_arb";
  const groupedProbability = Number(selected.evidence?.summed_yes_probability || 0);
  const memberCount = Number(selected.evidence?.member_count || 0);
  const pricingBlock = isCrossMarket
    ? `
        <div class="detail-block">
          <div class="eyebrow">Structure</div>
          <div class="detail-stat-list">
            <div class="detail-row"><span>Grouped markets</span><strong>${memberCount || selected.related_market_ids?.length + 1 || 0}</strong></div>
            <div class="detail-row"><span>Summed YES mass</span><strong>${formatPercent(groupedProbability)}</strong></div>
            <div class="detail-row"><span>Net edge</span><strong>${formatPercent(selected.net_edge)}</strong></div>
          </div>
          <p class="detail-copy">Cross-market opportunities are scored from broken grouped probability mass, not a single YES/NO book.</p>
        </div>
      `
    : `
        <div class="detail-block">
          <div class="eyebrow">Pricing</div>
          <div class="detail-stat-list">
            <div class="detail-row"><span>YES</span><strong>${formatPercent(market.yes_price || 0)}</strong></div>
            <div class="detail-row"><span>NO</span><strong>${formatPercent(market.no_price || 0)}</strong></div>
            <div class="detail-row"><span>Net edge</span><strong>${formatPercent(selected.net_edge)}</strong></div>
          </div>
        </div>
      `;
  const opportunitySizeLabel = baseOpportunitySize > 0 ? formatMoney(baseOpportunitySize) : "Derived from live sizing";
  const blockedPills = (risk.blocked_by || []).length
    ? `<div class="pill-row" style="margin-top:0.8rem;">${risk.blocked_by.map((item) => `<span class="pill">${item}</span>`).join("")}</div>`
    : `<div class="pill-row" style="margin-top:0.8rem;"><span class="pill">No blocks</span></div>`;
  const tradeSizeButtons = renderTradeSizeButtons(
    "manual",
    tradeSizeSource === "manual" ? "fixed" : "auto",
    tradeSizeSource === "manual" ? requestedFraction : null,
    tradeSizing.presets || [0.02, 0.05, 0.10],
    selected.opportunity_id
  );
  const executionMetrics = [
    {
      label: "Capital at risk",
      value: formatMoney(tradeNotional),
      meta: "Sized notional",
    },
    {
      label: "Investing",
      value: formatMoney(tradeNotional),
      meta: `of ${formatMoney(activeBankroll)}`,
    },
    {
      label: "Balance usage",
      value: formatPercent(balanceUsage),
      meta: "Of active bankroll",
    },
    {
      label: "Expected profit",
      value: formatMoney(scaledExpectedProfit),
      meta: estimatedAiCost > 0 ? `After Claude: ${formatMoney(estimatedProfitAfterAi)}` : "Before fees already buffered",
    },
    {
      label: "Full opportunity size",
      value: opportunitySizeLabel,
      meta: baseOpportunitySize > 0 ? "Venue-sized capacity" : "Fallback sizing view",
    },
    {
      label: "Sizing cap",
      value: formatPercent(risk.sizing?.capped_fraction || 0),
      meta: `${formatTradeSizeSource(tradeSizeSource)}`,
    },
  ]
    .map(
      (metric) => `
        <div class="execution-metric-card">
          <div class="execution-metric-label">${metric.label}</div>
          <div class="execution-metric-value">${metric.value}</div>
          <div class="execution-metric-meta">${metric.meta}</div>
        </div>
      `
    )
    .join("");
  byId("market-detail").innerHTML = `
    <div class="stack">
      <div class="detail-block">
        <strong>${selected.question}</strong>
        <p class="detail-copy">${selected.rationale}</p>
      </div>

      <div class="detail-grid">
        ${pricingBlock}
        <div class="detail-block">
          <div class="eyebrow">Execution</div>
          <div class="execution-metric-grid">
            ${executionMetrics}
          </div>
          ${tradeSizeButtons}
          <p class="detail-copy execution-note">${formatTradeSizeSource(tradeSizeSource)} is active. ${bankrollDescriptor} bankroll is driving sizing for this trade.${requestedFraction > cappedFraction ? ` Requested ${formatPercent(requestedFraction)} is clipped to the hard cap ${formatPercent(cappedFraction)}.` : ""}${estimatedAiCost > 0 ? ` Claude cost floor: ${formatMoney(estimatedAiCost)}.` : ""}</p>
        </div>
        <div class="detail-block">
          <div class="eyebrow">Risk verdict</div>
          <div class="detail-stat-list">
            <div class="detail-row"><span>Approved</span><strong>${risk.approved ? "Yes" : "No"}</strong></div>
          </div>
          ${blockedPills}
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
  const mode = state.payloads.health?.mode || "paper";
  executeButton.disabled = !risk.approved;
  executeButton.textContent = risk.approved ? `${mode.charAt(0).toUpperCase()}${mode.slice(1)} Execute` : displayState.badge;
  document.querySelectorAll("[data-opportunity-trade-size]").forEach((node) => {
    node.addEventListener("click", async () => {
      const sizeMode = node.dataset.opportunityTradeSize;
      const fraction = node.dataset.tradeSizeFraction ? Number(node.dataset.tradeSizeFraction) : null;
      await setOpportunityTradeSize(node.dataset.opportunityId, sizeMode, fraction);
    });
  });
}

function renderRisk() {
  const risk = state.payloads.risk || {};
  const exposures = Object.entries(risk.category_exposure || {});
  const account = risk.account || {};
  const activeAccount = account.active || {};
  const venueAccount = account.venue || {};
  const paperAccount = account.paper || {};
  byId("risk-panel").innerHTML = `
    <div class="stack">
      <div class="detail-block">
        <div class="detail-row"><span>Bankroll source</span><strong>${formatBankrollSource(activeAccount.source)}</strong></div>
        <div class="detail-row"><span>Active bankroll</span><strong>${formatMoney(activeAccount.active_bankroll)}</strong></div>
        <div class="detail-row"><span>Total equity</span><strong>${formatMoney(activeAccount.total_equity)}</strong></div>
        <div class="detail-row"><span>Kill switch</span><strong>${risk.kill_switch ? "ACTIVE" : "clear"}</strong></div>
        <div class="detail-row"><span>Daily loss</span><strong>${formatMoney(risk.daily_loss)}</strong></div>
        <div class="detail-row"><span>Drawdown</span><strong>${formatPercent(risk.drawdown_fraction || 0)}</strong></div>
      </div>
      <div class="detail-block">
        <div class="eyebrow">Bankroll split</div>
        <div class="detail-row"><span>Paper bankroll</span><strong>${formatMoney(paperAccount.active_bankroll)}</strong></div>
        <div class="detail-row"><span>Venue cash</span><strong>${formatMoney(venueAccount.available_cash)}</strong></div>
        <div class="detail-row"><span>Venue positions</span><strong>${formatMoney(venueAccount.positions_value)}</strong></div>
        ${venueAccount.sync_error ? `<p class="detail-copy">${venueAccount.sync_error}</p>` : `<p class="detail-copy">${venueAccount.synced ? `Synced ${formatDate(venueAccount.last_synced_at)}` : "Venue bankroll not synced yet."}</p>`}
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
  const account = settings.account || {};
  const activeAccount = account.active || {};
  const venueAccount = account.venue || {};
  const paperAccount = account.paper || {};
  const tradeSizing = settings.trade_sizing || {};
  const globalTradeSize = tradeSizing.global || { mode: "auto", fraction: null };
  const selectedMode = state.pendingAppMode || settings.current_mode || settings.app?.mode || "paper";
  byId("settings-panel").innerHTML = `
    <div class="stack">
      <div class="detail-block">
        <div class="setting-line"><span>Live trading enabled</span><strong>${settings.app?.enable_live_trading ? "Yes" : "No"}</strong></div>
        <div class="setting-line"><span>Research mode</span><strong>${settings.app?.enable_research_mode ? "On" : "Off"}</strong></div>
        <div class="setting-line"><span>Market orders</span><strong>${settings.app?.enable_market_orders ? "On" : "Off"}</strong></div>
        <div class="setting-line"><span>Demo data active</span><strong>${settings.using_demo_data ? "Yes" : "No"}</strong></div>
        <div class="setting-line"><span>Bankroll source</span><strong>${formatBankrollSource(activeAccount.source)}</strong></div>
        <div class="setting-line"><span>Refresh</span><strong>${settings.scanner?.refresh_seconds || 0}s</strong></div>
        <div class="setting-line"><span>Min net edge</span><strong>${formatPercent(settings.risk?.min_net_edge || 0)}</strong></div>
      </div>
      <div class="detail-block">
        <div class="eyebrow">App mode</div>
        <div class="setting-line"><span>Current mode</span><strong>${settings.current_mode || settings.app?.mode || "unknown"}</strong></div>
        <div class="custom-select">
          <button class="mode-select mode-select-trigger ${state.modeMenuOpen ? "open" : ""}" id="app-mode-trigger" type="button" aria-expanded="${state.modeMenuOpen ? "true" : "false"}">
            <span class="mode-select-label">${selectedMode}</span>
            <span class="mode-select-arrow">▾</span>
          </button>
          <div class="mode-select-menu" id="app-mode-menu" ${state.modeMenuOpen ? "" : "hidden"}>
            ${(settings.available_modes || []).map((mode) => `<button class="mode-option ${mode === selectedMode ? "active" : ""}" type="button" data-mode-option="${mode}">${mode}</button>`).join("")}
          </div>
        </div>
        <button class="action-button" id="save-mode-button" style="margin-top:0.8rem;">Apply mode</button>
        ${
          settings.current_mode === "live" && settings.app?.enable_live_trading !== true
            ? `<p class="detail-copy" style="margin-top:0.7rem;">Live mode is selected, but live execution is still blocked until the live execution gate is enabled below.</p>`
            : ""
        }
        <div class="runtime-toggle-stack">
          <div class="runtime-toggle-item">
            <div class="setting-line"><span>Live execution gate</span><strong>${settings.app?.enable_live_trading ? "Enabled" : "Blocked"}</strong></div>
            ${renderRuntimeToggleButtons("live-trading", settings.app?.enable_live_trading === true)}
          </div>
          <div class="runtime-toggle-item">
            <div class="setting-line"><span>Research assist</span><strong>${settings.app?.enable_research_mode ? "Enabled" : "Off"}</strong></div>
            ${renderRuntimeToggleButtons("research-mode", settings.app?.enable_research_mode === true)}
          </div>
          <div class="runtime-toggle-item">
            <div class="setting-line"><span>Market orders</span><strong>${settings.app?.enable_market_orders ? "Enabled" : "Off"}</strong></div>
            ${renderRuntimeToggleButtons("market-orders", settings.app?.enable_market_orders === true)}
            <p class="detail-copy" style="margin-top:0.65rem;">Keep this off unless you explicitly want emergency-style liquidity taking later.</p>
          </div>
        </div>
      </div>
      <div class="detail-block">
        <div class="eyebrow">Presets</div>
        <div class="pill-row">${(settings.preset_files || []).map((preset) => `<span class="pill">${preset}</span>`).join("")}</div>
      </div>
      <div class="detail-block">
        <div class="eyebrow">Trade sizing</div>
        <div class="setting-line"><span>Global profile</span><strong>${globalTradeSize.mode === "fixed" ? formatPercent(globalTradeSize.fraction) : "Auto Kelly"}</strong></div>
        <div class="setting-line"><span>Hard cap</span><strong>${formatPercent(tradeSizing.hard_cap || 0)}</strong></div>
        <div class="setting-line"><span>Claude cost floor</span><strong>${formatMoney(tradeSizing.estimated_claude_cost_per_trade_usd || 0)}</strong></div>
        ${renderTradeSizeButtons("global", globalTradeSize.mode, globalTradeSize.fraction, tradeSizing.presets || [0.02, 0.05, 0.10])}
        <p class="detail-copy">Global fixed sizing is still clipped by the deterministic hard cap and venue liquidity. Auto uses Kelly-style sizing.</p>
      </div>
      <div class="detail-block">
        <div class="eyebrow">Bankroll</div>
        <div class="setting-line"><span>Paper bankroll</span><strong>${formatMoney(paperAccount.active_bankroll)}</strong></div>
        <div class="setting-line"><span>Venue cash</span><strong>${formatMoney(venueAccount.available_cash)}</strong></div>
        <div class="setting-line"><span>Venue equity</span><strong>${formatMoney(venueAccount.total_equity)}</strong></div>
        <div class="setting-line"><span>Wallet</span><strong>${formatShortAddress(venueAccount.proxy_wallet || venueAccount.wallet_address)}</strong></div>
        <p class="detail-copy">${venueAccount.sync_error || (venueAccount.synced ? `Venue balance synced ${formatDate(venueAccount.last_synced_at)}.` : "Venue balance is not synced yet.")}</p>
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
  const modeTrigger = byId("app-mode-trigger");
  if (modeTrigger) {
    modeTrigger.addEventListener("click", toggleModeMenu);
  }
  document.querySelectorAll("[data-mode-option]").forEach((node) => {
    node.addEventListener("click", () => {
      state.pendingAppMode = node.dataset.modeOption;
      state.modeMenuOpen = false;
      renderSettings();
    });
  });
  document.querySelectorAll("[data-global-trade-size]").forEach((node) => {
    node.addEventListener("click", async () => {
      const mode = node.dataset.globalTradeSize;
      const fraction = node.dataset.tradeSizeFraction ? Number(node.dataset.tradeSizeFraction) : null;
      await setGlobalTradeSize(mode, fraction);
    });
  });
  document.querySelectorAll("[data-runtime-toggle]").forEach((node) => {
    node.addEventListener("click", async () => {
      const setting = node.dataset.runtimeToggle;
      const enabled = node.dataset.runtimeEnabled === "true";
      await setRuntimeToggle(setting, enabled);
    });
  });
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
      bankroll: risk.account?.active?.active_bankroll ?? risk.bankroll,
      realized_pnl: analytics.realized_pnl,
      unrealized_pnl: analytics.unrealized_pnl,
      active_positions: positions.length,
      blocked_trades: opportunities.filter((item) => item.status === "blocked").length,
      concurrent_positions: positions.length,
      mode: health.mode,
    },
  };

  applyWorkspaceLayout();
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

async function setGlobalTradeSize(mode, fraction = null) {
  await fetchJson("/settings/trade-size", {
    method: "POST",
    body: JSON.stringify({ mode, fraction }),
  });
  await loadDashboard();
}

async function setOpportunityTradeSize(opportunityId, mode, fraction = null) {
  const selectedOpportunity = (state.payloads.opportunities || []).find((item) => item.opportunity_id === opportunityId);
  await fetchJson(`/opportunities/${opportunityId}/trade-size`, {
    method: "POST",
    body: JSON.stringify({ mode, fraction }),
  });
  await loadDashboard();
  if (selectedOpportunity) {
    const match = (state.payloads.opportunities || []).find(
      (item) => item.market_id === selectedOpportunity.market_id && item.strategy_type === selectedOpportunity.strategy_type
    );
    if (match) {
      state.selectedOpportunityId = match.opportunity_id;
      renderOpportunities();
      renderMarketDetail();
    }
  }
}

async function applyAppMode() {
  const mode = state.pendingAppMode || state.payloads.settings?.current_mode || state.payloads.settings?.app?.mode;
  if (!mode) return;
  await fetchJson("/settings/app-mode", { method: "POST", body: JSON.stringify({ mode }) });
  state.modeMenuOpen = false;
  state.pendingAppMode = null;
  await loadDashboard();
}

async function toggleClaudeAgent() {
  const enabled = !(state.payloads.settings?.claude?.operator_enabled);
  await fetchJson("/settings/claude-agent", { method: "POST", body: JSON.stringify({ enabled }) });
  await loadDashboard();
}

async function setRuntimeToggle(setting, enabled) {
  if (!setting) return;
  await fetchJson(`/settings/${setting}`, { method: "POST", body: JSON.stringify({ enabled }) });
  await loadDashboard();
}

function toggleModeMenu() {
  state.modeMenuOpen = !state.modeMenuOpen;
  renderSettings();
}

byId("layout-settings-button").addEventListener("click", openLayoutEditor);
byId("refresh-button").addEventListener("click", refreshScan);
byId("execute-button").addEventListener("click", executeSelected);
byId("kill-switch-button").addEventListener("click", toggleKillSwitch);
byId("layout-close-button").addEventListener("click", closeLayoutEditor);
byId("layout-reset-button").addEventListener("click", resetLayoutEditor);
byId("layout-overlay").addEventListener("click", (event) => {
  if (event.target === event.currentTarget) {
    closeLayoutEditor();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.layoutEditorOpen) {
    closeLayoutEditor();
  }
});

applyWorkspaceLayout();
renderLayoutEditor();
loadDashboard().catch((error) => {
  console.error(error);
});

setInterval(() => {
  loadDashboard().catch((error) => console.error(error));
}, 15000);
