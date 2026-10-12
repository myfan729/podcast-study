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

  Promise.all([
    fetch('data/episodes/' + encodeURIComponent(id) + '.json', { cache: 'no-cache' }).then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }),
    fetch('data/sync/' + encodeURIComponent(id) + '.json', { cache: 'no-cache' }).then(r => r.ok ? r.json() : null).catch(() => null),
  ]).then(([ep, sync]) => { ep.sync = sync; return init(ep); })
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
      const c = cues[+cue.dataset.i];
      if (syncMode) { const guess = audio.currentTime - REACTION; addAnchor(c.s, guess); setSyncMode(false); showToast('싱크 맞춤: ' + fmt(c.s) + ' 문장'); snapAnchor(c.s, guess); return; }
      seekTo(toAudio(c.s), true);
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
    $$('#panel-summary .chapters li').forEach(li => li.addEventListener('click', () => seekTo(toAudio(+li.dataset.t), true)));

    $('#panel-expr').innerHTML = `<div class="card">` + (study.expressions || []).map((ex, i) => exprHTML(ex, i, true)).join('') + `</div>`;
    $('#panel-expr').addEventListener('click', (e) => { const b = e.target.closest('.jump'); if (b) seekTo(toAudio(+b.dataset.t), true); });

    // (회화/discussion panel removed from the UI for now; study.discussion is still generated and stored)

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
      $('#bsPlay').addEventListener('click', () => { if (seg) seekTo(toAudio(seg.start), true); closeSheet(); });
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
      ['summary', 'expr'].forEach(k => { const on = (mobile ? view : railView) === k; $('#panel-' + k).classList.toggle('on', on); $('#panel-' + k).classList.toggle('on-mobile', on); });
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
    $('#player').hidden = false;
    const srcUrl = ep.demo ? ep.audio_url : (ep.audio_url_original || ep.audio_url);
    const hasRefs = !!(ep.sync && window.PodSync && ep.sync.refs && ep.sync.refs.length);
    // fixed: the file has no inserted ads and is identical for everyone (e.g. BBC's programme download);
    // cue times are already on its clock, so nothing needs aligning — the fingerprint only confirms it.
    const fixedSync = !!((ep.sync && ep.sync.fixed) || (ep.audio_meta && ep.audio_meta.fixed));
    let wantPlay = false, blobUrl = null, syncBlob = null, syncIndex = null;
    const ua = navigator.userAgent;
    const webkitOnly = /AppleWebKit/.test(ua) && (/iPhone|iPad|iPod/.test(ua) || !/Chrome|Chromium|Edg|OPR|Firefox/.test(ua));
    const needsPcm = webkitOnly || new URLSearchParams(location.search).has('pcm');
    // phase: none | downloading | aligning | auto | fixed | failed | stream | manual
    const sync = { phase: hasRefs ? 'downloading' : (fixedSync ? 'fixed' : 'none'), report: null, error: null, snaps: [] };
    function saveReport() {
      sync.saved = new Date().toISOString();
      store.set('syncrep:' + ep.id, { phase: sync.phase, error: sync.error, report: sync.report, pcm: sync.pcm || null, snaps: sync.snaps.slice(-5), anchors, ua: navigator.userAgent, at: sync.saved });
    }
    if (hasRefs) {
      // Download the stream once (counted by the publisher like any podcast app), play it from memory,
      // and find this download's ad breaks automatically.
      $('#play').disabled = true; $('#play').classList.add('busy');
      $('#nowLine').style.display = 'block'; $('#nowLine').textContent = '음원 받는 중…';
      PodSync.download(srcUrl, (got, total) => { $('#nowLine').textContent = total ? `음원 받는 중 ${Math.round(got / total * 100)}% (${(total / 1048576).toFixed(0)} MB)` : `음원 받는 중 ${(got / 1048576).toFixed(1)} MB`; })
        .then(async (blob) => {
          syncBlob = blob;
          if (needsPcm) {
            // Safari/iOS: VBR MP3 playback time drifts seconds from the sound; play uncompressed audio instead
            $('#nowLine').textContent = 'iPhone용 변환 중…';
            try { const wav = await PodSync.toWav(blob, 22050); blobUrl = URL.createObjectURL(wav.blob); sync.pcm = `wav ${wav.sr} Hz ${(wav.blob.size / 1048576).toFixed(0)} MB`; }
            catch (e) { console.warn('wav conversion failed', e); sync.pcm = 'failed: ' + (e && e.message || e); }
          }
          if (!blobUrl) blobUrl = URL.createObjectURL(blob);
          audio.src = blobUrl;
          $('#play').disabled = false; $('#play').classList.remove('busy');
          if (wantPlay) audio.play().catch(() => {});
          sync.phase = 'aligning'; renderSyncState();
          try {
            const res = await PodSync.align(blob, ep.sync, (s) => { if (!fixedSync) $('#nowLine').textContent = s; }, { slack: fixedSync ? 30 : 0 });
            sync.report = res.report; syncIndex = res.index;
            if (fixedSync) {
              // only move away from the file's own clock on a strong match that disagrees with it (file replaced)
              const r = res.report.refs.find(x => x.ok);
              if (r && r.ber < 0.2 && r.second - r.ber > 0.1 && Math.abs(r.offset) > 0.7) {
                anchors = [{ c: r.c, a: r.a }]; store.set('sync:' + ep.id, anchors);
                sync.phase = 'auto'; showToast(`음원이 바뀌어 싱크를 ${r.offset > 0 ? '+' : '−'}${Math.abs(r.offset).toFixed(1)}초 맞췄습니다`);
              } else {
                sync.phase = 'fixed';
              }
            } else if (res.anchors.length) {
              anchors = res.anchors.map(x => ({ c: x.c, a: x.a })); store.set('sync:' + ep.id, anchors);
              sync.phase = 'auto'; dismissedPrompt = null;
              showToast(res.report.adTotal < 60 ? '자동 싱크 완료' : `자동 싱크 완료 · 광고 약 ${(res.report.adTotal / 60).toFixed(1)}분 건너뜀`);
            } else {
              sync.phase = 'failed'; sync.error = 'no reference matched';
              showToast('자동 싱크 실패 — 첫 문장이 들리면 눌러 주세요');
            }
            console.log('sync report ' + JSON.stringify(res.report));
          } catch (e) {
            console.warn('auto-sync failed', e); sync.phase = fixedSync ? 'fixed' : 'failed'; sync.error = String(e && e.message || e);
            if (!fixedSync) showToast('자동 싱크 실패 — 첫 문장이 들리면 눌러 주세요');
          }
          saveReport(); renderSyncState(); $('#nowLine').style.display = ''; update(true);
        })
        .catch((e) => {
          console.warn('download failed, streaming instead', e); audio.src = srcUrl; sync.phase = fixedSync ? 'fixed' : 'stream'; sync.error = String(e && e.message || e); saveReport();
          $('#play').disabled = false; $('#play').classList.remove('busy'); $('#nowLine').style.display = ''; renderSyncState(); update(true); if (wantPlay) audio.play().catch(() => {});
        });
    } else {
      audio.src = ep.audio_url;
    }
    const setPlayerH = () => document.documentElement.style.setProperty('--player-h', $('#player').offsetHeight + 'px');
    if ('ResizeObserver' in window) new ResizeObserver(setPlayerH).observe($('#player')); setPlayerH();
    const prog = store.get('prog:' + ep.id, null);
    if (prog && prog.pos > 20 && prog.pos < (ep.duration_sec || 1e9) - 30) audio.currentTime = prog.pos;
    audio.addEventListener('loadedmetadata', () => { $('#tDur').textContent = fmt(audio.duration); if (prog && prog.pos > 20 && audio.currentTime < 1) audio.currentTime = prog.pos; });
    audio.addEventListener('error', () => { $('#nowLine').textContent = '음원을 불러올 수 없습니다'; $('#nowLine').style.display = 'block'; });
    $('#tDur').textContent = fmt(ep.duration_sec);

    const setPlayIcon = () => { $('#icoPlay').classList.toggle('hide', !audio.paused); $('#icoPause').classList.toggle('hide', audio.paused); $('#play').setAttribute('aria-label', audio.paused ? '재생 (Space)' : '일시정지 (Space)'); };
    $('#play').addEventListener('click', () => { if (!audio.src) { wantPlay = !wantPlay; $('#nowLine').textContent = wantPlay ? '받는 대로 재생합니다…' : '음원 받는 중…'; return; } audio.paused ? audio.play() : audio.pause(); });
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
      if (loopSeg) { if (btn) btn.setAttribute('aria-pressed', 'true'); seekTo(toAudio(seg.start), true); }
    }
    $('#loop').addEventListener('click', () => { const seg = segs.find(s => s.id === activeSegId) || segs[0]; toggleLoop(seg, segEls[seg.id]?.querySelector('.loop')); });

    // ---- time map: content time (transcript) ↔ audio time (file with inserted ads) ----------
    // Podcast hosts stitch ads into the file at download time, so the transcript's timestamps (content
    // time) drift from the audio clock by the length of each ad break. The listener anchors the map
    // with one tap per ad break ("지금 들려요"); between anchors the offset is constant.
    const REACTION = 0.4;                         // seconds between hearing a line start and tapping
    const am = ep.audio_meta || {};
    const contentDur = am.content_duration || ep.duration_sec || (cues.length ? cues[cues.length - 1].e : 0);
    const midMarkers = (am.ad_markers || []).filter(m => m.type === 'mid').map(m => m.sec).sort((a, b) => a - b);
    // anchors persist only for shows without references (nothing else can re-derive them); with references
    // (or a fixed file) every visit starts from the file's clock and the automatic step takes it from there
    let anchors = (hasRefs || fixedSync) ? [] : (store.get('sync:' + ep.id, []) || []).filter(x => typeof x.c === 'number' && typeof x.a === 'number').sort((x, y) => x.c - y.c);
    let adTotal = 0;                              // audio duration − content duration, once metadata is known
    // the first anchor's offset also covers the content before it (the pre-roll sits before everything)
    const offsetAt = (c) => { let off = anchors.length ? anchors[0].a - anchors[0].c : 0; for (const an of anchors) { if (an.c <= c + 0.05) off = an.a - an.c; else break; } return off; };
    const toAudio = (c) => c + offsetAt(c);
    function toContent(a) {
      let off = anchors.length ? anchors[0].a - anchors[0].c : 0;
      for (const an of anchors) { if (an.a <= a) off = an.a - an.c; else break; }
      const c = a - off;
      if (anchors.length && c < -0.05) return { c: 0, inAd: true, adEnd: off };           // pre-roll ads
      const next = anchors.find(an => an.a > a);
      if (next && c >= next.c - 0.05) return { c: next.c, inAd: true, adEnd: next.a };   // inside a known ad break
      return { c, inAd: false };
    }
    let anchorRev = 0;
    function addAnchor(c, a) {
      anchors = anchors.filter(an => an.c < c - 0.05);
      anchors.push({ c: Math.max(0, c), a: Math.max(0, a) }); anchors.sort((x, y) => x.c - y.c);
      anchorRev++; if (sync.phase !== 'auto' && sync.phase !== 'fixed') sync.phase = 'manual';
      store.set('sync:' + ep.id, anchors); dismissedPrompt = null; renderSyncState(); update(true);
    }
    // A tap carries reaction time; when the downloaded audio and reference fingerprints are at hand,
    // look for the reference within ±6 s of the tap and replace the guess with the exact position.
    async function snapAnchor(c, aGuess) {
      if (!syncBlob || !syncIndex || !hasRefs) return;
      const refs = ep.sync.refs.slice().sort((x, y) => x.c - y.c);
      const ref = refs.filter(r => r.c <= c + 0.05).pop() || refs[0];
      const rev = anchorRev;
      try {
        const r = await PodSync.alignLocal(syncBlob, syncIndex, ref, aGuess + (ref.c - c), 6);
        sync.snaps.push({ c: +c.toFixed(2), tap: +aGuess.toFixed(2), ref: ref.c, ok: r.ok, ber: r.ber, a: r.a == null ? null : +r.a.toFixed(3) });
        if (rev !== anchorRev) return;                 // the listener moved on
        if (r.ok) {
          const a = c + (r.a - ref.c);
          if (Math.abs(a - aGuess) > 0.05) { addAnchor(c, a); showToast(`지문으로 ${(aGuess - a) >= 0 ? '−' : '+'}${Math.abs(aGuess - a).toFixed(1)}초 보정했습니다`); }
        }
      } catch (e) { sync.snaps.push({ c, error: String(e && e.message || e) }); }
      saveReport();
    }
    function nudge(delta) {                       // fine-tune the anchor that governs the current position
      if (!anchors.length) { addAnchor(0, delta); return; }
      const a = audio.currentTime; let idx = 0;
      anchors.forEach((an, i) => { if (an.a <= a) idx = i; });
      anchors[idx].a = Math.max(0, anchors[idx].a + delta); store.set('sync:' + ep.id, anchors); renderSyncState(); update(true);
    }
    let syncMode = false, dismissedPrompt = null, toastTimer = null;
    function setSyncMode(on) { syncMode = on; $('#syncBtn').setAttribute('aria-pressed', String(on)); tEl.classList.toggle('syncing', on); renderBanner(); }
    function showToast(msg) { const t = $('#toast'); t.textContent = msg; t.classList.add('on'); clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('on'), 2200); }
    function renderSyncState() {
      const off = offsetAt(toContent(audio.currentTime).c);
      const narrow = window.innerWidth < 600;
      const b = $('#syncBtn');
      const label = { downloading: '싱크 …', aligning: '싱크 …', failed: '싱크 !', stream: '싱크 !' }[sync.phase];
      b.textContent = label || (!anchors.length ? (sync.phase === 'fixed' ? '싱크 ✓' : '싱크') : narrow ? '싱크 ✓' : `싱크 ${off >= 0 ? '+' : '−'}${fmt(Math.abs(off))}`);
      b.title = { downloading: '음원을 받는 중입니다', aligning: '광고 위치를 찾는 중입니다', auto: '자동으로 맞춰졌습니다 (F: 미세 조정·정보)',
        fixed: '광고 없는 파일 — 싱크가 고정돼 있습니다 (F: 정보)', failed: '자동 싱크 실패 — 첫 문장이 들리면 눌러 주세요', stream: '음원을 스트리밍 중 — 수동으로 맞춰 주세요',
        manual: '수동으로 맞춘 상태 (F: 미세 조정)', none: '들리는 문장을 탭해 싱크를 맞춥니다' }[sync.phase] || '';
    }
    function syncInfoText() {
      const rep = sync.report || {}, L = [];
      const phaseKo = { downloading: '음원 받는 중', aligning: '맞추는 중', auto: '자동 싱크 완료', fixed: '고정(광고 없는 파일)', failed: '자동 싱크 실패 → 수동', stream: '스트리밍(수동)', manual: '수동', none: '수동' }[sync.phase] || sync.phase;
      L.push(`상태: ${phaseKo}`);
      if (sync.error) L.push(`오류: ${sync.error}`);
      if (rep.fileDur) L.push(`음원 ${fmt(rep.fileDur)} · 대본 ${fmt(rep.contentDur)} · 광고 합계 ${rep.adTotal != null ? rep.adTotal.toFixed(1) + 's' : '?'} · ${rep.ms || 0}ms`);
      (rep.refs || []).forEach((r, i) => L.push(`기준점 ${i + 1} (대본 ${fmt(r.c)}): ${r.ok ? `음원 ${fmt(r.a)} (오프셋 ${r.offset >= 0 ? '+' : ''}${r.offset}s)` : '불일치'} · BER ${r.ber ?? '-'} / 차순위 ${r.second ?? '-'}${r.error ? ' · ' + r.error : ''}`));
      if (rep.decode && rep.decode.length) L.push(`디코더: ${rep.decode.join(', ')}`);
      if (sync.pcm) L.push(`재생 음원: ${sync.pcm}`);
      if (anchors.length) L.push(`앵커: ${anchors.map(a => `${fmt(a.c)}→${fmt(a.a)} (${(a.a - a.c) >= 0 ? '+' : ''}${(a.a - a.c).toFixed(2)}s)`).join(', ')}`);
      sync.snaps.slice(-3).forEach(s => L.push(`탭 보정: 대본 ${fmt(s.c)} 탭 ${s.tap != null ? fmt(s.tap) : '?'} → ${s.ok ? fmt(s.a) + ' (BER ' + s.ber + ')' : '지문 불일치' + (s.ber != null ? ' (BER ' + s.ber + ')' : '') + (s.error ? ' ' + s.error : '')}`));
      L.push(`재생 위치 ${fmt(audio.currentTime)} · 대본 위치 ${fmt(toContent(audio.currentTime).c)} · 속도 ${(prefs.speed || 1).toFixed(1)}×`);
      L.push(`${navigator.userAgent}`);
      return L.join('\n');
    }
    function openSyncInfo() {
      const txt = syncInfoText();
      $('#bsBody').innerHTML = `<div class="ex"><div class="head"><span class="expr">싱크 상태</span></div><pre class="diag">${esc(txt)}</pre>` +
        `<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap"><button class="pbtn" type="button" id="diagCopy">복사</button><button class="pbtn" type="button" id="diagReset">싱크 초기화</button></div></div>`;
      $('#bsheet').classList.add('on'); $('#scrim').classList.add('on');
      $('#diagCopy').addEventListener('click', () => { (navigator.clipboard ? navigator.clipboard.writeText(txt) : Promise.reject()).then(() => showToast('복사했습니다'), () => showToast('복사 실패 — 길게 눌러 선택하세요')); });
      $('#diagReset').addEventListener('click', () => { anchors = []; store.set('sync:' + ep.id, anchors); dismissedPrompt = null; if (sync.phase === 'manual') sync.phase = hasRefs ? 'failed' : 'none'; renderSyncState(); update(true); closeSheet(); });
    }
    $('#syncBtn').addEventListener('click', () => setSyncMode(!syncMode));
    $('#adbar').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      const act = b.dataset.act;
      if (act === 'hear') { const target = +b.dataset.c; const guess = audio.currentTime - REACTION; addAnchor(target, guess); showToast('싱크 맞춤'); snapAnchor(target, guess); }
      else if (act === 'skip') { seekTo(+b.dataset.a + 0.05, true); }
      else if (act === 'nudge') { nudge(+b.dataset.d); }
      else if (act === 'reset') { anchors = []; store.set('sync:' + ep.id, anchors); dismissedPrompt = null; if (sync.phase === 'manual') sync.phase = hasRefs ? 'failed' : 'none'; renderSyncState(); update(true); }
      else if (act === 'info') { openSyncInfo(); }
      else if (act === 'close') { dismissedPrompt = b.dataset.key || 'x'; renderBanner(); }
      else if (act === 'cancel') { setSyncMode(false); }
    });
    // ad-break dividers in the transcript (where the host inserts mid-roll ads)
    midMarkers.forEach(m => {
      const seg = segs.find(s => s.start >= m - 0.5); if (!seg) return;
      const div = document.createElement('div'); div.className = 'adbreak';
      div.innerHTML = `<span>광고 삽입 지점 ${fmt(m)}</span><span class="hint">광고가 끝나고 다음 문장이 들리면 '지금 들려요'를 누르세요</span>`;
      segEls[seg.id].before(div);
    });
    let bannerState = '';
    function renderBanner(info) {
      const bar = $('#adbar'); let html = '', key = '';
      const daiLikely = adTotal > 15 || am.dai === 'yes' || am.dai === 'likely';
      if (syncMode) {
        key = 'sync'; html = `<span>지금 들리는 문장을 스크립트에서 탭하세요 — 그 문장부터 싱크가 맞춰집니다.</span><button data-act="cancel">취소</button>`;
      } else if (info && info.inAd) {
        key = 'inad:' + Math.round(info.adEnd);
        html = `<span>광고 구간 (이미 맞춘 위치)</span><button data-act="skip" data-a="${info.adEnd}">광고 건너뛰기 →</button>`;
      } else if (info && info.prompt) {
        key = 'prompt:' + info.prompt.kind + ':' + Math.round(info.prompt.c);
        const label = info.prompt.kind === 'pre' ? '이 음원은 앞뒤·중간에 광고가 들어 있어요(재생마다 길이가 달라져요). 광고가 끝나고 첫 문장이 들리면 눌러 주세요.' : '중간 광고 구간입니다. 광고가 끝나고 다음 문장이 들리면 눌러 주세요.';
        html = `<span>${label}<br><em>“${esc(info.prompt.text)}”</em></span><button class="primary" data-act="hear" data-c="${info.prompt.c}">지금 들려요</button><button data-act="close" data-key="${key}" aria-label="닫기">✕</button>`;
      } else if (info && info.fine) {
        key = 'fine'; html = `<span>미세 조정</span><button data-act="nudge" data-d="-1">−1s</button><button data-act="nudge" data-d="-0.3">−0.3</button><button data-act="nudge" data-d="0.3">+0.3</button><button data-act="nudge" data-d="1">+1s</button>${anchors.length ? '<button data-act="reset">초기화</button>' : ''}<button data-act="info">정보</button><button data-act="close" data-key="fine" aria-label="닫기">✕</button>`;
      }
      if (key && dismissedPrompt === key) { html = ''; key = ''; }
      if (html !== bannerState) { bar.innerHTML = html; bar.hidden = !html; bannerState = html; }
    }
    audio.addEventListener('loadedmetadata', () => { if (audio.duration && contentDur) adTotal = audio.duration - contentDur; renderSyncState(); update(true); });

    let activeIdx = -1, activeSegId = null, progScroll = 0, lastSave = 0, lastNow = null;
    const starts = cues.map(c => c.s);
    const findCue = (t) => { let lo = 0, hi = starts.length - 1, ans = -1; while (lo <= hi) { const mid = (lo + hi) >> 1; if (starts[mid] <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1; } return ans; };
    function promptFor(c, a) {                   // which ad break (if any) should the listener confirm now?
      const daiLikely = adTotal > 15 || am.dai === 'yes' || am.dai === 'likely';
      if (!daiLikely || fixedSync) return null;
      if (sync.phase === 'downloading' || sync.phase === 'aligning') return null;   // the automatic step is still running
      if (!anchors.length) { const first = cues[0]; return first && a >= 0.5 ? { kind: 'pre', c: first.s, text: first.t } : null; }
      const last = anchors[anchors.length - 1];
      const m = midMarkers.find(x => x > last.c + 1 && c >= x - 1.5);
      if (m == null) return null;
      const cue = cues.find(x => x.s >= m - 0.5); return cue ? { kind: 'mid', c: cue.s, text: cue.t } : null;
    }
    function update(force) {
      const t = audio.currentTime;
      if (!seeking) { seek.value = Math.round(t / (audio.duration || ep.duration_sec || 1) * 1000); $('#tCur').textContent = fmt(t); }
      const pos = toContent(t);
      if (loopSeg && pos.c >= loopSeg.end - 0.05) { audio.currentTime = toAudio(loopSeg.start); return; }
      renderBanner({ inAd: pos.inAd, adEnd: pos.adEnd, prompt: pos.inAd ? null : promptFor(pos.c, t), fine: syncFineOpen });
      const i = pos.inAd ? activeIdx : findCue(pos.c);
      if (i !== activeIdx || force) {
        if (activeIdx >= 0 && cueEls[activeIdx]) cueEls[activeIdx].classList.remove('active');
        activeIdx = i;
        if (i >= 0) {
          cueEls[i].classList.add('active');
          const segEl = cueEls[i].closest('.seg');
          if (segEl && segEl.id !== activeSegId) { if (activeSegId) segEls[activeSegId]?.classList.remove('now'); segEl.classList.add('now'); activeSegId = segEl.id; }
          if (prefs.auto && !userScrolled && view === 'transcript') scrollToActive(false);
        }
      }
      // the "now playing" line: current sentence, or where we are relative to the script
      if (sync.phase !== 'downloading' && sync.phase !== 'aligning' && cues.length) {
        let now = '';
        if (i >= 0) now = (i === cues.length - 1 && pos.c > cues[i].e + 1) ? '대본 끝 · 아웃트로' : cues[i].t;
        else if (!pos.inAd && pos.c < cues[0].s) now = `인트로 · 대본은 ${fmt(cues[0].s)}부터 시작합니다`;
        if (now !== lastNow) { lastNow = now; $('#nowLine').textContent = now; }
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
    let syncFineOpen = false;
    $('#syncBtn').addEventListener('contextmenu', (e) => { e.preventDefault(); syncFineOpen = !syncFineOpen; dismissedPrompt = null; update(true); });
    $('#syncBtn').addEventListener('dblclick', () => { syncFineOpen = !syncFineOpen; dismissedPrompt = null; update(true); });
    function saveProgress() {
      lastSave = Date.now(); const dur = audio.duration || ep.duration_sec || 0;
      const done = dur && audio.currentTime > dur * 0.9;
      store.set('prog:' + ep.id, { pos: Math.floor(audio.currentTime), done: done || (prog && prog.done) || false, at: Date.now() });
    }
    audio.addEventListener('timeupdate', () => update(false));
    audio.addEventListener('ended', () => { saveProgress(); setPlayIcon(); });
    renderSyncState(); update(true);

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
      else if (k === 's' || k === 'S') setSyncMode(!syncMode);
      else if (k === 'f' || k === 'F') { syncFineOpen = !syncFineOpen; dismissedPrompt = null; update(true); }
      else if (k === 'Escape') { closeSheet(); setSyncMode(false); }
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
