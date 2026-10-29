/* Gedeelde functies van de supportsite: feedback per artikel, chatknop, nieuwsbrief, scherm delen (ISL). */
(function () {
  "use strict";

  /* "Was deze informatie nuttig?" — zonder server: Ja bedankt, Nee opent een voorgevulde mail aan support. */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-fb]");
    if (!b) return;
    var box = b.closest(".feedback");
    box.querySelectorAll("[data-fb]").forEach(function (x) { x.disabled = true; x.setAttribute("aria-pressed", x === b); });
    var out = box.querySelector(".fb-out");
    if (b.dataset.fb === "ja") {
      out.textContent = "Bedankt voor je feedback!";
    } else {
      var t = document.querySelector("main h1") ? document.querySelector("main h1").textContent.trim() : document.title;
      var u = location.href.split("#")[0].replace(/index\.html(?=$|\?)/, "");
      var mail = "mailto:support-eblinqx@blinqx.tech?subject=" + encodeURIComponent("Feedback op supportartikel: " + t) +
        "&body=" + encodeURIComponent("Artikel: " + t + "\n" + u + "\n\nWat mist er of wat kan beter?\n");
      out.innerHTML = 'Jammer! Laat ons weten wat er beter kan: <a class="fb-mail" href="' + mail + '">mail je opmerking naar support</a>.';
    }
    out.hidden = false;
  });

  /* Nieuwsbrief (HubSpot-formulier van Blinqx V&H): pas laden na een klik. */
  document.addEventListener("click", function (e) {
    var b = e.target.closest("[data-nieuwsbrief]");
    if (!b) return;
    b.disabled = true;
    b.textContent = "Formulier wordt geladen…";
    var s = document.createElement("script");
    s.src = "https://js-eu1.hsforms.net/forms/embed/v2.js";
    s.onload = function () {
      window.hbspt.forms.create({
        region: "eu1", portalId: "143378200", formId: "cfe966df-8f53-471d-8112-05ad6acd826c", target: "#nb-form",
        // het formulier is gestyled voor de donkere footer van Blinqx: na het laden de teksten donker maken
        onFormReady: function (form) {
          var f = form && (form.jquery ? form[0] : form);
          var doc = f && f.ownerDocument;
          if (!doc) return;
          var st = doc.createElement("style");
          st.textContent = "label, label span, label p, .hs-richtext, .hs-richtext p{color:#1D2632 !important}";
          doc.head.appendChild(st);
        }
      });
      b.remove();
    };
    s.onerror = function () {
      b.textContent = "Het formulier kon niet worden geladen";
      document.getElementById("nb-fallback").hidden = false;
    };
    document.head.appendChild(s);
  });

  /* Scherm delen via ISL Online (zoals op de oorspronkelijke contactpagina). */
  var isl = document.getElementById("isl-connect-form");
  if (isl) {
    var api = document.createElement("script");
    api.src = "https://www.islonline.net/webapi/api.js?libs=join";
    document.head.appendChild(api);
    isl.addEventListener("submit", function (e) {
      e.preventDefault();
      var r = document.getElementById("isl-feedback"), code = isl.code.value.trim();
      if (!code) { r.textContent = "Vul eerst de sessiecode in die je van support hebt gekregen."; return; }
      if (!window.ISLOnline || !window.ISLOnline.Join) {
        r.innerHTML = 'Scherm delen kon niet worden gestart. Gebruik <a href="https://www.islonline.net/users/main/join.html" target="_blank" rel="noopener">de ISL Online-pagina</a> en vul daar je code in.';
        return;
      }
      r.textContent = "Bezig met verbinden…";
      var klaar = false;
      setTimeout(function () {
        if (klaar) return;
        r.innerHTML = 'Er komt geen antwoord van ISL Online. Ga naar <a href="https://www.islonline.net/users/main/join.html" target="_blank" rel="noopener">de ISL Online-pagina</a> en vul daar je sessiecode in.';
      }, 10000);
      window.ISLOnline.Join.getSessionInfoByCode(code, function (info) {
        klaar = true;
        r.className = "isl-ok";
        r.textContent = "Verbinden met sessie " + info.getAttribute("sessionCode") + "…";
        info.join();
      }, function () {
        klaar = true;
        r.className = "isl-fout";
        r.innerHTML = 'Deze sessiecode is niet geldig. Controleer de code, of gebruik <a href="https://www.islonline.net/users/main/join.html" target="_blank" rel="noopener">de ISL Online-pagina</a>.';
      });
    });
  }

  /* Chatknop (Blinqx-chatbot, zoals op de oorspronkelijke site): laden zodra de pagina klaar is. */
  function chat() {
    var s = document.createElement("script");
    s.src = "https://chatbot-prod-we-ffapp.azurewebsites.net/assets/chat-embed.js";
    s.id = "my-chatbot-js";
    s.async = true;
    document.body.appendChild(s);
  }
  if (document.readyState === "complete") setTimeout(chat, 800);
  else window.addEventListener("load", function () { setTimeout(chat, 800); });
})();
