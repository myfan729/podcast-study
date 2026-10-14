/*
 * Podcast Study — 카카오톡 오픈채팅 자동 게시 봇 (메신저봇R 용)  v4
 *
 * 사이트의 게시 대기열(data/daily/queue.json)을 5분마다 확인해서, 글마다 정해진 시각(아침 07:00 두 편,
 * 저녁 21:00 한 편 — 시각과 편수는 사이트 설정이 정함)이 되면 등록된 방에 한 편씩 올립니다.
 * 같은 글은 두 번 올리지 않고, 폰이 꺼져 있었으면 다시 켜진 뒤 그 글의 마감 시각 전까지 올립니다.
 *
 * 처음 한 번: 게시할 방에서 "!여기" → 그 방이 게시 방으로 등록됩니다 (이전 버전에서 이미 했다면 그대로 유지).
 *
 * 명령 (어느 방에서나)
 *   !여기    이 방을 게시 방으로 등록
 *   !핑      봇 상태: 게시 방, 다음 게시, 마지막 확인
 *   !다음    올라갈 예정인 글 목록
 *   !오늘    오늘 이미 게시 시각이 지난 글을 지금 이 방에 다시 올림
 *   !방이름  봇이 인식하는 이 방의 이름/단톡 여부 (진단용)
 *   !업데이트 사이트 업데이트를 지금 깨움 (GH_TOKEN을 넣었을 때)
 *
 * (선택, 권장) GH_TOKEN: GitHub의 예약 실행은 자주 빠지거나 늦어서, 아침 7시·저녁 9시 직전에 새 에피소드가
 * 제때 준비되지 않을 수 있습니다. 아래 GH_TOKEN에 토큰을 넣으면 봇이 게시 전 정해진 시각마다 사이트 업데이트를
 * 직접 깨웁니다. 토큰 만들기: GitHub → Settings → Developer settings → Personal access tokens →
 * Fine-grained tokens → Generate new token → Repository access: Only select repositories → podcast-study →
 * Permissions → Actions: Read and write → Generate. 이 토큰으로는 이 리포의 작업 실행만 할 수 있습니다.
 * 한 번 넣고 컴파일하면 폰에 저장되므로, 다음 버전 스크립트에서는 다시 넣지 않아도 됩니다.
 *
 * 메신저봇R은 카카오톡 "알림에 답장" 방식으로 보냅니다. 폰 재부팅 뒤에는 그 방에 메시지가 한 번 올라와야
 * 보낼 수 있어서, 실패하면 1분마다 다시 시도하고 그 방에 메시지가 올라오는 즉시 올립니다.
 */
var ROOM = "";                       // 비워 두세요. 게시할 방에서 "!여기"로 등록합니다.
var SITE = "https://myfan729.github.io/podcast-study/";
var ADMINS = [];                     // "!여기", "!오늘"을 쓸 수 있는 닉네임 (비우면 누구나)
var GH_TOKEN = "";                   // (선택) 위 설명의 GitHub 토큰 — 이 파일을 GitHub에 올릴 때는 절대 넣지 마세요
var GH_REPO = "myfan729/podcast-study";
var KICK_KST = ["05:25", "05:55", "06:25", "06:45", "07:10", "18:25", "19:05", "19:35", "20:05", "20:35", "20:50"];
var POLL_MINUTES = 5;                // 대기열 확인 간격
var GAP_MS = 4000;                   // 한 번에 여러 편이면 사이 간격
var STATE_KEY = "podcast_bot_state";
var STATE_PATH = "/sdcard/msgbot/podcast_bot_state.json";

var KST = java.util.TimeZone.getTimeZone("Asia/Seoul");
function pad(n) { return (n < 10 ? "0" : "") + n; }
function kstParts(ms) {
  var c = java.util.Calendar.getInstance(KST);
  if (ms != null) c.setTimeInMillis(ms);
  return { y: c.get(java.util.Calendar.YEAR), mo: c.get(java.util.Calendar.MONTH) + 1, d: c.get(java.util.Calendar.DAY_OF_MONTH),
           h: c.get(java.util.Calendar.HOUR_OF_DAY), mi: c.get(java.util.Calendar.MINUTE) };
}
function dateKst(ms) { var p = kstParts(ms); return p.y + "-" + pad(p.mo) + "-" + pad(p.d); }
function hhmm(ms) { var p = kstParts(ms); return pad(p.h) + ":" + pad(p.mi); }
function whenLabel(ms) { return (dateKst(ms) === dateKst(Date.now()) ? "오늘 " : (kstParts(ms).mo + "/" + kstParts(ms).d + " ")) + hhmm(ms); }

/** 방 이름 비교용: 유니코드 정규화(NFC) + 공백 정리 */
function norm(s) {
  s = String(s == null ? "" : s);
  try { s = String(java.text.Normalizer.normalize(s, java.text.Normalizer.Form.NFC)); } catch (e) {}
  return s.replace(/[\s​　 ]+/g, " ").trim();
}
function isAdmin(sender) { return !ADMINS.length || ADMINS.indexOf(String(sender)) >= 0; }

// ---- 상태: 메모리 + (가능하면) DataBase/파일. 저장이 실패해도 메모리 상태로 중복 게시를 막음 ----
var STATE = null;
function loadState() {
  if (STATE) return STATE;
  var raw = null;
  try { raw = DataBase.getDataBase(STATE_KEY); } catch (e) {}
  if (!raw) { try { raw = FileStream.read(STATE_PATH); } catch (e) {} }
  try { STATE = JSON.parse(String(raw || "{}")) || {}; } catch (e) { STATE = {}; }
  if (!STATE.posted) STATE.posted = {};
  if (STATE.lastPostedId && !STATE.posted[STATE.lastPostedId]) STATE.posted[STATE.lastPostedId] = Date.now();  // v2 → v3
  return STATE;
}
function saveState() {
  var s = loadState(), cutoff = Date.now() - 10 * 24 * 3600 * 1000;
  for (var id in s.posted) { if (s.posted[id] < cutoff) delete s.posted[id]; }
  var txt = JSON.stringify(s);
  try { DataBase.setDataBase(STATE_KEY, txt); return; } catch (e) {}
  try { FileStream.write(STATE_PATH, txt); } catch (e) { Log.e("state save failed (memory only): " + e); }
}
function targetRoom() { return loadState().room || ROOM; }

// ---- 대기열 ----
var QUEUE = null, QUEUE_META = null, lastFetch = 0, lastFetchError = "";
function fetchQueue(force) {
  if (!force && QUEUE && Date.now() - lastFetch < POLL_MINUTES * 60 * 1000) return QUEUE;
  try {
    var body = org.jsoup.Jsoup.connect(SITE + "data/daily/queue.json?t=" + Date.now())
      .ignoreContentType(true).header("Cache-Control", "no-cache").timeout(20000).execute().body();
    var q = JSON.parse(String(body));
    QUEUE = (q && q.posts) ? q.posts : [];
    QUEUE_META = q || null;
    lastFetch = Date.now(); lastFetchError = "";
  } catch (e) {
    lastFetchError = String(e); lastFetch = Date.now() - (POLL_MINUTES - 1) * 60 * 1000;   // 1분 뒤 재시도
    Log.e("queue fetch failed: " + e);
  }
  return QUEUE || [];
}
function byTime(a, b) { return (a.post_at_ms - b.post_at_ms) || ((a.order || 0) - (b.order || 0)); }
function duePosts() {
  var now = Date.now(), st = loadState(), out = [];
  var q = fetchQueue(false);
  for (var i = 0; i < q.length; i++) {
    var p = q[i];
    if (!p || !p.id || st.posted[p.id]) continue;
    if (p.post_at_ms <= now && now < (p.until_ms || p.post_at_ms + 4 * 3600 * 1000)) out.push(p);
  }
  return out.sort(byTime);
}
function upcoming() {
  var now = Date.now(), st = loadState(), out = [];
  var q = fetchQueue(false);
  for (var i = 0; i < q.length; i++) { var p = q[i]; if (p && !st.posted[p.id] && p.post_at_ms > now) out.push(p); }
  return out.sort(byTime);
}

// ---- 사이트 업데이트 깨우기 (GitHub Actions workflow_dispatch) ----
var GH_KEY = "podcast_bot_gh";
function ghToken() {
  if (GH_TOKEN) { try { DataBase.setDataBase(GH_KEY, GH_TOKEN); } catch (e) {} return GH_TOKEN; }
  try { return String(DataBase.getDataBase(GH_KEY) || ""); } catch (e) { return ""; }
}
var lastKick = { at: 0, result: "" };
function kickUpdate() {
  var tok = ghToken();
  if (!tok) return "토큰 없음";
  var res;
  try {
    res = org.jsoup.Jsoup.connect("https://api.github.com/repos/" + GH_REPO + "/actions/workflows/update.yml/dispatches")
      .ignoreContentType(true).ignoreHttpErrors(true).timeout(20000)
      .header("Authorization", "Bearer " + tok).header("Accept", "application/vnd.github+json")
      .header("X-GitHub-Api-Version", "2022-11-28").header("Content-Type", "application/json")
      .requestBody('{"ref":"main"}').method(org.jsoup.Connection.Method.POST).execute();
  } catch (e) { lastKick.result = "오류: " + e; Log.e("kick failed: " + e); return lastKick.result; }
  var code = res.statusCode();
  lastKick.at = Date.now();
  lastKick.result = code === 204 ? "OK" : ("HTTP " + code + (code === 401 || code === 403 || code === 404 ? " (토큰 권한 확인)" : ""));
  if (code !== 204) Log.e("kick: " + lastKick.result + " " + String(res.body()).slice(0, 200));
  return lastKick.result;
}
function kickTimes() { return (QUEUE_META && QUEUE_META.kick_kst && QUEUE_META.kick_kst.length) ? QUEUE_META.kick_kst : KICK_KST; }
var lastKickCheck = 0;
function minuteOfDay(ms) { var p = kstParts(ms); return p.h * 60 + p.mi; }
/** 깨울 시각(KST "HH:MM")이 지난 확인 이후 지나갔으면 한 번 깨움 (루프가 1분을 건너뛰어도 놓치지 않게) */
function maybeKick() {
  var now = Date.now(), prev = lastKickCheck || now - 60 * 1000;
  lastKickCheck = now;
  if (!ghToken()) return;
  var a = minuteOfDay(prev), b = minuteOfDay(now), times = kickTimes(), due = null;
  for (var i = 0; i < times.length; i++) {
    var hm = String(times[i]).split(":"), m = parseInt(hm[0], 10) * 60 + parseInt(hm[1], 10);
    if ((a < b && a < m && m <= b) || (a > b && (m > a || m <= b))) due = times[i];
  }
  if (!due || now - prev > 30 * 60 * 1000) return;     // (폰이 오래 잠들었다 깨면 지난 시각은 건너뜀)
  Log.i("kick update (" + due + "): " + kickUpdate());
}

// ---- 보내기 ----
var lastTargetReplier = null;        // 게시 방에서 마지막으로 받은 알림의 답장 경로 (replyRoom 실패 시 대안)
function send(room, text) {
  var ok = false;
  try { ok = Api.replyRoom(room, text); } catch (e) { Log.e("replyRoom error: " + e); }
  if (!ok && lastTargetReplier && norm(room) === norm(targetRoom())) {
    try { lastTargetReplier.reply(text); ok = true; } catch (e) { Log.e("replier fallback failed: " + e); }
  }
  return ok;
}

var LOCK = new java.util.concurrent.locks.ReentrantLock();
/** 게시 시각이 된 글을 게시 방에 올림. 올린 개수를 돌려줌 */
function postDue() {
  var tgt = targetRoom();
  if (!tgt) return 0;
  if (!LOCK.tryLock()) return 0;
  var n = 0;
  try {
    var due = duePosts(), st = loadState();
    for (var i = 0; i < due.length; i++) {
      if (i > 0) { try { java.lang.Thread.sleep(GAP_MS); } catch (e) {} }
      if (!send(tgt, due[i].text)) { Log.e("could not post to [" + tgt + "] yet (no notification from that room since the bot started?)"); break; }
      st.posted[due[i].id] = Date.now(); saveState(); n++;
      Log.i("posted " + due[i].id + " to [" + tgt + "]");
    }
  } finally { LOCK.unlock(); }
  return n;
}

// ---- 스케줄러: 1분마다 확인 (대기열은 5분마다 새로 받음) ----
var running = true;
var worker = new java.lang.Thread(new java.lang.Runnable({
  run: function () {
    while (running) {
      try { maybeKick(); } catch (e) { Log.e("kick: " + e); }
      try { postDue(); } catch (e) { Log.e("scheduler: " + e); }
      try { java.lang.Thread.sleep(60 * 1000); } catch (e) { break; }
    }
  }
}));
worker.setDaemon(true);
worker.start();

// ---- 메시지 수신 ----
function response(room, msg, sender, isGroupChat, replier, imageDB, packageName) {
  var r = String(room), text = String(msg).trim();

  if (text === "!방이름") { replier.reply("봇이 보는 이 방: [" + r + "] · 단톡=" + isGroupChat + " · 게시 방: [" + (targetRoom() || "미등록") + "]"); return; }
  if (text === "!핑") {
    var nx = upcoming()[0];
    replier.reply("살아 있어요 (v4) · " + dateKst() + " " + hhmm() + " KST\n게시 방: [" + (targetRoom() || "미등록 — 게시할 방에서 !여기") + "]"
      + "\n다음 게시: " + (nx ? whenLabel(nx.post_at_ms) + " · " + nx.show.name : "대기 중인 글 없음")
      + "\n대기열 확인: " + (lastFetch ? hhmm(lastFetch) : "아직") + (lastFetchError ? " (오류: " + lastFetchError.slice(0, 80) + ")" : "")
      + "\n업데이트 깨우기: " + (ghToken() ? "켜짐" + (lastKick.at ? " · 마지막 " + hhmm(lastKick.at) + " " + lastKick.result : "") : "꺼짐 (GH_TOKEN 없음)"));
    return;
  }
  if (text === "!다음") {
    var up = upcoming();
    if (!up.length) { replier.reply("올라갈 예정인 글이 아직 없어요. (에피소드가 준비되면 대기열에 들어와요)"); return; }
    var lines = [];
    for (var i = 0; i < up.length && i < 6; i++) lines.push(whenLabel(up[i].post_at_ms) + " · " + up[i].show.name + " — " + up[i].title);
    replier.reply("예정된 글\n" + lines.join("\n"));
    return;
  }
  if (text === "!업데이트") {
    if (!isAdmin(sender)) return;
    replier.reply(ghToken() ? "사이트 업데이트를 깨웠어요: " + kickUpdate() + " (몇 분 뒤 반영)" : "GH_TOKEN이 없어서 깨울 수 없어요. 스크립트 맨 위 설명을 보세요.");
    return;
  }
  if (text === "!여기") {
    if (!isAdmin(sender)) return;
    var st = loadState(); st.room = r; saveState();
    lastTargetReplier = replier;
    replier.reply("이 방을 게시 방으로 등록했어요: [" + r + "]\n아침 7시·저녁 9시에 새 글이 자동으로 올라와요.");
    postDue();
    return;
  }
  if (text === "!오늘") {
    if (!isAdmin(sender)) return;
    var q = fetchQueue(true), now = Date.now(), today = dateKst(now), mine = [];
    for (var j = 0; j < q.length; j++) if (q[j].post_at_ms <= now && dateKst(q[j].post_at_ms) === today) mine.push(q[j]);
    mine.sort(byTime);
    if (!mine.length) { var nx2 = upcoming()[0]; replier.reply("오늘 게시 시각이 지난 글이 아직 없어요." + (nx2 ? " 다음: " + whenLabel(nx2.post_at_ms) : "")); return; }
    var s2 = loadState();
    for (var m = 0; m < mine.length; m++) {
      if (m > 0) { try { java.lang.Thread.sleep(GAP_MS); } catch (e) {} }
      replier.reply(mine[m].text);
      if (norm(r) === norm(targetRoom())) s2.posted[mine[m].id] = Date.now();
    }
    saveState();
    return;
  }

  // 게시 방의 아무 메시지: 답장 경로를 기억하고, 밀린 글이 있으면 지금 올림 (재부팅 뒤 복구)
  if (targetRoom() && norm(r) === norm(targetRoom())) {
    lastTargetReplier = replier;
    postDue();
  }
}

function onStartCompile() { running = false; try { worker.interrupt(); } catch (e) {} }

// 메신저봇R 선택 이벤트(없으면 "There is no function ..." 경고가 로그에 남음)
function onPause() {}
function onResume() {}
function onCreate(savedInstanceState, activity) {}
function onStart(activity) {}
function onStop(activity) {}
function onRestart(activity) {}
function onDestroy(activity) {}
function onBackPressed(activity) {}
function onNotificationPosted(sbn, sm) {}
