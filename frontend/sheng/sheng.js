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

  /** @type {{ tableId?: string; tokens?: Record<string,string>; seat?: number; np?: number; ws?: WebSocket | null; lastState?: unknown }} */
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
  const trickArea = $('trickArea'); // legacy (unused)
  const handArea = $('handArea'); // legacy
  const tableSection = $('tableSection');
  const board = $('board');
  const metaBar = $('metaBar');
  const dealOverlay = $('dealOverlay');
  const myHandDock = $('myHandDock');
  const scoreBoard = $('scoreBoard');
  const trickHistorySelect = $('trickHistorySelect');
  const trickHistoryView = $('trickHistoryView');
  const statusLine = $('statusLine');
  const summaryBox = $('summaryBox');
  const btnNext = $('btnNext');
  const eventLog = $('eventLog');
  const chkAutoBot = $('chkAutoBot');
  const chkFriendCalls = $('chkFriendCalls');
  const friendSixSection = $('friendSixSection');

  let botBusy = false;
  const DEAL_STAGGER_MS = 42;
  let dealTimers = [];
  let dealingInProgress = false;
  let dealAnimConsumedKey = '';
  let boardLayoutKey = '';

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
  /** @returns {void} */
  function syncFriendFieldsDisabled() {
    const on = !!(chkFriendCalls && chkFriendCalls.checked);
    for (let w = 1; w <= 2; w++) {
      const ids = [`fc${w}_nth`, `fc${w}_suit`, `fc${w}_rank`];
      ids.forEach((id) => {
        const el = $(id);
        if (el) el.disabled = !on;
      });
    }
  }
  chkFriendCalls?.addEventListener('change', syncFriendFieldsDisabled);
  syncFriendFieldsDisabled();

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
    trickArea && (trickArea.innerHTML = '');
    handArea && (handArea.innerHTML = '');
    tableSection?.classList.add('hidden');
    metaBar.textContent = '';
    if (dealTimers.length) {
      dealTimers.forEach((tid) => clearTimeout(tid));
      dealTimers = [];
    }
    dealingInProgress = false;
    dealAnimConsumedKey = '';
    boardLayoutKey = '';
    if (board) board.innerHTML = '';
    if (myHandDock) myHandDock.innerHTML = '';
    if (trickHistorySelect) trickHistorySelect.innerHTML = '';
    if (trickHistoryView) trickHistoryView.textContent = '';
    if (dealOverlay) dealOverlay.classList.add('hidden');
    if (scoreBoard) scoreBoard.innerHTML = '';
    statusLine.textContent = '';
    summaryBox.classList.add('hidden');
    app.lastState = null;
    eventLog.textContent = '(无)';
    wsPill.textContent = 'WS: —';
    $('friendSixSection')?.classList.add('hidden');
  }

  /** @returns {{ nth: number, suit: string, rank: number } | null} */
  function parseFriendRow(which) {
    const nth = parseInt($(`fc${which}_nth`).value, 10);
    const suit = $(`fc${which}_suit`).value;
    const rank = parseInt($(`fc${which}_rank`).value, 10);
    if (!Number.isFinite(nth) || nth < 1) return null;
    if (!['C', 'D', 'H', 'S'].includes(suit)) return null;
    if (!Number.isFinite(rank) || rank < 2 || rank > 14) return null;
    return { nth, suit, rank };
  }

  function currentMatchLevelRank() {
    const st = app.lastState;
    const lr = st && st.trump && st.trump.level_rank;
    if (typeof lr === 'number' && lr >= 2 && lr <= 14) return lr;
    return 5;
  }

  /**
   * @param {number} matchLevelRank
   * @param {'create' | 'next'} purpose
   * @returns {{ ok: true, calls: any } | { ok: false, message: string }}
   */
  function validateSixFriendCalls(matchLevelRank, purpose) {
    if (!chkFriendCalls || !chkFriendCalls.checked) {
      return { ok: true, calls: purpose === 'next' ? [] : null };
    }
    const a = parseFriendRow(1);
    const b = parseFriendRow(2);
    if (!a || !b) {
      return { ok: false, message: '朋友叫牌：请填写第几张与花色、点数' };
    }
    if (a.nth === b.nth && a.suit === b.suit && a.rank === b.rank) {
      return { ok: false, message: '两张朋友叫牌不能完全相同' };
    }
    if (a.rank === matchLevelRank || b.rank === matchLevelRank) {
      return { ok: false, message: `朋友牌点数不可等于当前级别（${matchLevelRank}）` };
    }
    return { ok: true, calls: [a, b] };
  }

  function tokenForSeat(s) {
    if (!app.tokens) return '';
    return app.tokens[String(s)] || '';
  }

  /** When it is another seat's turn, play their first legal card via REST so one human can solo the table. */
  async function autoplayOthersIfNeeded() {
    if (!chkAutoBot || !chkAutoBot.checked || botBusy || dealingInProgress || !app.tableId) return;
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

  const SUIT_GLYPH = { C: '\u2663', D: '\u2666', H: '\u2665', S: '\u2660' };

  function rankShort(rank) {
    if (rank === 14) return 'A';
    if (rank === 13) return 'K';
    if (rank === 12) return 'Q';
    if (rank === 11) return 'J';
    if (rank === 10) return '10';
    return String(rank);
  }

  /**
   * @param {HTMLElement} el
   * @param {any} card
   */
  function applyCardFace(el, card) {
    el.textContent = '';
    el.classList.remove(
      'card-face--graphic',
      'card-suit-C',
      'card-suit-D',
      'card-suit-H',
      'card-suit-S',
      'card-joker',
      'card-joker-big',
      'card-joker-small'
    );

    if (!card) {
      el.textContent = '?';
      return;
    }

    const k = card.kind;
    if (k === 'bj' || k === 'sj') {
      el.classList.add('card-face--graphic', 'card-joker', k === 'bj' ? 'card-joker-big' : 'card-joker-small');
      const inner = document.createElement('div');
      inner.className = 'card-joker-inner';
      const t1 = document.createElement('span');
      t1.className = 'card-joker-title';
      t1.textContent = k === 'bj' ? '大王' : '小王';
      const t2 = document.createElement('span');
      t2.className = 'card-joker-en';
      t2.textContent = 'JOKER';
      inner.appendChild(t1);
      inner.appendChild(t2);
      el.appendChild(inner);
      return;
    }

    if (k === 'regular' && card.suit && card.rank != null) {
      const suit = String(card.suit);
      const g = SUIT_GLYPH[suit] || suit;
      const rt = rankShort(Number(card.rank));
      el.classList.add('card-face--graphic', 'card-suit-' + suit);

      function corner(mod) {
        const d = document.createElement('div');
        d.className = 'card-corner card-corner--' + mod;
        const r = document.createElement('span');
        r.className = 'card-rank';
        r.textContent = rt;
        const s = document.createElement('span');
        s.className = 'card-suit-micro';
        s.textContent = g;
        d.appendChild(r);
        d.appendChild(s);
        return d;
      }

      el.appendChild(corner('tl'));
      const cen = document.createElement('div');
      cen.className = 'card-suit-center';
      cen.textContent = g;
      el.appendChild(cen);
      el.appendChild(corner('br'));
      return;
    }

    el.textContent = card.label != null ? String(card.label) : String(card.cid);
  }

  function cancelDealAnimation() {
    dealTimers.forEach((tid) => clearTimeout(tid));
    dealTimers = [];
    dealingInProgress = false;
    dealOverlay?.classList.add('hidden');
  }

  function seatOffsetViewer(physicalSeat, viewerSeat, np) {
    return ((physicalSeat - viewerSeat + np) % np + np) % np;
  }

  function seatRingPct(offset, np) {
    const r = np === 4 ? 43 : np === 6 ? 46 : 43;
    const deg = (90 + offset * (360 / np)) * (Math.PI / 180);
    return { left: 50 + r * Math.cos(deg), top: 50 + r * Math.sin(deg) };
  }

  function trickMatPct(offset, np) {
    const r = np === 4 ? 36 : np === 6 ? 39 : 36;
    const deg = (90 + offset * (360 / np)) * (Math.PI / 180);
    return { x: 50 + r * Math.cos(deg), y: 50 + r * Math.sin(deg) };
  }

  function sortHandForReveal(cards) {
    const order = { S: 0, H: 1, D: 2, C: 3 };
    return [...cards].sort((a, b) => {
      const ak = String(a.kind || '');
      const bk = String(b.kind || '');
      if (ak === 'bj' || ak === 'sj') return 1;
      if (bk === 'bj' || bk === 'sj') return -1;
      const sa = order[String(a.suit)] ?? 99;
      const sb = order[String(b.suit)] ?? 99;
      if (sa !== sb) return sa - sb;
      return Number(b.rank || 0) - Number(a.rank || 0);
    });
  }

  function backStacksHtml(count) {
    const n = Math.min(8, Math.max(0, count));
    let h = '';
    for (let i = 0; i < Math.max(1, Math.min(count, n)); i++) {
      const z = Math.min(count, n) <= 4 ? i * 5 : i * 3;
      h += `<span class="card-back-mini" style="--z:${z}px"></span>`;
    }
    if (!count)
      return '<span class="seat-hand-empty">—</span>';
    return `<div class="card-back-stack" title="${count} 张">${h}</div><span class="seat-hand-count">×${count}</span>`;
  }

  function ensureBoardLayout(st) {
    if (!board) return null;
    const np = st.num_players || 4;
    const v = st.viewer_seat;
    const hands = st.hands || [];
    const finger = hands
      .map((h, si) => (si === v ? 'x' : typeof h.count === 'number' ? String(h.count) : '?'))
      .join(',');
    const key = `${np}|${v}|${finger}`;
    let pm = board.querySelector('.trick-playmat');
    if (boardLayoutKey === key && pm) {
      updateSeatActingHighlight(st);
      return pm;
    }
    boardLayoutKey = key;
    board.className = 'board board-np-' + np;
    board.innerHTML = '';
    const ring = document.createElement('div');
    ring.className = 'board-ring';
    const center = document.createElement('div');
    center.className = 'board-center';
    pm = document.createElement('div');
    pm.className = 'trick-playmat';
    center.appendChild(pm);
    board.appendChild(ring);
    board.appendChild(center);

    for (let offset = 0; offset < np; offset++) {
      const seat = (v + offset) % np;
      const pct = seatRingPct(offset, np);
      const node = document.createElement('div');
      node.className = 'seat-node';
      node.dataset.seat = String(seat);
      node.style.left = pct.left + '%';
      node.style.top = pct.top + '%';

      const tag = ['座 ' + seat];
      if (seat === st.declarer_seat) tag.push('庄');
      if (seat === v) tag.push('你');

      const seatLine = tag.join(' · ');
      if (seat === v) {
        node.innerHTML = `<div class="seat-tag">${escapeHtml(seatLine)} · 我方手牌在下方横排</div>`;
      } else {
        const hi = hands[seat];
        const cnt = hi && typeof hi.count === 'number' ? hi.count : 0;
        node.innerHTML = `<div class="seat-tag">${escapeHtml(seatLine)}</div><div class="seat-opp-wrap">${backStacksHtml(
          cnt
        )}</div>`;
      }
      ring.appendChild(node);
    }
    updateSeatActingHighlight(st);
    return pm;
  }

  function updateSeatActingHighlight(st) {
    if (!board) return;
    board.querySelectorAll('.seat-node').forEach((n) => {
      const s = Number(n.dataset.seat);
      const on = st.phase === 'play' && Number.isFinite(s) && s === st.to_act_seat;
      n.classList.toggle('seat-node--acting', !!on);
    });
  }

  function paintTrickPlays(playmatEl, plays, viewerSeat, np, highlights) {
    if (!playmatEl) return;
    playmatEl.innerHTML = '';
    if (!plays || !plays.length) return;
    const hi = highlights || {};
    const mini = playmatEl.classList.contains('trick-playmat--mini');
    plays.forEach((p) => {
      const seat = p.seat;
      const off = seatOffsetViewer(seat, viewerSeat, np);
      const pos = trickMatPct(off, np);
      const wrap = document.createElement('div');
      wrap.className = 'trick-mat-slot';
      wrap.style.left = pos.x + '%';
      wrap.style.top = pos.y + '%';
      const cf = document.createElement('div');
      cf.className = mini ? 'card-face card-face--sm' : 'card-face card-face--trick';
      applyCardFace(cf, p.card);
      wrap.appendChild(cf);
      const lb = document.createElement('div');
      lb.className = 'trick-mat-tag';
      lb.textContent = '座' + seat;
      wrap.appendChild(lb);
      if (hi.winnerSeat === seat) wrap.classList.add('trick-mat-slot--win');
      playmatEl.appendChild(wrap);
    });
  }

  function fillMetaBar(st) {
    if (!metaBar) return;
    const tr = st.trump || {};
    metaBar.textContent = [
      `阶段 ${st.phase}`,
      `庄 座${st.declarer_seat}`,
      `领出 座${st.leader}`,
      `主 ${tr.trump_suit || '?'} @${tr.level_rank}`,
      `台面 A${st.teams?.A} / B${st.teams?.B}`,
      `已完墩 ${(st.completed_tricks || []).length}`,
    ].join(' · ');
  }

  function fillScoreBoard(st) {
    if (!scoreBoard) return;
    const th = st.defenders_threshold ?? (st.num_players === 6 ? 120 : 80);
    const dr = Number(st.defender_trick_points_running ?? 0);
    const kitty = st.kitty?.count ?? '—';
    const teams = `<div class="sb-rows">
      <div class="sb-row"><span class="lbl">队伍 A · 级</span><b>${escapeHtml(String(st.teams?.A ?? '?'))}</b></div>
      <div class="sb-row"><span class="lbl">队伍 B · 级</span><b>${escapeHtml(String(st.teams?.B ?? '?'))}</b></div>
      <div class="sb-row"><span class="lbl">闲家墩分（累计）</span><b>${dr}</b> <span class="muted">/ 目标 ${th}</span></div>
      <div class="sb-row"><span class="lbl">底牌</span><span>${escapeHtml(String(kitty))} 张</span></div>
      <div class="sb-row"><span class="lbl">出牌序</span><span>轮到 座<b>${escapeHtml(String(st.to_act_seat ?? '—'))}</b></span></div>
    </div>`;
    let six = '';
    if (st.num_players === 6) {
      const fc = st.friend_calls || [];
      const rev = st.revealed_friend_seats || [];
      six = `<div class="sb-sub muted small">朋友: ${
        fc.length ? escapeHtml(fc.map((c) => `第${c.nth}张${c.suit}${c.rank}`).join(' / ')) : '对角组队'
      } · 揭牌友: ${rev.length ? escapeHtml(rev.join(' / ')) : '—'}</div>`;
    }
    scoreBoard.innerHTML = teams + six;
  }

  function syncHistorySelect(st) {
    if (!trickHistorySelect || !trickHistoryView) return;
    const done = st.completed_tricks || [];
    const prev = trickHistorySelect.value;
    trickHistorySelect.innerHTML = '';
    const o0 = document.createElement('option');
    o0.value = 'cur';
    o0.textContent = '当前墩';
    trickHistorySelect.appendChild(o0);
    done.forEach((t, i) => {
      const o = document.createElement('option');
      const idx = t.index ?? i + 1;
      o.value = String(idx - 1);
      o.textContent = `第 ${idx} 墩 · ${t.trick_points} 分 · 胜 座 ${t.winner_seat}`;
      trickHistorySelect.appendChild(o);
    });
    trickHistorySelect.value = prev === 'cur' || !done.some((_, i) => String(i) === prev) ? 'cur' : prev;
    renderTrickHistoryPanel(st);
  }

  function renderTrickHistoryPanel(st) {
    if (!trickHistorySelect || !trickHistoryView) return;
    const val = trickHistorySelect.value;
    const done = st.completed_tricks || [];
    if (val === 'cur') {
      trickHistoryView.innerHTML = '';
      const hint = document.createElement('p');
      hint.className = 'trick-hist-hint muted small';
      const cur = st.current_trick || [];
      hint.textContent = cur.length ? '与桌面中央的「本墩」一致。' : '尚未有人出牌 · 由下家领出。';
      trickHistoryView.appendChild(hint);
      const mini = document.createElement('div');
      mini.className = 'trick-playmat trick-playmat--mini';
      paintTrickPlays(mini, cur, st.viewer_seat, st.num_players, {});
      trickHistoryView.appendChild(mini);
      return;
    }
    const i = parseInt(val, 10);
    const tr = done[i];
    if (!tr) {
      trickHistoryView.textContent = '—';
      return;
    }
    trickHistoryView.innerHTML =
      `<p class="trick-hist-meta muted small">第 ${escapeHtml(String(tr.index || i + 1))} 墩 · ${escapeHtml(
        String(tr.trick_points)
      )} 分 · 获胜 座 ${escapeHtml(String(tr.winner_seat))} · ${tr.defenders_gained ? '闲家捡分' : '庄防守'}</p>` +
      `<div class="trick-playmat trick-playmat--mini trick-hist-body-mat"></div>`;
    const mini = trickHistoryView.querySelector('.trick-playmat');
    paintTrickPlays(mini, tr.plays || [], st.viewer_seat, st.num_players, { winnerSeat: tr.winner_seat });
  }

  function renderMyHand(st, myTurn, legalIds) {
    if (!myHandDock) return;
    const epochKey = `${st.table_id}:${st.deal_epoch ?? 0}`;
    const tricking =
      (st.completed_tricks || []).length > 0 || ((st.current_trick || []).length > 0);
    if (dealingInProgress && tricking) {
      cancelDealAnimation();
      dealAnimConsumedKey = epochKey;
    }

    const mine = (st.hands || [])[st.viewer_seat];
    myHandDock.innerHTML = '';
    const title = document.createElement('div');
    title.className = 'my-hand-title';
    title.textContent = '你的手牌';
    myHandDock.appendChild(title);
    const row = document.createElement('div');
    row.className = 'my-hand-row';
    myHandDock.appendChild(row);

    if (!Array.isArray(mine) || !mine.length) {
      row.textContent = '（暂无手牌）';
      return;
    }

    const sorted = sortHandForReveal(mine);
    const shouldStagger =
      st.phase === 'play' && epochKey !== dealAnimConsumedKey && !tricking;

    if (shouldStagger) {
      cancelDealAnimation();
      dealingInProgress = true;
      dealOverlay?.classList.remove('hidden');
      sorted.forEach((c, i) => {
        const el = document.createElement('div');
        el.className = 'card-face card-deal-pending' + (myTurn && legalIds.has(c.cid) ? ' playable' : ' dim');
        applyCardFace(el, c);
        el.style.opacity = '0';
        el.title = (c.label || '') + ' · cid=' + c.cid;
        if (myTurn && legalIds.has(c.cid)) {
          el.addEventListener('click', () => {
            if (dealingInProgress) return;
            playCard(c.cid);
          });
        }
        row.appendChild(el);
        const tid = setTimeout(() => {
          el.style.opacity = '1';
          el.classList.remove('card-deal-pending');
        }, i * DEAL_STAGGER_MS);
        dealTimers.push(tid);
      });
      const fin = setTimeout(() => {
        dealingInProgress = false;
        dealAnimConsumedKey = epochKey;
        dealOverlay?.classList.add('hidden');
      }, sorted.length * DEAL_STAGGER_MS + 120);
      dealTimers.push(fin);
    } else {
      sorted.forEach((c) => {
        const el = document.createElement('div');
        el.className = 'card-face' + (myTurn && legalIds.has(c.cid) ? ' playable' : ' dim');
        applyCardFace(el, c);
        el.title = (c.label || '') + ' · cid=' + c.cid;
        if (myTurn && legalIds.has(c.cid) && !dealingInProgress) {
          el.addEventListener('click', () => playCard(c.cid));
        }
        row.appendChild(el);
      });
    }
  }

  function renderState(st) {
    app.lastState = st;
    const np = st.num_players || app.np;
    app.np = np;
    tableSection?.classList.remove('hidden');

    const playmat = ensureBoardLayout(st);
    fillMetaBar(st);
    fillScoreBoard(st);
    syncHistorySelect(st);
    paintTrickPlays(playmat, st.current_trick || [], st.viewer_seat, np, {});
    updateSeatActingHighlight(st);

    const legal = st.legal_plays || [];
    const legalIds = new Set(legal.map((x) => x.cid));
    const viewer = st.viewer_seat;
    const myTurn = st.phase === 'play' && st.to_act_seat === viewer;

    renderMyHand(st, myTurn, legalIds);

    if (st.phase === 'scored') {
      btnNext.classList.remove('hidden');
      const hs = st.hand_summary;
      summaryBox.classList.remove('hidden');
      summaryBox.innerHTML = hs
        ? `<strong>本副结束</strong><br/>闲家分: ${hs.defender_points_final}（墩上 ${hs.defender_points_tricks_only}，底牌奖 ${hs.kitty_bonus_to_defenders}）<br/><code>${escapeHtml(JSON.stringify(hs.level_change || {}))}</code>`
        : '已记分';
      cancelDealAnimation();
      dealAnimConsumedKey = '';
    } else {
      btnNext.classList.add('hidden');
      summaryBox.classList.add('hidden');
    }

    statusLine.textContent =
      st.phase === 'play'
        ? `轮到 座${st.to_act_seat} · 你在 座${viewer}` +
          (myTurn
            ? dealingInProgress
              ? ' — 发牌后可以出牌'
              : ' — 点下方手牌'
            : dealingInProgress
              ? ' — 发牌中…'
              : ' — 等待')
        : '本副已结束，可点「下一副」';
    eventLog.textContent = JSON.stringify(st, null, 2);
    setTimeout(() => {
      if (!dealingInProgress) void autoplayOthersIfNeeded();
    }, 0);
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function playCard(cid) {
    if (dealingInProgress) return;
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
    if (numPlayers === 6) {
      friendSixSection?.classList.remove('hidden');
    } else {
      friendSixSection?.classList.add('hidden');
    }
    const seedRaw = seedIn.value.trim();
    const seed = seedRaw === '' ? null : parseInt(seedRaw, 10);
    const body = {
      num_players: numPlayers,
      declarer_seat: 0,
      match_level_rank: 5,
    };
    if (seed !== null && !Number.isNaN(seed)) body.seed = seed;

    if (numPlayers === 6) {
      const vr = validateSixFriendCalls(5, 'create');
      if (!vr.ok) {
        statusLine.textContent = vr.message || '朋友叫牌有误';
        return;
      }
      if (vr.calls) body.friend_calls = vr.calls;
    }

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
    const body = { token: tokenForSeat(app.seat), seed: null };
    if (app.np === 6) {
      const vr = validateSixFriendCalls(currentMatchLevelRank(), 'next');
      if (!vr.ok) {
        statusLine.textContent = vr.message || '朋友叫牌有误';
        return;
      }
      body.friend_calls = vr.calls;
    }
    const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/next_hand`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body),
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

  trickHistorySelect?.addEventListener('change', () => {
    if (app.lastState) renderTrickHistoryPanel(app.lastState);
  });

  $('btn4').addEventListener('click', () => void createTable(4));
  $('btn6').addEventListener('click', () => void createTable(6));
  $('btnLeave').addEventListener('click', leaveTable);
  btnNext.addEventListener('click', () => void nextHand());

  if (loadSession() && app.tableId) {
    if (app.np === 6) friendSixSection?.classList.remove('hidden');
    seatStrip.classList.remove('hidden');
    buildSeatStrip();
    connectWs();
    void fetchStateRest();
  }
})();
