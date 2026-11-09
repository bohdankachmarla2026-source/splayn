// MacBook Air scroll story. Everything is scrubbed by the scroll position,
// so scrolling back plays it backwards.
// 1) Start of the section: the lid opens around the hinge (-90deg closed -> 0deg,
//    upright, 90deg to the table) while the camera moves from a top view to the front.
// 2) Rest of the section drives one timeline on the screen: the customer asks the AI,
//    gets a description and photos, approves; the order is confirmed; the shot moves
//    to the printer; the part goes into a box; tape and a waybill label; the van leaves.
(function () {
  "use strict";

  var section = document.querySelector(".story");
  if (!section) return;

  var rig = section.querySelector(".rig");
  var lid = section.querySelector(".lid");
  var bar = document.querySelector(".progress-bar");
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var OPEN_END = 0.10;   // lid fully open at 10% of the section

  // Camera and framing: closed (top view, further away) -> open (front view).
  // tx, ty, tz are in laptop widths.
  var CLOSED = { rx: -40, ry: -14, tx: 0.09, ty: -0.22, tz: -0.6 };
  var OPEN = { rx: -8, ry: 0, tx: 0, ty: 0.30, tz: 0 };

  // ---------- helpers ----------
  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
  function seg(t, a, b) { return clamp01((t - a) / (b - a)); }
  function lerp(a, b, t) { return a + (b - a) * t; }
  function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function easeBack(t) { var c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2); }
  function $(id) { return document.getElementById(id); }
  function set(el, name, v) { if (el) el.setAttribute(name, v); }
  function op(el, v) { if (el) el.setAttribute("opacity", Math.max(0, Math.min(1, v)).toFixed(3)); }
  function f(n) { return n.toFixed(2); }
  function about(cx, cy, s) { return "translate(" + cx + " " + cy + ") scale(" + f(s) + ") translate(" + -cx + " " + -cy + ")"; }

  // ---------- Keyboard (MacBook layout, widths in key units) ----------
  var ROWS = [
    { cls: "fn", keys: [1.5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, "touchid"] },
    { keys: [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1.5] },
    { keys: [1.5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1] },
    { keys: [1.8, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1.7] },
    { keys: [2.3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2.2] },
    { keys: [1, 1, 1, 1.25, 5, 1.25, 1, "arrows"] }
  ];
  var kb = section.querySelector(".keyboard");
  if (kb) {
    ROWS.forEach(function (row) {
      var r = document.createElement("div");
      r.className = "krow" + (row.cls ? " " + row.cls : "");
      row.keys.forEach(function (k) {
        if (k === "arrows") {
          var a = document.createElement("div");
          a.className = "arrows";
          a.style.flex = "3 1 0";
          a.innerHTML =
            '<div class="key half" style="width:31%"></div>' +
            '<div class="ud" style="width:31%"><div class="key"></div><div class="key"></div></div>' +
            '<div class="key half" style="width:31%"></div>';
          r.appendChild(a);
          return;
        }
        var key = document.createElement("div");
        key.className = "key" + (k === "touchid" ? " touchid" : "");
        key.style.flex = (k === "touchid" ? 1 : k) + " 1 0";
        r.appendChild(key);
      });
      kb.appendChild(r);
    });
  }

  // ---------- Rounded side walls (base and lid) ----------
  // CSS can round a flat face but not the walls around it, so each wall ring is built
  // from strips: one per straight side and ARC_STEPS per rounded corner.
  // Factors match the CSS variables in .stage3d (--d, --tb, --tl, --r).
  var stage = section.querySelector(".stage3d");
  var baseWalls = section.querySelector(".base-walls");
  var lidWalls = section.querySelector(".lid-walls");
  var ARC_STEPS = 12;
  var DEG = Math.PI / 180;

  // Strips around a rounded rectangle in the (u, v) plane.
  // th is the outward normal angle: 0 = +u, 90 = +v (front / bottom), 180 = -u, 270 = -v.
  function perimeter(W, D, R) {
    var out = [
      { u: W, v: D / 2, len: D - 2 * R, th: 0 },
      { u: W / 2, v: D, len: W - 2 * R, th: 90, front: true },
      { u: 0, v: D / 2, len: D - 2 * R, th: 180 },
      { u: W / 2, v: 0, len: W - 2 * R, th: 270 }
    ];
    var centers = [[W - R, D - R], [R, D - R], [R, R], [W - R, R]];
    var step = 90 / ARC_STEPS;
    var segLen = 2 * R * Math.tan((step / 2) * DEG) * 1.15;   // polygon side + small overlap
    for (var q = 0; q < 4; q++) {
      for (var i = 0; i < ARC_STEPS; i++) {
        var th = q * 90 + step * (i + 0.5);
        out.push({
          u: centers[q][0] + R * Math.cos(th * DEG),
          v: centers[q][1] + R * Math.sin(th * DEG),
          len: segLen,
          th: th
        });
      }
    }
    return out;
  }

  function gray(l) {
    var v = Math.max(0, Math.min(255, Math.round(l)));
    return "rgb(" + v + "," + Math.min(255, v + 3) + "," + Math.min(255, v + 7) + ")";
  }

  function buildWalls() {
    if (!stage) return;
    var W = stage.clientWidth;
    var D = W * 0.707, Tb = W * 0.024, Tl = W * 0.012, R = W * 0.034;

    if (baseWalls) {
      baseWalls.innerHTML = "";
      perimeter(W, D, R).forEach(function (s) {
        var nx = Math.cos(s.th * DEG), nz = Math.sin(s.th * DEG);
        var L = s.len + 1;
        var el = document.createElement("div");
        el.style.width = L + "px";
        el.style.height = Tb + "px";
        el.style.transform =
          "translate3d(" + (s.u - L / 2) + "px,0," + s.v + "px) rotateY(" + (Math.atan2(nx, nz) / DEG) + "deg)";
        var light = 150 + 40 * nz - 18 * nx;   // light from the front, slightly from the left
        el.style.background = "linear-gradient(180deg," + gray(light + 10) + "," + gray(light - 28) + ")";
        if (s.front) {
          var sc = document.createElement("div");
          sc.className = "scoop-front";
          el.appendChild(sc);
        }
        baseWalls.appendChild(el);
      });
    }

    if (lidWalls) {
      lidWalls.innerHTML = "";
      perimeter(W, D, R).forEach(function (s) {
        var nx = Math.cos(s.th * DEG), ny = Math.sin(s.th * DEG);
        var L = s.len + 1;
        var el = document.createElement("div");
        el.style.width = L + "px";
        el.style.height = Tl + "px";
        el.style.transform =
          "translate3d(" + (s.u - L / 2) + "px," + (s.v - Tl / 2) + "px," + (-Tl / 2) + "px) " +
          "rotateZ(" + (Math.atan2(nx, -ny) / DEG) + "deg) rotateX(90deg)";
        el.style.background = gray(150 - 30 * ny - 14 * nx);
        lidWalls.appendChild(el);
      });
    }
  }
  buildWalls();
  var resizeTimer = null;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(buildWalls, 150);
  });

  // ---------- Storyboard setup (no text anywhere: words and lines are drawn as bars) ----------
  function gearPath(cx, cy, rOut, rIn, teeth, hole) {
    var pts = [], steps = teeth * 4;
    for (var i = 0; i < steps; i++) {
      var ang = (i / steps) * Math.PI * 2;
      var r = (i % 4 === 1 || i % 4 === 2) ? rOut : rIn;
      pts.push((cx + r * Math.cos(ang)).toFixed(2) + " " + (cy + r * Math.sin(ang)).toFixed(2));
    }
    var d = "M" + pts.join(" L") + " Z";
    if (hole) {
      d += " M" + (cx + hole) + " " + cy +
        " A" + hole + " " + hole + " 0 1 0 " + (cx - hole) + " " + cy +
        " A" + hole + " " + hole + " 0 1 0 " + (cx + hole) + " " + cy + " Z";
    }
    return d;
  }
  set($("thumb1"), "d", gearPath(85, 178, 18, 14.5, 12, 4));
  set($("thumb2b"), "d", gearPath(163, 182, 18, 14.5, 12, 4));
  set($("thumb2a"), "d", gearPath(163, 178, 18, 14.5, 12, 4));
  set($("thumb3a"), "d", gearPath(236, 184, 15, 12, 12, 3.5));
  set($("thumb3b"), "d", gearPath(256, 168, 9.5, 7.2, 8, 2.5));
  var GEAR = gearPath(0, 0, 30, 25.5, 12, 6);   // the printed part, drawn around (0, 0)
  set($("gearPrint"), "d", GEAR);
  set($("gearPrint"), "transform", "translate(150 140)");
  set($("gearMove"), "d", GEAR);

  // "Words" in the input field: bars of different length, revealed left to right
  var WORDS = [30, 48, 20, 36, 16, 44, 28, 22, 34, 18, 26];
  var WORDS_X = 40, WORD_GAP = 5;
  var wordsEl = $("words");
  var typedWidth = 0;
  if (wordsEl) {
    var wx = WORDS_X, wh = "";
    WORDS.forEach(function (w) {
      wh += '<rect x="' + wx + '" y="312.5" width="' + w + '" height="5" rx="2.5" fill="#1d1d1f" fill-opacity="0.7"/>';
      wx += w + WORD_GAP;
    });
    wordsEl.innerHTML = wh;
    typedWidth = wx - WORD_GAP - WORDS_X;
  }

  // Barcode on the waybill label
  var bc = $("barcode");
  if (bc) {
    var BW = [0.7, 1.3, 0.5, 1.9, 0.9, 1.4, 0.6, 1.1];
    var x = 0, i = 0, html = "";
    while (x < 84) {
      var w = BW[(i * 5 + 3) % BW.length];
      if (i % 2 === 0) html += '<rect x="' + x.toFixed(2) + '" y="0" width="' + w + '" height="12" fill="#1d1d1f"/>';
      x += w;
      i++;
    }
    bc.innerHTML = html;
  }

  var el = {
    chat: $("chat"), shop: $("shop"), cam: $("cam"),
    typeClipRect: $("typeClipRect"), caret: $("caret"),
    uBubble: $("uBubble"), aiAvatar: $("aiAvatar"), dots: $("dots"), aBubble: $("aBubble"),
    buttons: $("buttons"), approveRect: $("approveRect"), cursor: $("cursor"),
    confirm: $("confirm"), confirmCard: $("confirmCard"), confirmRing: $("confirmRing"), confirmCheck: $("confirmCheck"),
    printClipRect: $("printClipRect"), gearPrint: $("gearPrint"), head: $("head"), rail: $("rail"),
    door: $("door"), progress: $("progress"), gearMove: $("gearMove"),
    flapBack: $("flapBack"), flapFront: $("flapFront"),
    tape: $("tape"), tapeBand: $("tapeBand"), tapeShine: $("tapeShine"), tapeGun: $("tapeGun"),
    label: $("label"), labelShadow: $("labelShadow"),
    box: $("box"), van: $("van"), done: $("done")
  };
  var dotEls = Array.prototype.slice.call(section.querySelectorAll("#dots .dot"));
  var alines = Array.prototype.slice.call(section.querySelectorAll("#aBubble .aline"));
  var photos = Array.prototype.slice.call(section.querySelectorAll(".photo"));
  var stageDots = Array.prototype.slice.call(section.querySelectorAll("#stageDots circle"));
  var PHOTO_CENTERS = [[85, 178], [163, 178], [241, 178]];

  // Camera keyframes in the workshop: center (cx, cy) in world units and zoom s.
  var CAM = [
    { t: 0.34, cx: 150, cy: 124, s: 1.0 },
    { t: 0.40, cx: 150, cy: 124, s: 1.35 },   // printer
    { t: 0.56, cx: 150, cy: 124, s: 1.35 },
    { t: 0.60, cx: 275, cy: 130, s: 1.1 },    // printer + box
    { t: 0.66, cx: 275, cy: 130, s: 1.1 },
    { t: 0.69, cx: 412, cy: 160, s: 2.0 },    // close-up on the box
    { t: 0.86, cx: 412, cy: 160, s: 2.0 },
    { t: 0.89, cx: 640, cy: 160, s: 0.8 },    // box, van, ground
    { t: 0.92, cx: 640, cy: 160, s: 0.8 },
    { t: 0.98, cx: 770, cy: 160, s: 0.8 },    // follow the van to the client
    { t: 1.00, cx: 770, cy: 160, s: 0.8 }
  ];
  function camAt(t) {
    if (t <= CAM[0].t) return CAM[0];
    for (var k = 0; k < CAM.length - 1; k++) {
      var a = CAM[k], b = CAM[k + 1];
      if (t <= b.t) {
        var u = ease(seg(t, a.t, b.t));
        return { cx: lerp(a.cx, b.cx, u), cy: lerp(a.cy, b.cy, u), s: lerp(a.s, b.s, u) };
      }
    }
    return CAM[CAM.length - 1];
  }

  function pts(list) {
    return list.map(function (p) { return f(p[0]) + "," + f(p[1]); }).join(" ");
  }

  // ---------- Storyboard: t from 0 to 1 ----------
  function renderStory(t) {
    // 1. The request is typed word by word (0 - 0.10), then sent
    var a = seg(t, 0, 0.10);
    var shown = t < 0.10 ? Math.round(typedWidth * a / 4) * 4 : 0;   // steps, like typing
    set(el.typeClipRect, "width", f(shown + 4));
    if (t >= 0.10) set(el.typeClipRect, "width", "0");
    op(el.caret, t < 0.10 ? 1 : 0);
    set(el.caret, "x", f(WORDS_X + shown + 1));
    var u = seg(t, 0.10, 0.115);
    op(el.uBubble, u);
    set(el.uBubble, "transform", "translate(0 " + f((1 - u) * 8) + ")");

    // 2. Typing dots, then the answer lines and three photos
    op(el.aiAvatar, seg(t, 0.115, 0.125));
    op(el.dots, seg(t, 0.115, 0.12) * (1 - seg(t, 0.13, 0.135)));
    dotEls.forEach(function (d, i) { set(d, "cy", f(100 - 2.2 * Math.abs(Math.sin(t * 900 + i * 0.9)))); });
    op(el.aBubble, seg(t, 0.135, 0.145));
    alines.forEach(function (l, i) {
      var k = easeOut(seg(t, 0.14 + i * 0.016, 0.158 + i * 0.016));
      set(l, "width", f(Number(l.getAttribute("data-w")) * k));
    });
    photos.forEach(function (p, i) {
      var k = seg(t, 0.19 + i * 0.016, 0.204 + i * 0.016);
      op(p, k);
      set(p, "transform", about(PHOTO_CENTERS[i][0], PHOTO_CENTERS[i][1], Math.max(0.001, easeBack(k))));
    });
    var b = seg(t, 0.225, 0.24);
    op(el.buttons, b);
    set(el.buttons, "transform", about(330, 178, Math.max(0.001, easeBack(b))));

    // 3. The cursor presses the check button, the order is confirmed
    op(el.cursor, seg(t, 0.24, 0.25) * (1 - seg(t, 0.33, 0.34)));
    var c = ease(seg(t, 0.245, 0.28));
    var click = seg(t, 0.28, 0.29);
    set(el.cursor, "transform",
      "translate(" + f(lerp(440, 326, c)) + " " + f(lerp(318, 174, c)) + ") scale(" + f(1 - 0.18 * Math.sin(Math.PI * click)) + ")");
    set(el.approveRect, "fill", click > 0 && click < 1 ? "#48484a" : "#1d1d1f");
    op(el.confirm, seg(t, 0.29, 0.30));
    set(el.confirmCard, "transform", about(260, 170, 0.85 + 0.15 * easeBack(seg(t, 0.29, 0.305))));
    set(el.confirmRing, "stroke-dashoffset", f(189 * (1 - ease(seg(t, 0.30, 0.32)))));
    set(el.confirmCheck, "stroke-dashoffset", f(40 * (1 - seg(t, 0.315, 0.33))));

    // 4. The shot moves from the screen to the printer
    var d = ease(seg(t, 0.34, 0.40));
    op(el.chat, 1 - d);
    set(el.chat, "transform", about(260, 180, 1 + 0.6 * d));
    op(el.shop, d);
    var cam = camAt(t);
    set(el.cam, "transform",
      "translate(260 180) scale(" + f(cam.s) + ") translate(" + f(-cam.cx) + " " + f(-cam.cy) + ")");

    // 5. Printing: the part grows layer by layer, the head moves over the top layer
    var e = seg(t, 0.40, 0.56);
    // The clip rect lives in the part's own coordinates (part spans y -30..30).
    set(el.printClipRect, "y", f(30 - 60 * e));
    set(el.printClipRect, "height", f(60 * e));
    set(el.progress, "width", f(180 * e));
    var park = ease(seg(t, 0.56, 0.59));
    var hx = e < 1 ? 150 + 30 * Math.sin(e * 80) : 150;
    var hy = lerp(170 - 60 * e - 10.5, 58, park);
    set(el.head, "transform", "translate(" + f(hx) + " " + f(hy) + ")");
    set(el.rail, "y", f(hy - 3));

    // 6. The door opens, the part goes into the box
    var f1 = ease(seg(t, 0.56, 0.59));
    set(el.door, "transform", "translate(72 0) scale(" + f(1 - 0.9 * f1) + " 1) translate(-72 0)");
    op(el.gearPrint, t < 0.59 ? 1 : 0);
    var f2 = ease(seg(t, 0.59, 0.66));
    var gx = (1 - f2) * (1 - f2) * 150 + 2 * (1 - f2) * f2 * 290 + f2 * f2 * 412;
    var gy = (1 - f2) * (1 - f2) * 140 + 2 * (1 - f2) * f2 * 30 + f2 * f2 * 152;
    set(el.gearMove, "transform",
      "translate(" + f(gx) + " " + f(gy) + ") rotate(" + f(90 * f2) + ") scale(" + f(lerp(1, 0.8, f2)) + ")");
    op(el.gearMove, (t >= 0.59 ? 1 : 0) * (1 - seg(t, 0.695, 0.705)));

    // 7. Flaps close, tape goes along the seam
    var g1 = ease(seg(t, 0.68, 0.72));
    set(el.flapBack, "points", pts([[354, 118], [494, 118], [lerp(494, 482, g1), lerp(92, 129, g1)], [lerp(354, 342, g1), lerp(92, 129, g1)]]));
    set(el.flapFront, "points", pts([[330, 140], [470, 140], [lerp(470, 482, g1), lerp(166, 129, g1)], [lerp(330, 342, g1), lerp(166, 129, g1)]]));
    var g2 = seg(t, 0.72, 0.78);
    op(el.tape, g2 > 0 ? 1 : 0);
    set(el.tapeBand, "width", f(152 * g2));
    set(el.tapeShine, "width", f(152 * g2));
    op(el.tapeGun, seg(t, 0.71, 0.72) * (1 - seg(t, 0.78, 0.79)));
    set(el.tapeGun, "transform", "translate(" + f(336 + 152 * g2) + " 121)");

    // 8. The waybill label flies in and sticks to the front of the box
    var h = seg(t, 0.78, 0.86);
    var fly = easeOut(seg(h, 0, 0.7));
    var press = seg(h, 0.72, 1);
    var lx = lerp(90, 0, fly), ly = lerp(-100, 0, fly), rot = lerp(-24, -2, fly);
    var ls = lerp(1.6, 1, fly) * (1 - 0.05 * Math.sin(Math.PI * press));
    var tail = "rotate(" + f(rot) + " 400 176) " + about(400, 176, ls);
    set(el.label, "transform", "translate(" + f(lx) + " " + f(ly) + ") " + tail);
    op(el.label, seg(h, 0, 0.12));
    set(el.labelShadow, "transform",
      "translate(" + f(lx + lerp(14, 1.5, fly)) + " " + f(ly + lerp(18, 2, fly)) + ") " + tail);
    op(el.labelShadow, 0.9 * seg(h, 0, 0.12) * (1 - 0.7 * press));

    // 9. The box goes into the van, the van drives to the client
    var i2 = ease(seg(t, 0.89, 0.92));
    set(el.box, "transform", "translate(" + f(194 * i2) + " " + f(15 * i2) + ") " + about(412, 165, 1 - 0.65 * i2));
    op(el.box, 1 - seg(t, 0.915, 0.925));
    var i3 = ease(seg(t, 0.92, 0.98));
    var bump = i3 > 0 && i3 < 1 ? -1.2 * Math.abs(Math.sin(i3 * 40)) : 0;
    set(el.van, "transform", "translate(" + f(300 * i3) + " " + f(bump) + ")");
    var i4 = seg(t, 0.975, 1);
    op(el.done, i4);
    set(el.done, "transform", about(1035, 108, Math.max(0.001, easeBack(i4))));
  }

  // ---------- Five progress dots ----------
  var current = -1;
  function setStage(t) {
    var stageIdx = t < 0.24 ? 0 : t < 0.40 ? 1 : t < 0.66 ? 2 : t < 0.86 ? 3 : 4;
    if (stageIdx === current) return;
    current = stageIdx;
    stageDots.forEach(function (dot, i) {
      set(dot, "fill", i === stageIdx ? "#1d1d1f" : i < stageIdx ? "#8e8e93" : "#d1d1d6");
    });
  }

  // ---------- Scroll ----------
  function update() {
    var rect = section.getBoundingClientRect();
    var range = section.offsetHeight - window.innerHeight;
    var p = range > 0 ? clamp01(-rect.top / range) : 0;

    var e = reduce ? 1 : ease(clamp01(p / OPEN_END));
    if (lid) lid.style.transform = "rotateX(" + (-90 * (1 - e)).toFixed(2) + "deg)";
    if (rig) {
      rig.style.transform =
        "translate3d(calc(var(--w) * " + lerp(CLOSED.tx, OPEN.tx, e).toFixed(4) + "), " +
        "calc(var(--w) * " + lerp(CLOSED.ty, OPEN.ty, e).toFixed(4) + "), " +
        "calc(var(--w) * " + lerp(CLOSED.tz, OPEN.tz, e).toFixed(4) + ")) " +
        "rotateX(" + lerp(CLOSED.rx, OPEN.rx, e).toFixed(2) + "deg) " +
        "rotateY(" + lerp(CLOSED.ry, OPEN.ry, e).toFixed(2) + "deg)";
    }

    var t = clamp01((p - OPEN_END) / (1 - OPEN_END));
    renderStory(t);
    setStage(t);

    if (bar) bar.style.transform = "scaleX(" + p.toFixed(4) + ")";
  }

  var queued = false;
  function onScroll() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () { queued = false; update(); });
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  window.addEventListener("resize", onScroll);
  update();

  // "Як це працює" in the top bar: jump to the point where the laptop is already open.
  function scrollToHow(smooth) {
    var top = section.getBoundingClientRect().top + window.scrollY;
    var range = section.offsetHeight - window.innerHeight;
    window.scrollTo({ top: top + range * (OPEN_END + 0.02), behavior: smooth ? "smooth" : "auto" });
  }
  Array.prototype.forEach.call(document.querySelectorAll('a[href="index.html#how"], a[href="#how"]'), function (a) {
    a.addEventListener("click", function (ev) {
      ev.preventDefault();
      scrollToHow(true);
      if (history.replaceState) history.replaceState(null, "", "#how");
    });
  });
  if (location.hash === "#how") setTimeout(function () { scrollToHow(false); }, 60);
})();
