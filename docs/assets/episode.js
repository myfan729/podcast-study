/* Episode page: synced transcript + study material. Plain JS, no build step. */
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (sec) => { sec = Math.max(0, Math.round(sec || 0)); const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60; return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0'); };
  const store = { get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
  const TYPE_KO = { idiom: '관용구', collocation: '연어', phrasal_verb: '구동사', discourse_marker: '담화표지', pattern: '패턴', vocabulary: '어휘' };

  // ---- theme -------------------------------------------------------------
  $('#themeBtn').addEventListener('click', () => {
    const cur = document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next; try { localStorage.setItem('theme', next); } catch (e) {}
  });

  const id = new URLSearchParams(location.search).get('id');
  if (!id) { $('#head').innerHTML = '<div class="err">에피소드 id가 없습니다. <a href="./">목록으로</a></div>'; return; }

  fetch('data/episodes/' + encodeURIComponent(id) + '.json', { cache: 'no-cache' })
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(init)
    .catch(err => { $('#head').innerHTML = `<div class="err">에피소드를 불러오지 못했습니다 (${esc(err.message)}). <a href="./">목록으로</a></div>`; });

  function init(ep) {
    const cues = ep.transcript.cues;
    let userScrolled = false;
    const segs = ep.transcript.segments;
    const study = ep.study || {};
    const tr = study.translations || {};
    const audio = $('#audio');
    document.title = ep.title + ' · Podcast Study';

    // ---- header ----------------------------------------------------------
    const d = new Date(ep.published_at);
    $('#head').innerHTML = `
      <div class="meta"><span class="chip"><span class="dot" style="--show:${esc(ep.show.color)}"></span>${esc(ep.show.name)}</span>
        <span>${esc(d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }))}</span>
        <span>${fmt(ep.duration_sec)}</span>
        ${study.difficulty?.cefr ? `<span class="badge" title="${esc(study.difficulty.note_ko || '')}">${esc(study.difficulty.cefr)}</span>` : ''}
        ${ep.demo ? '<span class="badge demo">DEMO</span>' : ''}${study.mock ? '<span class="badge mock">mock</span>' : ''}</div>
      <h1>${esc(ep.title)}</h1>
      ${study.one_liner_ko ? `<p class="one">${esc(study.one_liner_ko)}</p>` : ''}`;
    if (ep.demo) $('#demoNotice').hidden = false;
    if (study.mock) $('#mockNotice').hidden = false;
    if (ep.episode_url) { const a = $('#srcLink'); a.href = ep.episode_url; a.hidden = false; }
    const st = ep.transcript.stats || {};
    $('#tstats').textContent = `${(st.words || 0).toLocaleString()} words · ${segs.length} paragraphs · ${study.expressions?.length || 0} expressions`;

    // ---- transcript ------------------------------------------------------
    const tEl = $('#transcript');
    const shadowBy = Object.fromEntries((study.shadowing || []).map(s => [s.segment_id, s.reason_ko]));
    const cueEls = new Array(cues.length);
    const segEls = {};
    segs.forEach(seg => {
      const art = document.createElement('article'); art.className = 'seg'; art.id = seg.id; art.dataset.start = seg.start; art.dataset.end = seg.end;
      const who = document.createElement('div'); who.className = 'who';
      who.innerHTML = `<span class="t">${fmt(seg.start)}</span>${seg.display_speaker ? `<span class="name">${esc(seg.display_speaker)}</span>` : ''}` +
        (shadowBy[seg.id] ? `<span class="shadow" title="${esc(shadowBy[seg.id])}">섀도잉 추천</span>` : '') +
        `<button class="loop" type="button" aria-pressed="false" title="이 문단 반복">반복</button>`;
      const p = document.createElement('p');
      for (let i = seg.cue_from; i <= seg.cue_to; i++) {
        const c = cues[i]; const span = document.createElement('span'); span.className = 'cue'; span.dataset.i = i; span.textContent = c.t; cueEls[i] = span;
        p.appendChild(span); if (i < seg.cue_to) p.appendChild(document.createTextNode(' '));
      }
      art.appendChild(who); art.appendChild(p);
      if (shadowBy[seg.id]) { const why = document.createElement('div'); why.className = 'ko'; why.style.display = 'block'; why.style.color = 'var(--ink-3)'; why.textContent = shadowBy[seg.id]; art.appendChild(why); }
      if (tr[seg.id]) { const ko = document.createElement('div'); ko.className = 'ko'; ko.textContent = tr[seg.id]; art.appendChild(ko); }
      tEl.appendChild(art); segEls[seg.id] = art;
      who.querySelector('.loop').addEventListener('click', (e) => { toggleLoop(seg, e.currentTarget); });
    });
    if (!Object.keys(tr).length) $('#swKo').hidden = true;

    // expression highlights (quote may cross cue boundaries)
    (study.expressions || []).forEach((ex, idx) => {
      if (!ex.quote || ex.quote_unmatched) return;
      const seg = segs.find(s => s.id === ex.segment_id); if (!seg) return;
      const parts = []; let joined = ''; for (let i = seg.cue_from; i <= seg.cue_to; i++) { parts.push({ i, off: joined.length, len: cues[i].t.length }); joined += cues[i].t + (i < seg.cue_to ? ' ' : ''); }
      const at = joined.toLowerCase().indexOf(ex.quote.toLowerCase()); if (at < 0) return;
      const end = at + ex.quote.length;
      parts.forEach(pt => {
        const a = Math.max(at, pt.off), b = Math.min(end, pt.off + pt.len); if (a >= b) return;
        const span = cueEls[pt.i]; const text = cues[pt.i].t; const la = a - pt.off, lb = b - pt.off;
        span.textContent = ''; if (la > 0) span.appendChild(document.createTextNode(text.slice(0, la)));
        const m = document.createElement('mark'); m.className = 'hl'; m.dataset.ex = idx; m.textContent = text.slice(la, lb); m.title = ex.meaning_ko || ''; span.appendChild(m);
        if (lb < text.length) span.appendChild(document.createTextNode(text.slice(lb)));
      });
    });
    tEl.addEventListener('click', (e) => {
      const mark = e.target.closest('mark.hl');
      if (mark && !tEl.classList.contains('no-hl')) { openSheet(+mark.dataset.ex); e.stopPropagation(); return; }
      const cue = e.target.closest('.cue'); if (!cue) return;
      seekTo(cues[+cue.dataset.i].s, true);
    });

    // ---- rail panels -----------------------------------------------------
    const segById = Object.fromEntries(segs.map(s => [s.id, s]));
    $('#panel-summary').innerHTML = `
      <div class="card"><h3>핵심 요약</h3><ul>${(study.summary_ko || []).map(b => `<li>${esc(b)}</li>`).join('')}</ul></div>
      ${study.summary_en ? `<div class="card"><h3>In my own words<small>소리 내어 다시 말해보기</small></h3><p class="en">${esc(study.summary_en)}</p></div>` : ''}
      ${study.chapters?.length ? `<div class="card"><h3>챕터</h3><ul class="chapters">${study.chapters.map(c => { const s = segById[c.segment_id]; return `<li data-t="${s ? s.start : 0}"><span class="t">${fmt(s ? s.start : 0)}</span><span><span class="en">${esc(c.title_en)}</span><br><span class="ko">${esc(c.title_ko)}</span></span></li>`; }).join('')}</ul></div>` : ''}
      ${study.vocab?.length ? `<div class="card"><h3>단어<small>${study.vocab.length}</small></h3><ul class="vocab">${study.vocab.map(v => `<li><span><b>${esc(v.word)}</b><i>${esc(v.pos)}</i></span><span>${esc(v.meaning_ko)}<br><span class="ex">${esc(v.example)}</span></span></li>`).join('')}</ul></div>` : ''}
      ${study.difficulty?.note_ko ? `<div class="card"><h3>난이도 ${esc(study.difficulty.cefr || '')}</h3><p>${esc(study.difficulty.note_ko)}</p></div>` : ''}
      ${study.model ? `<p class="foot" style="margin:4px 2px">생성: ${esc(study.model)}${study.generated_at ? ' · ' + new Date(study.generated_at).toLocaleString('ko-KR') : ''}</p>` : ''}`;
    $$('#panel-summary .chapters li').forEach(li => li.addEventListener('click', () => seekTo(+li.dataset.t, true)));

    $('#panel-expr').innerHTML = `<div class="card">` + (study.expressions || []).map((ex, i) => exprHTML(ex, i, true)).join('') + `</div>`;
    $('#panel-expr').addEventListener('click', (e) => { const b = e.target.closest('.jump'); if (b) seekTo(+b.dataset.t, true); });

    const disc = study.discussion || {};
    const qs = [...(disc.warmup || []).map(q => ({ ...q, kind: 'warmup' })), ...(disc.opinion || []).map(q => ({ ...q, kind: 'opinion' })), ...(disc.debate || []).map(q => ({ ...q, kind: 'debate' }))];
    $('#panel-talk').innerHTML = `
      <div class="card"><h3>오늘의 질문<small>랜덤</small></h3><div id="randomQ" class="q" style="border:0;padding:0"><span style="color:var(--ink-3)">버튼을 누르면 아래 질문 중 하나를 뽑습니다.</span></div>
        <div class="timer"><button type="button" id="pickQ">질문 뽑기</button><div class="row2"><span class="clock" id="clock">0:00</span><span style="font-size:12.5px;color:var(--ink-3)">말하기 타이머</span><button type="button" data-min="1">1분</button><button type="button" data-min="2">2분</button><button type="button" data-min="3">3분</button><button type="button" id="tStop">정지</button></div></div></div>
      ${disc.warmup?.length ? `<div class="card"><h3>Warm-up<small>내용 확인</small></h3>${disc.warmup.map(q => `<div class="q"><div class="en">${esc(q.q)}</div><div class="hint">${esc(q.hint_ko)}</div></div>`).join('')}</div>` : ''}
      ${disc.opinion?.length ? `<div class="card"><h3>Your take<small>의견</small></h3>${disc.opinion.map(q => `<div class="q"><div class="en">${esc(q.q)}</div><div class="hint">${esc(q.hint_ko)}</div></div>`).join('')}</div>` : ''}
      ${disc.debate?.length ? `<div class="card"><h3>Debate<small>양쪽 다 말해보기</small></h3>${disc.debate.map(q => `<div class="q"><div class="en">${esc(q.q)}</div><div class="sides"><div><b>For</b>${esc(q.for)}</div><div><b>Against</b>${esc(q.against)}</div></div></div>`).join('')}</div>` : ''}
      ${disc.roleplay ? `<div class="card"><h3>Role-play</h3><div class="role"><p>${esc(disc.roleplay.scenario)}</p><div><b>You</b> · ${esc(disc.roleplay.your_role)}</div><div><b>Partner</b> · ${esc(disc.roleplay.partner_role)}</div><ul>${(disc.roleplay.goals || []).map(g => `<li>${esc(g)}</li>`).join('')}</ul></div></div>` : ''}
      ${disc.useful_phrases?.length ? `<div class="card"><h3>Useful phrases</h3><ul class="phr">${disc.useful_phrases.map(p => `<li><span class="en">${esc(p.phrase)}</span><span class="ko">${esc(p.ko)}</span></li>`).join('')}</ul></div>` : ''}`;
    $('#pickQ')?.addEventListener('click', () => {
      if (!qs.length) return; const q = qs[Math.floor(Math.random() * qs.length)];
      $('#randomQ').innerHTML = `<div class="en">${esc(q.q)}</div>` + (q.hint_ko ? `<div class="hint">${esc(q.hint_ko)}</div>` : '') + (q.kind === 'debate' ? `<div class="sides"><div><b>For</b>${esc(q.for)}</div><div><b>Against</b>${esc(q.against)}</div></div>` : '');
    });
    // speaking timer
    let tTimer = null, tStart = 0, tTarget = 0;
    const tick = () => { const s = Math.floor((Date.now() - tStart) / 1000); const c = $('#clock'); c.textContent = fmt(s); c.classList.toggle('over', tTarget && s >= tTarget); };
    $$('#panel-talk .timer button[data-min]').forEach(b => b.addEventListener('click', () => { clearInterval(tTimer); tStart = Date.now(); tTarget = +b.dataset.min * 60; $$('#panel-talk .timer button').forEach(x => x.classList.remove('on')); b.classList.add('on'); tick(); tTimer = setInterval(tick, 500); }));
    $('#tStop')?.addEventListener('click', () => { clearInterval(tTimer); tTimer = null; $$('#panel-talk .timer button').forEach(x => x.classList.remove('on')); });

    function exprHTML(ex, i, withJump) {
      const seg = segById[ex.segment_id]; const t = seg ? seg.start : 0;
      const quoteHTML = ex.quote && seg ? esc(seg.text).replace(new RegExp(esc(ex.quote).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i'), m => `<mark>${m}</mark>`) : '';
      return `<div class="ex" id="ex-${i}"><div class="head"><span class="expr">${esc(ex.expression)}</span><span class="type">${esc(TYPE_KO[ex.type] || ex.type)}</span>${withJump ? `<button class="jump" type="button" data-t="${t}" title="이 부분 듣기">▶ ${fmt(t)}</button>` : ''}</div>
        <p class="meaning">${esc(ex.meaning_ko)}</p><p class="nuance">${esc(ex.nuance_ko)}</p>
        ${quoteHTML ? `<p class="quote">“${quoteHTML}”</p>` : ''}
        <details><summary>예문 ${ex.examples?.length || 0} · 비슷한 표현 ${ex.similar?.length || 0}</summary>
          <ul class="examples">${(ex.examples || []).map(e => `<li>${esc(e)}</li>`).join('')}</ul>
          <ul class="similar">${(ex.similar || []).map(s => `<li><b>${esc(s.expression)}</b> — <span>${esc(s.example)}</span></li>`).join('')}</ul></details></div>`;
    }

    // ---- bottom sheet ------------------------------------------------------
    function openSheet(i) {
      const ex = study.expressions[i]; if (!ex) return;
      const seg = segById[ex.segment_id];
      $('#bsBody').innerHTML = exprHTML(ex, i, false).replace('<details>', '<details open>') +
        `<div style="display:flex;gap:8px;margin-top:10px"><button class="pbtn" type="button" id="bsPlay">▶ 이 문장 듣기</button><button class="pbtn" type="button" id="bsGo">표현 탭에서 보기</button></div>`;
      $('#bsheet').classList.add('on'); $('#scrim').classList.add('on');
      $('#bsPlay').addEventListener('click', () => { if (seg) seekTo(seg.start, true); closeSheet(); });
      $('#bsGo').addEventListener('click', () => { closeSheet(); setView('expr'); setTimeout(() => $('#ex-' + i)?.scrollIntoView({ block: 'start', behavior: 'smooth' }), 50); });
    }
    function closeSheet() { $('#bsheet').classList.remove('on'); $('#scrim').classList.remove('on'); }
    $('#bsClose').addEventListener('click', closeSheet); $('#scrim').addEventListener('click', closeSheet);

    // ---- views (tabs) ------------------------------------------------------
    let view = 'transcript', railView = 'summary';
    const isMobile = () => matchMedia('(max-width: 979px)').matches;
    function setView(v) {
      const mobile = isMobile();
      if (v !== 'transcript') railView = v;
      view = mobile ? v : 'transcript';   // on desktop the transcript is always on screen
      $('#main').hidden = mobile && view !== 'transcript';
      $('#rail').hidden = mobile && view === 'transcript';
      ['summary', 'expr', 'talk'].forEach(k => { const on = (mobile ? view : railView) === k; $('#panel-' + k).classList.toggle('on', on); $('#panel-' + k).classList.toggle('on-mobile', on); });
      $$('#mtabs [role=tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.view === view)));
      $$('#rtabs [role=tab]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.view === railView)));
      if (view !== 'transcript') { userScrolled = false; $('#repill').classList.remove('on'); }
      if (mobile && view !== 'transcript') window.scrollTo({ top: 0 });
    }
    $$('#mtabs [role=tab]').forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));
    $$('#rtabs [role=tab]').forEach(b => b.addEventListener('click', () => setView(b.dataset.view)));
    matchMedia('(max-width: 979px)').addEventListener('change', () => setView(isMobile() ? view : 'transcript'));
    setView('transcript');

    // ---- switches ----------------------------------------------------------
    const prefs = store.get('prefs', { hl: true, ko: false, auto: true, speed: 1 });
    const applyPrefs = () => {
      tEl.classList.toggle('no-hl', !prefs.hl); tEl.classList.toggle('show-ko', !!prefs.ko);
      $('#swHl').setAttribute('aria-pressed', String(!!prefs.hl)); $('#swKo').setAttribute('aria-pressed', String(!!prefs.ko)); $('#swAuto').setAttribute('aria-pressed', String(!!prefs.auto));
      audio.playbackRate = prefs.speed || 1; $('#speed').textContent = (prefs.speed || 1).toFixed(1) + '×';
      store.set('prefs', prefs);
    };
    $('#swHl').addEventListener('click', () => { prefs.hl = !prefs.hl; applyPrefs(); });
    $('#swKo').addEventListener('click', () => { prefs.ko = !prefs.ko; applyPrefs(); });
    $('#swAuto').addEventListener('click', () => { prefs.auto = !prefs.auto; userScrolled = false; $('#repill').classList.remove('on'); applyPrefs(); if (prefs.auto) scrollToActive(true); });
    applyPrefs();

    // ---- audio -------------------------------------------------------------
    audio.src = ep.audio_url; $('#player').hidden = false;
    const prog = store.get('prog:' + ep.id, null);
    if (prog && prog.pos > 20 && prog.pos < (ep.duration_sec || 1e9) - 30) audio.currentTime = prog.pos;
    audio.addEventListener('loadedmetadata', () => { $('#tDur').textContent = fmt(audio.duration); if (prog && prog.pos > 20 && audio.currentTime < 1) audio.currentTime = prog.pos; });
    audio.addEventListener('error', () => { $('#nowLine').textContent = '음원을 불러올 수 없습니다'; $('#nowLine').style.display = 'block'; });
    $('#tDur').textContent = fmt(ep.duration_sec);

    const setPlayIcon = () => { $('#icoPlay').classList.toggle('hide', !audio.paused); $('#icoPause').classList.toggle('hide', audio.paused); $('#play').setAttribute('aria-label', audio.paused ? '재생 (Space)' : '일시정지 (Space)'); };
    $('#play').addEventListener('click', () => { audio.paused ? audio.play() : audio.pause(); });
    audio.addEventListener('play', setPlayIcon); audio.addEventListener('pause', () => { setPlayIcon(); saveProgress(); });
    $('#back').addEventListener('click', () => seekTo(audio.currentTime - 5));
    $('#fwd').addEventListener('click', () => seekTo(audio.currentTime + 5));
    const SPEEDS = [0.8, 1, 1.2, 1.5];
    $('#speed').addEventListener('click', () => { prefs.speed = SPEEDS[(SPEEDS.indexOf(prefs.speed || 1) + 1) % SPEEDS.length]; applyPrefs(); });

    const seek = $('#seek'); let seeking = false;
    seek.addEventListener('input', () => { seeking = true; $('#tCur').textContent = fmt(seek.value / 1000 * (audio.duration || ep.duration_sec)); });
    seek.addEventListener('change', () => { seeking = false; seekTo(seek.value / 1000 * (audio.duration || ep.duration_sec), false); });

    function seekTo(t, play) {
      audio.currentTime = Math.max(0, Math.min(t, (audio.duration || ep.duration_sec || t)));
      userScrolled = false; $('#repill').classList.remove('on');
      if (play && audio.paused) audio.play().catch(() => {});
      update(true);
    }

    // loop a paragraph
    let loopSeg = null;
    function toggleLoop(seg, btn) {
      const on = loopSeg && loopSeg.id === seg.id;
      $$('.seg .loop[aria-pressed=true]').forEach(b => b.setAttribute('aria-pressed', 'false'));
      loopSeg = on ? null : seg; $('#loop').setAttribute('aria-pressed', String(!!loopSeg)); $('#loop').textContent = loopSeg ? '반복 중' : '반복';
      if (loopSeg) { if (btn) btn.setAttribute('aria-pressed', 'true'); seekTo(seg.start, true); }
    }
    $('#loop').addEventListener('click', () => { const seg = segs.find(s => s.id === activeSegId) || segs[0]; toggleLoop(seg, segEls[seg.id]?.querySelector('.loop')); });

    // ---- sync ------------------------------------------------------------
    let activeIdx = -1, activeSegId = null, progScroll = 0, lastSave = 0;
    const starts = cues.map(c => c.s);
    const findCue = (t) => { let lo = 0, hi = starts.length - 1, ans = -1; while (lo <= hi) { const mid = (lo + hi) >> 1; if (starts[mid] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1; } return ans; };
    function update(force) {
      const t = audio.currentTime;
      if (!seeking) { seek.value = Math.round(t / (audio.duration || ep.duration_sec || 1) * 1000); $('#tCur').textContent = fmt(t); }
      if (loopSeg && t >= loopSeg.end - 0.05) { audio.currentTime = loopSeg.start; return; }
      const i = findCue(t);
      if (i !== activeIdx || force) {
        if (activeIdx >= 0 && cueEls[activeIdx]) cueEls[activeIdx].classList.remove('active');
        activeIdx = i;
        if (i >= 0) {
          cueEls[i].classList.add('active'); $('#nowLine').textContent = cues[i].t;
          const segEl = cueEls[i].closest('.seg');
          if (segEl && segEl.id !== activeSegId) { if (activeSegId) segEls[activeSegId]?.classList.remove('now'); segEl.classList.add('now'); activeSegId = segEl.id; }
          if (prefs.auto && !userScrolled && view === 'transcript') scrollToActive(false);
        }
      }
      if (Date.now() - lastSave > 5000) saveProgress();
    }
    function scrollToActive(immediate) {
      const el = activeIdx >= 0 ? cueEls[activeIdx] : null; if (!el) return;
      const r = el.getBoundingClientRect(); const target = window.innerHeight * 0.38;
      if (!immediate && Math.abs(r.top - target) < 40) return;
      progScroll = Date.now();
      window.scrollTo({ top: window.scrollY + r.top - target, behavior: immediate ? 'auto' : 'smooth' });
    }
    function saveProgress() {
      lastSave = Date.now(); const dur = audio.duration || ep.duration_sec || 0;
      const done = dur && audio.currentTime > dur * 0.9;
      store.set('prog:' + ep.id, { pos: Math.floor(audio.currentTime), done: done || (prog && prog.done) || false, at: Date.now() });
    }
    audio.addEventListener('timeupdate', () => update(false));
    audio.addEventListener('ended', () => { saveProgress(); setPlayIcon(); });
    update(true);

    // user scroll detection → pause auto-scroll until the pill is tapped
    let lastY = window.scrollY;
    window.addEventListener('scroll', () => {
      if (Date.now() - progScroll < 900) { lastY = window.scrollY; return; }
      if (Math.abs(window.scrollY - lastY) > 30 && !audio.paused && prefs.auto && view === 'transcript') { userScrolled = true; $('#repill').classList.add('on'); }
      lastY = window.scrollY;
    }, { passive: true });
    $('#repill').addEventListener('click', () => { userScrolled = false; $('#repill').classList.remove('on'); scrollToActive(false); });

    // keyboard
    document.addEventListener('keydown', (e) => {
      if (e.target.matches('input, textarea, select') || e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key;
      if (k === ' ') { e.preventDefault(); audio.paused ? audio.play() : audio.pause(); }
      else if (k === 'ArrowLeft') { e.preventDefault(); seekTo(audio.currentTime - 5); }
      else if (k === 'ArrowRight') { e.preventDefault(); seekTo(audio.currentTime + 5); }
      else if (k === '[') { prefs.speed = SPEEDS[Math.max(0, SPEEDS.indexOf(prefs.speed || 1) - 1)]; applyPrefs(); }
      else if (k === ']') { prefs.speed = SPEEDS[Math.min(SPEEDS.length - 1, SPEEDS.indexOf(prefs.speed || 1) + 1)]; applyPrefs(); }
      else if (k === 'l' || k === 'L') $('#loop').click();
      else if (k === 't' || k === 'T') $('#swKo').click();
      else if (k === 'h' || k === 'H') $('#swHl').click();
      else if (k === 'a' || k === 'A') $('#swAuto').click();
      else if (k === 'Escape') closeSheet();
    });

    // lock-screen controls
    if ('mediaSession' in navigator) {
      try {
        navigator.mediaSession.metadata = new MediaMetadata({ title: ep.title, artist: ep.show.name, album: 'Podcast Study', artwork: ep.image_url ? [{ src: ep.image_url }] : [] });
        navigator.mediaSession.setActionHandler('play', () => audio.play()); navigator.mediaSession.setActionHandler('pause', () => audio.pause());
        navigator.mediaSession.setActionHandler('seekbackward', () => seekTo(audio.currentTime - 5)); navigator.mediaSession.setActionHandler('seekforward', () => seekTo(audio.currentTime + 5));
      } catch (e) {}
    }
  }
})();
