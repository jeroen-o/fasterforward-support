/* Zoekfunctie van de supportsite. Werkt volledig in de browser met window.ZOEKINDEX (zoekindex.js).
 * - hoofdletters en accenten maken niet uit (efficiënt = efficient)
 * - alle woorden moeten voorkomen; levert dat niets op, dan volstaat één van de woorden
 * - woorden in de titel wegen zwaarder dan woorden in de tekst; begin van een woord telt ook (HDN -> HDN25)
 * - Nederlandse woordvormen: facturen vindt ook factuur, verzekeringen ook verzekering (stam, lager gewogen)
 */
(function () {
  "use strict";
  var IDX = window.ZOEKINDEX || [];
  var STOP = { de: 1, het: 1, een: 1, en: 1, van: 1, in: 1, op: 1, voor: 1, met: 1, je: 1, is: 1, te: 1, ik: 1, hoe: 1, wat: 1, kan: 1, aan: 1, bij: 1, of: 1, om: 1, mijn: 1 };
  var PAGE = 25;
  var input = document.querySelector(".search input");
  var resEl = document.getElementById("sres"), cntEl = document.getElementById("scount"), hEl = document.getElementById("sh");
  var moreBtn = document.getElementById("smore");
  var kind = "", shown = 0, results = [], terms = [], tstems = [], timer = null, stemsKlaar = false;

  /* Eenvoudige Nederlandse stemmer (naar het Snowball-algoritme): facturen = factuur, verzekeringen = verzekering. */
  function stem(w) {
    if (w.length <= 3 || /\d/.test(w)) return w;
    var isV = function (c) { return "aeiouy".indexOf(c) >= 0; };
    var undouble = function (x) { return /([bcdfgklmnprstvz])\1$/.test(x) ? x.slice(0, -1) : x; };
    w = w.replace(/heden$/, "heid");
    var m = /^(.*?)(ene|en)$/.exec(w);
    if (m && m[1].length >= 3 && !isV(m[1].slice(-1)) && !/gem$/.test(m[1])) w = undouble(m[1]);
    else if ((m = /^(.*?)(se|s)$/.exec(w)) && m[1].length >= 3 && !isV(m[1].slice(-1)) && m[1].slice(-1) !== "j") w = m[1];
    if ((m = /^(.*)e$/.exec(w)) && m[1].length >= 3 && !isV(m[1].slice(-1))) w = undouble(m[1]);
    if ((m = /^(.*[^c])heid$/.exec(w)) && m[1].length >= 3) w = m[1];
    if ((m = /^(.*)(ing|end)$/.exec(w)) && m[1].length >= 3) w = /[^e]ig$/.test(m[1]) ? m[1].slice(0, -2) : undouble(m[1]);
    if ((m = /^(.*)(lijk|baar|bar)$/.exec(w)) && m[1].length >= 3) w = m[1];
    return w.replace(/([^aeiouy])(aa|ee|oo|uu)([^aeiouy])$/, function (_, a, b, c) { return a + b[0] + c; });
  }

  function stemZin(t) { return " " + t.trim().split(" ").map(stem).join(" ") + " "; }
  function zorgVoorStammen() {
    if (stemsKlaar) return;
    IDX.forEach(function (r) { r._ts = stemZin(r._t); r._xs = stemZin(r._x); });
    stemsKlaar = true;
  }

  function strip(s) { return (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase(); }
  function norm(s) {
    return strip(s)
      .replace(/\be[\s-]?mail/g, "email")             // e-mail = email
      .replace(/([a-z])(\d)/g, "$1 $2").replace(/(\d)([a-z])/g, "$1 $2") // hdn26 = hdn 26
      .replace(/[^a-z0-9€]+/g, " ");
  }
  function esc(s) { return (s || "").replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  IDX.forEach(function (r) {
    r._t = " " + norm(r.t) + " ";
    r._c = " " + norm(r.c) + " ";
    r._x = " " + norm(r.x) + " ";
  });

  function count(hay, needle, max) {
    var n = 0, i = hay.indexOf(needle);
    while (i !== -1 && n < max) { n++; i = hay.indexOf(needle, i + needle.length); }
    return n;
  }

  function scoreTerm(r, t, st) {
    var s = 0;
    if (r._t.indexOf(" " + t + " ") !== -1) s += 30;
    else if (r._t.indexOf(" " + t) !== -1) s += 20;
    else if (r._t.indexOf(t) !== -1) s += 10;
    if (r._c.indexOf(" " + t) !== -1) s += 6;
    var w = count(r._x, " " + t, 8);
    if (w) s += 4 + w;
    else if (t.length >= 4 && r._x.indexOf(t) !== -1) s += 2;
    if (!s && st && st.length >= 3) {             // andere woordvorm (stam): iets lager dan een exacte treffer
      if (r._ts.indexOf(" " + st + " ") !== -1) s += 18;
      var w2 = count(r._xs, " " + st + " ", 8);
      if (w2) s += 3 + w2;
    }
    return s;
  }

  function search(q) {
    var nq = norm(q).trim();
    terms = nq.split(" ").filter(function (t) { return t && !STOP[t]; });
    if (!terms.length && nq) terms = nq.split(" ").filter(Boolean);
    if (!terms.length) return { list: [], loose: false };
    zorgVoorStammen();
    tstems = terms.map(stem);
    var phrase = " " + nq + " ";
    function run(all) {
      var out = [];
      IDX.forEach(function (r) {
        if (kind && r.k !== kind && !(kind === "nieuws" && r.k === "tips")) return;
        var total = 0, hit = 0;
        for (var i = 0; i < terms.length; i++) {
          var s = scoreTerm(r, terms[i], tstems[i]);
          if (s) { hit++; total += s; } else if (all) return;
        }
        if (!hit) return;
        if (r._t === phrase) total += 120;       // exacte titel altijd bovenaan
        if (terms.length > 1) {
          if (r._t.indexOf(phrase) !== -1 || r._t.indexOf(" " + nq) !== -1) total += 40;
          else if (r._x.indexOf(" " + nq) !== -1) total += 12;
        }
        if (r.k === "categorie") total += 3;
        if (r.o) total -= 5;
        out.push([total + hit * 10, r]);
      });
      out.sort(function (a, b) { return b[0] - a[0]; });
      return out.map(function (x) { return x[1]; });
    }
    var list = run(true), loose = false;
    if (!list.length && terms.length > 1) { list = run(false); loose = true; }
    return { list: list, loose: loose };
  }

  /* Uitsnede rond de eerste treffer, met <mark>. Werkt op de originele tekst. */
  function snippet(text) {
    if (!text) return "";
    var pos = -1, low = strip(text), re = /[a-z0-9]+/g, m;
    while ((m = re.exec(low)) && pos === -1) { if (treft(m[0])) pos = m.index; }
    var start = pos < 0 ? 0 : Math.max(0, pos - 70);
    if (start > 0) { var sp = text.indexOf(" ", start); if (sp !== -1 && sp - start < 20) start = sp + 1; }
    var piece = text.slice(start, start + 230);
    var cut = piece.lastIndexOf(" ");
    if (start + 230 < text.length && cut > 150) piece = piece.slice(0, cut);
    return (start > 0 ? "… " : "") + highlight(piece) + (start + piece.length < text.length ? " …" : "");
  }

  /* Treft dit woord een zoekterm? Begin van het woord (HDN -> HDN25) of dezelfde stam (facturen -> factuur). */
  function treft(w) {
    for (var i = 0; i < terms.length; i++) {
      if (w.indexOf(terms[i]) === 0) return terms[i].length;
      if (tstems[i] && tstems[i].length >= 3 && stem(w) === tstems[i]) return w.length;
    }
    return 0;
  }

  function highlight(s) {
    var low = strip(s), marks = [], re = /[a-z0-9]+/g, m, n;
    while ((m = re.exec(low))) { if ((n = treft(m[0]))) marks.push([m.index, m.index + n]); }
    marks.sort(function (a, b) { return a[0] - b[0]; });
    var out = "", i = 0;
    marks.forEach(function (mk) {
      if (mk[0] < i) return;
      out += esc(s.slice(i, mk[0])) + "<mark>" + esc(s.slice(mk[0], mk[1])) + "</mark>";
      i = mk[1];
    });
    return out + esc(s.slice(i));
  }

  var LABEL = { kennisbank: "Kennisbank", nieuws: "Nieuws", tips: "Tip", release: "Releasenotes", video: "Video", categorie: "Categorie", overig: "Pagina" };

  function card(r) {
    var href = r.ext ? r.h : "../" + r.h;
    var ext = r.ext ? ' target="_blank" rel="noopener"' : "";
    return '<article class="ex"><p class="cpath"><span class="kbadge">' + LABEL[r.k] + "</span>" + esc(r.c) +
      (r.d ? " · " + esc(r.d) : "") + (r.o ? ' <span class="obadge">mogelijk verouderd</span>' : "") + "</p>" +
      '<h2><a href="' + esc(href) + '"' + ext + ">" + highlight(r.t) + "</a></h2>" +
      (r.x && r.k !== "video" ? "<p>" + snippet(r.x) + "</p>" : "") + "</article>";
  }

  function renderMore() {
    resEl.insertAdjacentHTML("beforeend", results.slice(shown, shown + PAGE).map(card).join(""));
    shown = Math.min(results.length, shown + PAGE);
    moreBtn.hidden = shown >= results.length;
  }

  function run(q, push) {
    q = (q || "").trim();
    if (push) {
      var u = new URL(location.href);
      if (q) u.searchParams.set("q", q); else u.searchParams.delete("q");
      history.replaceState(null, "", u);
    }
    resEl.innerHTML = ""; shown = 0;
    if (!q) {
      hEl.textContent = "Zoeken";
      cntEl.textContent = "Typ een zoekterm in het zoekveld hierboven, bijvoorbeeld “HDN”, “Uwkluis” of “factuur”.";
      results = []; moreBtn.hidden = true; return;
    }
    hEl.textContent = "Zoekresultaten voor “" + q + "”";
    var r = search(q);
    results = r.list;
    cntEl.textContent = results.length
      ? results.length + (results.length === 1 ? " resultaat" : " resultaten") + (r.loose ? " (niet alle woorden gevonden; resultaten met één of meer woorden)" : "")
      : "Geen resultaten gevonden. Probeer een ander of korter zoekwoord.";
    renderMore();
  }

  document.querySelectorAll(".sfilters button").forEach(function (b) {
    b.addEventListener("click", function () {
      kind = b.dataset.k;
      document.querySelectorAll(".sfilters button").forEach(function (x) { x.setAttribute("aria-pressed", x === b); });
      run(input.value, false);
    });
  });
  moreBtn.addEventListener("click", renderMore);
  if (input) {
    input.addEventListener("input", function () { clearTimeout(timer); timer = setTimeout(function () { run(input.value, true); }, 150); });
    input.form.addEventListener("submit", function (e) { e.preventDefault(); run(input.value, true); });
  }
  // stammen alvast berekenen als de browser niets te doen heeft, zodat de eerste zoekactie direct is
  (window.requestIdleCallback || function (f) { setTimeout(f, 300); })(zorgVoorStammen);
  var q0 = new URLSearchParams(location.search).get("q") || "";
  if (input) input.value = q0;
  run(q0, false);
  if (input && !q0) input.focus();
})();
