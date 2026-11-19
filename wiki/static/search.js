// Static A-Z filter: hides index entries that do not contain every typed word.
(function () {
  var q = document.getElementById('q');
  if (!q) return;
  var items = Array.prototype.slice.call(document.querySelectorAll('ul.az li'));
  function run() {
    var words = q.value.toLowerCase().split(/\s+/).filter(Boolean);
    items.forEach(function (li) {
      var k = li.getAttribute('data-k');
      li.style.display = words.every(function (w) { return k.indexOf(w) >= 0; }) ? '' : 'none';
    });
  }
  var m = /[?&]q=([^&]*)/.exec(location.search);
  if (m) q.value = decodeURIComponent(m[1].replace(/\+/g, ' '));
  q.addEventListener('input', run);
  run();
})();
