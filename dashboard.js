const overlay = document.getElementById("overlay");
const manualActions = document.getElementById("manualActions");
const manualRunSelect = document.getElementById("manualRunSelect");
const manualFileInput = document.getElementById("manualFileInput");
const uploadButton = document.getElementById("uploadButton");
const dataModeSelect = document.getElementById("dataModeSelect");
const analysisModeSelect = document.getElementById("analysisModeSelect");
const sortMetricSelect = document.getElementById("sortMetricSelect");
const simulationResultSelect = document.getElementById("simulationResultSelect");

const DATA_MODES = [
  ["test", "Test Backtest"],
  ["strategy", "Real Strategy"],
  ["paper", "Paper Trading"],
];

let mainChart = null;
let ddChart = null;
let currentRunId = null;
let availableDashboards = [];
let currentPayload = null;
let currentDataMode = "test";
let currentAnalysisMode = "Normal Training";
let currentSortMetric = "Max Drawdown";
let currentSimulationResult = "Selection";

function syncStageScale() {
  const viewportWidth = Math.max(window.innerWidth - 8, 320);
  const viewportHeight = Math.max(window.innerHeight - 8, 320);
  const scale = Math.min(viewportWidth / 1448, viewportHeight / 768, 1);
  document.documentElement.style.setProperty("--stage-scale", String(scale));
}

function formatNumber(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits);
}

function formatPercent(value, digits = 2) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function formatMetricValue(value, metricName) {
  if (value == null || Number.isNaN(Number(value))) return "--";
  if ((metricName || "").toLowerCase().includes("drawdown")) {
    return Number(value).toFixed(2);
  }
  return Number(value).toFixed(2);
}

function toNumberOrNull(value) {
  if (value == null || value === "") return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function toAbsNumberOrNull(value) {
  const numeric = toNumberOrNull(value);
  return numeric == null ? null : Math.abs(numeric);
}

function sanitizeControlOptions(options, fallbackOptions) {
  const merged = [...(options || []), ...(fallbackOptions || [])]
    .filter(Boolean)
    .map((value) => String(value));
  return [...new Set(merged)];
}

function getControlConfig(payload) {
  const visuals = payload?.visuals || {};
  return {
    analysisModes: sanitizeControlOptions(
      visuals.analysis_modes,
      ["Normal Training", "Bootstrap Review", "Scenario Matrix", "Strategy Profile"]
    ),
    sortMetrics: sanitizeControlOptions(
      visuals.sort_metrics,
      ["Max Drawdown", "Sharpe Ratio", "Net Profit"]
    ),
    simulationResults: sanitizeControlOptions(
      visuals.simulation_results,
      ["Selection", "Median", "Worst Case"]
    ),
  };
}

function setSelectOptions(elementId, values, activeValue) {
  const select = document.getElementById(elementId);
  select.innerHTML = "";
  const options = values && values.length ? values : ["--"];
  options.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    if (activeValue && value === activeValue) {
      option.selected = true;
    }
    select.appendChild(option);
  });
}

function setDataModeOptions() {
  dataModeSelect.innerHTML = "";
  DATA_MODES.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    if (value === currentDataMode) option.selected = true;
    dataModeSelect.appendChild(option);
  });
}

function hashThemeSeed(value) {
  let hash = 0;
  const input = String(value || "strategy-forge");
  for (let index = 0; index < input.length; index += 1) {
    hash = ((hash << 5) - hash) + input.charCodeAt(index);
    hash |= 0;
  }
  return Math.abs(hash);
}

function pickStrategyTheme(payload) {
  const context = payload?.visuals?.context || {};
  const artifacts = payload?.artifacts || {};
  const themeSeed = [
    payload?.run_id,
    context.symbol || artifacts.symbol,
    context.snapshot_id || artifacts.snapshot_id,
  ].filter(Boolean).join("|");

  const themes = [
    { purple: "#d71921", purpleStrong: "#f2efe7", accentRgb: "215, 25, 33", accentStrongRgb: "242, 239, 231" },
    { purple: "#f2efe7", purpleStrong: "#d71921", accentRgb: "242, 239, 231", accentStrongRgb: "215, 25, 33" },
    { purple: "#8f8d87", purpleStrong: "#f2efe7", accentRgb: "143, 141, 135", accentStrongRgb: "242, 239, 231" },
  ];

  return themes[hashThemeSeed(themeSeed) % themes.length];
}

function applyStrategyTheme(payload) {
  const theme = pickStrategyTheme(payload);
  document.body.removeAttribute("data-theme");
  document.documentElement.style.setProperty("--purple", theme.purple);
  document.documentElement.style.setProperty("--purple-strong", theme.purpleStrong);
  document.documentElement.style.setProperty("--accent-rgb", theme.accentRgb);
  document.documentElement.style.setProperty("--accent-strong-rgb", theme.accentStrongRgb);
  document.documentElement.style.setProperty(
    "--panel-shadow",
    "none"
  );
}

function getThemeAccentColor() {
  return getComputedStyle(document.body).getPropertyValue("--purple").trim() || "#d71921";
}

function buildParameterEntries(payload) {
  const runtime = payload.runtime_settings || {};
  const selectedParameters = payload.selected_parameters || {};
  const strategy = payload.strategy || {};
  const acceptedLayers = Array.isArray(strategy.layers) ? strategy.layers : [];
  const entries = [];

  Object.entries(runtime).forEach(([key, value]) => {
    if (value == null) return;
    if (Array.isArray(value)) {
      entries.push([key, value.length ? JSON.stringify(value[0]).slice(0, 26) : "[]"]);
    } else if (typeof value === "object") {
      entries.push([key, "{...}"]);
    } else {
      entries.push([key, String(value)]);
    }
  });

  Object.entries(selectedParameters).forEach(([key, value]) => {
    entries.push([key, String(value)]);
  });

  if (acceptedLayers.length) {
    entries.push(["accepted_layers", acceptedLayers.join(", ")]);
  }

  return entries.slice(0, 28);
}

function renderParameterPills(payload) {
  const container = document.getElementById("paramContainer");
  container.innerHTML = "";
  const entries = buildParameterEntries(payload);
  if (!entries.length) {
    container.innerHTML = `<div class="param-pill">strategy <span>no parameter data</span></div>`;
    return;
  }

  entries.forEach(([key, value]) => {
    const pill = document.createElement("div");
    pill.className = "param-pill";
    pill.appendChild(document.createTextNode(String(key)));
    const valueSpan = document.createElement("span");
    valueSpan.title = String(value);
    valueSpan.textContent = String(value);
    pill.appendChild(valueSpan);
    container.appendChild(pill);
  });
}

function setTableHeaders(labels) {
  const headers = document.querySelectorAll(".table-panel thead th");
  labels.forEach((label, index) => {
    if (headers[index]) {
      headers[index].textContent = label;
    }
  });
}

function getSimulationSnapshot(payload) {
  const metrics = payload.metrics || {};
  const bootstrap = payload.bootstrap || {};
  const simulationKey = String(currentSimulationResult || "Selection").toLowerCase();

  const selectionProfit = toNumberOrNull(metrics.selection_oos_net_pnl ?? metrics.net_profit);
  const selectionDrawdown = toAbsNumberOrNull(metrics.selection_oos_drawdown ?? metrics.max_drawdown);
  const selectionSharpe = toNumberOrNull(metrics.selection_oos_sharpe ?? metrics.sharpe_ratio);
  const selectionSortino = toNumberOrNull(metrics.sortino_ratio);
  const selectionTrades = toNumberOrNull(metrics.total_trades);
  const selectionWinRate = toNumberOrNull(metrics.win_rate);
  const bootstrapPass = toNumberOrNull(bootstrap.pass_rate);

  let netProfit = selectionProfit;
  let drawdown = selectionDrawdown;
  let sharpe = selectionSharpe;
  let sortino = selectionSortino;
  let totalTrades = selectionTrades;
  let winRate = selectionWinRate;
  let drawdownAmount = null;

  if (simulationKey.includes("median")) {
    netProfit = toNumberOrNull(bootstrap.median_net_profit);
    drawdown = toAbsNumberOrNull(bootstrap.median_max_drawdown) ?? selectionDrawdown;
    sharpe = toNumberOrNull(bootstrap.median_sharpe);
    sortino = toNumberOrNull(bootstrap.median_sortino);
    totalTrades = toNumberOrNull(bootstrap.median_total_trades);
    winRate = toNumberOrNull(bootstrap.median_win_rate);
  } else if (simulationKey.includes("worst")) {
    netProfit = toNumberOrNull(bootstrap.worst_case_net_profit);
    drawdown = toAbsNumberOrNull(bootstrap.worst_case_drawdown) ?? toAbsNumberOrNull(bootstrap.max_drawdown);
    sharpe = toNumberOrNull(bootstrap.worst_case_sharpe);
    sortino = toNumberOrNull(bootstrap.worst_case_sortino);
    totalTrades = toNumberOrNull(bootstrap.worst_case_total_trades);
    winRate = toNumberOrNull(bootstrap.worst_case_win_rate);
  }

  if (simulationKey.includes("selection")) {
    const timeseries = Array.isArray(payload.timeseries) ? payload.timeseries : [];
    if (timeseries.length) {
      let peak = null;
      let maxDrawdownAmount = null;
      timeseries.forEach((entry) => {
        const equity = toNumberOrNull(entry.equity);
        const drawdownValue = Math.abs(toNumberOrNull(entry.drawdown) ?? 0);
        if (equity == null) return;
        peak = peak == null ? equity : Math.max(peak, equity);
        const amount = peak != null ? peak * drawdownValue : null;
        if (amount != null) {
          maxDrawdownAmount = maxDrawdownAmount == null ? amount : Math.max(maxDrawdownAmount, amount);
        }
      });
      drawdownAmount = maxDrawdownAmount;
    }
  }

  if (drawdownAmount == null) {
    drawdownAmount = toNumberOrNull(
      metrics.selection_oos_drawdown_amount
      ?? metrics.max_drawdown_amount
      ?? bootstrap.median_drawdown_amount
      ?? bootstrap.worst_case_drawdown_amount
    );
  }

  return {
    label: currentSimulationResult,
    netProfit,
    drawdown,
    drawdownAmount,
    sharpe,
    sortino,
    totalTrades,
    winRate,
    bootstrapPass,
  };
}

function buildNormalTrainingRows(payload, snapshot) {
  const tableStats = payload.table_stats || {};
  const metrics = payload.metrics || {};
  return {
    headers: ["Metric", "All", "Long", "Short"],
    sectionLabel: "Normal Training",
    rows: [
      ["Net Profit", formatNumber(snapshot.netProfit), formatNumber(tableStats.long_profit), formatNumber(tableStats.short_profit)],
      ["Net Profit %", metrics.net_profit_pct != null ? formatPercent(metrics.net_profit_pct) : "--", "--", "--"],
      ["Commission Paid", formatNumber(tableStats.all_commission), formatNumber(tableStats.long_commission), formatNumber(tableStats.short_commission)],
      ["Avg Bars In Trades", formatNumber(tableStats.all_bars), formatNumber(tableStats.long_bars), formatNumber(tableStats.short_bars)],
      ["Total Trades", snapshot.totalTrades != null ? formatNumber(snapshot.totalTrades, 0) : "--", "--", "--"],
      ["Win Rate", snapshot.winRate != null ? formatPercent(snapshot.winRate) : "--", "--", "--"],
      ["Sortino Ratio", snapshot.sortino != null ? formatNumber(snapshot.sortino) : "--", "--", "--"],
    ],
  };
}

function buildBootstrapRows(payload, snapshot) {
  const metrics = payload.metrics || {};
  const bootstrap = payload.bootstrap || {};
  const sampleCount = toNumberOrNull(bootstrap.sample_count);
  return {
    headers: ["Metric", "Selection", "Median", "Worst Case"],
    sectionLabel: "Bootstrap Review",
    rows: [
      ["Pass Rate", snapshot.bootstrapPass != null ? formatPercent(snapshot.bootstrapPass) : "--", "--", "--"],
      ["Net Profit", formatNumber(toNumberOrNull(metrics.selection_oos_net_pnl ?? metrics.net_profit)), formatNumber(toNumberOrNull(bootstrap.median_net_profit)), formatNumber(toNumberOrNull(bootstrap.worst_case_net_profit))],
      ["Max Drawdown", formatPercent(toAbsNumberOrNull(metrics.selection_oos_drawdown ?? metrics.max_drawdown)), formatPercent(toAbsNumberOrNull(bootstrap.median_max_drawdown)), formatPercent(toAbsNumberOrNull(bootstrap.worst_case_drawdown))],
      ["Sharpe", formatNumber(toNumberOrNull(metrics.selection_oos_sharpe ?? metrics.sharpe_ratio)), formatNumber(toNumberOrNull(bootstrap.median_sharpe)), formatNumber(toNumberOrNull(bootstrap.worst_case_sharpe))],
      ["Samples", sampleCount != null ? formatNumber(sampleCount, 0) : "--", sampleCount != null ? formatNumber(sampleCount, 0) : "--", sampleCount != null ? formatNumber(sampleCount, 0) : "--"],
      ["Simulation", currentSimulationResult, "Resilience", snapshot.bootstrapPass != null ? formatPercent(snapshot.bootstrapPass) : "--"],
    ],
  };
}

function buildScenarioRows(payload) {
  const scenarios = Array.isArray(payload.scenarios) ? payload.scenarios : [];
  const rows = scenarios.slice(0, 6).map((scenario) => [
    scenario.name || scenario.scenario_name || "Scenario",
    scenario.passed === false ? "Fail" : "Pass",
    formatNumber(toNumberOrNull(scenario.sharpe)),
    formatPercent(toAbsNumberOrNull(scenario.max_drawdown)),
  ]);

  if (!rows.length) {
    rows.push(["No scenario data", "--", "--", "--"]);
  }

  return {
    headers: ["Scenario", "Status", "Sharpe", "Drawdown"],
    sectionLabel: "Scenario Matrix",
    rows,
  };
}

function buildNewStrategyRows(payload) {
  const runtime = payload.runtime_settings || {};
  const selectedParameters = payload.selected_parameters || {};
  const selectedKeys = Object.keys(selectedParameters);
  return {
    headers: ["Setting", "Value", "Context", "Note"],
    sectionLabel: "Strategy Profile",
    rows: [
      ["Position Side", runtime.position_side || "--", "Leverage", runtime.position_leverage != null ? `x${formatNumber(runtime.position_leverage, 2)}` : "--"],
      ["Simulation", currentSimulationResult, "Sort Metric", currentSortMetric],
      ["Accepted Layers", Array.isArray(payload.strategy?.layers) ? payload.strategy.layers.join(", ") : "--", "Layer Count", Array.isArray(payload.strategy?.layers) ? formatNumber(payload.strategy.layers.length, 0) : "--"],
      ["Primary Parameter", selectedKeys[0] || "--", "Value", selectedKeys.length ? String(selectedParameters[selectedKeys[0]]) : "--"],
      ["Slippage", runtime.slippage_bps != null ? `${formatNumber(runtime.slippage_bps, 2)} bps` : "--", "Funding", runtime.funding_rate_bps != null ? `${formatNumber(runtime.funding_rate_bps, 2)} bps` : "--"],
      ["Latest Run", payload.run_id || "--", "Decision", payload.decision || payload.artifacts?.final_status || "--"],
    ],
  };
}

function renderTrainingTable(payload) {
  const tableBody = document.getElementById("trainingTableBody");
  const snapshot = getSimulationSnapshot(payload);
  let tableModel = buildNormalTrainingRows(payload, snapshot);
  const modeKey = String(currentAnalysisMode).toLowerCase();

  if (modeKey.includes("bootstrap")) {
    tableModel = buildBootstrapRows(payload, snapshot);
  } else if (modeKey.includes("scenario")) {
    tableModel = buildScenarioRows(payload);
  } else if (modeKey.includes("strategy profile")) {
    tableModel = buildNewStrategyRows(payload);
  }

  const glowTitle = document.querySelector(".glow-title");
  if (glowTitle) {
    glowTitle.textContent = tableModel.sectionLabel.toUpperCase();
  }
  document.getElementById("tableKicker").textContent = tableModel.sectionLabel.toUpperCase();
  setTableHeaders(tableModel.headers);

  tableBody.replaceChildren();
  tableModel.rows.forEach((row) => {
    const tableRow = document.createElement("tr");
    row.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = String(value ?? "--");
      tableRow.appendChild(cell);
    });
    tableBody.appendChild(tableRow);
  });
}

function getRankMetricValue(entry, metricName) {
  const normalizedMetric = String(metricName || "").toLowerCase();
  if (normalizedMetric.includes("drawdown")) {
    return toAbsNumberOrNull(entry.max_drawdown ?? entry.metric_value);
  }
  if (normalizedMetric.includes("sharpe")) {
    return toNumberOrNull(entry.oos_sharpe ?? entry.metric_value);
  }
  return toNumberOrNull(entry.oos_net_pnl ?? entry.metric_value);
}

function getRankedSets(payload) {
  const ranked = (payload.visuals?.ranked_parameter_sets || []).map((entry, index) => ({
    ...entry,
    label: entry.label || entry.layer_name || `parameter-set-${index + 1}`,
  }));

  if (!ranked.length) {
    const selectionEntry = {
      label: payload.strategy?.layers?.[0] || payload.run_id || "selection",
      max_drawdown: toAbsNumberOrNull(payload.metrics?.selection_oos_drawdown ?? payload.metrics?.max_drawdown),
      oos_sharpe: toNumberOrNull(payload.metrics?.selection_oos_sharpe ?? payload.metrics?.sharpe_ratio),
      oos_net_pnl: toNumberOrNull(payload.metrics?.selection_oos_net_pnl ?? payload.metrics?.net_profit),
    };
    if (
      selectionEntry.max_drawdown == null
      && selectionEntry.oos_sharpe == null
      && selectionEntry.oos_net_pnl == null
    ) {
      return [];
    }
    return [selectionEntry];
  }

  return ranked.sort((left, right) => {
    const leftValue = getRankMetricValue(left, currentSortMetric) ?? 0;
    const rightValue = getRankMetricValue(right, currentSortMetric) ?? 0;
    if (String(currentSortMetric).toLowerCase().includes("drawdown")) {
      return leftValue - rightValue;
    }
    return rightValue - leftValue;
  });
}

function renderRankedResults(payload) {
  const rankList = document.getElementById("rankList");
  const ranked = getRankedSets(payload);
  document.getElementById("rankTitle").textContent = `Ranked Results: ${ranked.length || 1} Parameter Sets`;
  rankList.innerHTML = "";

  if (!ranked.length) {
    const chip = document.createElement("div");
    chip.className = "rank-chip";
    chip.textContent = "No ranked parameter data";
    rankList.appendChild(chip);
    return;
  }

  ranked.slice(0, 6).forEach((entry, index) => {
    const chip = document.createElement("div");
    chip.className = `rank-chip${index === 0 ? " active" : ""}`;
    chip.textContent = `${entry.label}: ${currentSortMetric} ${formatMetricValue(getRankMetricValue(entry, currentSortMetric), currentSortMetric)}`;
    rankList.appendChild(chip);
  });
}

function renderMetrics(payload) {
  const snapshot = getSimulationSnapshot(payload);
  document.getElementById("mtProfit").textContent = formatNumber(snapshot.netProfit);
  document.getElementById("mtDD1").textContent = snapshot.drawdownAmount != null ? `${formatNumber(snapshot.drawdownAmount, 2)} USDT` : "--";
  document.getElementById("mtDD2").textContent = snapshot.drawdown != null ? formatPercent(snapshot.drawdown) : "--";
  document.getElementById("mtTrades").textContent = snapshot.totalTrades != null ? formatNumber(snapshot.totalTrades, 0) : "--";
  document.getElementById("mtWin").textContent = snapshot.winRate != null ? formatPercent(snapshot.winRate) : "--";
  document.getElementById("mtSharpe").textContent = formatNumber(snapshot.sharpe);
  document.getElementById("mtSortino").textContent = snapshot.sortino != null ? formatNumber(snapshot.sortino) : "nan";
  document.getElementById("mtBoot").textContent = snapshot.bootstrapPass != null ? formatPercent(snapshot.bootstrapPass) : "--";
  document.getElementById("sidebarStats").textContent =
    `MaxDD: ${snapshot.drawdown ? formatNumber(snapshot.drawdown * 100) : "--"}  Sharpe: ${formatNumber(snapshot.sharpe)}  Sortino: ${snapshot.sortino != null ? formatNumber(snapshot.sortino) : "nan"}  WinRate: ${snapshot.winRate != null ? formatPercent(snapshot.winRate) : "--"}`;
}

function renderHeader(payload) {
  const headerContext = document.getElementById("headerContext");
  if (!headerContext) return;
  const context = payload.visuals?.context || {};
  const symbol = context.symbol || payload.artifacts?.symbol || "UNKNOWN";
  const timeframe = context.timeframe && context.timeframe !== "--" ? ` ${context.timeframe}` : "";
  headerContext.textContent = `${symbol}${timeframe}`;
}

function renderControls(payload) {
  const config = getControlConfig(payload);
  if (!config.analysisModes.includes(currentAnalysisMode)) currentAnalysisMode = config.analysisModes[0];
  if (!config.sortMetrics.includes(currentSortMetric)) currentSortMetric = config.sortMetrics[0];
  if (!config.simulationResults.includes(currentSimulationResult)) currentSimulationResult = config.simulationResults[0];
  setSelectOptions("analysisModeSelect", config.analysisModes, currentAnalysisMode);
  setSelectOptions("sortMetricSelect", config.sortMetrics, currentSortMetric);
  setSelectOptions("simulationResultSelect", config.simulationResults, currentSimulationResult);
}

function initCharts() {
  Chart.defaults.color = "rgba(242,239,231,0.62)";
  Chart.defaults.font.family = "'Space Mono', monospace";
  Chart.defaults.borderColor = "rgba(242,239,231,0.10)";

  mainChart = new Chart(document.getElementById("mainEquityChart").getContext("2d"), {
    type: "line",
    data: { labels: [], datasets: [] },
    options: {
      maintainAspectRatio: false,
      responsive: true,
      animation: false,
      interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false } },
      layout: { padding: { left: 6, right: 8, top: 4, bottom: 0 } },
      scales: {
        x: {
          grid: { color: "rgba(242,239,231,0.08)" },
          ticks: { maxTicksLimit: 6 },
          title: { display: true, text: "Timestamp", color: "rgba(242,239,231,0.62)", font: { size: 11, weight: "600" } },
        },
        y: {
          grid: { color: "rgba(242,239,231,0.08)" },
          title: { display: true, text: "Equity ($)", color: "rgba(242,239,231,0.62)", font: { size: 11, weight: "600" } },
        },
      },
      elements: { point: { radius: 0 }, line: { tension: 0 } },
    },
  });

  ddChart = new Chart(document.getElementById("ddChartCanvas").getContext("2d"), {
    type: "line",
    data: { labels: [], datasets: [] },
    options: {
      maintainAspectRatio: false,
      responsive: true,
      animation: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { display: false },
        y: { display: false, reverse: true },
      },
      elements: { point: { radius: 0 }, line: { tension: 0 } },
    },
  });
}

function renderCharts(payload) {
  const timeseries = payload.visuals?.timeseries || payload.timeseries || [];
  const fallback = document.getElementById("equityFallback");
  if (!timeseries.length) {
    fallback.style.display = "flex";
    mainChart.data.labels = [];
    mainChart.data.datasets = [];
    mainChart.update();
    ddChart.data.labels = [];
    ddChart.data.datasets = [];
    ddChart.update();
    return;
  }

  fallback.style.display = "none";
  const labels = timeseries.map((entry) => entry.timestamp);
  const equity = timeseries.map((entry) => toNumberOrNull(entry.equity) ?? 0);
  const drawdown = timeseries.map((entry) => Math.abs(toNumberOrNull(entry.drawdown) ?? 0) * 100);
  const accent = getThemeAccentColor();

  mainChart.data.labels = labels;
  mainChart.data.datasets = [{ data: equity, borderColor: accent, backgroundColor: "transparent", fill: false, borderWidth: 2 }];
  mainChart.update();

  ddChart.data.labels = labels;
  ddChart.data.datasets = [{ data: drawdown, borderColor: accent, backgroundColor: "transparent", fill: false, borderWidth: 1.5 }];
  ddChart.update();
}

function renderDashboard() {
  if (!currentPayload) return;
  applyStrategyTheme(currentPayload);
  renderHeader(currentPayload);
  renderControls(currentPayload);
  renderParameterPills(currentPayload);
  renderMetrics(currentPayload);
  renderTrainingTable(currentPayload);
  renderRankedResults(currentPayload);
  renderCharts(currentPayload);
  overlay.classList.add("hidden");
}

function showOverlayMessage(title, message) {
  const heading = overlay.querySelector("h2");
  const body = overlay.querySelector("p");
  if (heading) heading.textContent = title;
  if (body) body.textContent = message;
  overlay.classList.remove("hidden");
}

function sourceQuery() {
  if (currentDataMode === "paper") return "source=paper";
  return "source=strategy";
}

function populate(payload) {
  currentPayload = payload;
  const config = getControlConfig(payload);
  if (!config.analysisModes.includes(currentAnalysisMode)) currentAnalysisMode = config.analysisModes[0];
  if (!config.sortMetrics.includes(currentSortMetric)) currentSortMetric = config.sortMetrics[0];
  if (!config.simulationResults.includes(currentSimulationResult)) currentSimulationResult = config.simulationResults[0];
  currentRunId = payload.run_id || payload.visuals?.context?.snapshot_id || payload.artifacts?.snapshot_id || "loaded";
  renderDashboard();
}

async function fetchLatestDashboard() {
  try {
    const endpoint = currentDataMode === "test"
      ? "/api/test_dashboard"
      : `/api/latest_dashboard?${sourceQuery()}`;
    const response = await fetch(endpoint, { cache: "no-store" });
    if (!response.ok) return false;
    const payload = await response.json();
    if (payload.error) {
      showOverlayMessage("NO DATA FOR SELECTED MODE", payload.error);
      return false;
    }
    populate(payload);
    return true;
  } catch (error) {
    return false;
  }
}

async function fetchDashboardList() {
  try {
    if (currentDataMode === "test") {
      availableDashboards = [{ run_id: "test-backtest", symbol: "TEST", path: "__test__", status: "test" }];
    } else {
      const response = await fetch(`/api/dashboard_files?${sourceQuery()}`, { cache: "no-store" });
      if (!response.ok) return [];
      const payload = await response.json();
      availableDashboards = payload.items || [];
    }
  } catch (error) {
    availableDashboards = [];
  }

  manualRunSelect.innerHTML = "";
  availableDashboards.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.path;
    option.textContent = `${item.symbol} | ${item.run_id}`;
    manualRunSelect.appendChild(option);
  });
  if (availableDashboards.length && !manualRunSelect.value) {
    manualRunSelect.value = availableDashboards[0].path;
  }
  if (!availableDashboards.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = currentDataMode === "paper" ? "No paper telemetry found" : "No real strategy dashboards found";
    manualRunSelect.appendChild(option);
  }
  return availableDashboards;
}

async function loadSelectedDashboard(path) {
  if (!path) return;
  if (currentDataMode === "test" || path === "__test__") {
    await fetchLatestDashboard();
    return;
  }
  await loadManualDashboardFromServer(path);
}

async function loadManualDashboardFromServer(path) {
  if (!path) return;
  const response = await fetch(`/api/dashboard_file?path=${encodeURIComponent(path)}&${sourceQuery()}`, { cache: "no-store" });
  if (!response.ok) return;
  const payload = await response.json();
  if (payload.error) return;
  populate(payload);
}

dataModeSelect.addEventListener("change", async (event) => {
  currentDataMode = event.target.value;
  currentRunId = null;
  await fetchDashboardList();
  await fetchLatestDashboard();
});

analysisModeSelect.addEventListener("change", (event) => {
  currentAnalysisMode = event.target.value;
  renderDashboard();
});

sortMetricSelect.addEventListener("change", (event) => {
  currentSortMetric = event.target.value;
  renderDashboard();
});

simulationResultSelect.addEventListener("change", (event) => {
  currentSimulationResult = event.target.value;
  renderDashboard();
});

manualRunSelect.addEventListener("change", async (event) => {
  await loadSelectedDashboard(event.target.value);
});

uploadButton.addEventListener("click", () => {
  manualFileInput.click();
});

manualFileInput.addEventListener("change", (event) => {
  const [file] = event.target.files;
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (loadEvent) => {
    try {
      const payload = JSON.parse(loadEvent.target.result);
      populate(payload);
    } catch (error) {
      console.error(`Could not load ${file.name}: invalid JSON`);
    }
  };
  reader.readAsText(file);
});

window.addEventListener("resize", syncStageScale);

window.addEventListener("DOMContentLoaded", async () => {
  syncStageScale();
  initCharts();
  setDataModeOptions();
  await fetchDashboardList();
  await fetchLatestDashboard();
  window.setInterval(fetchLatestDashboard, 4000);
});
