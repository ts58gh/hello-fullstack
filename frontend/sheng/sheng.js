(function () {
  const STORAGE_SESSION = 'hello_fullstack_sheng_session_v1';
  const STORAGE_API = 'hello_fullstack_api_base';
  const STORAGE_AUTOBOT = 'hello_fullstack_sheng_autobot_other';
  const STORAGE_BOARD_H = 'hello_fullstack_sheng_board_height_v1';
  const STORAGE_SIDE_W = 'hello_fullstack_sheng_side_width_v1';

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
  const gameShell = $('gameShell');
  const boardResizeFrame = $('boardResizeFrame');
  const boardResizeHost = $('boardResizeHost');
  const boardResizeHandle = $('boardResizeHandle');
  const boardResizeHandleX = $('boardResizeHandleX');
  const boardScaleWrap = $('boardScaleWrap');
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
  const DEAL_STAGGER_MS = 88;
  let dealTimers = [];
  let dealAdvanceChainTid = null;
  let dealingInProgress = false;
  let dealAnimConsumedKey = '';
  let boardLayoutKey = '';
  /** Selected card cids (multiset) before confirming a legal combo. */
  let selectedPlayIds = [];
  /** Trick history sidebar: default to last completed trick until user touches the dropdown. */
  let trickHistManual = false;
  /** New deal resets trickHistManual when epoch changes. */
  let trickHistSyncedEpoch = null;

  apiPill.textContent = `API: ${API_BASE}`;
  apiBaseInput.value = API_BASE;
  try {
    const vb = sessionStorage.getItem(STORAGE_AUTOBOT);
    if (chkAutoBot && vb === '0') chkAutoBot.checked = false;
    else if (chkAutoBot && vb === '1') chkAutoBot.checked = true;
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
    if (dealAdvanceChainTid) {
      clearTimeout(dealAdvanceChainTid);
      dealAdvanceChainTid = null;
    }
    dealingInProgress = false;
    dealAnimConsumedKey = '';
    boardLayoutKey = '';
    trickHistManual = false;
    trickHistSyncedEpoch = null;
    selectedPlayIds = [];
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
    return 2;
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

  function phaseLabelZh(ph) {
    if (ph === 'declare') return '叫主';
    if (ph === 'kitty') return '埋底';
    if (ph === 'play') return '出牌';
    if (ph === 'scored') return '记分';
    return String(ph ?? '—');
  }

  function cancelDealAdvanceChain() {
    if (dealAdvanceChainTid) {
      clearTimeout(dealAdvanceChainTid);
      dealAdvanceChainTid = null;
    }
  }

  /** FastAPI 404 with detail "table not found" when in-memory table is gone. */
  function detailLooksLikeTableMissing(body) {
    const d = body && (body.detail ?? body.message);
    return typeof d === 'string' && /table not found/i.test(d);
  }

  function abandonTableSessionBecauseMissing(contextLabel) {
    cancelDealAdvanceChain();
    leaveTable();
    statusLine.textContent =
      (contextLabel ? contextLabel + ' — ' : '') +
      '服务器上没有这桌了（常见：主机重启、桌位满时淘汰最早一桌、或 API 地址与开桌时不一致）。本地进度已清除，请重新「开桌」。';
  }

  async function fetchStateRest() {
    if (!app.tableId || !tokenForSeat(app.seat)) return;
    const tok = encodeURIComponent(tokenForSeat(app.seat));
    const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}?token=${tok}`);
    const st = await r.json().catch(() => null);
    if (!r.ok) {
      if (r.status === 404 && (!st || detailLooksLikeTableMissing(st))) {
        abandonTableSessionBecauseMissing('同步失败');
      }
      return;
    }
    if (st) renderState(st);
  }

  async function advanceDealViaRestOnce(steps) {
    if (!app.tableId || !tokenForSeat(app.seat)) return false;
    const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/deal_advance`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: tokenForSeat(app.seat), steps: Math.min(20, Math.max(1, steps || 1)) }),
    });
    const jd = await r.json().catch(() => null);
    if (r.ok && jd && jd.state) {
      renderState(jd.state);
      return true;
    }
    if (!r.ok && r.status === 404 && (!jd || detailLooksLikeTableMissing(jd))) {
      abandonTableSessionBecauseMissing('发牌同步');
    }
    return false;
  }

  function scheduleDealAdvanceIfNeeded(st) {
    cancelDealAdvanceChain();
    if (!st || st.phase !== 'declare' || !app.tableId) return;
    const cur = Number(st.deal_reveal_steps ?? 0);
    const tot = Number(st.deal_total_steps ?? 0);
    if (!Number.isFinite(cur) || !Number.isFinite(tot) || tot <= 0 || cur >= tot) return;
    dealAdvanceChainTid = setTimeout(() => {
      dealAdvanceChainTid = null;
      const ls = app.lastState;
      if (!ls || ls.phase !== 'declare' || !app.tableId) return;
      const c2 = Number(ls.deal_reveal_steps ?? 0);
      const t2 = Number(ls.deal_total_steps ?? 0);
      if (c2 >= t2) return;
      if (app.ws && app.ws.readyState === 1) {
        try {
          app.ws.send(JSON.stringify({ type: 'deal_advance', steps: 1 }));
        } catch (_) {}
      } else {
        void advanceDealViaRestOnce(1);
      }
    }, DEAL_STAGGER_MS);
  }

  /** Auto-seat: mix pass / first random legal bid (higher chance when stakes already on table). */
  function botDeclarePayloadFromLegal(ld, declareStakes) {
    const opts = (ld || []).filter((o) => o && o.kind && o.kind !== 'pass');
    if (!opts.length) return { action: 'pass' };
    const stkAmt = Number(declareStakes);
    const pBid = stkAmt > 0 ? 0.52 : 0.38;
    if (Math.random() >= pBid) return { action: 'pass' };
    const pick = opts[Math.floor(Math.random() * opts.length)];
    if (pick.kind === 'bid_plain' || pick.kind === 'bid_suit')
      return { action: 'bid_plain', suit: pick.suit };
    if (pick.kind === 'bid_pair') return { action: 'bid_pair', suit: pick.suit };
    if (pick.kind === 'bid_nt') return { action: 'bid_nt' };
    return { action: 'pass' };
  }

  function formatDeclareHistLine(h) {
    if (!h) return '';
    if (h.kind === 'pass') return `座${h.seat} 过`;
    if (h.kind === 'bid') {
      const m = {
        plain: '亮级',
        pair: '对级',
        nt: '无主',
      };
      const lab = m[h.bid_kind] || h.bid_kind;
      const su = h.suit ? `${h.suit} ` : '';
      return `座${h.seat} 叫 ${su}${lab}`;
    }
    if (h.kind === 'declare_done') {
      const b = h.bury_card_count != null ? ` · 底${h.bury_card_count}张待扣` : '';
      return `▼ 定局 庄 ${h.declarer_seat}${b}`;
    }
    if (h.kind === 'bury_done') return `座${h.seat} 已埋底`;
    return escapeHtml(JSON.stringify(h));
  }

  /** When declare or play for another seat — REST solo helper. */
  async function autoplayOthersIfNeeded() {
    if (!chkAutoBot || !chkAutoBot.checked || botBusy || !app.tableId) return;
    const st = app.lastState;
    if (!st) return;
    if (st.phase === 'declare') {
      const free = !!st.declare_turn_free_for_all;
      const ds = st.declare_to_act_seat;
      if (!free && (ds === undefined || ds === null)) return;
      if (!free && Number(ds) === Number(st.viewer_seat)) return;
      botBusy = true;
      try {
        if (free) {
          const np = st.num_players || app.np || 4;
          for (let si = 0; si < np; si++) {
            if (Number(si) === Number(st.viewer_seat)) continue;
            const tsi = tokenForSeat(si);
            if (!tsi) continue;
            const tokq = encodeURIComponent(tsi);
            const rPeek = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}?token=${tokq}`);
            const jPeek = await rPeek.json().catch(() => null);
            if (
              !rPeek.ok &&
              rPeek.status === 404 &&
              (!jPeek || detailLooksLikeTableMissing(jPeek))
            ) {
              abandonTableSessionBecauseMissing('叫主失败');
              return;
            }
            const ldPeer = jPeek && jPeek.legal_declare;
            if (!ldPeer || !ldPeer.length) continue;
            const pay = botDeclarePayloadFromLegal(ldPeer, jPeek.declare_stakes);
            const rd = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/declare`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
              body: JSON.stringify({ token: tsi, ...pay }),
            });
            const jdd = await rd.json().catch(() => null);
            if (!rd.ok && rd.status === 404 && (!jdd || detailLooksLikeTableMissing(jdd))) {
              abandonTableSessionBecauseMissing('叫主失败');
              return;
            }
            await fetchStateRest();
            break;
          }
        } else {
          const tOrd = tokenForSeat(ds);
          if (!tOrd) return;
          const tokOrd = encodeURIComponent(tOrd);
          const rPeekO = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}?token=${tokOrd}`);
          const jPeekO = await rPeekO.json().catch(() => null);
          if (
            !rPeekO.ok &&
            rPeekO.status === 404 &&
            (!jPeekO || detailLooksLikeTableMissing(jPeekO))
          ) {
            abandonTableSessionBecauseMissing('叫主失败');
            return;
          }
          const ldOrd = (jPeekO && jPeekO.legal_declare) || [];
          if (!ldOrd.length) return;
          const payO = botDeclarePayloadFromLegal(ldOrd, jPeekO && jPeekO.declare_stakes);
          const rd = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/declare`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: JSON.stringify({ token: tOrd, ...payO }),
          });
          const jdd = await rd.json().catch(() => null);
          if (!rd.ok && rd.status === 404 && (!jdd || detailLooksLikeTableMissing(jdd))) {
            abandonTableSessionBecauseMissing('叫主失败');
            return;
          }
          await fetchStateRest();
        }
      } catch (_) {
        /* ignore */
      } finally {
        botBusy = false;
      }
      return;
    }
    if (st.phase === 'kitty') {
      const bt = st.bury_to_act_seat;
      if (bt === undefined || bt === null) return;
      if (Number(bt) === Number(st.viewer_seat)) return;
      const need = Number(st.kitty?.bury_needed ?? 0);
      if (!Number.isFinite(need) || need <= 0) return;
      botBusy = true;
      try {
        const tt = encodeURIComponent(tokenForSeat(bt));
        const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}?token=${tt}`);
        const peerErr = await r.json().catch(() => null);
        if (!r.ok) {
          if (r.status === 404 && (!peerErr || detailLooksLikeTableMissing(peerErr))) {
            abandonTableSessionBecauseMissing('埋底失败');
          }
          return;
        }
        const peer = peerErr;
        const hand = peer.hands && peer.hands[bt];
        if (!Array.isArray(hand)) return;
        const ids = hand
          .map((c) => cidKey(c.cid))
          .filter((n) => n != null)
          .sort((a, b) => a - b)
          .slice(0, need);
        if (ids.length !== need) return;
        const r2 = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/bury`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ token: tokenForSeat(bt), card_ids: ids }),
        });
        const jb = await r2.json().catch(() => null);
        if (!r2.ok && r2.status === 404 && (!jb || detailLooksLikeTableMissing(jb))) {
          abandonTableSessionBecauseMissing('埋底失败');
          return;
        }
        if (r2.ok) await fetchStateRest();
      } catch (_) {
        /* ignore */
      } finally {
        botBusy = false;
      }
      return;
    }
    if (!st || st.phase !== 'play' || dealingInProgress) return;
    const actor = st.to_act_seat;
    if (actor === undefined || actor === null) return;
    if (Number(actor) === Number(st.viewer_seat)) return;

    botBusy = true;
    try {
      const tt = encodeURIComponent(tokenForSeat(actor));
      const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}?token=${tt}`);
      const peerErrOrState = await r.json().catch(() => null);
      if (!r.ok) {
        if (r.status === 404 && (!peerErrOrState || detailLooksLikeTableMissing(peerErrOrState))) {
          abandonTableSessionBecauseMissing('出牌失败');
        }
        return;
      }
      const peer = peerErrOrState;
      const legal = peer.legal_plays || [];
      if (!legal.length) return;
      const ids = legalOptionCardIds(legal[0]);
      if (!ids.length) return;
      const r2 = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/actions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ token: tokenForSeat(actor), card_ids: ids }),
      });
      const body = await r2.json().catch(() => null);
      if (!r2.ok && r2.status === 404 && (!body || detailLooksLikeTableMissing(body))) {
        abandonTableSessionBecauseMissing('出牌失败');
        return;
      }
      if (r2.ok && body) {
        /* Do not render(body.state): it is viewer=actor snapshot and desyncs our active seat WS view. */
        await fetchStateRest();
      }
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
        selectedPlayIds = [];
        const em = msg.message || '';
        if (/table not found/i.test(em)) {
          abandonTableSessionBecauseMissing('连接错误');
        } else {
          statusLine.textContent = '错误: ' + em;
          void fetchStateRest();
        }
      }
    });
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

  function trickMatPct(offset, np) {
    const r = np === 4 ? 36 : np === 6 ? 39 : 36;
    const deg = (90 + offset * (360 / np)) * (Math.PI / 180);
    return { x: 50 + r * Math.cos(deg), y: 50 + r * Math.sin(deg) };
  }

  /** Canonical numeric card id for Set / compares (handles string ids from JSON). */
  function cidKey(x) {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }

  /** @param {any} lp One entry from ``legal_plays`` */
  function legalOptionCardIds(lp) {
    if (!lp) return [];
    if (Array.isArray(lp.card_ids) && lp.card_ids.length)
      return lp.card_ids.map((x) => cidKey(x)).filter((n) => n != null);
    if (Array.isArray(lp.cards) && lp.cards.length)
      return lp.cards.map((c) => cidKey(c.cid)).filter((n) => n != null);
    if (lp.card != null) {
      const n = cidKey(lp.card.cid);
      return n != null ? [n] : [];
    }
    return [];
  }

  function unionLegalTouchIds(legalPlays) {
    const s = new Set();
    (legalPlays || []).forEach((lp) => legalOptionCardIds(lp).forEach((id) => s.add(id)));
    return s;
  }

  function sortedIdKey(ids) {
    return JSON.stringify(
      [...ids]
        .map((x) => cidKey(x))
        .filter((n) => n != null)
        .sort((a, b) => a - b),
    );
  }

  /** @returns {number[] | null} */
  function findMatchingLegalCardIds(legalPlays, selectedIds) {
    const want = sortedIdKey(selectedIds);
    for (const lp of legalPlays || []) {
      const ids = legalOptionCardIds(lp);
      if (ids.length && sortedIdKey(ids) === want) return ids.slice();
    }
    return null;
  }

  /**
   * 手牌展示顺序：固定主（大王→小王→级牌按黑红梅方）→有主时再排主花色非级牌（点数从大至小）
   * →其余副牌按黑红梅方、同花内从大至小。无主则无「主花色」段。
   */
  function sortHandForReveal(cards, st) {
    const trump = st && st.trump ? st.trump : {};
    const levelRank = Number(trump.level_rank);
    const lrOk = Number.isFinite(levelRank) && levelRank >= 2 && levelRank <= 14;
    const tsRaw = trump.trump_suit;
    const tsOk = typeof tsRaw === 'string' && /^[SHCD]$/.test(tsRaw) ? tsRaw : null;

    /** 黑桃·红桃·梅花·方块 */
    const suitOrder = { S: 0, H: 1, C: 2, D: 3 };

    function key(card) {
      const kind = String(card.kind || '');
      const cidTie = Number(card.cid);
      const tie = Number.isFinite(cidTie) ? cidTie : 0;

      if (kind === 'bj') return [0, 0, tie];
      if (kind === 'sj') return [0, 1, tie];

      const rank = Number(card.rank);
      const suit = String(card.suit || '');
      const so = suitOrder[suit];
      const suitK = Number.isFinite(so) ? so : 99;

      if (lrOk && rank === levelRank) {
        return [0, 2, suitK, tie];
      }

      if (tsOk && suit === tsOk) {
        return [1, -rank, tie];
      }

      return [2, suitK, -rank, tie];
    }

    return [...cards].sort((a, b) => {
      const ka = key(a);
      const kb = key(b);
      for (let i = 0; i < Math.max(ka.length, kb.length); i++) {
        const x = ka[i] ?? 0;
        const y = kb[i] ?? 0;
        if (x !== y) return x - y;
      }
      return 0;
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
    return `<div class="seat-opp-wrap"><div class="card-back-stack" title="${count} 张">${h}</div><span class="seat-hand-count">×${count}</span></div>`;
  }

  function fillSeatPanel(el, seat, st, hands, viewer, np) {
    el.dataset.seat = String(seat);
    el.classList.add('sb-seat');
    const lbl = document.createElement('div');
    lbl.className = 'sb-seat-label';
    const tag = ['座 ' + seat];
    if (seat === st.declarer_seat) tag.push('庄');
    if (seat === viewer) tag.push('你');
    let line = tag.join(' · ');
    if (seat === viewer) line += ' · 手牌在下方横排';
    lbl.textContent = line;
    el.appendChild(lbl);
    const handBox = document.createElement('div');
    if (seat === viewer) {
      handBox.className = 'sb-hand-row sb-hand-row--viewer-hint';
      handBox.innerHTML = '<span class="seat-hand-empty muted small">见下方横排</span>';
    } else {
      const hi = hands[seat];
      const cnt = hi && typeof hi.count === 'number' ? hi.count : 0;
      const vert = np === 4 && (el.classList.contains('sb-seat-w') || el.classList.contains('sb-seat-e'));
      handBox.className = vert ? 'sb-hand-col' : 'sb-hand-row';
      handBox.innerHTML = backStacksHtml(cnt);
    }
    el.appendChild(handBox);
  }

  let boardHeightPinned = false;
  function boardHeightBounds() {
    const min = 240;
    // Looser cap so auto-fit can use full width (hw*nh/nw) without shrinking the green felt.
    const max = Math.max(min + 80, Math.min(window.innerHeight - 20, 2200));
    return { min, max };
  }

  function clampBoardHeight(px) {
    const { min, max } = boardHeightBounds();
    return Math.round(Math.min(max, Math.max(min, px)));
  }

  let boardFitRafQueued = false;
  /** 将整桌按比例缩放于 host 内，保证无滚动条、内容完整可见。 */
  function scheduleBoardFit() {
    if (boardFitRafQueued) return;
    boardFitRafQueued = true;
    requestAnimationFrame(() => {
      boardFitRafQueued = false;
      syncBoardFitScale();
    });
  }

  function applyBoardHostHeight(px, opts) {
    const host = boardResizeHost;
    if (!host) return;
    const persist = !!(opts && opts.persist);
    const h = clampBoardHeight(px);
    host.style.setProperty('--sheng-board-h', `${h}px`);
    if (persist) {
      boardHeightPinned = true;
      try {
        localStorage.setItem(STORAGE_BOARD_H, String(h));
      } catch (_) {}
    }
  }

  function syncBoardFitScale() {
    const host = boardResizeHost;
    const wrap = boardScaleWrap;
    const panel = board;
    if (!host || !panel || !wrap) return;

    panel.style.transform = '';
    wrap.style.width = '';
    wrap.style.height = '';

    let hw = host.clientWidth;
    let hh = host.clientHeight;
    if (hw < 12 || hh < 12) return;

    let nw = panel.offsetWidth;
    let nh = panel.offsetHeight;
    if (nw < 12) nw = panel.scrollWidth;
    if (nh < 12) nh = panel.scrollHeight;
    if (nw < 8 || nh < 8) return;

    // Smart aspect ratio: only auto-adjust height (board is always hand-width).
    if (!boardHeightPinned) {
      const ratio = nh / nw;
      const hb = boardHeightBounds();
      // Fill width first (host width), then compute ideal height.
      let wantH = hw * ratio;
      if (wantH > hb.max) wantH = hb.max;
      if (wantH < hb.min) wantH = hb.min;
      applyBoardHostHeight(wantH, { persist: false });
      hh = host.clientHeight;
    }

    let s = Math.min(hw / nw, hh / nh, 1);
    s = Math.max(0.08, Math.min(s, 1));

    if (s >= 0.9995) return;

    panel.style.transformOrigin = 'center center';
    panel.style.transform = `scale(${s})`;
    wrap.style.width = `${Math.ceil(nw * s)}px`;
    wrap.style.height = `${Math.ceil(nh * s)}px`;
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
      scheduleBoardFit();
      return pm;
    }
    boardLayoutKey = key;
    board.innerHTML = '';

    if (np === 4) {
      board.className = 'sb-board board board-np-4';

      const nEl = document.createElement('div');
      nEl.className = 'sb-seat sb-seat-n';
      fillSeatPanel(nEl, (v + 2) % 4, st, hands, v, np);

      const wEl = document.createElement('div');
      wEl.className = 'sb-seat sb-seat-w';
      fillSeatPanel(wEl, (v + 1) % 4, st, hands, v, np);

      const center = document.createElement('div');
      center.className = 'sb-center-b';
      pm = document.createElement('div');
      pm.className = 'sb-trick-playmat trick-playmat';
      center.appendChild(pm);

      const eEl = document.createElement('div');
      eEl.className = 'sb-seat sb-seat-e';
      fillSeatPanel(eEl, (v + 3) % 4, st, hands, v, np);

      const sEl = document.createElement('div');
      sEl.className = 'sb-seat sb-seat-s';
      fillSeatPanel(sEl, v, st, hands, v, np);

      board.appendChild(nEl);
      board.appendChild(wEl);
      board.appendChild(center);
      board.appendChild(eEl);
      board.appendChild(sEl);
    } else {
      board.className = 'sb-board sb-board--6 board board-np-6';

      const top = document.createElement('div');
      top.className = 'sb-six-top';
      const mid = document.createElement('div');
      mid.className = 'sb-six-mid';
      pm = document.createElement('div');
      pm.className = 'sb-trick-playmat trick-playmat';
      mid.appendChild(pm);
      const bot = document.createElement('div');
      bot.className = 'sb-six-bot';

      [4, 3, 2].forEach((off) => {
        const el = document.createElement('div');
        el.className = 'sb-seat sb-six-seat';
        fillSeatPanel(el, (v + off) % 6, st, hands, v, np);
        top.appendChild(el);
      });
      [5, 0, 1].forEach((off) => {
        const el = document.createElement('div');
        el.className = 'sb-seat sb-six-seat';
        fillSeatPanel(el, (v + off) % 6, st, hands, v, np);
        bot.appendChild(el);
      });
      board.appendChild(top);
      board.appendChild(mid);
      board.appendChild(bot);
    }

    updateSeatActingHighlight(st);
    scheduleBoardFit();
    return pm;
  }

  function updateSeatActingHighlight(st) {
    if (!board) return;
    let act = NaN;
    if (st.phase === 'play' && st.to_act_seat != null) act = Number(st.to_act_seat);
    else if (
      st.phase === 'declare' &&
      !st.declare_turn_free_for_all &&
      st.declare_to_act_seat != null
    )
      act = Number(st.declare_to_act_seat);
    else if (st.phase === 'kitty' && st.bury_to_act_seat != null) act = Number(st.bury_to_act_seat);
    board.querySelectorAll('.sb-seat').forEach((n) => {
      const s = Number(n.dataset.seat);
      const on = Number.isFinite(s) && Number.isFinite(act) && s === act;
      n.classList.toggle('sb-seat--acting', !!on);
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
      const cards = p.cards && p.cards.length ? p.cards : p.card ? [p.card] : [];
      const wrap = document.createElement('div');
      const stack = document.createElement('div');
      stack.className = 'trick-cards-stack';
      cards.forEach((card) => {
        const cf = document.createElement('div');
        cf.className = mini ? 'card-face card-face--sm' : 'card-face card-face--trick';
        applyCardFace(cf, card);
        stack.appendChild(cf);
      });
      wrap.appendChild(stack);
      const lb = document.createElement('div');
      lb.textContent = '座' + seat + (cards.length > 1 ? ` · ${cards.length}张` : '');
      if (mini) {
        const pos = trickMatPct(off, np);
        wrap.className = 'trick-mat-slot';
        wrap.style.left = pos.x + '%';
        wrap.style.top = pos.y + '%';
        lb.className = 'trick-mat-tag';
        if (hi.winnerSeat === seat) wrap.classList.add('trick-mat-slot--win');
      } else if (np === 4) {
        const dir = ['s', 'w', 'n', 'e'][off];
        wrap.className = 'sb-trick-slot sb-tr-pos-' + dir;
        lb.className = 'sb-trick-tag';
        if (hi.winnerSeat === seat) wrap.classList.add('sb-trick-slot--win');
      } else {
        const pos = trickMatPct(off, np);
        wrap.className = 'trick-mat-slot';
        wrap.style.left = pos.x + '%';
        wrap.style.top = pos.y + '%';
        lb.className = 'trick-mat-tag';
        if (hi.winnerSeat === seat) wrap.classList.add('trick-mat-slot--win');
      }
      wrap.appendChild(lb);
      playmatEl.appendChild(wrap);
    });
  }

  function fillMetaBar(st) {
    if (!metaBar) return;
    const tr = st.trump || {};
    const ob =
      st.opening_bank_seat !== undefined && st.opening_bank_seat !== null
        ? Number(st.opening_bank_seat)
        : NaN;
    const stk = Number(st.declare_stakes ?? 0);
    const stkPart = stk > 0 ? `累扣分 ${stk}` : null;
    const obPart =
      Number.isFinite(ob) && st.phase === 'declare' ? `原位庄座${ob}（叫到者当庄先出；全过则原位庄红心）` : null;
    const curDeal = Number(st.deal_reveal_steps ?? 0);
    const totDeal = Number(st.deal_total_steps ?? 0);
    const dealPart =
      st.phase === 'declare' && Number.isFinite(totDeal) && totDeal > 0
        ? `发牌 ${Math.min(curDeal, totDeal)}/${totDeal}`
        : null;
    const parts = [
      `阶段 ${phaseLabelZh(st.phase)}`,
      dealPart,
      `庄 座${st.declarer_seat}`,
      `领出 座${st.leader}`,
      `主 ${tr.trump_suit == null ? '无主' : tr.trump_suit} · 级@${tr.level_rank}`,
      stkPart,
      obPart,
      `台面 A${st.teams?.A} / B${st.teams?.B}`,
      `已完墩 ${(st.completed_tricks || []).length}`,
    ].filter(Boolean);
    metaBar.textContent = parts.join(' · ');
  }

  function fillScoreBoard(st) {
    if (!scoreBoard) return;
    const th = st.defenders_threshold ?? (st.num_players === 6 ? 120 : 80);
    const dr = Number(st.defender_trick_points_running ?? 0);
    const kObj = st.kitty || {};
    let kittyBrief = `${escapeHtml(String(kObj.count ?? '—'))} 张`;
    if (st.phase === 'kitty') kittyBrief = `庄已拿底 · 待扣 <b>${escapeHtml(String(kObj.bury_needed ?? '—'))}</b> 张`;
    else if (kObj.status === 'buried') kittyBrief = `${escapeHtml(String(kObj.count ?? '—'))} 张（已埋）`;

    const turnLbl = st.phase === 'declare' ? '叫主' : st.phase === 'kitty' ? '埋底' : '出牌';
    const turnSeat =
      st.phase === 'declare' ? st.declare_to_act_seat : st.phase === 'kitty' ? st.bury_to_act_seat : st.to_act_seat;

    const hist = st.declare_history || [];
    const logBlock =
      hist.length > 0
        ? `<div class="declare-log muted small"><div class="lbl">叫牌记录</div><ol style="margin:6px 0 0;padding-left:1.1em">${hist
            .map((h) => `<li>${formatDeclareHistLine(h)}</li>`)
            .join('')}</ol></div>`
        : '';

    const teams = `<div class="sb-rows">
      <div class="sb-row"><span class="lbl">队伍 A · 级</span><b>${escapeHtml(String(st.teams?.A ?? '?'))}</b></div>
      <div class="sb-row"><span class="lbl">队伍 B · 级</span><b>${escapeHtml(String(st.teams?.B ?? '?'))}</b></div>
      <div class="sb-row"><span class="lbl">闲家墩分（累计）</span><b>${dr}</b> <span class="muted">/ 目标 ${th}</span></div>
      <div class="sb-row"><span class="lbl">底牌</span><span>${kittyBrief}</span></div>
      <div class="sb-row"><span class="lbl">${turnLbl}</span><span>轮到 座<b>${escapeHtml(String(turnSeat ?? '—'))}</b></span></div>
      <div class="sb-row"><span class="lbl">叫主累扣分</span><span><b>${escapeHtml(String(Number(st.declare_stakes ?? 0)))}</b></span></div>
    </div>${logBlock}`;
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
    const epoch = st.deal_epoch ?? 0;
    if (trickHistSyncedEpoch !== epoch) {
      trickHistSyncedEpoch = epoch;
      trickHistManual = false;
    }

    trickHistorySelect.innerHTML = '';
    const o0 = document.createElement('option');
    o0.value = 'cur';
    o0.textContent = '当前墩';
    trickHistorySelect.appendChild(o0);
    done.forEach((t, i) => {
      const o = document.createElement('option');
      const idx = t.index ?? i + 1;
      o.value = String(i);
      o.textContent = `第 ${idx} 墩 · ${t.trick_points} 分 · 胜 座 ${t.winner_seat}`;
      trickHistorySelect.appendChild(o);
    });

    const lastKey = done.length ? String(done.length - 1) : null;
    const prevOk = prev === 'cur' || (prev !== '' && done.some((_, i) => String(i) === prev));
    let pick;
    if (!trickHistManual) pick = lastKey !== null ? lastKey : 'cur';
    else pick = prevOk ? prev : lastKey !== null ? lastKey : 'cur';
    trickHistorySelect.value = pick;
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

  /** @param {Record<number, number>} handCounts */
  function pruneSelectedPlayIds(legalPlaysUnion, handCounts) {
    const next = [];
    const used = {};
    for (const cidRaw of selectedPlayIds) {
      const cid = cidKey(cidRaw);
      if (cid == null || !legalPlaysUnion.has(cid)) continue;
      const cap = handCounts[cid] || 0;
      used[cid] = (used[cid] || 0) + 1;
      if (used[cid] <= cap) next.push(cid);
    }
    selectedPlayIds = next;
  }

  function renderMyHand(st, myTurn, legalPlays, declareTurn, legalDeclare) {
    if (!myHandDock) return;
    const legalUnion = unionLegalTouchIds(legalPlays);
    const viewerNum = Number(st.viewer_seat);
    const mine = Number.isFinite(viewerNum) ? (st.hands || [])[viewerNum] : [];
    const handCounts = {};
    if (Array.isArray(mine)) {
      mine.forEach((c) => {
        const ck = cidKey(c.cid);
        if (ck == null) return;
        handCounts[ck] = (handCounts[ck] || 0) + 1;
      });
    }

    if (!myTurn) selectedPlayIds = [];
    else pruneSelectedPlayIds(legalUnion, handCounts);

    const epochKey = `${st.table_id}:${st.deal_epoch ?? 0}`;
    const tricking =
      (st.completed_tricks || []).length > 0 || ((st.current_trick || []).length > 0);
    if (dealingInProgress && tricking) {
      cancelDealAnimation();
      dealAnimConsumedKey = epochKey;
    }

    myHandDock.innerHTML = '';
    const title = document.createElement('div');
    title.className = 'my-hand-title';
    title.textContent = '你的手牌';
    myHandDock.appendChild(title);

    const bar = document.createElement('div');
    bar.className = 'my-play-bar my-play-bar--above-hand';
    const btnPlay = document.createElement('button');
    btnPlay.type = 'button';
    btnPlay.className = 'btn primary';
    btnPlay.textContent = '出牌';
    const hintSpan = document.createElement('span');
    hintSpan.className = 'muted small play-hint';
    bar.appendChild(btnPlay);
    bar.appendChild(hintSpan);
    myHandDock.appendChild(bar);

    const row = document.createElement('div');
    row.className = 'my-hand-row';
    myHandDock.appendChild(row);

    function applyHandSelectionHighlights() {
      const need = {};
      selectedPlayIds.forEach((id) => {
        need[id] = (need[id] || 0) + 1;
      });
      const seen = {};
      row.querySelectorAll('.card-face').forEach((x) => {
        const id = cidKey(x.dataset.pickCid);
        if (id == null) return;
        const n = need[id] || 0;
        seen[id] = (seen[id] || 0) + 1;
        x.classList.toggle('card-selected', n > 0 && seen[id] <= n);
      });
    }

    function updatePlayChrome() {
      const canAct = myTurn && !dealingInProgress;
      const matchIds = findMatchingLegalCardIds(legalPlays, selectedPlayIds);
      btnPlay.disabled = !canAct || matchIds == null;
      if (!myTurn) hintSpan.textContent = '';
      else if (dealingInProgress) hintSpan.textContent = '发牌中，请稍候…';
      else if (!selectedPlayIds.length) hintSpan.textContent = '点击手牌组成合法组合（单张/对子/三张/拖拉机），再点「出牌」';
      else if (matchIds == null) hintSpan.textContent = '当前选牌不构成合法组合，请增删手牌或重选';
      else hintSpan.textContent = `已匹配合法组合（${matchIds.length} 张），点「出牌」提交`;
    }

    if (!Array.isArray(mine)) {
      row.textContent = '（暂无手牌）';
      btnPlay.disabled = true;
      hintSpan.textContent = '';
      return;
    }

    if (!mine.length && st.phase === 'declare') {
      title.textContent = '叫主 · 发牌中…';
      btnPlay.disabled = true;
      btnPlay.style.display = 'none';
      hintSpan.textContent = '待发牌 · 仅能用已发到手中的牌参与叫主（与服务器同步）';
      row.textContent = '（尚未发到本手）';
      return;
    }

    if (!mine.length) {
      row.textContent = '（暂无手牌）';
      btnPlay.disabled = true;
      hintSpan.textContent = '';
      return;
    }

    const sorted = sortHandForReveal(mine, st);

    if (st.phase === 'kitty') {
      btnPlay.onclick = null;
      const buryNeed = Number(st.kitty?.bury_needed ?? 0);
      const burySeat = Number(st.bury_to_act_seat ?? NaN);
      const buryTurn = Number.isFinite(viewerNum) && Number.isFinite(burySeat) && viewerNum === burySeat;
      title.textContent = `埋底 · 庄家请将 ${buryNeed} 张扣回底牌`;
      btnPlay.textContent = '埋底';
      btnPlay.style.display = '';
      btnPlay.disabled = true;
      if (!buryTurn) selectedPlayIds = [];

      function updateBuryChrome() {
        const ok = buryTurn && selectedPlayIds.length === buryNeed && buryNeed > 0;
        btnPlay.disabled = !ok || dealingInProgress;
        if (!buryTurn) hintSpan.textContent = `等待 座${burySeat}（庄家）埋底 · 须 ${buryNeed} 张`;
        else if (!buryNeed) hintSpan.textContent = '';
        else
          hintSpan.textContent =
            selectedPlayIds.length === buryNeed
              ? `已选 ${buryNeed} 张，点「埋底」`
              : `点选手牌恰好 ${buryNeed} 张作为新底（已选 ${selectedPlayIds.length}/${buryNeed}）`;
      }

      function applyBuryHighlights() {
        const need = {};
        selectedPlayIds.forEach((id) => {
          need[id] = (need[id] || 0) + 1;
        });
        const seen = {};
        row.querySelectorAll('.card-face').forEach((x) => {
          const id = cidKey(x.dataset.pickCid);
          if (id == null) return;
          const n = need[id] || 0;
          seen[id] = (seen[id] || 0) + 1;
          x.classList.toggle('card-selected', n > 0 && seen[id] <= n);
        });
      }

      btnPlay.onclick = () => {
        if (dealingInProgress || !buryTurn || selectedPlayIds.length !== buryNeed) return;
        submitBury(selectedPlayIds.slice());
      };

      row.innerHTML = '';
      sorted.forEach((c) => {
        const el = document.createElement('div');
        const ck = cidKey(c.cid);
        el.className = 'card-face' + (buryTurn ? ' playable' : ' dim');
        el.dataset.pickCid = ck != null ? String(ck) : '';
        applyCardFace(el, c);
        el.title = (c.label || '') + ' · cid=' + c.cid;
        if (buryTurn && ck != null) {
          el.addEventListener('click', () => {
            if (dealingInProgress) return;
            const ix = selectedPlayIds.indexOf(ck);
            if (ix >= 0) selectedPlayIds.splice(ix, 1);
            else {
              if (selectedPlayIds.length >= buryNeed) return;
              selectedPlayIds.push(ck);
            }
            applyBuryHighlights();
            updateBuryChrome();
          });
        }
        row.appendChild(el);
      });
      applyBuryHighlights();
      updateBuryChrome();
      return;
    }

    if (st.phase === 'declare') {
      const ld = legalDeclare || [];
      title.textContent =
        '叫主 · 发牌中不按序叫/过 · 亮满后从领先者下家按序反主 · 无主须大王+小王';
      btnPlay.onclick = null;
      btnPlay.disabled = true;
      btnPlay.style.display = 'none';
      hintSpan.textContent = declareTurn
        ? ld.length > 1
          ? '点下方「过」或叫品；不须点手牌出牌'
          : '仅可「过」'
        : st.declare_turn_free_for_all
          ? '等待其他家过/叫（当前不发牌轮转）'
          : `等待他家 · 应门 座${st.declare_to_act_seat ?? '—'} `;

      const passBtn = document.createElement('button');
      passBtn.type = 'button';
      passBtn.className = 'btn primary tiny';
      passBtn.textContent = '过';
      passBtn.disabled = !declareTurn;
      passBtn.addEventListener('click', () => submitDeclare({ action: 'pass' }));
      bar.insertBefore(passBtn, hintSpan);

      const suitNames = { C: '♣ 梅', D: '♦ 方', H: '♥ 红', S: '♠ 黑' };
      function declarePayloadFor(opt) {
        if (!opt || opt.kind === 'pass') return null;
        if (opt.kind === 'bid_plain' || opt.kind === 'bid_suit')
          return { action: 'bid_plain', suit: opt.suit };
        if (opt.kind === 'bid_pair') return { action: 'bid_pair', suit: opt.suit };
        if (opt.kind === 'bid_nt') return { action: 'bid_nt' };
        return null;
      }
      function declareLabel(opt) {
        const sn = suitNames[opt.suit] || opt.suit || '';
        if (opt.kind === 'bid_plain' || opt.kind === 'bid_suit') return `${sn} 亮级`;
        if (opt.kind === 'bid_pair') return `${sn} 对级`;
        return '';
      }
      ld.forEach((opt) => {
        if (!opt || opt.kind === 'pass') return;
        const pay = declarePayloadFor(opt);
        if (!pay) return;
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn ghost tiny';
        b.textContent = pay.action === 'bid_nt' ? '无主' : declareLabel(opt);
        b.disabled = !declareTurn;
        b.addEventListener('click', () => submitDeclare(pay));
        bar.insertBefore(b, hintSpan);
      });

      row.innerHTML = '';
      sorted.forEach((c) => {
        const el = document.createElement('div');
        el.className = 'card-face dim';
        applyCardFace(el, c);
        el.title = (c.label || '') + ' · cid=' + c.cid;
        row.appendChild(el);
      });
      return;
    }

    btnPlay.style.display = '';

    btnPlay.onclick = () => {
      if (dealingInProgress || !myTurn) return;
      const matchIds = findMatchingLegalCardIds(legalPlays, selectedPlayIds);
      if (!matchIds) return;
      submitPlayCardIds(matchIds);
    };

    function wirePick(el, c) {
      const ck = cidKey(c.cid);
      if (ck == null) return;
      el.dataset.pickCid = String(ck);
      if (!(myTurn && legalUnion.has(ck))) return;
      el.addEventListener('click', () => {
        if (dealingInProgress) return;
        const i = selectedPlayIds.indexOf(ck);
        if (i >= 0) selectedPlayIds.splice(i, 1);
        else {
          const cur = selectedPlayIds.filter((x) => x === ck).length;
          if (cur >= (handCounts[ck] || 0)) return;
          selectedPlayIds.push(ck);
        }
        applyHandSelectionHighlights();
        updatePlayChrome();
      });
    }

    const shouldStagger =
      st.phase === 'play' && epochKey !== dealAnimConsumedKey && !tricking;

    if (shouldStagger) {
      cancelDealAnimation();
      dealingInProgress = true;
      dealOverlay?.classList.remove('hidden');
      selectedPlayIds = [];
      updatePlayChrome();
      sorted.forEach((c, i) => {
        const ck = cidKey(c.cid);
        const playable = myTurn && ck != null && legalUnion.has(ck);
        const el = document.createElement('div');
        el.className = 'card-face card-deal-pending' + (playable ? ' playable' : ' dim');
        applyCardFace(el, c);
        el.style.opacity = '0';
        el.title = (c.label || '') + ' · cid=' + c.cid;
        wirePick(el, c);
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
        updatePlayChrome();
      }, sorted.length * DEAL_STAGGER_MS + 120);
      dealTimers.push(fin);
    } else {
      sorted.forEach((c) => {
        const el = document.createElement('div');
        const ckDeal = cidKey(c.cid);
        el.className = 'card-face' + (myTurn && ckDeal != null && legalUnion.has(ckDeal) ? ' playable' : ' dim');
        applyCardFace(el, c);
        el.title = (c.label || '') + ' · cid=' + c.cid;
        wirePick(el, c);
        row.appendChild(el);
      });
      applyHandSelectionHighlights();
      updatePlayChrome();
    }
  }

  function renderState(st) {
    app.lastState = st;
    const np = st.num_players || app.np;
    app.np = np;
    tableSection?.classList.remove('hidden');
    gameShell?.classList.toggle('game-shell--6', np === 6);

    const playmat = ensureBoardLayout(st);
    fillMetaBar(st);
    fillScoreBoard(st);
    syncHistorySelect(st);
    paintTrickPlays(playmat, st.current_trick || [], st.viewer_seat, np, {});
    scheduleBoardFit();
    updateSeatActingHighlight(st);

    const legal = st.legal_plays || [];
    const viewerNum = Number(st.viewer_seat);
    const actNum = st.to_act_seat != null ? Number(st.to_act_seat) : NaN;
    const myTurn =
      st.phase === 'play' && Number.isFinite(viewerNum) && Number.isFinite(actNum) && viewerNum === actNum;

    const ld = st.legal_declare || [];
    const declareTurn =
      st.phase === 'declare' &&
      ld.length > 0 &&
      Number.isFinite(viewerNum) &&
      (st.declare_turn_free_for_all ||
        (st.declare_to_act_seat != null && Number(st.declare_to_act_seat) === viewerNum));

    renderMyHand(st, myTurn, legal, declareTurn, ld);

    if (st.phase === 'scored') {
      btnNext.classList.remove('hidden');
      const hs = st.hand_summary;
      summaryBox.classList.remove('hidden');
      summaryBox.innerHTML = hs
        ? `<strong>本副结束</strong><br/>闲家分: ${hs.defender_points_final}（墩上 ${hs.defender_points_tricks_only}，底牌奖 ${hs.kitty_bonus_to_defenders}${
            Number(hs.declare_stakes_bonus) > 0
              ? `，叫主累扣分奖 ${hs.declare_stakes_bonus}`
              : ''
          }）<br/><code>${escapeHtml(JSON.stringify(hs.level_change || {}))}</code>`
        : '已记分';
      cancelDealAnimation();
      dealAnimConsumedKey = '';
    } else {
      btnNext.classList.add('hidden');
      summaryBox.classList.add('hidden');
    }

    statusLine.textContent =
      st.phase === 'declare'
        ? (st.declare_turn_free_for_all
            ? `叫主 · 发牌不按序 · 你可操作则见下方按钮 · 你在 座${viewerNum}`
            : `叫主 · 应门 座${st.declare_to_act_seat ?? '—'} · 你在 座${viewerNum}`) +
          (declareTurn ? ' — 仅能用手上已发到牌 · 见下方记录' : '')
        : st.phase === 'kitty'
          ? `埋底 · 庄 座${st.bury_to_act_seat ?? '—'} 扣 ${st.kitty?.bury_needed ?? '—'} 张 · 你在 座${viewerNum}` +
            (Number(st.bury_to_act_seat) === viewerNum ? ' — 点选恰好张数后点「埋底」' : ' — 等待庄家埋底')
          : st.phase === 'play'
            ? `轮到 座${st.to_act_seat} · 你在 座${viewerNum}` +
              (myTurn
                ? dealingInProgress
                  ? ' — 发牌后可选手牌组成合法组合，再点出牌'
                  : ' — 多点组成合法组合后点「出牌」'
                : dealingInProgress
                  ? ' — 发牌中…'
                  : ' — 等待')
            : '本副已结束，可点「下一副」';
    eventLog.textContent = JSON.stringify(st, null, 2);
    if (st.phase === 'scored') cancelDealAdvanceChain();
    else scheduleDealAdvanceIfNeeded(st);
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

  function submitPlayCardIds(cardIds) {
    if (dealingInProgress) return;
    const st = app.lastState;
    const v = Number(st?.viewer_seat);
    const t = st?.to_act_seat != null ? Number(st.to_act_seat) : NaN;
    if (
      !st ||
      st.phase !== 'play' ||
      !Number.isFinite(v) ||
      !Number.isFinite(t) ||
      v !== t
    ) {
      selectedPlayIds = [];
      statusLine.textContent = '出牌已过时（请先同步状态）…';
      void fetchStateRest();
      return;
    }
    const ids = (cardIds || []).map((x) => Number(x)).filter((n) => !Number.isNaN(n));
    if (!ids.length) return;
    selectedPlayIds = [];
    if (app.ws && app.ws.readyState === 1) {
      app.ws.send(JSON.stringify({ type: 'action', card_ids: ids }));
      return;
    }
    void postAction(ids);
  }

  async function postDeclare(extra) {
    if (!app.tableId) return;
    const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/declare`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: tokenForSeat(app.seat), ...extra }),
    });
    const jd = await r.json().catch(() => null);
    if (r.ok && jd && jd.state) renderState(jd.state);
    else {
      if (!r.ok && r.status === 404 && (!jd || detailLooksLikeTableMissing(jd))) {
        abandonTableSessionBecauseMissing('叫主失败');
        return;
      }
      const det = jd && (jd.detail || jd.message);
      statusLine.textContent = `叫主失败: ${det ? JSON.stringify(det) : r.status}`;
    }
  }

  function submitDeclare(extra) {
    const st = app.lastState;
    const v = Number(st?.viewer_seat);
    const free = !!(st && st.declare_turn_free_for_all);
    const ld = (st && st.legal_declare) || [];
    const turnOk =
      st &&
      st.phase === 'declare' &&
      Number.isFinite(v) &&
      ld.length > 0 &&
      (free || (st.declare_to_act_seat != null && Number(st.declare_to_act_seat) === v));
    if (!turnOk) {
      statusLine.textContent = '叫主已过时…';
      void fetchStateRest();
      return;
    }
    const msg = { type: 'declare', action: extra.action };
    if (extra.suit != null && extra.suit !== '') msg.suit = extra.suit;
    if (app.ws && app.ws.readyState === 1) {
      app.ws.send(JSON.stringify(msg));
      return;
    }
    void postDeclare(extra);
  }

  async function postBury(cardIds) {
    if (!app.tableId) return;
    const ids = (cardIds || []).map((x) => Number(x)).filter((n) => !Number.isNaN(n));
    const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/bury`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: tokenForSeat(app.seat), card_ids: ids }),
    });
    const jd = await r.json().catch(() => null);
    if (r.ok && jd && jd.state) renderState(jd.state);
    else {
      if (!r.ok && r.status === 404 && (!jd || detailLooksLikeTableMissing(jd))) {
        abandonTableSessionBecauseMissing('埋底失败');
        return;
      }
      const det = jd && (jd.detail || jd.message);
      statusLine.textContent = `埋底失败: ${det ? JSON.stringify(det) : r.status}`;
    }
  }

  function submitBury(cardIds) {
    const st = app.lastState;
    const v = Number(st?.viewer_seat);
    const b = st && st.phase === 'kitty' && st.bury_to_act_seat != null ? Number(st.bury_to_act_seat) : NaN;
    if (!st || st.phase !== 'kitty' || !Number.isFinite(v) || !Number.isFinite(b) || v !== b) {
      statusLine.textContent = '埋底已过时…';
      void fetchStateRest();
      return;
    }
    const ids = (cardIds || []).map((x) => Number(x)).filter((n) => !Number.isNaN(n));
    if (!ids.length) return;
    if (app.ws && app.ws.readyState === 1) {
      app.ws.send(JSON.stringify({ type: 'bury', card_ids: ids }));
      return;
    }
    void postBury(ids);
  }

  async function postAction(cardIds) {
    if (!app.tableId) return;
    const ids = Array.isArray(cardIds) ? cardIds : [cardIds];
    const r = await fetch(`${API_BASE}/api/sheng/tables/${app.tableId}/actions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ token: tokenForSeat(app.seat), card_ids: ids }),
    });
    const body = await r.json().catch(() => null);
    if (r.ok && body && body.state) renderState(body.state);
    else if (!r.ok && r.status === 404 && (!body || detailLooksLikeTableMissing(body))) {
      abandonTableSessionBecauseMissing('出牌失败');
    }
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
      match_level_rank: 2,
    };
    if (seed !== null && !Number.isNaN(seed)) body.seed = seed;

    if (numPlayers === 6) {
      const vr = validateSixFriendCalls(2, 'create');
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
      if (!r.ok && r.status === 404 && (!data || detailLooksLikeTableMissing(data))) {
        abandonTableSessionBecauseMissing('下一副');
        return;
      }
      statusLine.textContent =
        'next_hand 失败: ' +
        (data && data.detail ? JSON.stringify(data.detail) : r.statusText);
      await fetchStateRest();
    }
  }

  function initBoardResize() {
    const host = boardResizeHost;
    const handle = boardResizeHandle;
    if (!host || !handle) return;

    function readSaved() {
      try {
        const v = parseInt(localStorage.getItem(STORAGE_BOARD_H), 10);
        return Number.isFinite(v) ? v : null;
      } catch {
        return null;
      }
    }

    const saved = readSaved();
    if (saved != null) {
      boardHeightPinned = true;
      applyBoardHostHeight(saved, { persist: true });
    }

    // Width resize (does not affect height).
    function readSavedSideW() {
      try {
        const v = parseInt(localStorage.getItem(STORAGE_SIDE_W), 10);
        return Number.isFinite(v) ? v : null;
      } catch {
        return null;
      }
    }

    function clampSideW(px) {
      const shell = gameShell;
      const full = shell ? shell.getBoundingClientRect().width : window.innerWidth;
      const min = 168;
      const max = Math.max(min + 40, Math.min(full * 0.4, 400));
      return Math.round(Math.min(max, Math.max(min, px)));
    }

    function applySideW(px, persist) {
      const shell = gameShell;
      if (!shell) return;
      const w = clampSideW(px);
      shell.style.setProperty('--sheng-side-w', `${w}px`);
      if (persist) {
        try {
          localStorage.setItem(STORAGE_SIDE_W, String(w));
        } catch (_) {}
      }
    }

    const savedSideW = readSavedSideW();
    if (savedSideW != null) applySideW(savedSideW, true);

    let drag = false;
    let startY = 0;
    let startH = 0;

    function onMove(e) {
      if (!drag) return;
      applyBoardHostHeight(startH + (e.clientY - startY), { persist: true });
      e.preventDefault();
    }

    function endDrag(e) {
      if (!drag) return;
      drag = false;
      document.body.classList.remove('board-resize-dragging');
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', endDrag);
      window.removeEventListener('pointercancel', endDrag);
      if (e && typeof handle.releasePointerCapture === 'function') {
        try {
          handle.releasePointerCapture(e.pointerId);
        } catch (_) {}
      }
    }

    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      drag = true;
      startY = e.clientY;
      startH = host.getBoundingClientRect().height;
      document.body.classList.add('board-resize-dragging');
      try {
        handle.setPointerCapture(e.pointerId);
      } catch (_) {}
      window.addEventListener('pointermove', onMove, { passive: false });
      window.addEventListener('pointerup', endDrag);
      window.addEventListener('pointercancel', endDrag);
      e.preventDefault();
    });

    // Horizontal handle: resize width only.
    if (boardResizeHandleX) {
      let dragX = false;
      let startX = 0;
      let startW = 0;

      function onMoveX(e) {
        if (!dragX) return;
        applySideW(startW + (e.clientX - startX), true);
        scheduleBoardFit();
        e.preventDefault();
      }

      function endDragX(e) {
        if (!dragX) return;
        dragX = false;
        document.body.classList.remove('board-resize-dragging-x');
        window.removeEventListener('pointermove', onMoveX);
        window.removeEventListener('pointerup', endDragX);
        window.removeEventListener('pointercancel', endDragX);
        if (e && typeof boardResizeHandleX.releasePointerCapture === 'function') {
          try {
            boardResizeHandleX.releasePointerCapture(e.pointerId);
          } catch (_) {}
        }
      }

      boardResizeHandleX.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        dragX = true;
        startX = e.clientX;
        const cur = gameShell?.style.getPropertyValue('--sheng-side-w').trim();
        startW = parseInt(cur, 10);
        if (!Number.isFinite(startW)) startW = 172;
        document.body.classList.add('board-resize-dragging-x');
        try {
          boardResizeHandleX.setPointerCapture(e.pointerId);
        } catch (_) {}
        window.addEventListener('pointermove', onMoveX, { passive: false });
        window.addEventListener('pointerup', endDragX);
        window.addEventListener('pointercancel', endDragX);
        e.preventDefault();
      });

      boardResizeHandleX.addEventListener('dblclick', () => {
        gameShell?.style.removeProperty('--sheng-side-w');
        try {
          localStorage.removeItem(STORAGE_SIDE_W);
        } catch (_) {}
        scheduleBoardFit();
      });

      boardResizeHandleX.addEventListener('keydown', (e) => {
        if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
        e.preventDefault();
        const raw = gameShell?.style.getPropertyValue('--sheng-side-w').trim();
        let base = parseInt(raw, 10);
        if (!Number.isFinite(base)) base = 172;
        const delta = e.key === 'ArrowRight' ? 24 : -24;
        applySideW(base + delta, true);
        scheduleBoardFit();
      });
    }

    handle.addEventListener('dblclick', () => {
      host.style.removeProperty('--sheng-board-h');
      try {
        localStorage.removeItem(STORAGE_BOARD_H);
      } catch (_) {}
      boardHeightPinned = false;
      scheduleBoardFit();
    });

    handle.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
      e.preventDefault();
      const raw = host.style.getPropertyValue('--sheng-board-h').trim();
      let base = parseInt(raw, 10);
      if (!Number.isFinite(base)) base = host.getBoundingClientRect().height;
      const delta = e.key === 'ArrowDown' ? 20 : -20;
      applyBoardHostHeight(base + delta, { persist: true });
      scheduleBoardFit();
    });

    window.addEventListener('resize', () => {
      const prop = host.style.getPropertyValue('--sheng-board-h').trim();
      if (prop) {
        const cur = parseInt(prop, 10);
        if (Number.isFinite(cur)) applyBoardHostHeight(cur, { persist: true });
      }
      scheduleBoardFit();
    });

    if (typeof ResizeObserver !== 'undefined') {
      const ro = new ResizeObserver(() => scheduleBoardFit());
      ro.observe(host);
      if (board) ro.observe(board);
    }
    scheduleBoardFit();
  }

  initBoardResize();

  trickHistorySelect?.addEventListener('change', () => {
    trickHistManual = true;
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
