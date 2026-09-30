/* Firmabok — small, dependency-free UI behaviours. */
(function () {
  "use strict";

  /* ---- mobile menu ---- */
  function initNav() {
    var btn = document.querySelector(".nav-toggle");
    var menu = document.getElementById("main-menu");
    if (!btn || !menu) return;
    btn.addEventListener("click", function () {
      var open = menu.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    /* close after navigating (mobile) */
    menu.addEventListener("click", function (e) {
      if (e.target.closest("a") && window.matchMedia("(max-width: 900px)").matches) {
        menu.classList.remove("open");
        btn.setAttribute("aria-expanded", "false");
      }
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && menu.classList.contains("open")) {
        menu.classList.remove("open");
        btn.setAttribute("aria-expanded", "false");
        btn.focus();
      }
    });
  }

  /* ---- loading state for slow actions (PDF, exports, backups) ---- */
  function initLoading() {
    document.addEventListener("click", function (e) {
      var el = e.target.closest("[data-loading]");
      if (!el) return;
      el.classList.add("is-loading");
      var label = el.getAttribute("data-loading");
      if (label && !el.dataset.origText) {
        el.dataset.origText = el.textContent;
        el.textContent = label;
      }
      /* safety: restore if navigation did not happen (e.g. same-page) */
      setTimeout(function () {
        el.classList.remove("is-loading");
        if (el.dataset.origText) { el.textContent = el.dataset.origText; delete el.dataset.origText; }
      }, 20000);
    });
    document.addEventListener("submit", function (e) {
      var form = e.target.closest("form[data-loading]");
      if (!form) return;
      var btn = form.querySelector("[type=submit]:not([value]), [type=submit][data-primary], button[type=submit]");
      if (btn) {
        btn.classList.add("is-loading");
        btn.disabled = false; /* keep submit going, show spinner */
      }
    });
  }

  /* ---- auto-dismiss non-error flashes after 6 s ---- */
  function initFlash() {
    document.querySelectorAll(".flash-success").forEach(function (el) {
      setTimeout(function () {
        el.style.transition = "opacity .5s";
        el.style.opacity = "0";
        setTimeout(function () { el.remove(); }, 550);
      }, 6000);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initNav();
    initLoading();
    initFlash();
  });
})();
