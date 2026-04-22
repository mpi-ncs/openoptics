// Turn server-provided metric metadata + per-epoch series into Chart.js charts.
// Charts are keyed by (metric_type, device, labels-stringified) so live pushes
// can find the right dataset without any hardcoded metric name.
//
// Layout: each metric type groups its (device) tiles in a responsive grid;
// every tile eagerly instantiates its chart so the whole page is scannable
// without clicks. Clicking a tile expands it to the full grid row for a
// closer look; clicking again collapses it.

// Tailwind-ish palette: hues match the CSS accent (indigo) and sit well on
// light cards. Keep them fairly saturated so multi-series lines separate.
const PALETTE = [
  "#6366f1", // indigo
  "#06b6d4", // cyan
  "#10b981", // emerald
  "#f59e0b", // amber
  "#ef4444", // red
  "#8b5cf6", // violet
  "#14b8a6", // teal
  "#ec4899", // pink
  "#3b82f6", // blue
  "#84cc16", // lime
];

// Hex colour → rgba(…, alpha). Works for #RRGGBB only (our palette is).
function withAlpha(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  const r = (n >> 16) & 0xff;
  const g = (n >> 8) & 0xff;
  const b = n & 0xff;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

const CHART_COLORS = {
  text:       "#334155",   // slate-700
  textMuted:  "#64748b",   // slate-500
  grid:       "rgba(148, 163, 184, 0.18)", // slate-400 @ 18%
  tooltipBg:  "rgba(15, 23, 42, 0.94)",
  tooltipTxt: "#e2e8f0",
};

const CHART_FONT = {
  family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  size: 11,
};

function labelsKey(labels) {
  return JSON.stringify(
    Object.keys(labels || {}).sort().reduce((acc, k) => {
      acc[k] = labels[k];
      return acc;
    }, {}),
  );
}

function sampleKey(metricType, device, labels) {
  return `${metricType}|${device}|${labelsKey(labels)}`;
}

function prettyLabels(labels) {
  if (!labels || Object.keys(labels).length === 0) return "";
  return Object.entries(labels).map(([k, v]) => `${k}=${v}`).join(", ");
}

export class ChartManager {
  constructor({ container, metricTypes, aggregateDevice }) {
    this.container = container;
    this.aggregateDevice = aggregateDevice;
    this.metaByType = new Map(metricTypes.map(m => [m.metric_type, m]));
    // chartKey → {canvas, metricType, device, datasets, chart|null}
    this.groups = new Map();
    // sample key → {chartKey, datasetIndex}
    this.datasets = new Map();
  }

  renderAll(seriesByType) {
    this.container.innerHTML = "";
    this.groups.clear();
    this.datasets.clear();

    // Render every declared metric type — including ones with zero initial
    // samples — so (a) users see all dashboards from epoch start and
    // (b) ``pushSample`` can attach a new device/dataset under a pre-existing
    // group when the first live sample of a sparse type arrives.
    for (const metricType of this.metaByType.keys()) {
      const { gridEl } = this._ensureGroup(metricType);
      const entries = seriesByType[metricType] || [];
      const byDevice = new Map();
      for (const entry of entries) {
        if (!byDevice.has(entry.device)) byDevice.set(entry.device, []);
        byDevice.get(entry.device).push(entry);
      }
      // Aggregate device first.
      const sortedDevices = Array.from(byDevice.keys()).sort((a, b) => {
        if (a === this.aggregateDevice) return -1;
        if (b === this.aggregateDevice) return 1;
        return a.localeCompare(b);
      });

      for (const device of sortedDevices) {
        this._renderDeviceChart(
          gridEl, metricType, device, byDevice.get(device),
        );
      }

      if (sortedDevices.length === 0) {
        const empty = document.createElement("div");
        empty.className = "metric-empty";
        empty.textContent = "No samples yet.";
        gridEl.appendChild(empty);
      }
    }
  }

  // Ensure a `.metric-group` exists for this metric type and return both the
  // group element and its inner `.metric-chart-grid` (where tiles live).
  _ensureGroup(metricType) {
    const existing = this.container.querySelector(
      `.metric-group[data-metric-type="${CSS.escape(metricType)}"]`,
    );
    if (existing) {
      return { groupEl: existing, gridEl: existing.querySelector(".metric-chart-grid") };
    }
    const groupEl = document.createElement("div");
    groupEl.className = "metric-group";
    groupEl.dataset.metricType = metricType;
    const meta = this.metaByType.get(metricType) || { display_name: metricType };
    const header = document.createElement("h3");
    header.textContent = meta.display_name + (meta.unit ? ` (${meta.unit})` : "");
    groupEl.appendChild(header);
    const gridEl = document.createElement("div");
    gridEl.className = "metric-chart-grid";
    groupEl.appendChild(gridEl);
    this.container.appendChild(groupEl);
    return { groupEl, gridEl };
  }

  _renderDeviceChart(gridEl, metricType, device, entries) {
    const chartKey = `${metricType}|${device}`;
    const isAggregate = device === this.aggregateDevice;

    const wrap = document.createElement("div");
    wrap.className = "metric-chart-wrap" + (isAggregate ? " is-aggregate" : "");

    const headerBtn = document.createElement("div");
    headerBtn.className = "metric-chart-header";
    const title = document.createElement("span");
    title.textContent = device;
    headerBtn.appendChild(title);

    const canvasWrap = document.createElement("div");
    canvasWrap.className = "metric-chart-canvas-wrap";
    const canvas = document.createElement("canvas");
    canvasWrap.appendChild(canvas);

    wrap.appendChild(headerBtn);
    wrap.appendChild(canvasWrap);
    gridEl.appendChild(wrap);

    const datasets = entries.map((entry, i) => {
      const color = PALETTE[i % PALETTE.length];
      return {
        label: prettyLabels(entry.labels) || entry.device,
        data: entry.series.map(([t, v]) => ({ x: t, y: v })),
        borderColor: color,
        backgroundColor: withAlpha(color, 0.12),
        borderWidth: 2,
        pointRadius: 0,
        pointHoverRadius: 4,
        pointHoverBackgroundColor: color,
        pointHoverBorderColor: "#ffffff",
        pointHoverBorderWidth: 2,
        cubicInterpolationMode: "monotone",
        fill: false,
      };
    });

    const group = {
      chartKey,
      metricType,
      device,
      canvas,
      wrap,
      headerBtn,
      datasets,  // raw config
      chart: null,
    };
    this.groups.set(chartKey, group);

    entries.forEach((entry, i) => {
      const key = sampleKey(metricType, device, entry.labels);
      this.datasets.set(key, { chartKey, datasetIndex: i });
    });

    // Click the header to toggle expand (full-row + taller); let the CSS
    // transition finish before asking Chart.js to resize.
    headerBtn.addEventListener("click", () => {
      wrap.classList.toggle("is-expanded");
      if (group.chart !== null) {
        setTimeout(() => group.chart.resize(), 200);
      }
    });

    // Eager instantiation: the tile is always visible in the grid, so
    // Chart.js's responsive sizing finds a real parent rect immediately.
    this._instantiate(group);
  }

  _instantiate(group) {
    if (group.chart !== null) return;
    const meta = this.metaByType.get(group.metricType);
    const axisTitleFont = { ...CHART_FONT, size: 11, weight: "500" };
    group.chart = new Chart(group.canvas, {
      type: meta?.chart_kind === "bar" ? "bar" : "line",
      data: { datasets: group.datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 260, easing: "easeOutCubic" },
        interaction: { mode: "nearest", axis: "x", intersect: false },
        layout: { padding: { top: 2, right: 4, bottom: 2, left: 2 } },
        scales: {
          x: {
            type: "linear",
            title: {
              display: true, text: "timestep",
              color: CHART_COLORS.textMuted, font: axisTitleFont,
              padding: { top: 6 },
            },
            grid: { color: CHART_COLORS.grid, drawTicks: false },
            border: { display: false },
            ticks: {
              color: CHART_COLORS.textMuted, font: CHART_FONT,
              padding: 6, maxTicksLimit: 8,
            },
          },
          y: {
            beginAtZero: true,
            title: {
              display: !!meta?.unit, text: meta?.unit || "",
              color: CHART_COLORS.textMuted, font: axisTitleFont,
              padding: { bottom: 6 },
            },
            grid: { color: CHART_COLORS.grid, drawTicks: false },
            border: { display: false },
            ticks: {
              color: CHART_COLORS.textMuted, font: CHART_FONT,
              padding: 8, maxTicksLimit: 6,
            },
          },
        },
        plugins: {
          legend: {
            display: true,
            position: "bottom",
            align: "center",
            labels: {
              usePointStyle: true,
              pointStyle: "circle",
              boxWidth: 5,
              boxHeight: 5,
              padding: 8,
              color: CHART_COLORS.text,
              font: { ...CHART_FONT, size: 10 },
            },
          },
          tooltip: {
            enabled: true,
            backgroundColor: CHART_COLORS.tooltipBg,
            titleColor: "#f8fafc",
            bodyColor: CHART_COLORS.tooltipTxt,
            borderColor: "rgba(255, 255, 255, 0.08)",
            borderWidth: 1,
            cornerRadius: 6,
            padding: 10,
            displayColors: true,
            boxWidth: 8,
            boxHeight: 8,
            usePointStyle: true,
            titleFont: { ...CHART_FONT, weight: "600" },
            bodyFont: CHART_FONT,
          },
        },
      },
    });
  }

  pushSample(msg, maxPoints) {
    const key = sampleKey(msg.metric_type, msg.device, msg.labels);
    let mapping = this.datasets.get(key);
    if (!mapping) {
      // First time we've seen this (metric_type, device, labels). Create the
      // chart group / device sub-chart / dataset on the fly so sparse metrics
      // (ta_reconfig, latency, OCS hits once traffic starts) show up live.
      if (!this._lazyAddDataset(msg)) return;
      mapping = this.datasets.get(key);
      if (!mapping) return;
    }
    const group = this.groups.get(mapping.chartKey);
    if (!group) return;
    // Append to the raw dataset config so the in-memory buffer is correct
    // even before the Chart instance exists; when the user finally opens
    // the row the chart is created with the up-to-date buffer.
    const ds = group.datasets[mapping.datasetIndex];
    ds.data.push({ x: msg.timestep, y: msg.value });
    if (ds.data.length > maxPoints) ds.data.splice(0, ds.data.length - maxPoints);
    if (group.chart !== null) group.chart.update("none");
  }

  // Attach a new (metric_type, device, labels) tuple without a full re-render.
  // Returns true on success, false if the metric type isn't declared server-side
  // (in which case the sample is dropped silently — same as before).
  _lazyAddDataset(msg) {
    if (!this.metaByType.has(msg.metric_type)) return false;
    const chartKey = `${msg.metric_type}|${msg.device}`;
    let group = this.groups.get(chartKey);
    if (!group) {
      // New (metric_type, device): ensure the type's group exists, then
      // append a sub-chart for this device with a single empty dataset.
      const { gridEl } = this._ensureGroup(msg.metric_type);
      const empty = gridEl.querySelector(".metric-empty");
      if (empty) empty.remove();
      this._renderDeviceChart(gridEl, msg.metric_type, msg.device, [{
        device: msg.device,
        labels: msg.labels || {},
        series: [],
      }]);
      return true;
    }
    // Existing (metric_type, device), new labels tuple: add a new dataset
    // to the live chart without tearing it down.
    const color = PALETTE[group.datasets.length % PALETTE.length];
    const newDs = {
      label: prettyLabels(msg.labels) || msg.device,
      data: [],
      borderColor: color,
      backgroundColor: withAlpha(color, 0.12),
      borderWidth: 2,
      pointRadius: 0,
      pointHoverRadius: 4,
      pointHoverBackgroundColor: color,
      pointHoverBorderColor: "#ffffff",
      pointHoverBorderWidth: 2,
      cubicInterpolationMode: "monotone",
      fill: false,
    };
    group.datasets.push(newDs);
    const idx = group.datasets.length - 1;
    this.datasets.set(
      sampleKey(msg.metric_type, msg.device, msg.labels),
      { chartKey, datasetIndex: idx },
    );
    if (group.chart !== null) {
      group.chart.data.datasets.push(newDs);
      group.chart.update("none");
    }
    return true;
  }
}
