/*
 * Podcast Study — 카카오톡 오픈채팅 자동 게시 봇 (메신저봇R 용)
 *
 * 설치 후 게시할 방에서 "!여기" 한 번 → 그 방이 게시 방으로 등록됩니다(방 이름을 직접 입력할 필요 없음).
 * 매일 07:00~12:00 KST 사이, 사이트에 오늘 카드(data/daily/latest.json)가 생기면 그 방에 한 번 올립니다.
 *
 * 명령 (어느 방에서나)
 *   !여기    이 방을 게시 방으로 등록 (오늘 카드가 아직 안 올라갔으면 바로 올림)
 *   !방이름  봇이 인식하는 이 방의 이름/단톡 여부를 보여줌 (진단용)
 *   !핑      봇 생존 확인
 *   !오늘    오늘 카드를 지금 이 방에 올림
 *
 * 메신저봇R은 카카오톡 "알림에 답장" 방식으로 보냅니다. 폰 재부팅 뒤에는 그 방에 메시지가 한 번 올라와야
 * 보낼 수 있어서, 07:00에 실패하면 12:00까지 10분 간격으로 재시도하고 방에 메시지가 올라오는 즉시 올립니다.
 */
var ROOM = "";                       // 비워 두세요. 게시할 방에서 "!여기"로 등록합니다.
var SITE = "https://myfan729.github.io/podcast-study/";
var POST_HOUR_KST = 7, POST_MIN_KST = 0;
var RETRY_UNTIL_HOUR_KST = 12;
var ADMINS = [];                     // "!여기", "!오늘"을 쓸 수 있는 닉네임 (비우면 누구나)
var STATE_KEY = "podcast_bot_state";
var STATE_PATH = "/sdcard/msgbot/podcast_bot_state.json";

var KST = java.util.TimeZone.getTimeZone("Asia/Seoul");

function nowKst() { return java.util.Calendar.getInstance(KST); }
function pad(n) { return (n < 10 ? "0" : "") + n; }
function todayKst() {
  var c = nowKst();
  return c.get(java.util.Calendar.YEAR) + "-" + pad(c.get(java.util.Calendar.MONTH) + 1) + "-" + pad(c.get(java.util.Calendar.DAY_OF_MONTH));
}
function hhmmKst() { var c = nowKst(); return pad(c.get(java.util.Calendar.HOUR_OF_DAY)) + ":" + pad(c.get(java.util.Calendar.MINUTE)); }

/** 방 이름 비교용: 유니코드 정규화(NFC) + 공백 정리 */
function norm(s) {
  s = String(s == null ? "" : s);
  try { s = String(java.text.Normalizer.normalize(s, java.text.Normalizer.Form.NFC)); } catch (e) {}
  return s.replace(/[\s​　 ]+/g, " ").trim();
}
function isAdmin(sender) { return !ADMINS.length || ADMINS.indexOf(String(sender)) >= 0; }

// ---- 상태 저장: 메모리 + (가능하면) 파일. 저장이 실패해도 메모리 상태로 중복 게시를 막음 ----
var STATE = null;
function loadState() {
  if (STATE) return STATE;
  var raw = null;
  try { raw = DataBase.getDataBase(STATE_KEY); } catch (e) {}
  if (!raw) { try { raw = FileStream.read(STATE_PATH); } catch (e) {} }
  try { STATE = JSON.parse(String(raw || "{}")) || {}; } catch (e) { STATE = {}; }
  return STATE;
}
function saveState(s) {
  STATE = s;
  var txt = JSON.stringify(s);
  try { DataBase.setDataBase(STATE_KEY, txt); return; } catch (e) {}
  try { FileStream.write(STATE_PATH, txt); } catch (e) { Log.e("state save failed (memory only): " + e); }
}
function targetRoom() { var st = loadState(); return st.room || ROOM; }

function fetchCard() {
  var body = org.jsoup.Jsoup.connect(SITE + "data/daily/latest.json?t=" + Date.now())
    .ignoreContentType(true).header("Cache-Control", "no-cache").timeout(20000).execute().body();
  return JSON.parse(String(body));
}

var lastTargetReplier = null;        // 게시 방에서 마지막으로 받은 알림의 답장 경로 (replyRoom 실패 시 대안)

/** 오늘 카드를 게시 방에 올림. 성공/이미 올림 → true */
function postCard() {
  var tgt = targetRoom();
  if (!tgt) { Log.i("no target room yet — type !여기 in the room"); return false; }
  var st = loadState();
  var card;
  try { card = fetchCard(); } catch (e) { Log.e("card fetch failed: " + e); return false; }
  if (card.date_kst !== todayKst()) { Log.i("card is for " + card.date_kst + ", not today (" + todayKst() + "); wait"); return false; }
  if (st.lastPostedId === card.id) return true;
  var ok = false;
  try { ok = Api.replyRoom(tgt, card.text); } catch (e) { Log.e("replyRoom error: " + e); }
  if (!ok && lastTargetReplier) { try { lastTargetReplier.reply(card.text); ok = true; } catch (e) { Log.e("replier fallback failed: " + e); } }
  if (ok) { st.lastPostedId = card.id; st.lastPostedDate = todayKst(); saveState(st); Log.i("posted " + card.id + " to [" + tgt + "]"); }
  else { Log.e("could not post to [" + tgt + "] yet (no notification from that room since the bot started?)"); }
  return ok;
}

function dueNow() {
  var c = nowKst(); var h = c.get(java.util.Calendar.HOUR_OF_DAY), m = c.get(java.util.Calendar.MINUTE);
  var afterStart = h > POST_HOUR_KST || (h === POST_HOUR_KST && m >= POST_MIN_KST);
  return afterStart && h < RETRY_UNTIL_HOUR_KST;
}

// ---- 스케줄러: 1분마다 깨어나 게시 시간대면 10분 간격으로 시도 ----
var running = true;
var worker = new java.lang.Thread(new java.lang.Runnable({
  run: function () {
    var lastTry = 0;
    while (running) {
      try {
        if (dueNow() && loadState().lastPostedDate !== todayKst() && Date.now() - lastTry > 10 * 60 * 1000) {
          lastTry = Date.now(); postCard();
        }
      } catch (e) { Log.e("scheduler: " + e); }
      try { java.lang.Thread.sleep(60 * 1000); } catch (e) { break; }
    }
  }
}));
worker.setDaemon(true);
worker.start();

// ---- 메시지 수신 ----
function response(room, msg, sender, isGroupChat, replier, imageDB, packageName) {
  var r = String(room), text = String(msg).trim();
  Log.i("msg room=[" + r + "] group=" + isGroupChat + " sender=" + sender);

  if (text === "!방이름") { replier.reply("봇이 보는 이 방: [" + r + "] · 단톡=" + isGroupChat + " · 게시 방: [" + (targetRoom() || "미등록") + "]"); return; }
  if (text === "!핑") { replier.reply("살아 있어요 · " + todayKst() + " " + hhmmKst() + " KST · 게시 방: [" + (targetRoom() || "미등록") + "]"); return; }
  if (text === "!여기") {
    if (!isAdmin(sender)) return;
    var st = loadState(); st.room = r; saveState(st);
    lastTargetReplier = replier;
    replier.reply("이 방을 매일 아침 게시 방으로 등록했어요: [" + r + "]");
    if (dueNow()) postCard();
    return;
  }
  if (text === "!오늘") {
    if (!isAdmin(sender)) return;
    var card = null;
    try { card = fetchCard(); } catch (e) { replier.reply("오늘의 카드를 가져오지 못했어요."); return; }
    replier.reply(card.text);
    if (norm(r) === norm(targetRoom()) && card.date_kst === todayKst()) { var s2 = loadState(); s2.lastPostedId = card.id; s2.lastPostedDate = todayKst(); saveState(s2); }
    return;
  }

  // 게시 방의 아무 메시지: 답장 경로를 기억하고, 오늘 카드가 아직이면 지금 올림 (재부팅 뒤 복구)
  if (targetRoom() && norm(r) === norm(targetRoom())) {
    lastTargetReplier = replier;
    if (dueNow() && loadState().lastPostedDate !== todayKst()) postCard();
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
