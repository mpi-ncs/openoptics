// Dashboard entry point.
// Loads metric-type metadata + epochs + current-epoch data, wires live WS.

import { ChartManager } from "./chart-manager.js";
import { LiveClient } from "./websocket-client.js";

const AGGREGATE_DEVICE = "network";
const MAX_LIVE_POINTS = 60;

function qs(id) { return document.getElementById(id); }

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.json();
}

function buildEpochNav(epochs, selectedId) {
  const el = qs("epoch-list");
  el.innerHTML = "";
  for (const epoch of epochs) {
    const a = document.createElement("a");
    a.href = `?epoch_id=${epoch.id}`;
    a.textContent = epoch.display_name;
    if (epoch.id === selectedId) a.classList.add("active");
    el.appendChild(a);
  }
}

function setTopoImage(url) {
  const img = qs("topo-image");
  if (url) {
    img.src = url;
    img.style.display = "";
  } else {
    img.style.display = "none";
  }
}

async function main() {
  const params = new URLSearchParams(window.location.search);
  const selectedId = params.get("epoch_id")
    ? parseInt(params.get("epoch_id"), 10)
    : null;

  const [metricTypes, epochs] = await Promise.all([
    fetchJSON("/api/metric_types"),
    fetchJSON("/api/epochs"),
  ]);

  const epoch = selectedId
    ? epochs.find(e => e.id === selectedId)
    : epochs[epochs.length - 1];

  if (!epoch) {
    qs("empty-state").hidden = false;
    qs("topo-image").style.display = "none";
    return;
  }

  buildEpochNav(epochs, epoch.id);
  setTopoImage(epoch.topo_image_url);

  const seriesByType = await fetchJSON(`/api/epochs/${epoch.id}/metrics`);

  const charts = new ChartManager({
    container: qs("metrics-panel"),
    metricTypes,
    aggregateDevice: AGGREGATE_DEVICE,
  });
  charts.renderAll(seriesByType);

  // Live updates for the *current* epoch only.
  const isLatestEpoch = epoch.id === epochs[epochs.length - 1].id;
  if (isLatestEpoch) {
    const live = new LiveClient(epoch.id);
    live.onMessage(msg => {
      if (msg.kind === "metric") {
        charts.pushSample(msg, MAX_LIVE_POINTS);
      } else if (msg.kind === "topology") {
        setTopoImage(msg.image_url);
      }
    });
    live.connect();
  }
}

main().catch(err => {
  console.error("dashboard init failed:", err);
});
