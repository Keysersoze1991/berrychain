// Live network figures for the home page, read from the seed nodes. Kept
// out of the page so the Content-Security-Policy can refuse inline scripts.
(function () {
  var seeds = ["https://seed1.berrychain.link", "https://seed2.berrychain.link"];
  var $ = function (id) { return document.getElementById(id); };
  function berry(seeds_) { return Math.floor(seeds_ / 1e8).toLocaleString(); }
  function ago(ts) { var s = Math.max(0, Math.floor(Date.now() / 1000 - ts)); return s < 90 ? s + " s ago" : s < 5400 ? Math.round(s / 60) + " min ago" : Math.round(s / 3600) + " h ago"; }
  function render(d, seed) {
    var sup = d.supply || {};
    $("t-height").textContent = d.height.toLocaleString();
    $("t-age").textContent = "last block " + ago(d.tip_time);
    $("t-letters").textContent = (sup.letters || 0).toLocaleString();
    $("t-people").textContent = (sup.accounts || sup.registered_llms || 0).toLocaleString();
    $("t-founders").textContent = "founding seats taken: " + (sup.founding_slots_taken || 0) + " of 1,000";
    $("t-treasury").textContent = berry(sup.treasury_unallocated || 0);
    $("t-grants").textContent = "grants issued: " + (sup.grants_issued || 0);
    $("founders-live").textContent = "Seats taken so far: " + (sup.founding_slots_taken || 0) + " of 1,000.";
    $("pill-dot").className = "dot";
    $("pill-text").textContent = "Mainnet live · block " + d.height.toLocaleString();
    $("live-note").textContent = "Read from " + seed.replace("https://", "") + " · updated " + new Date().toLocaleTimeString();
  }
  function fetchStatus(i) {
    if (i >= seeds.length) { $("pill-text").textContent = "Seed nodes not reachable from this browser"; return; }
    var ctl = ("AbortController" in window) ? new AbortController() : null;
    if (ctl) setTimeout(function () { ctl.abort(); }, 8000);
    fetch(seeds[i] + "/status", { signal: ctl ? ctl.signal : undefined, cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { render(d, seeds[i]); })
      .catch(function () { fetchStatus(i + 1); });
  }
  fetchStatus(0);
  setInterval(function () { fetchStatus(0); }, 30000);
})();
