// Start page: one field for text and files, backed by the AI assistant (/api/chat).
// After the first message the page turns into a chat: messages above, the field at the bottom.
// Price cards show the part in 3D on the plate (js/viewer.js) and let the customer change
// plastic, quality (re-priced by the server) and colour. Printables models get cards with «Порахувати».
(function () {
  "use strict";

  var MAX_BYTES = 50 * 1024 * 1024;
  var ALLOWED = ["stl", "3mf", "obj"];
  var MATERIAL = { pla: "PLA", petg: "PETG", abs: "ABS" };

  var form = document.getElementById("composer");
  var prompt = document.getElementById("prompt");
  var input = document.getElementById("file");
  var list = document.getElementById("files");
  var send = document.getElementById("send");
  var note = document.getElementById("note");
  var thread = document.getElementById("thread");
  if (!form || !prompt || !thread) return;

  var files = [];
  var conversationId = null;
  var busy = false;

  // Typed on the English layout by mistake: "ot dfhsfynb" becomes "ще варіанти" (js/layout-fix.js).
  if (window.LayoutFix) window.LayoutFix.attach(prompt);

  // ---------- field ----------

  function autosize() {
    prompt.style.height = "auto";
    prompt.style.height = Math.min(prompt.scrollHeight, 200) + "px";
  }

  function refresh() {
    send.disabled = busy || (!prompt.value.trim() && files.length === 0);
    list.innerHTML = "";
    files.forEach(function (f, i) {
      var chip = document.createElement("span");
      chip.className = "file-chip";
      chip.textContent = f.name;
      var x = document.createElement("button");
      x.type = "button";
      x.setAttribute("aria-label", "Прибрати файл " + f.name);
      x.textContent = "×";
      x.addEventListener("click", function () { files.splice(i, 1); refresh(); });
      chip.appendChild(x);
      list.appendChild(chip);
    });
  }

  function add(fileList) {
    var rejected = [];
    Array.prototype.forEach.call(fileList, function (f) {
      var ext = (f.name.split(".").pop() || "").toLowerCase();
      if (ALLOWED.indexOf(ext) === -1 || f.size === 0 || f.size > MAX_BYTES) { rejected.push(f.name); return; }
      if (files.length < 5) files.push(f);
    });
    note.textContent = rejected.length ? "Не додано: " + rejected.join(", ") + ". Підходять STL, 3MF, OBJ до 50 МБ." : "";
    refresh();
  }

  prompt.addEventListener("input", function () { autosize(); refresh(); });
  prompt.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!send.disabled) form.requestSubmit(); }
  });
  input.addEventListener("change", function () { add(input.files); input.value = ""; });

  ["dragenter", "dragover"].forEach(function (ev) {
    form.addEventListener(ev, function (e) { e.preventDefault(); form.classList.add("over"); });
  });
  ["dragleave", "drop"].forEach(function (ev) {
    form.addEventListener(ev, function (e) { e.preventDefault(); form.classList.remove("over"); });
  });
  form.addEventListener("drop", function (e) { if (e.dataTransfer) add(e.dataTransfer.files); });

  // ---------- messages ----------

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Readable link text: decoded (Cyrillic instead of %D1%88...), no https://www., shortened.
  function linkLabel(url) {
    var label = url.replace(/&amp;/g, "&");
    try { label = decodeURIComponent(label.replace(/\+/g, " ")); } catch (e) { /* keep as is */ }
    label = label.replace(/^https?:\/\/(www\.)?/, "");
    return label.length > 60 ? label.slice(0, 57) + "…" : label;
  }

  // Plain text from the assistant -> safe HTML: links, **bold**, line breaks.
  function format(text) {
    var html = escapeHtml(text);
    html = html.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    html = html.replace(/(https?:\/\/[^\s<]+[^\s<.,;:!?)\]])/g, function (url) {
      return '<a href="' + url + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(linkLabel(url)) + "</a>";
    });
    return html.replace(/\n/g, "<br>");
  }

  function scrollDown() {
    window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
  }

  function addMessage(role, html) {
    var el = document.createElement("div");
    el.className = "msg msg-" + role;
    el.innerHTML = html;
    thread.appendChild(el);
    scrollDown();
    return el;
  }

  function addUser(text, names) {
    var html = text ? format(text) : "";
    if (names.length) {
      html += '<div class="msg-files">' + names.map(function (n) {
        return '<span class="file-chip">' + escapeHtml(n) + "</span>";
      }).join("") + "</div>";
    }
    addMessage("user", html);
  }

  // ---------- price card: 3D view, plastic, quality, colour ----------

  var COLORS = [
    { name: "Білий", hex: "#f3f0ea" },
    { name: "Чорний", hex: "#232120" },
    { name: "Сірий", hex: "#9b9792" },
    { name: "Червоний", hex: "#d4302a" },
    { name: "Помаранчевий", hex: "#ff6b2c" },
    { name: "Жовтий", hex: "#f4c21b" },
    { name: "Зелений", hex: "#2f9e55" },
    { name: "Синій", hex: "#2b62d3" }
  ];
  var QUALITY_LABEL = { draft: "Чернетка", standard: "Стандарт", fine: "Висока" };
  var QUALITY_HINT = { draft: "шар 0,28 мм", standard: "шар 0,20 мм", fine: "шар 0,12 мм" };
  var UAH = new Intl.NumberFormat("uk-UA", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  var GRAMS = new Intl.NumberFormat("uk-UA", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  var viewerModule = null;
  function loadViewer() {
    if (!viewerModule) viewerModule = import("/js/viewer.js");
    return viewerModule;
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function duration(mins) {
    return mins >= 60 ? Math.floor(mins / 60) + " год " + (mins % 60) + " хв" : mins + " хв";
  }

  function licenseBadge(license, ok) {
    var b = el("span", "badge " + (ok ? "ok" : "warn"), ok ? "Можна на продаж · " + license : "Потрібен дозвіл автора · " + license);
    b.title = ok ? "Ліцензія дозволяє друкувати на замовлення" : "Ліцензія не дозволяє продавати друк без дозволу автора";
    return b;
  }

  // Segmented control; onPick(value) is called on a new choice.
  function segmented(options, current, onPick) {
    var wrap = el("div", "seg");
    options.forEach(function (o) {
      var b = el("button", null, o.label);
      b.type = "button";
      b.dataset.value = o.value;
      if (o.title) b.title = o.title;
      b.setAttribute("aria-pressed", String(o.value === current));
      b.addEventListener("click", function () {
        if (b.getAttribute("aria-pressed") === "true") return;
        onPick(o.value);
      });
      wrap.appendChild(b);
    });
    return wrap;
  }

  function press(group, value) {
    Array.prototype.forEach.call(group.children, function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.value === value));
    });
  }

  function option(label, control) {
    var box = el("div", "opt");
    box.appendChild(el("div", "opt-label", label));
    box.appendChild(control);
    return box;
  }

  function buildQuoteCard(q) {
    var state = { material: q.material, quality: q.quality, qty: q.qty, color: COLORS[0].hex, request: 0 };
    var card = el("div", "quote");

    // 3D view
    var view = el("div", "quote-view");
    var note = el("div", "view-note");
    note.appendChild(window.splaynLoader("loader-lg"));
    var tools = el("div", "view-tools");
    var frameBtn = el("button", null, "Весь стіл");
    frameBtn.type = "button";
    frameBtn.hidden = true;
    tools.appendChild(frameBtn);
    var hint = el("div", "view-hint", "Тягніть, щоб покрутити");
    hint.hidden = true;
    view.appendChild(note);
    view.appendChild(hint);
    view.appendChild(tools);
    card.appendChild(view);
    var viewer = null;

    // Details
    var body = el("div", "quote-body");
    body.appendChild(el("div", "quote-head", q.file));
    if (q.source) {
      var src = el("div", "quote-source");
      src.appendChild(el("span", null, q.source.site));
      src.appendChild(licenseBadge(q.source.license, q.source.license_ok));
      var a = el("a", null, "Сторінка моделі");
      a.href = q.source.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      src.appendChild(a);
      body.appendChild(src);
    }

    var materialSeg = segmented(
      ["pla", "petg", "abs"].map(function (m) { return { value: m, label: MATERIAL[m] }; }),
      state.material, function (v) { requote({ material: v }); });
    var qualitySeg = segmented(
      ["draft", "standard", "fine"].map(function (v) { return { value: v, label: QUALITY_LABEL[v], title: QUALITY_HINT[v] }; }),
      state.quality, function (v) { requote({ quality: v }); });
    body.appendChild(option("Пластик", materialSeg));
    body.appendChild(option("Якість", qualitySeg));

    var swatches = el("div", "swatches");
    COLORS.forEach(function (c) {
      var s = el("button");
      s.type = "button";
      s.title = c.name;
      s.setAttribute("aria-label", "Колір: " + c.name);
      s.dataset.value = c.hex;
      s.style.setProperty("--swatch", c.hex);
      s.setAttribute("aria-pressed", String(c.hex === state.color));
      s.addEventListener("click", function () {
        state.color = c.hex;
        card.dataset.color = c.name;
        press(swatches, c.hex);
        if (viewer) viewer.setColor(c.hex);
      });
      swatches.appendChild(s);
    });
    card.dataset.color = COLORS[0].name;
    body.appendChild(option("Колір", swatches));

    var nums = el("div", "quote-nums");
    var totalRow = el("div", "quote-total-row");
    var total = el("div", "quote-total");
    totalRow.appendChild(total);
    totalRow.appendChild(window.splaynLoader("loader-sm")); // shown while re-pricing
    var error = el("div", "quote-error");
    error.setAttribute("role", "status");
    body.appendChild(nums);
    body.appendChild(totalRow);
    body.appendChild(error);
    card.appendChild(body);

    function show(r) {
      nums.textContent = GRAMS.format(r.grams) + " г пластику · " + duration(r.minutes) + " друку · " + r.qty + " шт.";
      total.textContent = UAH.format(r.total) + " ₴";
    }
    show(q);

    // Another plastic or quality: the server slices again (or answers from its cache).
    function requote(change) {
      var next = { material: change.material || state.material, quality: change.quality || state.quality };
      press(materialSeg, next.material);
      press(qualitySeg, next.quality);
      error.textContent = "";
      card.classList.add("busy");
      var id = ++state.request;
      fetch("/api/requote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_id: q.file_id, material: next.material, quality: next.quality, qty: state.qty })
      })
        .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, data: d }; }); })
        .then(function (r) {
          if (id !== state.request) return; // a newer choice is on its way
          card.classList.remove("busy");
          if (!r.ok) throw new Error(r.data.error || "Не вдалося перерахувати.");
          state.material = next.material;
          state.quality = next.quality;
          show(r.data.quote);
        })
        .catch(function (err) {
          if (id !== state.request) return;
          card.classList.remove("busy");
          press(materialSeg, state.material);
          press(qualitySeg, state.quality);
          error.textContent = err && err.message && err.message !== "Failed to fetch" ? err.message : "Немає зв'язку з сервером.";
        });
    }

    if (!q.file_id) {
      note.textContent = "3D-перегляд недоступний";
      return card;
    }
    loadViewer()
      .then(function (mod) {
        viewer = mod.createView(view, "/api/view/" + q.file_id, state.color, function (s) {
          if (s === "ready") {
            note.hidden = true;
            frameBtn.hidden = false;
            hint.hidden = false;
          } else if (s === "error") {
            note.hidden = false;
            note.textContent = "3D-перегляд недоступний";
          }
        });
      })
      .catch(function () { note.textContent = "3D-перегляд недоступний"; });
    frameBtn.addEventListener("click", function () {
      if (!viewer) return;
      frameBtn.textContent = viewer.toggleFrame() === "plate" ? "До моделі" : "Весь стіл";
    });
    view.addEventListener("pointerdown", function () { hint.hidden = true; });
    return card;
  }

  // ---------- found models (Printables) ----------

  function fileSize(bytes) {
    return bytes >= 1e6 ? (bytes / 1e6).toFixed(1).replace(".", ",") + " МБ" : Math.max(1, Math.round(bytes / 1e3)) + " КБ";
  }

  function importModel(m, fileId, buttons, error) {
    buttons.forEach(function (b) { b.disabled = true; });
    error.textContent = "";
    var dots = typing();
    return fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fileId ? { model_id: m.id, file_id: fileId } : { model_id: m.id })
    })
      .then(function (res) { return res.json().then(function (d) { return { ok: res.ok, data: d }; }); })
      .then(function (r) {
        dots.remove();
        if (!r.ok) throw new Error(r.data.error || "Не вдалося порахувати модель.");
        return r.data;
      })
      .catch(function (err) {
        if (dots.isConnected) dots.remove();
        error.textContent = err && err.message && err.message !== "Failed to fetch" ? err.message : "Немає зв'язку з сервером.";
        return null;
      })
      .then(function (data) {
        buttons.forEach(function (b) { b.disabled = false; });
        return data;
      });
  }

  function buildModelCard(m) {
    var card = el("div", "model");
    if (m.image) {
      var pic = el("div", "model-pic");
      pic.appendChild(window.splaynLoader()); // until the photo arrives
      var img = el("img");
      img.alt = m.name;
      img.loading = "lazy";
      img.referrerPolicy = "no-referrer";
      img.addEventListener("load", function () { pic.classList.add("loaded"); });
      img.addEventListener("error", function () { pic.classList.add("loaded", "broken"); });
      img.src = m.image;
      pic.appendChild(img);
      card.appendChild(pic);
    }
    var body = el("div", "model-body");
    body.appendChild(el("div", "model-name", m.name));
    var badgeRow = el("div");
    badgeRow.appendChild(licenseBadge(m.license, m.license_ok));
    body.appendChild(badgeRow);
    var files = el("div", "model-files");
    files.hidden = true;
    var error = el("div", "model-error");
    var actions = el("div", "model-actions");
    var go = el("button", "btn-sm", "Порахувати");
    go.type = "button";
    var link = el("a", null, m.source + " ↗");
    link.href = m.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    actions.appendChild(go);
    actions.appendChild(link);
    body.appendChild(files);
    body.appendChild(error);
    body.appendChild(actions);
    card.appendChild(body);

    function showQuote(data) {
      if (data && data.quote) addAssistant("", [data.quote], []);
    }

    function showFiles(list) {
      files.innerHTML = "";
      files.hidden = false;
      go.hidden = true;
      var buttons = [];
      list.forEach(function (f) {
        var tooBig = f.size > MAX_BYTES;
        var b = el("button");
        b.type = "button";
        b.appendChild(document.createTextNode(f.name + " "));
        b.appendChild(el("span", null, fileSize(f.size) + (tooBig ? " — завеликий" : "")));
        if (tooBig) {
          b.disabled = true;
          b.title = "Файли понад 50 МБ ми поки не приймаємо";
        } else {
          b.addEventListener("click", function () {
            importModel(m, f.id, buttons, error).then(showQuote);
          });
          buttons.push(b);
        }
        files.appendChild(b);
      });
    }

    if (m.pick && m.files && m.files.length > 1) showFiles(m.files);
    go.addEventListener("click", function () {
      if (m.files && m.files.length > 1) return showFiles(m.files);
      importModel(m, null, [go], error).then(function (data) {
        if (data && data.files) showFiles(data.files);
        else showQuote(data);
      });
    });
    return card;
  }

  function addAssistant(reply, quotes, models) {
    var msg = addMessage("assistant", format(reply || ""));
    if (quotes && quotes.length) {
      var q = el("div", "quotes");
      quotes.forEach(function (item) { q.appendChild(buildQuoteCard(item)); });
      msg.appendChild(q);
    }
    if (models && models.length) {
      var list = el("div", "models");
      models.forEach(function (m) { list.appendChild(buildModelCard(m)); });
      msg.appendChild(list);
    }
    if ((quotes && quotes.length) || (models && models.length)) {
      msg.classList.add("wide");
      if (!reply) msg.querySelector(".quotes, .models").style.marginTop = "0";
      scrollDown();
    }
  }

  // The assistant is working: the Splayn logo builds up in its bubble.
  function typing() {
    var msg = addMessage("assistant loading", "");
    msg.appendChild(window.splaynLoader());
    return msg;
  }

  // ---------- send ----------

  function upload(file) {
    return fetch("/api/upload", {
      method: "POST",
      headers: { "X-Filename": encodeURIComponent(file.name), "Content-Type": "application/octet-stream" },
      body: file
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || "Не вдалося завантажити " + file.name);
        return data.file_id;
      });
    });
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (busy) return;
    // The last word has no space after it yet: convert it (and anything pasted) now.
    var text = (window.LayoutFix ? window.LayoutFix.text(prompt.value) : prompt.value).trim();
    var sending = files.slice();
    if (!text && !sending.length) return;

    document.body.classList.add("chatting");
    addUser(text, sending.map(function (f) { return f.name; }));
    prompt.value = "";
    files = [];
    note.textContent = "";
    busy = true;
    autosize();
    refresh();
    var dots = typing();

    Promise.all(sending.map(upload))
      .then(function (ids) {
        return fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ conversation_id: conversationId, text: text, file_ids: ids })
        });
      })
      .then(function (res) {
        return res.json().then(function (data) { return { ok: res.ok, data: data }; });
      })
      .then(function (r) {
        dots.remove();
        if (!r.ok) { addMessage("assistant error", format(r.data.error || "Щось пішло не так.")); return; }
        conversationId = r.data.conversation_id;
        addAssistant(r.data.reply, r.data.quotes, r.data.models);
      })
      .catch(function (err) {
        dots.remove();
        addMessage("assistant error", format(err && err.message ? err.message : "Немає зв'язку з сервером."));
      })
      .then(function () {
        busy = false;
        refresh();
        prompt.focus();
      });
  });

  autosize();
  refresh();
})();
