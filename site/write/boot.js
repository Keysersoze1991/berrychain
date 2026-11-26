// Removes the "Rigging the letterbox…" line once Flutter has drawn its first frame.
// Kept in a file (not inline) so the page's Content-Security-Policy can refuse inline scripts.
window.addEventListener("flutter-first-frame", function () {
  var b = document.getElementById("boot");
  if (b) b.remove();
});
