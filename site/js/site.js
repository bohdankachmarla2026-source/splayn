// Shared page behavior: logo, loading indicator, top bar, phone menu, eye (accessibility) button,
// background blob.
(function () {
  "use strict";

  var root = document.documentElement;
  var header = document.querySelector(".site-header");

  // Loading indicator for every page: the Splayn logo printing layer by layer, no text.
  // window.splaynLoader("loader-sm" | "loader-lg" | "") -> element to put where something loads.
  var LAYERS =
    '<rect x="40" y="100" width="40" height="14" rx="7"/><rect x="28" y="80" width="64" height="14" rx="7"/>' +
    '<rect x="20" y="60" width="80" height="14" rx="7"/><rect x="28" y="40" width="64" height="14" rx="7"/>' +
    '<rect class="top" x="40" y="20" width="40" height="14" rx="7"/>';
  window.splaynLoader = function (extraClass) {
    var el = document.createElement("span");
    el.className = "loader" + (extraClass ? " " + extraClass : "");
    el.setAttribute("role", "status");
    el.setAttribute("aria-label", "Завантаження");
    el.innerHTML = '<svg viewBox="18 18 84 98" aria-hidden="true">' + LAYERS + "</svg>";
    return el;
  };

  // The logo stacks up once per visit (on the first page opened), not on every page.
  var logo = document.querySelector(".logo");
  try {
    if (logo && !sessionStorage.getItem("splayn-intro")) {
      logo.classList.add("logo-intro");
      sessionStorage.setItem("splayn-intro", "1");
    }
  } catch (e) { /* storage blocked: no intro */ }

  // Top bar gets a blurred background once the page is scrolled.
  function onScroll() {
    if (header) header.classList.toggle("scrolled", window.scrollY > 8);
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // Phone menu
  var burger = document.getElementById("burger");
  if (burger && header) {
    burger.addEventListener("click", function () {
      var open = !header.classList.contains("open");
      header.classList.toggle("open", open);
      burger.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.querySelectorAll(".nav a").forEach(function (a) {
      a.addEventListener("click", function () {
        header.classList.remove("open");
        burger.setAttribute("aria-expanded", "false");
      });
    });
  }

  // Eye button: larger text and stronger contrast. Remembered per browser when storage works.
  var eye = document.getElementById("a11y-btn");
  function readA11y() { try { return localStorage.getItem("a11y") === "1"; } catch (e) { return false; } }
  function writeA11y(on) { try { localStorage.setItem("a11y", on ? "1" : "0"); } catch (e) { /* storage blocked */ } }
  function applyA11y(on) {
    root.classList.toggle("a11y", on);
    if (eye) eye.setAttribute("aria-pressed", on ? "true" : "false");
  }
  applyA11y(readA11y());
  if (eye) {
    eye.addEventListener("click", function () {
      var on = !root.classList.contains("a11y");
      applyA11y(on);
      writeA11y(on);
    });
  }

  // One background blob slowly drifts toward the pointer (desktop only, respects reduced motion).
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var fine = window.matchMedia && window.matchMedia("(pointer: fine)").matches;
  if (!reduce && fine) {
    var queued = false, mx = 60, my = 40;
    window.addEventListener("pointermove", function (e) {
      mx = (e.clientX / window.innerWidth) * 100;
      my = (e.clientY / window.innerHeight) * 100;
      if (queued) return;
      queued = true;
      requestAnimationFrame(function () {
        queued = false;
        root.style.setProperty("--mx", mx.toFixed(1));
        root.style.setProperty("--my", my.toFixed(1));
      });
    }, { passive: true });
  }
})();
