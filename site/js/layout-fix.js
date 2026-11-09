// Wrong keyboard layout fix: "ot dfhsfynb" -> "ще варіанти".
//
// A word typed on the English layout is turned into Ukrainian or Russian when its letter pairs look
// like one of those languages and not like English (statistics in js/layout-model.js, built by
// tools/build_layout_model.py). Real English words, brands and codes stay as typed:
// "gear", "Bosch", "PETG", "M3", links.
//
// window.LayoutFix.word(token, "uk" | "ru") -> converted word or null
// window.LayoutFix.text(text)   -> text with every wrong-layout word converted
// window.LayoutFix.attach(textarea) converts each word as it is finished (space / line break);
//   Backspace right after a conversion brings the typed letters back and leaves that word alone.
(function () {
  "use strict";

  var M = window.LAYOUT_MODEL;
  if (!M) return;

  var LATIN = M.keys.latin;
  var LATIN_SHIFT = "QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>~|";
  var TOKEN_RE = /^[A-Za-z\[\]{};:'",.<>`~\\|]+$/;
  var TRAILING_RE = /[,.!?]+$/;      // may be real punctuation after a word
  var UNKNOWN = 18;                  // cost of a letter pair outside the alphabet

  function table(lang) {
    var syms = "^" + M.alphabets[lang];
    var idx = {};
    for (var i = 0; i < syms.length; i++) idx[syms[i]] = i;
    return { idx: idx, n: syms.length, data: M.tables[lang] };
  }
  var T = { en: table("en"), uk: table("uk"), ru: table("ru") };

  function set(list) {
    var s = {};
    list.forEach(function (w) { s[w] = true; });
    return s;
  }
  // The model's short words come from interface texts; chat adds a few everyday ones.
  var SHORT = {
    uk: set(M.short.uk.concat(["ти", "ми", "ну", "ой", "я", "й", "о"])),
    ru: set(M.short.ru.concat(["ты", "мы", "он", "да", "ну", "ой", "я"])),
    en: set(M.short.en)
  };
  var SPECIAL = { "3l": "3д", "3L": "3Д" };   // "3д модель"

  // Mean -log(p) per letter pair, word edges included. Lower = more typical for the language.
  function score(word, t) {
    var seq = "^" + word + "^";
    var sum = 0;
    for (var i = 0; i < seq.length - 1; i++) {
      var a = t.idx[seq[i]];
      var b = t.idx[seq[i + 1]];
      sum += a === undefined || b === undefined ? UNKNOWN : parseInt(t.data.charAt(a * t.n + b), 36) * M.step;
    }
    return sum / (seq.length - 1);
  }

  // Same keys on the Ukrainian / Russian layout; Shift gives capitals. null if a key is not a letter key.
  function toCyrillic(word, lang) {
    var keys = M.keys[lang];
    var out = "";
    for (var i = 0; i < word.length; i++) {
      var c = word.charAt(i);
      var k = LATIN.indexOf(c);
      if (k >= 0) { out += keys.charAt(k); continue; }
      k = LATIN_SHIFT.indexOf(c);
      if (k >= 0) { out += keys.charAt(k).toUpperCase(); continue; }
      return null;
    }
    return out;
  }

  var ignored = {};   // words the customer turned back with Backspace

  // Cyrillic spellings of a token on one layout. In Ukrainian the "'" key may also be meant
  // as the apostrophe (пам'ять), which sits on the "`" key.
  function spellings(core, lang) {
    var out = [];
    var c = toCyrillic(core, lang);
    if (c) out.push(c);
    var inner = core.slice(1, -1);
    if (lang === "uk" && inner.indexOf("'") >= 0) {
      var c2 = toCyrillic(core.charAt(0) + inner.replace(/'/g, "`") + core.slice(-1), lang);
      if (c2) out.push(c2);
    }
    return out;
  }

  // Best conversion of a token on one layout: { text, cyrScore } or null to keep the token.
  function evaluate(token, lang) {
    if (SPECIAL[token]) return { text: SPECIAL[token], cyrScore: 0 };
    var tok = token.replace(/[!?]+$/, "");                   // ! and ? are never letter keys
    var bang = token.slice(tok.length);
    if (/.\/$/.test(tok)) {                                  // "/" is the full stop on ЙЦУКЕН
      tok = tok.slice(0, -1);
      bang = "." + bang;
    }
    if (!tok || !TOKEN_RE.test(tok) || !/[A-Za-z]/.test(tok)) return null;
    if (ignored[tok.toLowerCase()]) return null;
    if (/^[A-Z]{2,5}$/.test(tok)) return null;               // PLA, PETG, ABS, STL...

    var variants = [{ core: tok, tail: "" }];
    var trail = tok.match(TRAILING_RE);                      // "ghbdtn," = "привет," not "приветб"
    if (trail && trail[0].length < tok.length) variants.push({ core: tok.slice(0, -trail[0].length), tail: trail[0] });

    var best = null;
    variants.forEach(function (v) {
      var low = v.core.toLowerCase();
      var english = low.replace(/[^a-z]/g, "");              // "don't" is judged as "dont"
      spellings(v.core, lang).forEach(function (cyr) {
        var cyrLow = cyr.toLowerCase();
        var pass, cs;
        if (v.core.length <= 2) {
          // Too short for statistics: only well-known little words, never English ones.
          pass = SHORT[lang][cyrLow] && !SHORT.en[low];
          cs = 0;
        } else {
          cs = score(cyrLow, T[lang]);
          pass = english.length > 0 && score(english, T.en) - cs > M.threshold;
        }
        // Among good readings take the most natural Cyrillic word; a trailing "," or "." counts
        // as punctuation only when that reads clearly better ("привет," but "знаю").
        var rank = cs + (v.tail ? 0.5 : 0);
        if (pass && (!best || rank < best.rank)) best = { text: cyr + v.tail + bang, cyrScore: cs, rank: rank };
      });
    });
    return best;
  }

  // Ukrainian or Russian for the whole text: letters only one language has, then which
  // reading of the English-layout words looks more natural. Ukrainian on a tie.
  function language(value) {
    var diff = 2 * ((value.match(/[іїєґ]/gi) || []).length - (value.match(/[ыэъё]/gi) || []).length);
    value.split(/\s+/).forEach(function (tok) {
      if (!/[A-Za-z]/.test(tok)) return;
      var uk = evaluate(tok, "uk");
      var ru = evaluate(tok, "ru");
      if (uk && ru) diff += ru.cyrScore - uk.cyrScore;
      else if (uk) diff += 1;
      else if (ru) diff -= 1;
    });
    return diff >= 0 ? "uk" : "ru";
  }

  function word(token, lang) {
    var r = evaluate(token, lang || "uk");
    return r ? r.text : null;
  }

  // One or two letters ("ot" = ще, "b" = и) are converted only next to a real Cyrillic word,
  // so "a b c" in English stays as typed.
  function isShort(tok) {
    return !SPECIAL[tok] && tok.replace(/[!?\/,.]+$/, "").length <= 2;
  }
  function cyrillicContext(value) {
    return /[а-яіїєґё]{3,}/i.test(value);
  }

  function text(value) {
    var lang = language(value);
    var long = value.replace(/\S+/g, function (tok) { return isShort(tok) ? tok : word(tok, lang) || tok; });
    if (!cyrillicContext(long)) return long;
    return long.replace(/\S+/g, function (tok) { return word(tok, lang) || tok; });
  }


  function attach(field) {
    var last = null;   // { start, from, to } of the conversion just made

    // After a space, a line break or a paste: every finished word before the caret is checked.
    // (Typing sends one space at a time; paste, autocorrect and fast input can send a whole phrase.)
    field.addEventListener("input", function (e) {
      last = null;
      var finished = e.inputType === "insertLineBreak" || e.inputType === "insertFromPaste" ||
        (e.inputType === "insertText" && /\s$/.test(e.data || ""));
      if (!finished) return;
      var caret = field.selectionStart;
      if (caret !== field.selectionEnd) return;
      var head = field.value.slice(0, caret);
      var done = head.replace(/\S+$/, "");                   // a word still being typed waits
      var fixed = text(done);
      if (fixed === done) return;
      // Conversions keep the length, so the caret stays where it is.
      field.setRangeText(fixed, 0, done.length, done.length === caret ? "end" : "preserve");
      // The last word that changed right before the caret can be undone with Backspace.
      var m = /(\S+)(\s)$/.exec(done);
      if (m) {
        var start = done.length - m[0].length;
        var to = fixed.substr(start, m[1].length);
        if (to !== m[1]) last = { start: start, from: m[1], to: to };
      }
    });

    field.addEventListener("keydown", function (e) {
      if (!last) return;
      var fix = last;
      if (e.key !== "Backspace") { if (e.key !== "Shift") last = null; return; }
      last = null;
      var caret = field.selectionStart;
      if (caret !== field.selectionEnd || caret !== fix.start + fix.to.length + 1) return;
      if (field.value.substr(fix.start, fix.to.length) !== fix.to) return;
      e.preventDefault();
      field.setRangeText(fix.from, fix.start, fix.start + fix.to.length, "preserve");
      ignored[fix.from.toLowerCase()] = true;
      field.dispatchEvent(new Event("input"));
    });
  }

  window.LayoutFix = { word: word, text: text, attach: attach };
})();
