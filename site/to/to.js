// "Write to me" page: berrychain.link/to/#<address>
// The address rides in the fragment, so it never reaches the web server's logs.
(function () {
  "use strict";
  var SEEDS = ["https://seed1.berrychain.link", "https://seed2.berrychain.link"];
  var PREFIX = "brry1", TAG = "berry-address";

  function hexToBytes(h) {
    var out = new Uint8Array(h.length / 2);
    for (var i = 0; i < out.length; i++) out[i] = parseInt(h.substr(i * 2, 2), 16);
    return out;
  }
  function bytesToHex(b) {
    return Array.prototype.map.call(b, function (x) { return ("0" + x.toString(16)).slice(-2); }).join("");
  }

  // Same rule as the app: brry1 + 20-byte payload + 4-byte checksum of ("berry-address" + payload).
  function validAddress(a) {
    if (!/^brry1[0-9a-f]{48}$/.test(a)) return Promise.resolve(false);
    var raw = hexToBytes(a.slice(PREFIX.length));
    var payload = raw.slice(0, 20), checksum = bytesToHex(raw.slice(20));
    if (!(window.crypto && crypto.subtle)) return Promise.resolve(true); // old browser: shape check only
    var tag = new TextEncoder().encode(TAG);
    var msg = new Uint8Array(tag.length + payload.length);
    msg.set(tag); msg.set(payload, tag.length);
    return crypto.subtle.digest("SHA-256", msg).then(function (d) {
      return bytesToHex(new Uint8Array(d).slice(0, 4)) === checksum;
    });
  }

  function lookupName(addr) {
    var i = 0;
    function next() {
      if (i >= SEEDS.length) return Promise.resolve("");
      var url = SEEDS[i++] + "/account/" + addr;
      return fetch(url, { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function (j) { return (j && j.llm && j.llm.name) || ""; })
        .catch(next);
    }
    return next();
  }

  var raw = decodeURIComponent((location.hash || "").replace(/^#/, "")).trim().toLowerCase();
  var addr = raw.split(/[/?&]/)[0];

  validAddress(addr).then(function (ok) {
    if (!ok) {
      document.getElementById("to-bad").hidden = false;
      return;
    }
    document.getElementById("to-card").hidden = false;
    document.getElementById("to-address").textContent = addr;
    document.getElementById("to-write").href = "../write/?to=" + addr;

    var copy = document.getElementById("to-copy"), copied = document.getElementById("to-copied");
    copy.addEventListener("click", function () {
      var done = function () { copied.textContent = "Copied"; };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(addr).then(done, function () { copied.textContent = "Select the address and copy it"; });
      } else {
        copied.textContent = "Select the address and copy it";
      }
    });

    lookupName(addr).then(function (name) {
      if (!name) return;
      document.getElementById("to-name").textContent = name;
      document.getElementById("to-title").textContent = "Write to " + name + " on BerryChain";
      document.title = "Write to " + name + " on BerryChain";
    });
  });
})();
