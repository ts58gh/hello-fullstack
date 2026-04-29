// Bridge frontend — single-player vs bots and real-time multi-player.
//
// View state machine: 'lobby' | 'seating' | 'playing'
// - Lobby: shows open tables and create-table controls.
// - Seating: shown when a table is selected but no seat is claimed yet
//   (e.g. via a shared link). User picks an open seat.
// - Playing: shows the felt board, auction grid, hand, etc. All real-time
//   updates come over WebSockets.
//
// HTTP is used for lobby polling, table creation, seat claim/release, and
// "next deal" requests. Actions during a deal go over the WebSocket.

(function () {
  // ---- constants ------------------------------------------------------
  const SUIT_INFO = {
    C: { sym: "\u2663", color: "black" },
    D: { sym: "\u2666", color: "red" },
    H: { sym: "\u2665", color: "red" },
    S: { sym: "\u2660", color: "black" },
    NT: { sym: "NT", color: "black" },
  };
  const RANK_LABEL = { 11: "J", 12: "Q", 13: "K", 14: "A" };
  function rankLabel(r) { return RANK_LABEL[r] || String(r); }

  const STORAGE = {
    apiBase: "hello_fullstack_api_base",
    clientId: "hello_fullstack_bridge_client_id",
    displayName: "hello_fullstack_bridge_display_name",
    session: "hello_fullstack_bridge_session", // {tableId, seat, token}
  };

  // ---- API base resolution -------------------------------------------
  function normalizeBaseUrl(x) { return String(x || "").trim().replace(/\/+$/, ""); }
  function getApiBaseFromUrl() {
    const v = new URLSearchParams(window.location.search).get("api");
    return v ? normalizeBaseUrl(v) : "";
  }
  function getApiBaseFromStorage() {
    try { return normalizeBaseUrl(localStorage.getItem(STORAGE.apiBase)); } catch { return ""; }
  }
  const API_BASE = getApiBaseFromUrl() || getApiBaseFromStorage() || "https://hello-fullstack-py.onrender.com";

  function wsUrl(path) {
    // Convert https/http -> wss/ws. API_BASE may be relative (no scheme); fall back to current host.
    let base = API_BASE;
    if (!/^https?:\/\//i.test(base)) base = window.location.origin;
    return base.replace(/^http/i, "ws") + path;
  }

  // ---- DOM refs -------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const lobbyEl = $("lobby");
  const gameEl = $("game");
  const seatOverlayEl = $("seatOverlay");
  const seatChoicesEl = $("seatChoices");
  const seatOverlayInfoEl = $("seatOverlayInfo");
  const endcardEl = $("endcard");
  const endTitleEl = $("endTitle");
  const endDetailEl = $("endDetail");
  const apiBasePillEl = $("apiBasePill");
  const connPillEl = $("connPill");
  const displayNameInputEl = $("displayNameInput");
  const leaveBtnEl = $("leaveBtn");
  const lobbyListEl = $("lobbyList");
  const lobbyStatusEl = $("lobbyStatus");
  const quickPlayBtnEl = $("quickPlayBtn");
  const toggleCreateBtnEl = $("toggleCreateBtn");
  const refreshLobbyBtnEl = $("refreshLobbyBtn");
  const createFormEl = $("createForm");
  const createConfirmBtnEl = $("createConfirmBtn");
  const tableInfoLineEl = $("tableInfoLine");
  const copyLinkBtnEl = $("copyLinkBtn");
  const nextDealBtnEl = $("nextDealBtn");
  const leaveTableBtnEl = $("leaveTableBtn");
  const leaveOverlayBtnEl = $("leaveOverlayBtn");
  const auctionCellsEl = $("auctionCells");
  const bidPanelEl = $("bidPanel");
  const tricksLineEl = $("tricksLine");
  const scoreNSEl = $("scoreNS");
  const scoreEWEl = $("scoreEW");
  const dealNumberEl = $("dealNumber");
  const trickAreaEl = $("trickArea");
  const statusLineEl = $("statusLine");
  const handEls = { N: $("hand-N"), E: $("hand-E"), S: $("hand-S"), W: $("hand-W") };
  const seatEls = { N: $("seat-N"), E: $("seat-E"), S: $("seat-S"), W: $("seat-W") };
  const labelEls = { N: $("label-N"), E: $("label-E"), S: $("label-S"), W: $("label-W") };

  apiBasePillEl.textContent = `API_BASE: ${API_BASE}`;

  // ---- Identity -------------------------------------------------------
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    return Array.from({ length: 16 }, () => Math.floor(Math.random() * 256))
      .map((b) => b.toString(16).padStart(2, "0")).join("");
  }
  function getClientId() {
    try {
      let v = localStorage.getItem(STORAGE.clientId);
      if (!v) {
        v = uuid();
        localStorage.setItem(STORAGE.clientId, v);
      }
      return v;
    } catch {
      return uuid();
    }
  }
  function getDisplayName() {
    try {
      const v = localStorage.getItem(STORAGE.displayName);
      return v || "";
    } catch { return ""; }
  }
  function setDisplayName(v) {
    try { localStorage.setItem(STORAGE.displayName, (v || "").trim().slice(0, 24)); } catch {}
  }

  const app = {
    clientId: getClientId(),
    displayName: getDisplayName(),
    view: "lobby", // 'lobby' | 'seating' | 'playing'
    tableId: null,
    seat: null,
    token: null,
    state: null,
    lobby: { tables: [] },
    pollHandle: null,
    ws: null,
    busy: false,
  };

  displayNameInputEl.value = app.displayName;
  displayNameInputEl.addEventListener("change", () => {
    app.displayName = displayNameInputEl.value.trim().slice(0, 24);
    setDisplayName(app.displayName);
  });

  // ---- Session persistence -------------------------------------------
  function persistSession() {
    try {
      if (app.tableId && app.seat && app.token) {
        localStorage.setItem(STORAGE.session, JSON.stringify({
          tableId: app.tableId, seat: app.seat, token: app.token,
        }));
      } else {
        localStorage.removeItem(STORAGE.session);
      }
    } catch {}
  }
  function loadSession() {
    try {
      const raw = localStorage.getItem(STORAGE.session);
      if (!raw) return null;
      const o = JSON.parse(raw);
      if (o && o.tableId && o.seat && o.token) return o;
    } catch {}
    return null;
  }

  // ---- HTTP helpers ---------------------------------------------------
  async function apiGet(path) {
    const r = await fetch(`${API_BASE}${path}`, { headers: { Accept: "application/json" } });
    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      throw new Error(`HTTP ${r.status}: ${detail.detail || r.statusText}`);
    }
    return r.json();
  }
  async function apiPost(path, body) {
    const r = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body || {}),
    });
    if (!r.ok) {
      const detail = await r.json().catch(() => ({}));
      throw new Error(`HTTP ${r.status}: ${detail.detail || r.statusText}`);
    }
    return r.json();
  }

  // ---- View transitions ----------------------------------------------
  function goLobby() {
    stopPolling();
    closeWS();
    app.view = "lobby";
    app.tableId = null;
    app.seat = null;
    app.token = null;
    app.state = null;
    persistSession();
    lobbyEl.classList.remove("hidden");
    gameEl.classList.add("hidden");
    seatOverlayEl.classList.add("hidden");
    endcardEl.classList.add("hidden");
    leaveBtnEl.classList.add("hidden");
    setUrl({});
    startPolling();
    refreshLobby();
  }

  function goSeating(tableId) {
    closeWS();
    app.view = "seating";
    app.tableId = tableId;
    app.seat = null;
    app.token = null;
    app.state = null;
    lobbyEl.classList.add("hidden");
    gameEl.classList.add("hidden");
    seatOverlayEl.classList.remove("hidden");
    leaveBtnEl.classList.add("hidden");
    setUrl({ table: tableId });
    refreshSeatOverlay(tableId);
  }

  function goPlaying() {
    stopPolling();
    app.view = "playing";
    lobbyEl.classList.add("hidden");
    gameEl.classList.remove("hidden");
    seatOverlayEl.classList.add("hidden");
    leaveBtnEl.classList.remove("hidden");
    setUrl({ table: app.tableId });
    persistSession();
    connectWS();
  }

  function setUrl(params) {
    const u = new URL(window.location.href);
    u.search = "";
    for (const [k, v] of Object.entries(params)) {
      if (v) u.searchParams.set(k, v);
    }
    // Preserve api override if it was present
    const apiOverride = new URLSearchParams(window.location.search).get("api");
    if (apiOverride) u.searchParams.set("api", apiOverride);
    window.history.replaceState({}, "", u.toString());
  }

  // ---- Lobby ----------------------------------------------------------
  function startPolling() {
    if (app.pollHandle) return;
    app.pollHandle = setInterval(refreshLobby, 3000);
  }
  function stopPolling() {
    if (app.pollHandle) { clearInterval(app.pollHandle); app.pollHandle = null; }
  }

  async function refreshLobby() {
    try {
      const data = await apiGet("/api/bridge/lobby");
      app.lobby = data;
      renderLobbyList();
    } catch (e) {
      lobbyStatusEl.textContent = `Lobby error: ${e.message}`;
    }
  }

  function renderLobbyList() {
    const items = (app.lobby && app.lobby.tables) || [];
    lobbyListEl.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "muted small";
      empty.textContent = "No open tables. Create one!";
      lobbyListEl.appendChild(empty);
      return;
    }
    for (const t of items) {
      lobbyListEl.appendChild(renderLobbyRow(t));
    }
  }

  function renderLobbyRow(t) {
    const row = document.createElement("div");
    row.className = "lobby-row";
    const meta = document.createElement("div");
    meta.className = "meta";
    const top = document.createElement("div");
    top.className = "top";
    const id = document.createElement("span");
    id.style.fontWeight = "700";
    id.textContent = `#${t.table_id}`;
    const modeBadge = document.createElement("span");
    modeBadge.className = "badge";
    modeBadge.textContent = t.mode === "humans_only" ? "humans only" : "with bots";
    const phaseBadge = document.createElement("span");
    phaseBadge.className = "badge";
    phaseBadge.textContent = `${t.deal_phase} · deal ${t.deal_number || 0}`;
    top.appendChild(id); top.appendChild(modeBadge); top.appendChild(phaseBadge);
    meta.appendChild(top);

    const seats = document.createElement("div");
    seats.className = "seats";
    for (const s of t.seats) {
      const chip = document.createElement("span");
      chip.className = `seat-chip ${s.kind}` + (s.connected === false ? " disconnected" : "");
      const dirEl = document.createElement("b");
      dirEl.textContent = s.seat;
      chip.appendChild(dirEl);
      const who = document.createElement("span");
      if (s.kind === "human") {
        who.textContent = s.display_name || "human";
      } else if (s.kind === "bot") {
        who.textContent = "bot";
      } else {
        who.textContent = "empty";
      }
      chip.appendChild(who);
      seats.appendChild(chip);
    }
    meta.appendChild(seats);
    row.appendChild(meta);

    const actions = document.createElement("div");
    actions.className = "actions";
    // Sit-here buttons for each empty seat
    let openSeats = 0;
    for (const s of t.seats) {
      if (s.kind === "empty" || s.kind === "bot") {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn tiny";
        b.textContent = `Sit ${s.seat}`;
        b.addEventListener("click", () => joinSeat(t.table_id, s.seat));
        actions.appendChild(b);
        openSeats++;
      }
    }
    if (openSeats === 0) {
      const watch = document.createElement("button");
      watch.type = "button";
      watch.className = "btn tiny ghost";
      watch.textContent = "Full";
      watch.disabled = true;
      actions.appendChild(watch);
    }
    row.appendChild(actions);
    return row;
  }

  // ---- Quick play / Create / Join -----------------------------------
  async function quickPlay() {
    if (app.busy) return;
    app.busy = true;
    lobbyStatusEl.textContent = "Creating table…";
    const slowTimer = setTimeout(() => {
      lobbyStatusEl.textContent = "Backend may be cold-starting on Render — hold on (up to a minute)…";
    }, 5000);
    try {
      const data = await apiPost("/api/bridge/tables", {
        client_id: app.clientId,
        display_name: app.displayName || "You",
      });
      app.tableId = data.table_id;
      app.seat = data.seat;
      app.token = data.token;
      app.state = data.state;
      lobbyStatusEl.textContent = "";
      goPlaying();
    } catch (e) {
      lobbyStatusEl.textContent = `Failed: ${e.message}`;
    } finally {
      clearTimeout(slowTimer);
      app.busy = false;
    }
  }

  async function createCustomTable() {
    if (app.busy) return;
    const mode = (document.querySelector('input[name="mode"]:checked') || {}).value || "with_bots";
    const seatVal = (document.querySelector('input[name="hostSeat"]:checked') || {}).value || "";
    const body = {
      mode,
      host: { client_id: app.clientId, display_name: app.displayName || "Host" },
      host_seat: seatVal || null,
    };
    app.busy = true;
    lobbyStatusEl.textContent = "Creating…";
    try {
      const data = await apiPost("/api/bridge/lobby", body);
      if (seatVal) {
        app.tableId = data.table_id;
        app.seat = data.seat;
        app.token = data.token;
        app.state = data.state;
        goPlaying();
      } else {
        // Just created without sitting -- send to lobby so user can pick a seat
        await refreshLobby();
        lobbyStatusEl.textContent = `Created table ${data.table_id}. Pick a seat below.`;
      }
    } catch (e) {
      lobbyStatusEl.textContent = `Failed: ${e.message}`;
    } finally {
      app.busy = false;
    }
  }

  async function joinSeat(tableId, seat) {
    if (app.busy) return;
    app.busy = true;
    lobbyStatusEl.textContent = `Joining table ${tableId} at seat ${seat}…`;
    try {
      const data = await apiPost(`/api/bridge/tables/${encodeURIComponent(tableId)}/claim_seat`, {
        client_id: app.clientId,
        display_name: app.displayName || "Guest",
        seat,
      });
      app.tableId = data.table_id;
      app.seat = data.seat;
      app.token = data.token;
      app.state = data.state;
      lobbyStatusEl.textContent = "";
      goPlaying();
    } catch (e) {
      lobbyStatusEl.textContent = `Failed: ${e.message}`;
    } finally {
      app.busy = false;
    }
  }

  // ---- Seat overlay (used when arriving via shared link without token)
  async function refreshSeatOverlay(tableId) {
    seatChoicesEl.innerHTML = "<div class=\"muted small\">Loading…</div>";
    seatOverlayInfoEl.textContent = `Table ${tableId}`;
    try {
      const data = await apiGet("/api/bridge/lobby");
      const found = (data.tables || []).find((t) => t.table_id === tableId);
      if (!found) {
        seatChoicesEl.innerHTML = "<div class=\"muted small\">Table not found.</div>";
        return;
      }
      seatOverlayInfoEl.textContent = `Table ${tableId} · ${found.mode === "humans_only" ? "humans only" : "with bots"}`;
      seatChoicesEl.innerHTML = "";
      for (const s of found.seats) {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn";
        const taken = s.kind === "human";
        b.textContent = taken ? `${s.seat}: ${s.display_name || "human"} (taken)` : `Sit at ${s.seat}`;
        b.disabled = taken;
        if (!taken) b.addEventListener("click", () => joinSeat(tableId, s.seat));
        seatChoicesEl.appendChild(b);
      }
    } catch (e) {
      seatChoicesEl.innerHTML = `<div class="muted small">Error: ${e.message}</div>`;
    }
  }

  // ---- WebSocket ------------------------------------------------------
  function connectWS() {
    closeWS();
    const url = wsUrl(`/api/bridge/tables/${encodeURIComponent(app.tableId)}/ws?token=${encodeURIComponent(app.token)}`);
    setConnectionPill("connecting");
    app.ws = new WSClient({
      url,
      onOpen: () => setConnectionPill("online"),
      onClose: () => setConnectionPill("offline"),
      onStateChange: (s) => setConnectionPill(s),
      onMessage: (msg) => handleWSMessage(msg),
    });
    app.ws.connect();
  }
  function closeWS() {
    if (app.ws) { try { app.ws.close(); } catch {} app.ws = null; }
    setConnectionPill("offline");
  }
  function setConnectionPill(s) {
    connPillEl.classList.remove("online", "connecting");
    if (s === "open" || s === "online") {
      connPillEl.classList.add("online");
      connPillEl.textContent = "online";
    } else if (s === "connecting") {
      connPillEl.classList.add("connecting");
      connPillEl.textContent = "connecting";
    } else {
      connPillEl.textContent = "offline";
    }
  }

  function handleWSMessage(msg) {
    if (!msg || typeof msg !== "object") return;
    if (msg.type === "state") {
      app.state = msg.state;
      render();
    } else if (msg.type === "error") {
      setStatus(`Error: ${msg.message}`);
    } else if (msg.type === "pong") {
      // ignore
    }
  }

  // ---- Action submission (over WS, fallback to HTTP) -----------------
  function sendAction(action) {
    if (app.ws && app.ws.state === "open") {
      app.ws.send({ type: "action", action });
      return;
    }
    // Fallback to HTTP if WS isn't ready
    apiPost(`/api/bridge/tables/${encodeURIComponent(app.tableId)}/actions`, { token: app.token, action })
      .then((data) => { app.state = data.state; render(); })
      .catch((e) => setStatus(`Error: ${e.message}`));
  }
  function sendNextDeal() {
    if (app.ws && app.ws.state === "open") {
      app.ws.send({ type: "next_deal" });
      return;
    }
    apiPost(`/api/bridge/tables/${encodeURIComponent(app.tableId)}/next_deal`, { token: app.token })
      .then((data) => { app.state = data.state; render(); })
      .catch((e) => setStatus(`Error: ${e.message}`));
  }

  function leaveTable() {
    if (app.ws && app.ws.state === "open") {
      app.ws.send({ type: "release_seat" });
    } else if (app.tableId && app.token) {
      apiPost(`/api/bridge/tables/${encodeURIComponent(app.tableId)}/release_seat`, { token: app.token }).catch(() => {});
    }
    goLobby();
  }

  // ---- Rendering ------------------------------------------------------
  function setStatus(msg) { statusLineEl.textContent = msg; }

  function cardElement(card, opts = {}) {
    const el = document.createElement("div");
    const klass = ["card"];
    if (opts.small) klass.push("small");
    if (card === null) {
      klass.push("back");
      el.className = klass.join(" ");
      return el;
    }
    const info = SUIT_INFO[card.suit] || { sym: "?", color: "black" };
    klass.push(info.color);
    el.className = klass.join(" ");
    if (opts.legal) el.classList.add("legal");
    if (opts.dimmed) el.classList.add("dimmed");
    const tl = document.createElement("div");
    tl.className = "corner-tl";
    tl.textContent = `${rankLabel(card.rank)}${info.sym}`;
    const br = document.createElement("div");
    br.className = "corner-br";
    br.textContent = `${rankLabel(card.rank)}${info.sym}`;
    const center = document.createElement("div");
    center.className = "pip-center";
    center.textContent = info.sym;
    el.appendChild(tl);
    el.appendChild(center);
    el.appendChild(br);
    if (opts.onClick) el.addEventListener("click", opts.onClick);
    return el;
  }

  function canViewerPlayFromSeat(seat) {
    const st = app.state;
    if (!st || st.phase !== "play" || !st.your_turn) return false;
    if (st.acting_controller !== st.viewer) return false;
    if (st.to_act !== seat) return false;
    return true;
  }

  function renderHand(seat) {
    const container = handEls[seat];
    container.innerHTML = "";
    const st = app.state;
    if (!st) return;
    const handPayload = (st.hands || {})[seat];
    if (!handPayload) return;
    const cards = handPayload.cards;
    if (cards === null) {
      const n = Math.min(handPayload.count || 13, 13);
      for (let i = 0; i < n; i++) {
        const back = cardElement(null);
        back.classList.add("dimmed");
        container.appendChild(back);
      }
      return;
    }
    const legal = (st.legal_plays || []).map((c) => `${c.suit}${c.rank}`);
    const viewerControls = canViewerPlayFromSeat(seat);
    for (const c of cards) {
      const isLegal = viewerControls && legal.includes(`${c.suit}${c.rank}`);
      const el = cardElement(c, {
        legal: isLegal,
        dimmed: !viewerControls,
        onClick: isLegal ? () => sendAction({ kind: "play", card: { suit: c.suit, rank: c.rank } }) : null,
      });
      container.appendChild(el);
    }
  }

  function renderTrick() {
    trickAreaEl.innerHTML = "";
    const st = app.state;
    if (!st) return;
    const t = st.current_trick;
    if (!t || !t.cards || !t.cards.length) return;
    for (const entry of t.cards) {
      const el = cardElement(entry.card);
      el.classList.add("trick-card", entry.seat.toLowerCase());
      trickAreaEl.appendChild(el);
    }
  }

  function callLabel(call) {
    if (call.kind === "pass") return "—";
    if (call.kind === "double") return "X";
    if (call.kind === "redouble") return "XX";
    if (call.kind === "bid") {
      const info = SUIT_INFO[call.strain] || { sym: "?", color: "black" };
      return `${call.level}<span class="${info.color}">${info.sym}</span>`;
    }
    return "?";
  }

  function renderAuction() {
    auctionCellsEl.innerHTML = "";
    const st = app.state;
    if (!st || !st.auction) return;
    const calls = st.auction.calls || [];
    const order = ["N", "E", "S", "W"];
    const dealer = st.dealer || "N";
    const startCol = order.indexOf(dealer);
    for (let i = 0; i < startCol; i++) {
      const blank = document.createElement("div");
      blank.className = "auction-cell";
      blank.innerHTML = "·";
      blank.style.color = "transparent";
      auctionCellsEl.appendChild(blank);
    }
    for (let i = 0; i < calls.length; i++) {
      const c = calls[i];
      const cell = document.createElement("div");
      cell.className = "auction-cell";
      if (c.kind === "pass") cell.classList.add("pass");
      cell.innerHTML = callLabel(c);
      auctionCellsEl.appendChild(cell);
    }
    if (st.phase === "auction" && st.auction.to_act) {
      const nextCell = document.createElement("div");
      nextCell.className = "auction-cell cur";
      nextCell.textContent = "?";
      auctionCellsEl.appendChild(nextCell);
    }
  }

  function renderBidPanel() {
    bidPanelEl.innerHTML = "";
    const st = app.state;
    if (!st || st.phase !== "auction" || !st.your_turn) {
      bidPanelEl.classList.add("hidden");
      return;
    }
    bidPanelEl.classList.remove("hidden");
    const legal = st.auction.legal_calls || [];
    const ctrlRow = document.createElement("div");
    ctrlRow.className = "bid-row";
    for (const kind of ["pass", "double", "redouble"]) {
      const has = legal.find((c) => c.kind === kind);
      if (!has) continue;
      const b = document.createElement("button");
      b.type = "button";
      b.className = "btn tiny";
      b.textContent = kind === "pass" ? "Pass" : kind === "double" ? "Double (X)" : "Redouble (XX)";
      b.addEventListener("click", () => sendAction({ kind }));
      ctrlRow.appendChild(b);
    }
    bidPanelEl.appendChild(ctrlRow);
    for (let level = 1; level <= 7; level++) {
      let row = null;
      for (const strain of ["C", "D", "H", "S", "NT"]) {
        const ok = legal.find((c) => c.kind === "bid" && c.level === level && c.strain === strain);
        if (!ok) continue;
        if (!row) {
          row = document.createElement("div");
          row.className = "bid-row";
          const meta = document.createElement("span");
          meta.className = "meta";
          meta.textContent = `Level ${level}`;
          row.appendChild(meta);
        }
        const info = SUIT_INFO[strain];
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn tiny" + (info.color === "red" ? " suit-red" : "");
        b.innerHTML = `${level}${info.sym}`;
        b.addEventListener("click", () => sendAction({ kind: "bid", level, strain }));
        row.appendChild(b);
      }
      if (row) bidPanelEl.appendChild(row);
    }
  }

  function renderSeatLabels() {
    const st = app.state;
    if (!st || !st.seats) return;
    for (const s of st.seats) {
      const el = labelEls[s.seat];
      if (!el) continue;
      el.innerHTML = "";
      const dir = document.createElement("span");
      dir.className = "dir";
      dir.textContent = s.seat;
      el.appendChild(dir);
      const who = document.createElement("span");
      who.className = "who";
      let label = "";
      if (s.kind === "human") label = s.display_name || "human";
      else if (s.kind === "bot") label = "bot";
      else label = "empty";
      who.textContent = label;
      el.appendChild(who);
      const badges = [];
      if (s.seat === st.viewer) badges.push({ cls: "you", text: "you" });
      if (s.kind === "bot") badges.push({ cls: "bot", text: "bot" });
      if (s.kind === "empty") badges.push({ cls: "empty", text: "empty" });
      if (s.kind === "human" && s.connected === false) badges.push({ cls: "disconnected", text: "offline" });
      if (s.is_dummy) badges.push({ cls: "bot", text: "dummy" });
      if (s.is_declarer) badges.push({ cls: "you", text: "decl." });
      for (const b of badges) {
        const span = document.createElement("span");
        span.className = `badge ${b.cls}`;
        span.textContent = b.text;
        el.appendChild(span);
      }
    }
  }

  function renderHeaderInfo() {
    const st = app.state;
    if (!st) return;
    const cs = st.cumulative_score || { NS: 0, EW: 0 };
    scoreNSEl.textContent = String(cs.NS);
    scoreEWEl.textContent = String(cs.EW);
    dealNumberEl.textContent = st.deal_number ? `Deal #${st.deal_number}` : "Deal —";
    if (tableInfoLineEl) {
      const modeText = st.mode === "humans_only" ? "Strict 4 humans" : "With bots";
      const claimedText = st.all_seats_claimed ? "all seats taken" : `${(st.seats || []).filter((s) => s.kind === "human").length}/4 humans`;
      tableInfoLineEl.textContent = `Table ${st.table_id} · ${modeText} · ${claimedText}`;
    }
    if (st.phase === "play" || st.phase === "complete") {
      if (st.contract) {
        const con = st.contract;
        const info = SUIT_INFO[con.strain] || { sym: "?" };
        const colorClass = info.color === "red" ? "red" : "fg";
        const t = st.tricks || {};
        tricksLineEl.innerHTML =
          `Contract: <b>${con.level}<span class="${colorClass}">${info.sym}</span>${con.doubled || ""}</b> by ${con.declarer}<br>` +
          `Tricks: declarer ${t.declarer ?? 0}/${t.needed ?? "?"}, defenders ${t.defender ?? 0}`;
      } else {
        tricksLineEl.textContent = "Passed out";
      }
    } else if (st.phase === "auction") {
      tricksLineEl.textContent = "Auction in progress";
    } else if (st.phase === "no_deal") {
      tricksLineEl.textContent = st.mode === "humans_only" ? "Waiting for 4 humans…" : "Waiting…";
    } else {
      tricksLineEl.textContent = "—";
    }
  }

  function renderActingHighlight() {
    for (const s of ["N", "E", "S", "W"]) seatEls[s].classList.remove("is-acting");
    const st = app.state;
    if (!st) return;
    let actor = null;
    if (st.phase === "auction") actor = st.auction && st.auction.to_act;
    else if (st.phase === "play") actor = st.to_act;
    if (actor && seatEls[actor]) seatEls[actor].classList.add("is-acting");
  }

  function renderStatus() {
    const st = app.state;
    if (!st) return;
    if (st.phase === "no_deal") {
      setStatus(st.mode === "humans_only" ? "Waiting for all 4 seats to be claimed." : "Waiting…");
      return;
    }
    if (!st.can_play) {
      setStatus("Waiting for more humans to sit down…");
      return;
    }
    if (st.phase === "auction") {
      if (st.your_turn) setStatus("Your turn — make a call.");
      else setStatus(`Waiting on ${st.auction.to_act}…`);
    } else if (st.phase === "play") {
      if (st.your_turn) setStatus(`Your turn — play from ${st.to_act}.`);
      else setStatus(`Playing: ${st.to_act}…`);
    } else if (st.phase === "complete") {
      setStatus("Deal complete.");
    }
  }

  function renderEndcard() {
    const st = app.state;
    if (!st || st.phase !== "complete") {
      endcardEl.classList.add("hidden");
      return;
    }
    endcardEl.classList.remove("hidden");
    const r = st.result || {};
    if (r.contract) {
      const c = r.contract;
      const info = SUIT_INFO[c.strain] || { sym: "?" };
      const made = r.score && r.score.made;
      endTitleEl.innerHTML = `${c.level}${info.sym}${c.doubled || ""} by ${c.declarer} ${made ? "MADE" : "DOWN"} (${r.declarer_tricks} tricks)`;
    } else {
      endTitleEl.textContent = "Passed out";
    }
    endDetailEl.textContent = JSON.stringify(r.score || {}, null, 2);
  }

  function render() {
    if (!app.state) return;
    for (const s of ["N", "E", "S", "W"]) renderHand(s);
    renderTrick();
    renderAuction();
    renderBidPanel();
    renderHeaderInfo();
    renderSeatLabels();
    renderActingHighlight();
    renderStatus();
    renderEndcard();
  }

  // ---- Wire up --------------------------------------------------------
  quickPlayBtnEl.addEventListener("click", quickPlay);
  toggleCreateBtnEl.addEventListener("click", () => {
    createFormEl.classList.toggle("hidden");
  });
  createConfirmBtnEl.addEventListener("click", createCustomTable);
  refreshLobbyBtnEl.addEventListener("click", refreshLobby);
  leaveBtnEl.addEventListener("click", leaveTable);
  leaveTableBtnEl.addEventListener("click", leaveTable);
  leaveOverlayBtnEl.addEventListener("click", goLobby);
  nextDealBtnEl.addEventListener("click", () => {
    endcardEl.classList.add("hidden");
    sendNextDeal();
  });
  copyLinkBtnEl.addEventListener("click", async () => {
    if (!app.tableId) return;
    const u = new URL(window.location.href);
    u.search = "";
    u.searchParams.set("table", app.tableId);
    try {
      await navigator.clipboard.writeText(u.toString());
      setStatus("Invite link copied.");
    } catch {
      setStatus(u.toString());
    }
  });

  // ---- Bootstrap ------------------------------------------------------
  (async () => {
    const params = new URLSearchParams(window.location.search);
    const tableParam = params.get("table");

    // Try to resume a saved session if URL matches it.
    const saved = loadSession();
    if (saved && (!tableParam || tableParam === saved.tableId)) {
      app.tableId = saved.tableId;
      app.seat = saved.seat;
      app.token = saved.token;
      // Validate by trying a state fetch
      try {
        const st = await apiGet(`/api/bridge/tables/${encodeURIComponent(app.tableId)}?token=${encodeURIComponent(app.token)}`);
        app.state = st;
        goPlaying();
        return;
      } catch {
        try { localStorage.removeItem(STORAGE.session); } catch {}
        app.tableId = null; app.seat = null; app.token = null;
      }
    }

    if (tableParam) {
      goSeating(tableParam);
      return;
    }

    goLobby();
  })();
})();
