/*
 * Podcast Study — 카카오톡 오픈채팅 자동 게시 봇 (메신저봇R 용)
 *
 * 매일 07:00 KST(= 06:00 싱가포르)에 사이트의 오늘의 카드(data/daily/latest.json)를 읽어 지정한 방에 올립니다.
 * 명령: "!오늘" → 지금 카드 게시(테스트/수동), "!핑" → 봇 생존 확인
 *
 * 메신저봇R은 카카오톡 "알림에 답장" 방식으로 보냅니다. 폰 재부팅 후에는 방에 메시지가 한 번 올라와야
 * 보낼 수 있어서, 07:00에 실패하면 10분마다 09:00까지 재시도하고, 그래도 안 되면 그날 방에 메시지가
 * 올라온 직후 한 번 게시합니다.
 */
var ROOM = "여기에_오픈채팅방_이름_정확히";        // 카톡 상단에 보이는 방 이름과 똑같이
var SITE = "https://myfan729.github.io/podcast-study/";
var POST_HOUR_KST = 7, POST_MIN_KST = 0;              // 게시 시각 (한국시간)
var RETRY_UNTIL_HOUR_KST = 12;                         // 이 시각까지 10분 간격 재시도 (서버 지연 대비)
var ADMINS = [];                                        // "!오늘"을 허용할 닉네임 목록 (비우면 누구나)
var STATE_FILE = "podcast_bot_state.json";

var KST = java.util.TimeZone.getTimeZone("Asia/Seoul");

function nowKst() { var c = java.util.Calendar.getInstance(KST); return c; }
function todayKst() {
  var c = nowKst();
  return c.get(java.util.Calendar.YEAR) + "-" + pad(c.get(java.util.Calendar.MONTH) + 1) + "-" + pad(c.get(java.util.Calendar.DAY_OF_MONTH));
}
function pad(n) { return (n < 10 ? "0" : "") + n; }
function loadState() { try { return JSON.parse(FileStream.read(STATE_FILE) || "{}"); } catch (e) { return {}; } }
function saveState(s) { FileStream.write(STATE_FILE, JSON.stringify(s)); }

function fetchCard() {
  var txt = org.jsoup.Jsoup.connect(SITE + "data/daily/latest.json?t=" + Date.now())
    .ignoreContentType(true).header("Cache-Control", "no-cache").timeout(20000).get().body().text();
  return JSON.parse(txt);
}

/** 오늘의 카드를 방에 게시. 성공 true. force=true면 이미 올렸어도 다시. */
function postCard(force) {
  var st = loadState();
  var card;
  try { card = fetchCard(); } catch (e) { Log.e("card fetch failed: " + e); return false; }
  // 카드가 오늘(KST) 만들어진 것인지 — 사이트 갱신(07:00)보다 먼저 돌면 어제 카드가 올라가는 걸 막음
  if (!force && card.date_kst !== todayKst()) { Log.i("card is for " + card.date_kst + ", not today; wait"); return false; }
  if (!force && st.lastPostedId === card.id) { Log.i("already posted " + card.id); return true; }
  var ok = Api.replyRoom(ROOM, card.text);
  if (ok) { st.lastPostedId = card.id; st.lastPostedDate = todayKst(); saveState(st); Log.i("posted " + card.id); }
  else { Log.e("replyRoom failed (no notification session for room yet?)"); }
  return ok;
}

function dueNow() {
  var c = nowKst(); var h = c.get(java.util.Calendar.HOUR_OF_DAY), m = c.get(java.util.Calendar.MINUTE);
  var afterStart = h > POST_HOUR_KST || (h === POST_HOUR_KST && m >= POST_MIN_KST);
  return afterStart && h < RETRY_UNTIL_HOUR_KST;      // 중복은 postCard가 카드 ID로 막음
}

// ---- 스케줄러: 1분마다 깨어나 게시 시각이면 시도 ----
var running = true;
var worker = new java.lang.Thread(new java.lang.Runnable({
  run: function () {
    var lastTry = 0;
    while (running) {
      try {
        if (dueNow() && Date.now() - lastTry > 10 * 60 * 1000) { lastTry = Date.now(); postCard(false); }
      } catch (e) { Log.e("scheduler: " + e); }
      java.lang.Thread.sleep(60 * 1000);
    }
  }
}));
worker.setDaemon(true);
worker.start();

// ---- 메시지 수신: 명령 처리 + 재부팅 후 세션 복구용 게시 ----
function response(room, msg, sender, isGroupChat, replier, imageDB, packageName) {
  if (room !== ROOM) return;
  var text = String(msg).trim();
  if (text === "!핑") { replier.reply("살아 있어요 · " + nowKst().getTime()); return; }
  if (text === "!오늘") {
    if (ADMINS.length && ADMINS.indexOf(sender) < 0) return;
    if (!postCard(true)) replier.reply("오늘의 카드를 가져오지 못했어요."); return;
  }
  // 07:00에 세션이 없어 못 보냈다면, 방에 첫 메시지가 올라온 지금 보냄
  if (dueNow()) postCard(false);
}

function onStartCompile() { running = false; }

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
