(function () {
  const STORAGE_SESSION = 'hello_fullstack_sheng_session_v1';
  const STORAGE_API = 'hello_fullstack_api_base';
  const STORAGE_AUTOBOT = 'hello_fullstack_sheng_autobot_other';

  function normalizeBaseUrl(x) {
    return String(x || '')
      .trim()
      .replace(/\/+$/, '');
  }

  function getApiBaseFromUrl() {
    const v = new URLSearchParams(window.location.search).get('api');
    return v ? normalizeBaseUrl(v) : '';
  }

  const DEFAULT_PUBLIC_API = 'https://hello-fullstack-py.onrender.com';

  function getApiBaseFromStorage() {
    try {
      return normalizeBaseUrl(localStorage.getItem(STORAGE_API));
    } catch {
      return '';
    }
  }

  /** Ignore stale localhost from dev machines when browsing from GitHub Pages. */
  function storageHttpsOrEmpty() {
    const s = getApiBaseFromStorage();
    if (!s) return '';
    if (s.includes('localhost') || s.includes('127.0.0.1')) return '';
    if (!/^https:\/\//i.test(s)) return '';
    return s;
  }

  const host =
    typeof window !== 'undefined' && window.location && window.location.hostname
      ? window.location.hostname
      : '';
  const isLocal =
    host === 'localhost' || host === '127.0.0.1' || host === '[::1]';

  const isProbablyStaticPages =
    host.endsWith('github.io') ||
    host.endsWith('gitlab.io') ||
    host.endsWith('cloudflarepages.com');

  /** GitHub / GitLab Pages are static — API always on Render unless ?api= or saved https URL. */
  const API_BASE = (function resolveApiBase() {
    const fromQuery = getApiBaseFromUrl();
    if (fromQuery) return fromQuery;
    const fromStorage = storageHttpsOrEmpty();
    if (fromStorage) return fromStorage;
    if (isLocal && typeof window !== 'undefined' && window.location) {
      return normalizeBaseUrl(window.location.origin);
    }
    if (isProbablyStaticPages) return DEFAULT_PUBLIC_API;
    return DEFAULT_PUBLIC_API;
  })();

  function wsBaseFromApi() {
    let base = API_BASE;
    if (!/^https?:\/\//i.test(base)) base = window.location.origin;
    const u = new URL(base);
    const proto = u.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${u.host}`;
  }

  function wsUrl(relPathQuery) {
    return wsBaseFromApi() + relPathQuery;
  }

  /** @type {{ tableId?: string; tokens?: Record<string,string>; seat?: number; np?: number; ws?: WebSocket | null }} */
  const app = {
    tableId: undefined,
    tokens: undefined,
    seat: 0,
    np: 4,
    ws: null,
    lastState: null,
  };

  const $ = (id) => document.getElementById(id);
  const apiPill = $('apiPill');
  const wsPill = $('wsPill');
  const apiBaseInput = $('apiBaseInput');
  const seedIn = $('seedIn');
  const seatStrip = $('seatStrip');
  const seatBtns = $('seatBtns');
  const trickArea = $('trickArea');
  const handArea = $('handArea');
  const statusLine = $('statusLine');
  const metaLine = $('metaLine');
  const summaryBox = $('summaryBox');
  const btnNext = $('btnNext');
  const eventLog = $('eventLog');
  const chkAutoBot = $('chkAutoBot');

  let botBusy = false;
  apiPill.textContent = `API: ${API_BASE}`;
  apiBaseInput.value = API_BASE;
  try {
    const vb = sessionStorage.getItem(STORAGE_AUTOBOT);
    if (chkAutoBot && vb === '0') chkAutoBot.checked = false;
  } catch {}
  chkAutoBot?.addEventListener('change', () => {
    try {
      sessionStorage.setItem(STORAGE_AUTOBOT, chkAutoBot.checked ? '1' : '0');
    } catch {}
  });
  apiBaseInput.addEventListener('change', () => {
    const v = normalizeBaseUrl(apiBaseInput.value);
    if (v) {
      try {
        localStorage.setItem(STORAGE_API, v);
      } catch {}
      location.reload();
    }
  });

  function persistSession() {
    try {
      if (app.tableId && app.tokens) {
        localStorage.setItem(
          STORAGE_SESSION,
          JSON.stringify({
            tableId: app.tableId,
            tokens: app.tokens,
            seat: app.seat,
            np: app.np,
          })
        );
      } else {
        localStorage.removeItem(STORAGE_SESSION);
      }
    } catch {}
  }

  function loadSession() {
    try {
      const raw = localStorage.getItem(STORAGE_SESSION);
      if (!raw) return false;
      const o = JSON.parse(raw);
      if (!o.tableId || !o.tokens) return false;
      app.tableId = o.tableId;
      app.tokens = o.tokens;
      app.seat = typeof o.seat === 'number' ? o.seat : 0;
      app.np = typeof o.np === 'number' ? o.np : 4;
      return true;
    } catch {
      return false;
    }
  }

  function leaveTable() {
    if (app.ws) {
      try {
        app.ws.close();
      } catch {}
    }
    app.ws = null;
    app.tableId = undefined;
    app.tokens = undefined;
    persistSession();
    seatStrip.classList.add('hidden');
    btnNext.classList.add('hidden');
    trickArea.innerHTML = '';
    handArea.innerHTML = '';
    metaLine.textContent = '';
    statusLine.textContent = '';
    summaryBox.classList.add('hidden');
    app.lastState = null;
    eventLog.textContent = '(无)';
    wsPill.textContent = 'WS: —';
  }

  function tokenForSeat(s) {
    if (!app.tokens) return '';
    return app.tokens[String(s)] || '';
  }

  /** When it is another seat's turn, play their first legal card via REST so one human can solo the table. */
  async function autoplayOthersIfNeeded() {
    if (!chkAutoBot || !chkAutoBot.checked || botBusy || !app.tableId) return;
    const st = app.lastState;
    if (!st || st.phase !== 'play') return;
    const actor = st.to_act_seat;
    if (actor === undefined || actor === null) return;
    if (actor === st.viewer_seat) return;

    botBusy = true;
    try {
      const tt = encodeURIComponent(tokenForSeat(actor));
      const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}?token=${tt}`);
      if (!r.ok) return;
      const peer = await r.json();
      const legal = peer.legal_plays || [];
      if (!legal.length) return;
      const cid = legal[0].cid;
      const r2 = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/actions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ token: tokenForSeat(actor), card_id: cid }),
      });
      const body = await r2.json().catch(() => null);
      if (r2.ok && body && body.state) renderState(body.state);
    } catch (_) {
      /* ignore */
    } finally {
      botBusy = false;
    }
  }

  function buildSeatStrip() {
    seatBtns.innerHTML = '';
    const n = app.np || 4;
    for (let s = 0; s < n; s++) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn tiny' + (s === app.seat ? ' active' : '');
      b.textContent = String(s);
      b.addEventListener('click', () => {
        app.seat = s;
        persistSession();
        buildSeatStrip();
        connectWs();
        fetchStateRest();
      });
      seatBtns.appendChild(b);
    }
  }

  function connectWs() {
    if (!app.tableId || !tokenForSeat(app.seat)) return;
    if (app.ws) {
      try {
        app.ws.close();
      } catch {}
      app.ws = null;
    }
    const tok = encodeURIComponent(tokenForSeat(app.seat));
    const url = wsUrl(`/api/sheng/tables/${app.tableId}/ws?token=${tok}`);
    wsPill.textContent = 'WS: 连接中…';
    const ws = new WebSocket(url);
    app.ws = ws;
    ws.addEventListener('open', () => {
      wsPill.textContent = 'WS: 已连接';
    });
    ws.addEventListener('close', () => {
      if (app.ws === ws) app.ws = null;
      wsPill.textContent = 'WS: 断开';
    });
    ws.addEventListener('error', () => {
      wsPill.textContent = 'WS: 错误';
    });
    ws.addEventListener('message', (ev) => {
      let msg;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      if (msg.type === 'state' && msg.state) {
        renderState(msg.state);
        if (msg.events && msg.events.length) {
          eventLog.textContent = JSON.stringify({ events: msg.events, state: msg.state }, null, 2);
        }
      }
      if (msg.type === 'error') {
        statusLine.textContent = '错误: ' + (msg.message || '');
      }
    });
  }

  async function fetchStateRest() {
    if (!app.tableId || !tokenForSeat(app.seat)) return;
    const tok = encodeURIComponent(tokenForSeat(app.seat));
    const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}?token=${tok}`);
    if (!r.ok) return;
    const st = await r.json();
    renderState(st);
  }

  function renderState(st) {
    app.lastState = st;
    const np = st.num_players || app.np;
    app.np = np;

    const tr = st.trump || {};
    metaLine.textContent = [
      `阶段: ${st.phase}`,
      `庄家座位: ${st.declarer_seat}`,
      `首出/当前领出: ${st.leader}`,
      `主: ${tr.trump_suit || '?'} @${tr.level_rank}`,
      `台次: A${(st.teams && st.teams.A) || '?'} / B${(st.teams && st.teams.B) || '?'}`,
    ].join(' · ');

    trickArea.textContent = '';
    const trick = st.current_trick || [];
    for (const t of trick) {
      const wrap = document.createElement('div');
      wrap.className = 'trick-slot';
      const cf = document.createElement('div');
      cf.className = 'card-face';
      cf.textContent = (t.card && t.card.label) || '?';
      const cap = document.createElement('div');
      cap.textContent = '座' + t.seat;
      wrap.appendChild(cf);
      wrap.appendChild(cap);
      trickArea.appendChild(wrap);
    }
    if (!trick.length) {
      const e = document.createElement('div');
      e.style.color = 'var(--muted)';
      e.textContent = '（本轮尚未出牌）';
      trickArea.appendChild(e);
    }

    const viewer = st.viewer_seat;
    const hands = st.hands || [];
    const mine = hands[viewer];
    handArea.innerHTML = '';

    const legal = st.legal_plays || [];
    const legalIds = new Set(legal.map((x) => x.cid));
    const myTurn = st.phase === 'play' && st.to_act_seat === viewer;

    if (Array.isArray(mine)) {
      for (const c of mine) {
        const el = document.createElement('div');
        el.className = 'card-face' + (myTurn && legalIds.has(c.cid) ? ' playable' : ' dim');
        el.textContent = c.label || String(c.cid);
        el.title = 'cid=' + c.cid;
        if (myTurn && legalIds.has(c.cid)) {
          el.addEventListener('click', () => playCard(c.cid));
        }
        handArea.appendChild(el);
      }
    } else if (mine && typeof mine.count === 'number') {
      const el = document.createElement('div');
      el.className = 'card-face dim';
      el.textContent = '他人手牌: ' + mine.count + ' 张';
      handArea.appendChild(el);
    }

    if (st.phase === 'scored') {
      btnNext.classList.remove('hidden');
      const hs = st.hand_summary;
      summaryBox.classList.remove('hidden');
      summaryBox.innerHTML = hs
        ? `<strong>本副结束</strong><br/>闲家分: ${hs.defender_points_final}（墩上 ${hs.defender_points_tricks_only}，底牌奖 ${hs.kitty_bonus_to_defenders}）<br/><code>${escapeHtml(JSON.stringify(hs.level_change || {}))}</code>`
        : '已记分';
    } else {
      btnNext.classList.add('hidden');
      summaryBox.classList.add('hidden');
    }

    statusLine.textContent =
      st.phase === 'play'
        ? `轮到: 座${st.to_act_seat} · 你是 座${viewer}` +
          (myTurn ? ' — 请点一张可出（金边）' : ' — 等待他人')
        : '本副已结束，可点「下一副」';
    eventLog.textContent = JSON.stringify(st, null, 2);
    setTimeout(() => void autoplayOthersIfNeeded(), 0);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function playCard(cid) {
    if (app.ws && app.ws.readyState === 1) {
      app.ws.send(JSON.stringify({ type: 'action', card_id: cid }));
      return;
    }
    void postAction(cid);
  }

  async function postAction(cardId) {
    if (!app.tableId) return;
    const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/actions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: tokenForSeat(app.seat), card_id: cardId }),
    });
    const body = await r.json().catch(() => null);
    if (r.ok && body && body.state) renderState(body.state);
  }

  async function createTable(numPlayers) {
    leaveTable();
    const seedRaw = seedIn.value.trim();
    const seed = seedRaw === '' ? null : parseInt(seedRaw, 10);
    const body = {
      num_players: numPlayers,
      declarer_seat: 0,
      match_level_rank: 5,
    };
    if (seed !== null && !Number.isNaN(seed)) body.seed = seed;

    const r = await fetch(`${API_BASE}/api/sheng/tables`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await r.json().catch(() => null);
    if (!r.ok) {
      statusLine.textContent = '开桌失败: ' + (data && (data.detail || data.message) ? JSON.stringify(data) : r.status);
      return;
    }
    app.tableId = data.table_id;
    app.tokens = data.tokens;
    app.np = numPlayers;
    app.seat = 0;
    seatStrip.classList.remove('hidden');
    buildSeatStrip();
    persistSession();
    connectWs();
    renderState(data.state_seat_0);
  }

  async function nextHand() {
    if (!app.tableId) return;
    const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/next_hand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: tokenForSeat(app.seat), seed: null }),
    });
    const data = await r.json().catch(() => null);
    if (r.ok && data && data.state) {
      renderState(data.state);
    } else {
      statusLine.textContent =
        'next_hand 失败: ' +
        (data && data.detail ? JSON.stringify(data.detail) : r.statusText);
      await fetchStateRest();
    }
  }

  $('btn4').addEventListener('click', () => void createTable(4));
  $('btn6').addEventListener('click', () => void createTable(6));
  $('btnLeave').addEventListener('click', leaveTable);
  btnNext.addEventListener('click', () => void nextHand());

  if (loadSession() && app.tableId) {
    seatStrip.classList.remove('hidden');
    buildSeatStrip();
    connectWs();
    void fetchStateRest();
  }
})();
