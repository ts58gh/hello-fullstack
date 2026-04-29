// Minimal reconnecting WebSocket client.
//
// Used by bridge.js to talk to /api/bridge/tables/{id}/ws. The server pushes
// per-seat views on every state mutation; the client sends actions back via
// `send({type: 'action', action: {...}})`. Pings every 25s to keep idle
// connections warm; reconnects with exponential backoff up to 30s on close.

(function (root) {
  class WSClient {
    constructor({ url, onOpen, onMessage, onClose, onStateChange } = {}) {
      this.url = url;
      this.onOpen = onOpen || (() => {});
      this.onMessage = onMessage || (() => {});
      this.onClose = onClose || (() => {});
      this.onStateChange = onStateChange || (() => {});
      this.ws = null;
      this.shouldClose = false;
      this.reconnectAttempt = 0;
      this.pingTimer = null;
      this.state = "closed"; // closed | connecting | open
    }

    connect() {
      if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return;
      this.shouldClose = false;
      this._setState("connecting");
      let socket;
      try {
        socket = new WebSocket(this.url);
      } catch (e) {
        this._setState("closed");
        this._scheduleReconnect();
        return;
      }
      this.ws = socket;
      socket.onopen = () => {
        this.reconnectAttempt = 0;
        this._setState("open");
        this._startPing();
        try { this.onOpen(); } catch {}
      };
      socket.onmessage = (ev) => {
        let data;
        try { data = JSON.parse(ev.data); } catch { return; }
        try { this.onMessage(data); } catch {}
      };
      socket.onclose = () => {
        this._stopPing();
        this._setState("closed");
        try { this.onClose(); } catch {}
        if (!this.shouldClose) this._scheduleReconnect();
      };
      socket.onerror = () => {
        // close handler will fire after this; nothing to do.
      };
    }

    send(obj) {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try { this.ws.send(JSON.stringify(obj)); } catch {}
      }
    }

    close() {
      this.shouldClose = true;
      this._stopPing();
      if (this.ws) {
        try { this.ws.close(); } catch {}
      }
    }

    _startPing() {
      this._stopPing();
      this.pingTimer = setInterval(() => this.send({ type: "ping" }), 25000);
    }
    _stopPing() {
      if (this.pingTimer) { clearInterval(this.pingTimer); this.pingTimer = null; }
    }
    _scheduleReconnect() {
      if (this.shouldClose) return;
      this.reconnectAttempt += 1;
      const delay = Math.min(30000, 1000 * Math.pow(2, this.reconnectAttempt - 1));
      setTimeout(() => this.connect(), delay);
    }
    _setState(s) {
      if (this.state !== s) {
        this.state = s;
        try { this.onStateChange(s); } catch {}
      }
    }
  }

  root.WSClient = WSClient;
})(window);
