/* Listener counts without any account: anonymous counters on Abacus (https://abacus.jasoncameron.dev, free,
   CORS, no cookies). Each browser is counted once per thing, so the numbers read as "people":
     d-YYYYMMDD        visitors to any episode that day (KST)
     v-<ep>            people who opened the episode (ever)      vd-<ep>-YYYYMMDD  …on that day
     p-<ep> / h-<ep> / f-<ep>   people who pressed play / reached half / reached 90 %
   The owner's browsers are excluded: opening the episode list page marks a browser as "me". */
window.PodStats = (function () {
  'use strict';
  var NS = 'myfan729-podcast-study', BASE = 'https://abacus.jasoncameron.dev';
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } },
  };
  function day(offset) {                       // KST calendar day as YYYYMMDD
    var d = new Date(Date.now() + 9 * 3600e3 - (offset || 0) * 86400e3);
    return d.toISOString().slice(0, 10).replace(/-/g, '');
  }
  function hash(s) {                           // FNV-1a 32-bit → short base36 id (episode ids are too long for keys)
    var h = 0x811c9dc5;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return h.toString(36);
  }
  function isMe() { return store.get('podstats:me') === '1'; }
  function hit(key) {
    try { fetch(BASE + '/hit/' + NS + '/' + key, { mode: 'cors', credentials: 'omit', keepalive: true }).catch(function () {}); } catch (e) {}
  }
  function once(flag, key) {                   // count this browser once for `key`
    if (isMe() || store.get(flag)) return;
    store.set(flag, '1');
    hit(key);
  }
  function get(key) {
    return fetch(BASE + '/get/' + NS + '/' + key, { mode: 'cors', credentials: 'omit' })
      .then(function (r) { return r.status === 404 ? { value: 0 } : r.json(); })
      .then(function (j) { return typeof j.value === 'number' && j.value >= 0 ? j.value : 0; })
      .catch(function () { return null; });
  }
  var EV = { play: 'p', half: 'h', done: 'f' };
  return {
    pageview: function (epId) {
      var d = day(), k = hash(epId);
      once('ps:d:' + d, 'd-' + d);
      once('ps:v:' + k, 'v-' + k);
      once('ps:vd:' + k + ':' + d, 'vd-' + k + '-' + d);
    },
    event: function (kind, epId) { var c = EV[kind]; if (c) once('ps:' + c + ':' + hash(epId), c + '-' + hash(epId)); },
    markMe: function () { store.set('podstats:me', '1'); },
    isMe: isMe, get: get, hash: hash, day: day,
  };
})();
