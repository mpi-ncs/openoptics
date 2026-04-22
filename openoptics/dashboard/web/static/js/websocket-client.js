// WebSocket client for the /ws/live endpoint.
//
// One connection, no auto-reconnect. When the OpenOptics script exits the
// server vanishes and any reconnection attempt would be forwarded through the
// user's SSH tunnel and logged as "channel N: connect failed" noise in their
// terminal. Requiring a manual page refresh to resume is a fair tradeoff for
// a quiet shell.

export class LiveClient {
  constructor(epochId) {
    this.epochId = epochId;
    this._msgHandlers = [];
    this._ws = null;
  }

  onMessage(fn) { this._msgHandlers.push(fn); }

  connect() {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${window.location.host}/ws/live?epoch_id=${this.epochId}`;
    this._ws = new WebSocket(url);
    this._ws.addEventListener("message", ev => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      for (const h of this._msgHandlers) {
        try { h(msg); } catch (e) { console.error("live handler threw:", e); }
      }
    });
  }

  close() {
    if (this._ws) this._ws.close();
  }
}
