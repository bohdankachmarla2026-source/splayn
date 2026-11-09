// Light prototype logic. Price comes from /api/quote (server/app.py).
(function () {
  "use strict";

  var MAX_BYTES = 50 * 1024 * 1024;
  var ALLOWED = ["stl", "3mf", "obj"];

  function $(id) { return document.getElementById(id); }

  function validate(file) {
    var ext = (file.name.split(".").pop() || "").toLowerCase();
    if (ALLOWED.indexOf(ext) === -1) return "Непідтримуваний формат. Дозволено: STL, 3MF, OBJ.";
    if (file.size > MAX_BYTES) return "Файл більший за 50 МБ.";
    if (file.size === 0) return "Файл порожній.";
    return "";
  }

  // Home page: just show the chosen name.
  function bindDropzone(dropId, inputId, nameId, errId, onFile) {
    var drop = $(dropId), input = $(inputId);
    if (!drop || !input) return;

    function take(file) {
      var err = validate(file);
      $(errId).textContent = err;
      if (err) return;
      $(nameId).textContent = file.name;
      if (onFile) onFile(file);
    }

    drop.addEventListener("click", function () { input.click(); });
    drop.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); }
    });
    input.addEventListener("change", function () { if (input.files[0]) take(input.files[0]); });
    drop.addEventListener("dragover", function (e) { e.preventDefault(); drop.classList.add("over"); });
    drop.addEventListener("dragleave", function () { drop.classList.remove("over"); });
    drop.addEventListener("drop", function (e) {
      e.preventDefault();
      drop.classList.remove("over");
      if (e.dataTransfer.files[0]) take(e.dataTransfer.files[0]);
    });
  }

  // Price comes from the server, which slices the file with PrusaSlicer.
  // A request counter drops answers to old requests when the user changes settings fast.
  var currentFile = null;
  var requestId = 0;

  function showEmpty(text) {
    $("price").textContent = "— ₴";
    $("details").textContent = "";
    $("order").disabled = true;
    $("status").textContent = text;
  }

  function quote() {
    if (!currentFile) { showEmpty("Спочатку завантажте файл."); return; }

    var mine = ++requestId;
    var qty = Math.min(100, Math.max(1, parseInt($("qty").value, 10) || 1));
    var url = "/api/quote?material=" + encodeURIComponent($("material").value) +
              "&quality=" + encodeURIComponent($("quality").value) +
              "&qty=" + qty;

    showEmpty("");
    if (window.splaynLoader) $("status").appendChild(window.splaynLoader()); // logo builds up while slicing

    fetch(url, {
      method: "POST",
      // URL-encoded so Cyrillic file names survive the HTTP header
      headers: { "X-Filename": encodeURIComponent(currentFile.name), "Content-Type": "application/octet-stream" },
      body: currentFile
    }).then(function (res) {
      return res.json().then(function (data) { return { ok: res.ok, data: data }; }, function () {
        // Not JSON: the page is probably served by something other than server/app.py
        return { ok: false, data: { error: "Сервер повернув неочікувану відповідь. Перевірте, що працює server/app.py." } };
      });
    }).then(function (r) {
      if (mine !== requestId) return;               // stale answer
      if (!r.ok) { showEmpty(r.data.error || "Помилка розрахунку."); return; }
      var d = r.data;
      $("price").textContent = d.total.toFixed(2) + " ₴";
      $("details").textContent = "≈ " + d.grams.toFixed(2) + " г, ≈ " + d.minutes + " хв, " + d.qty + " шт.";
      $("status").textContent = "Розраховано слайсером. Остаточна ціна після перевірки файлу.";
      $("order").disabled = false;
    }).catch(function () {
      if (mine !== requestId) return;
      if (window.location.protocol === "file:") {
        showEmpty("Відкрийте сторінку через http://127.0.0.1:8000/upload.html, а не з файлу.");
      } else {
        showEmpty("Сервер розрахунку не відповідає. Запустіть server/app.py і оновіть сторінку.");
      }
    });
  }

  bindDropzone("drop", "file", "file-name", "file-error", function (file) {
    currentFile = file;
    quote();
  });
  bindDropzone("home-drop", "home-file", "home-name", "home-error", null);

  ["material", "quality", "qty"].forEach(function (id) {
    var el = $(id);
    if (el) el.addEventListener("change", quote);
  });

  var order = $("order");
  if (order) {
    order.addEventListener("click", function () {
      // Placeholder: checkout is not built yet.
      $("status").textContent = "Оформлення замовлення буде підключено на наступному етапі.";
    });
  }
})();
