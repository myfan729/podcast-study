/* Listener counts via GoatCounter (https://www.goatcounter.com): no cookies, no personal data stored.
   Counts per episode: page opens, "재생 시작", "절반 들음", "끝까지 들음". Disabled while GC_CODE is empty.
   Your own visits: open any page with #toggle-goatcounter once per browser to stop counting yourself. */
window.PodStats = (function () {
  'use strict';
  var GC_CODE = '';                 // GoatCounter site code, e.g. 'podstudy' → https://podstudy.goatcounter.com
  var queue = [], loading = false;

  function flush() {
    if (!window.goatcounter || typeof window.goatcounter.count !== 'function') return false;
    queue.splice(0).forEach(function (o) { try { window.goatcounter.count(o); } catch (e) {} });
    return true;
  }
  function load() {
    if (loading) return; loading = true;
    window.goatcounter = window.goatcounter || {};
    window.goatcounter.no_onload = true;           // we send counts ourselves, with the episode title
    var s = document.createElement('script');
    s.async = true; s.src = 'https://gc.zgo.at/count.js';
    s.setAttribute('data-goatcounter', 'https://' + GC_CODE + '.goatcounter.com/count');
    s.setAttribute('data-goatcounter-settings', '{"no_onload": true}');
    s.onload = flush;
    document.head.appendChild(s);
  }
  function send(o) {
    if (!GC_CODE) return;
    queue.push(o);
    if (!flush()) load();
  }
  return {
    enabled: function () { return !!GC_CODE; },
    pageview: function (path, title) { send({ path: path, title: title }); },
    event: function (name, title) { send({ path: name, title: title, event: true }); },
  };
})();
