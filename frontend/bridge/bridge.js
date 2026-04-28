// Bridge vs Bots — frontend client
//
// Talks to /api/bridge/... on the backend. Single-player today; the same
// endpoints will work over WebSockets in a future iteration with only
// transport-layer changes here (replace fetch calls with a WS subscribe).

const SUIT_INFO = {
  C: { sym: "\u2663", color: "black" },
  D: { sym: "\u2666", color: "red" },
  H: { sym: "\u2665", color: "red" },
  S: { sym: "\u2660", color: "black" },
  NT: { sym: "NT", color: "black" },
};

const RANK_LABEL = { 11: "J", 12: "Q", 13: "K", 14: "A" };
function rankLabel(r) { return RANK_LABEL[r] || String(r); }

// --- API base resolution (mirrors the greet page) ---
function normalizeBaseUrl(x) { return String(x || "").trim().replace(/\/+$/, ""); }
function getApiBaseFromUrl() {
  const v = new URLSearchParams(window.location.search).get("api");
  return v ? normalizeBaseUrl(v) : "";
}
function getApiBaseFromStorage() {
  try { return normalizeBaseUrl(localStorage.getItem("hello_fullstack_api_base")); } catch { return ""; }
}
const API_BASE = getApiBaseFromUrl() || getApiBaseFromStorage() || "https://hello-fullstack-py.onrender.com";
document.getElementById("apiBasePill").textContent = `API_BASE: ${API_BASE}`;

// --- DOM refs ---
const welcomeEl = document.getElementById("welcome");
const gameEl = document.getElementById("game");
const startBtn = document.getElementById("startBtn");
const newTableBtn = document.getElementById("newTableBtn");
const newTableBtn2 = document.getElementById("newTableBtn2");
const nextDealBtn = document.getElementById("nextDealBtn");
const statusLine = document.getElementById("statusLine");
const welcomeStatusEl = document.getElementById("welcomeStatus");
const auctionCellsEl = document.getElementById("auctionCells");
const bidPanelEl = document.getElementById("bidPanel");
const tricksLineEl = document.getElementById("tricksLine");
const scoreNSEl = document.getElementById("scoreNS");
const scoreEWEl = document.getElementById("scoreEW");
const dealNumberEl = document.getElementById("dealNumber");
const trickAreaEl = document.getElementById("trickArea");
const endcardEl = document.getElementById("endcard");
const endTitleEl = document.getElementById("endTitle");
const endDetailEl = document.getElementById("endDetail");
const handEls = {
  N: document.getElementById("hand-N"),
  E: document.getElementById("hand-E"),
  S: document.getElementById("hand-S"),
  W: document.getElementById("hand-W"),
};
const seatEls = {
  N: document.getElementById("seat-N"),
  E: document.getElementById("seat-E"),
  S: document.getElementById("seat-S"),
  W: document.getElementById("seat-W"),
};

// --- session state ---
const session = {
  tableId: null,
  token: null,
  state: null,
  busy: false,
};

function persistSession() {
  try {
    localStorage.setItem(
      "hello_fullstack_bridge_session",
      JSON.stringify({ tableId: session.tableId, token: session.token })
    );
  } catch {}
}
function loadSession() {
  try {
    const raw = localStorage.getItem("hello_fullstack_bridge_session");
    if (!raw) return null;
    const obj = JSON.parse(raw);
    if (obj && obj.tableId && obj.token) return obj;
  } catch {}
  return null;
}

// --- API helpers ---
async function apiPost(path, body) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(`HTTP ${res.status}: ${detail.detail || res.statusText}`);
  }
  return res.json();
}
async function apiGet(path) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "GET",
    headers: { Accept: "application/json" },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(`HTTP ${res.status}: ${detail.detail || res.statusText}`);
  }
  return res.json();
}

// --- main flow ---
async function startNewTable() {
  if (session.busy) return;
  session.busy = true;
  startBtn.disabled = true;
  setWelcomeStatus("Creating table… (the backend may cold-start, this can take 30–60s on the free tier)");
  status("Creating table…");
  // Slow-start nudge: if the call hasn't finished after a few seconds, reassure the user.
  const slowTimer = setTimeout(() => {
    setWelcomeStatus("Still waking up the backend on Render free tier… hold tight.");
  }, 6000);
  try {
    const data = await apiPost("/api/bridge/tables", {});
    session.tableId = data.table_id;
    session.token = data.token;
    session.state = data.state;
    persistSession();
    welcomeEl.classList.add("hidden");
    gameEl.classList.remove("hidden");
    setWelcomeStatus("");
    render();
  } catch (e) {
    setWelcomeStatus(`Failed: ${e.message}. Check the API base (${API_BASE}) is reachable.`);
    status(`Failed: ${e.message}`);
  } finally {
    clearTimeout(slowTimer);
    session.busy = false;
    startBtn.disabled = false;
  }
}

function setWelcomeStatus(msg) {
  if (welcomeStatusEl) welcomeStatusEl.textContent = msg || "";
}

async function refreshState() {
  if (!session.tableId || !session.token) return;
  const data = await apiGet(
    `/api/bridge/tables/${encodeURIComponent(session.tableId)}?token=${encodeURIComponent(session.token)}`
  );
  session.state = data;
  render();
}

async function performAction(action) {
  if (!session.tableId || !session.token || session.busy) return;
  session.busy = true;
  status("…");
  try {
    const data = await apiPost(
      `/api/bridge/tables/${encodeURIComponent(session.tableId)}/actions`,
      { token: session.token, action }
    );
    session.state = data.state;
    await playEvents(data.events);
    render();
  } catch (e) {
    status(`Error: ${e.message}`);
  } finally {
    session.busy = false;
  }
}

async function nextDeal() {
  if (!session.tableId || !session.token) return;
  session.busy = true;
  endcardEl.classList.add("hidden");
  status("Dealing…");
  try {
    const data = await apiPost(
      `/api/bridge/tables/${encodeURIComponent(session.tableId)}/next_deal`,
      { token: session.token }
    );
    session.state = data.state;
    await playEvents(data.events);
    render();
  } catch (e) {
    status(`Error: ${e.message}`);
  } finally {
    session.busy = false;
  }
}

// --- event playback (bot pacing) ---
// We get all events for this turn at once. Animate them with small delays so
// the user feels each action.
function delay(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function playEvents(events) {
  if (!Array.isArray(events) || events.length === 0) return;
  // Light animation: short pause between successive events. Skip pauses if
  // the user spammed past a deal.
  for (const ev of events) {
    if (ev.type === "card") {
      await delay(280);
    } else if (ev.type === "trick_won") {
      await delay(600);
    } else if (ev.type === "call") {
      await delay(220);
    }
  }
}

// --- rendering ---
function status(msg) { statusLine.textContent = msg; }

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

function renderHand(seat) {
  const container = handEls[seat];
  container.innerHTML = "";
  const st = session.state;
  if (!st) return;
  const handPayload = (st.hands || {})[seat];
  if (!handPayload) return;
  const cards = handPayload.cards;

  if (cards === null) {
    // Show face-down stack (count)
    const n = Math.min(handPayload.count || 13, 13);
    for (let i = 0; i < n; i++) {
      const back = cardElement(null);
      back.classList.add("dimmed");
      container.appendChild(back);
    }
    return;
  }

  // Visible hand: render each card. Click handler for legal plays only.
  const legal = (st.legal_plays || []).map((c) => `${c.suit}${c.rank}`);
  // Determine if this seat is the one whose turn it is and the viewer controls it.
  const viewerControls = canViewerPlayFromSeat(seat);
  for (const c of cards) {
    const isLegal = viewerControls && legal.includes(`${c.suit}${c.rank}`);
    const el = cardElement(c, {
      legal: isLegal,
      dimmed: !viewerControls,
      onClick: isLegal ? () => playCard(c) : null,
    });
    container.appendChild(el);
  }
}

function canViewerPlayFromSeat(seat) {
  const st = session.state;
  if (!st || st.phase !== "play" || !st.your_turn) return false;
  if (st.acting_controller !== st.viewer) return false;
  if (st.to_act !== seat) return false;
  return true;
}

function playCard(card) {
  performAction({ kind: "play", card: { suit: card.suit, rank: card.rank } });
}

function renderTrick() {
  trickAreaEl.innerHTML = "";
  const st = session.state;
  if (!st) return;
  const t = st.current_trick;
  if (!t || !t.cards || !t.cards.length) {
    // Show last completed trick briefly? skip for now.
    return;
  }
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
  const st = session.state;
  if (!st || !st.auction) return;
  const calls = st.auction.calls || [];

  // Build a grid that aligns with N E S W headers. Row 1 starts at the dealer.
  const order = ["N", "E", "S", "W"];
  const dealer = st.dealer || "N";
  const startCol = order.indexOf(dealer);

  // Pad leading cells before the dealer's first call
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

  // Mark the next-to-act cell
  if (st.phase === "auction" && st.auction.to_act) {
    const nextIdx = startCol + calls.length;
    const nextCell = document.createElement("div");
    nextCell.className = "auction-cell cur";
    nextCell.textContent = "?";
    auctionCellsEl.appendChild(nextCell);
  }
}

function renderBidPanel() {
  bidPanelEl.innerHTML = "";
  const st = session.state;
  if (!st || st.phase !== "auction") {
    bidPanelEl.classList.add("hidden");
    return;
  }
  if (!st.your_turn) {
    bidPanelEl.classList.add("hidden");
    return;
  }
  bidPanelEl.classList.remove("hidden");

  const legal = st.auction.legal_calls || [];
  const minLevelByStrain = {};
  for (const c of legal) {
    if (c.kind !== "bid") continue;
    if (!(c.strain in minLevelByStrain) || c.level < minLevelByStrain[c.strain]) {
      minLevelByStrain[c.strain] = c.level;
    }
  }

  // Pass / Double / Redouble row
  const ctrlRow = document.createElement("div");
  ctrlRow.className = "bid-row";
  for (const kind of ["pass", "double", "redouble"]) {
    const has = legal.find((c) => c.kind === kind);
    if (!has) continue;
    const b = document.createElement("button");
    b.type = "button";
    b.className = "btn tiny";
    b.textContent = kind === "pass" ? "Pass" : kind === "double" ? "Double (X)" : "Redouble (XX)";
    b.addEventListener("click", () => performAction({ kind }));
    ctrlRow.appendChild(b);
  }
  bidPanelEl.appendChild(ctrlRow);

  // Level + strain grid
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
      b.addEventListener("click", () => performAction({ kind: "bid", level, strain }));
      row.appendChild(b);
    }
    if (row) bidPanelEl.appendChild(row);
  }
}

function renderHeaderInfo() {
  const st = session.state;
  if (!st) return;
  const cs = st.cumulative_score || { NS: 0, EW: 0 };
  scoreNSEl.textContent = String(cs.NS);
  scoreEWEl.textContent = String(cs.EW);
  dealNumberEl.textContent = st.deal_number ? `Deal #${st.deal_number}` : "Deal —";

  // Tricks / contract line
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
  } else {
    tricksLineEl.textContent = "—";
  }
}

function renderActingHighlight() {
  for (const s of ["N", "E", "S", "W"]) seatEls[s].classList.remove("is-acting");
  const st = session.state;
  if (!st) return;
  let actor = null;
  if (st.phase === "auction") actor = st.auction && st.auction.to_act;
  else if (st.phase === "play") actor = st.to_act;
  if (actor && seatEls[actor]) seatEls[actor].classList.add("is-acting");
}

function renderStatus() {
  const st = session.state;
  if (!st) return;
  if (st.phase === "auction") {
    if (st.your_turn) status("Your turn — make a call.");
    else status(`Waiting on ${st.auction.to_act}…`);
  } else if (st.phase === "play") {
    if (st.your_turn) status(`Your turn — play from ${st.to_act}.`);
    else status(`Playing: ${st.to_act} on lead/follow…`);
  } else if (st.phase === "complete") {
    status("Deal complete.");
  } else if (st.phase === "no_deal") {
    status("No active deal.");
  }
}

function renderEndcard() {
  const st = session.state;
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
  if (!session.state) return;
  for (const s of ["N", "E", "S", "W"]) renderHand(s);
  renderTrick();
  renderAuction();
  renderBidPanel();
  renderHeaderInfo();
  renderActingHighlight();
  renderStatus();
  renderEndcard();
}

// --- wire up ---
startBtn.addEventListener("click", startNewTable);
newTableBtn.addEventListener("click", () => {
  endcardEl.classList.add("hidden");
  startNewTable();
});
newTableBtn2.addEventListener("click", () => {
  endcardEl.classList.add("hidden");
  startNewTable();
});
nextDealBtn.addEventListener("click", nextDeal);

// Try to resume an existing session, else show welcome.
(async () => {
  const saved = loadSession();
  if (!saved) return;
  session.tableId = saved.tableId;
  session.token = saved.token;
  try {
    await refreshState();
    welcomeEl.classList.add("hidden");
    gameEl.classList.remove("hidden");
  } catch (e) {
    // Stale session — clear it.
    try { localStorage.removeItem("hello_fullstack_bridge_session"); } catch {}
  }
})();
