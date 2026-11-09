"""Local dev server: serves the site, the price API and the AI assistant.

Run (from the project folder):
    server/.venv/bin/python server/app.py
Then open http://127.0.0.1:8000/

The assistant needs an Anthropic API key: put ANTHROPIC_API_KEY=... into server/.env
(or export it before starting). Without a key the rest of the site still works.

POST /api/quote?material=pla&quality=standard&qty=1
    body: raw file bytes, header X-Filename (URL-encoded name)
    -> JSON with grams, hours, total price (UAH)
POST /api/upload
    body: raw file bytes, header X-Filename (URL-encoded name)
    -> {"file_id", "name"}; the file is kept in server/uploads for the assistant
POST /api/chat
    JSON {"conversation_id"?: str, "text": str, "file_ids": [str]}
    -> {"conversation_id", "reply", "quotes": [cards], "models": [Printables models]}
POST /api/requote
    JSON {"file_id", "material", "quality", "qty"} -> one price card (other plastic or quality)
POST /api/import
    JSON {"model_id", "file_id"?} -> {"quote": card} or {"model", "files"} to pick a file
    Downloads a model file from Printables, then prices it like an uploaded file.
GET /api/view/<file_id>
    The parts as the slicer placed them on the plate: binary STL, gzip-encoded (for the 3D view).
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import shutil
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import model_search
import printables
import slicer

HERE = os.path.dirname(os.path.abspath(__file__))
SITE_DIR = os.path.normpath(os.path.join(HERE, "..", "site"))
UPLOAD_DIR = os.path.join(HERE, "uploads")
ENV_FILE = os.path.join(HERE, ".env")
HOST, PORT = "127.0.0.1", 8000

MAX_BYTES = 50 * 1024 * 1024
ALLOWED_EXT = {"stl", "3mf", "obj"}
UPLOAD_TTL = 24 * 3600
MAX_CHAT_TEXT = 4000
MAX_CHAT_FILES = 5
FILE_ID_RE = re.compile(r"^[0-9a-f]{32}$")

# Prices in UAH. Plastic is 2 UAH per gram of total weight (model + supports).
# Density and slicer profiles live in server/slicer.py.
MATERIALS = {
    "pla":  {"rate_per_g": 2.0},
    "petg": {"rate_per_g": 2.0},
    "abs":  {"rate_per_g": 2.0},
}
HOUR_RATE = 40
SETUP_FEE = 50
MAX_QTY = 100

# Messages shown to the customer for each slicing failure reason.
FAILURE_MESSAGES = {
    "outside_volume": "Деталь не вміщується в робочу зону 256×256×250 мм або в файлі порожня пластина. Перевірте файл у Bambu Studio і завантажте знову.",
    "load_failed": "Файл пошкоджено або не читається. Спробуйте пересохранити модель як STL або 3MF.",
    "crash": "Слайсер не зміг обробити модель, ймовірно через пошкоджену сітку. Виправте модель у слайсері і завантажте знову.",
    "other": "Не вдалося нарізати файл. Перевірте модель.",
    "timeout": "Модель занадто складна для швидкого розрахунку.",
    "busy": "Сервер зайнятий, спробуйте за хвилину.",
}

# Limit how many slices run at once so the machine does not choke.
_slots = threading.BoundedSemaphore(2)

# Slicing results for uploaded files: (path, mtime, material, quality) -> SliceResult.
# Switching plastic or quality back and forth on a card then costs nothing.
_slice_cache: dict = {}
_slice_cache_lock = threading.Lock()
SLICE_CACHE_MAX = 500

log = logging.getLogger("server")
assistant = None   # set in main() when a key and the SDK are available
assistant_problem = "Помічник ще не налаштований."


def price(grams: float, hours: float, material: str, qty: int) -> float:
    unit = grams * MATERIALS[material]["rate_per_g"] + hours * HOUR_RATE
    return round(unit * qty + SETUP_FEE, 2)


def view_path_for(model_path: str) -> str | None:
    """Where the 3D view of an uploaded file lives (None for files outside server/uploads)."""
    if os.path.dirname(os.path.abspath(model_path)) != UPLOAD_DIR:
        return None
    return os.path.splitext(os.path.abspath(model_path))[0] + ".view.stl.gz"


def quote_path(path: str, material: str, quality: str, qty: int) -> dict:
    """Slice one file and price it. Returns {"ok": True, ...} or {"ok": False, "error", "reason"}.

    For uploaded files the result is cached, and the first slice also saves the 3D view.
    """
    view = view_path_for(path)
    key = (os.path.abspath(path), os.path.getmtime(path), material, quality) if view else None
    with _slice_cache_lock:
        result = _slice_cache.get(key) if key else None

    if result is None:
        if not _slots.acquire(timeout=5):
            return {"ok": False, "error": FAILURE_MESSAGES["busy"], "reason": "busy"}
        try:
            need_view = view if view and not os.path.exists(view) else None
            result = slicer.slice_model(path, material, quality, view_path=need_view)
        except subprocess.TimeoutExpired:
            log.warning("slicing timed out for %s", path)
            return {"ok": False, "error": FAILURE_MESSAGES["timeout"], "reason": "timeout"}
        except slicer.SliceError as e:
            log.error("slicing failed (%s) for %s: %s", e.reason, path, e)
            return {"ok": False, "error": FAILURE_MESSAGES.get(e.reason, FAILURE_MESSAGES["other"]), "reason": e.reason}
        except Exception:
            log.exception("slicing failed for %s", path)
            return {"ok": False, "error": FAILURE_MESSAGES["other"], "reason": "other"}
        finally:
            _slots.release()
        if key:
            with _slice_cache_lock:
                if len(_slice_cache) >= SLICE_CACHE_MAX:
                    _slice_cache.pop(next(iter(_slice_cache)))
                _slice_cache[key] = result

    hours = result.seconds / 3600
    rate = MATERIALS[material]["rate_per_g"]
    return {
        "ok": True,
        "grams": round(result.grams, 2),
        "hours": round(hours, 2),
        "minutes": round(result.seconds / 60),
        "qty": qty,
        "material": material,
        "quality": quality,
        "plastic_cost": round(result.grams * rate * qty, 2),
        "time_cost": round(hours * HOUR_RATE * qty, 2),
        "setup_fee": SETUP_FEE,
        "total": price(result.grams, hours, material, qty),
    }


# ---------- basic mode: the Start page without an API key ----------

SEARCH_SITES = [
    ("Printables", "https://www.printables.com/search/models?q={q}"),
    ("Thingiverse", "https://www.thingiverse.com/search?q={q}&type=things"),
    ("MakerWorld", "https://makerworld.com/en/search/models?keyword={q}"),
]
MATERIAL_NAMES = {"pla": "PLA", "petg": "PETG", "abs": "ABS"}
QUALITY_NAMES = {"draft": "чернетка", "standard": "стандартна", "fine": "висока"}


def guess_options(text: str) -> tuple[str, str, int]:
    """Material, quality and quantity named in the customer's text; PLA, standard, 1 otherwise."""
    t = text.lower()
    material = "petg" if ("petg" in t or "петг" in t) else "abs" if ("abs" in t or "абс" in t) else "pla"
    if "чернет" in t or "швидк" in t or "draft" in t:
        quality = "draft"
    elif "висок" in t or "гладк" in t or "fine" in t:
        quality = "fine"
    else:
        quality = "standard"
    m = re.search(r"(\d{1,3})\s*(шт|штук|копі|pcs)", t)
    qty = min(max(int(m.group(1)), 1), MAX_QTY) if m else 1
    return material, quality, qty


def make_card(file_id: str, info: dict, r: dict) -> dict:
    """What the price card on the Start page shows (and needs to re-price and load the 3D view)."""
    return {"file_id": file_id, "file": info["name"], "source": info.get("source"),
            "material": r["material"], "quality": r["quality"], "qty": r["qty"],
            "grams": r["grams"], "minutes": r["minutes"], "total": r["total"]}


def quote_upload(file_id: str, material: str, quality: str, qty: int) -> tuple[dict | None, str]:
    """Price an uploaded (or imported) file: (card, "") or (None, message for the customer)."""
    info = resolve_upload(file_id)
    if not info:
        return None, "Файл не знайдено, прикріпіть його ще раз."
    r = quote_path(info["path"], material, quality, qty)
    if not r["ok"]:
        return None, f"{info['name']}: {r['error']}"
    return make_card(file_id, info, r), ""


# ---------- models from Printables ----------

class ImportProblem(Exception):
    """A model could not be taken from Printables; the text is for the customer."""


_imported: dict[tuple[str, str], str] = {}   # (Printables model, Printables file) -> our file_id


def printables_model(model_id: str) -> dict:
    try:
        m = printables.model(model_id)
    except printables.PrintablesError as e:
        log.warning("printables model %s: %s", model_id, e)
        raise ImportProblem("Printables зараз не відповідає. Спробуйте за хвилину.")
    if not m:
        raise ImportProblem("Такої моделі на Printables немає.")
    if not m["files"]:
        raise ImportProblem(f"У моделі «{m['name']}» немає файлів STL, 3MF чи OBJ.")
    return m


def import_printables_file(m: dict, printables_file_id: str) -> str:
    """Download one file of a Printables model into uploads; returns our file_id."""
    f = next((f for f in m["files"] if f["id"] == str(printables_file_id)), None)
    if not f:
        raise ImportProblem("У цієї моделі немає такого файлу.")
    if f["size"] > MAX_BYTES:
        raise ImportProblem(f"Файл {f['name']} більший за 50 МБ, такі ми поки не приймаємо. Спробуйте інший файл моделі.")
    key = (m["id"], f["id"])
    known = _imported.get(key)
    if known and resolve_upload(known):
        return known
    try:
        body = printables.download(m["id"], f["id"], MAX_BYTES)
    except printables.PrintablesError as e:
        log.warning("printables download %s/%s: %s", m["id"], f["id"], e)
        raise ImportProblem("Не вдалося завантажити файл з Printables. Спробуйте за хвилину.")
    ext = f["name"].rsplit(".", 1)[-1].lower()
    source = {"site": m["source"], "model": m["name"], "url": m["url"],
              "license": m["license"], "license_ok": m["license_ok"]}
    file_id = save_upload(f["name"], ext, body, source)
    _imported[key] = file_id
    return file_id


# ---------- basic mode: the Start page without an API key ----------

def basic_chat(text: str, file_ids: list[str]) -> dict:
    """Without an API key: price attached files, import Printables links, search Printables for text."""
    material, quality, qty = guess_options(text)
    cards, problems, models = [], [], []
    to_price = list(file_ids)

    # Links to Printables models in the text: take the file and price it right away.
    linked = printables.model_ids_in(text)[:3]
    for model_id in linked:
        try:
            m = printables_model(model_id)
            if len(m["files"]) > 1:
                models.append(dict(m, pick=True))   # the card opens with its file list
            else:
                to_price.append(import_printables_file(m, m["files"][0]["id"]))
        except ImportProblem as e:
            problems.append(str(e))

    for fid in to_price:
        card, problem = quote_upload(fid, material, quality, qty)
        if card:
            cards.append(card)
        else:
            problems.append(problem)

    lines = []
    if cards:
        lines.append(f"Порахував для {MATERIAL_NAMES[material]}, якість {QUALITY_NAMES[quality]}, {qty} шт. "
                     "Пластик, якість і колір можна змінити на картці.")
    if models:
        lines.append("У моделі кілька файлів: оберіть на картці, який порахувати.")
    lines += problems

    if not file_ids and not linked and text.strip():
        # Ukrainian and Russian requests are translated to English: model sites search by English names.
        # Models that do not fit the request (another car, no MagSafe...) are left out.
        found, english, unknown, exact = model_search.find(text)
        models += found
        q = quote_plus(english or model_search.native_query(text) or " ".join(text.split()[:8]))
        searched = f"«{english}»" if english else "вашими словами"
        if found and exact:
            lines.append(f"Шукав на Printables за запитом {searched}. "
                         "Натисніть «Порахувати», щоб побачити модель у 3D і ціну.")
            others = SEARCH_SITES[1:]
        elif found:
            lines.append(f"Точних збігів на Printables за запитом {searched} немає, ось найближчі. "
                         "Можна уточнити запит або пошукати на інших сайтах.")
            others = SEARCH_SITES[1:]
        else:
            lines.append(f"На Printables за запитом {searched} нічого не знайшов.")
            others = SEARCH_SITES
        if unknown:
            lines.append("Не знаю слів " + ", ".join(f"«{w}»" for w in unknown[:4]) +
                         ". Якщо знайшлося не те, назвіть деталь інакше або англійською.")
        lines.append("Ще можна пошукати тут:")
        lines += [f"{name}: {url.format(q=q)}" for name, url in others]
        lines.append("З цих сайтів файл потрібно завантажити вручну й прикріпити сюди. "
                     "Для друку на замовлення підходять ліцензії CC0, CC BY і CC BY-SA.")
    if not lines:
        lines.append("Напишіть, що потрібно, або прикріпіть файл STL, 3MF чи OBJ.")
    return {"conversation_id": None, "reply": "\n".join(lines), "quotes": cards, "models": models, "mode": "basic"}


# ---------- uploads kept for the assistant ----------

def meta_path_for(file_id: str) -> str:
    return os.path.join(UPLOAD_DIR, file_id + ".json")


def resolve_upload(file_id: str) -> dict | None:
    """file_id -> {"name", "path"} where path keeps the right extension for the slicer."""
    if not FILE_ID_RE.match(file_id or ""):
        return None
    meta_path = meta_path_for(file_id)
    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        return None
    model_path = os.path.join(UPLOAD_DIR, file_id + "." + meta["ext"])
    if not os.path.exists(model_path):
        return None
    return {"name": meta["name"], "path": model_path, "source": meta.get("source")}


def save_upload(name: str, ext: str, body: bytes, source: dict | None = None) -> str:
    """Keep a model file in server/uploads; returns its new file_id."""
    file_id = secrets.token_hex(16)
    with open(os.path.join(UPLOAD_DIR, file_id + "." + ext), "wb") as f:
        f.write(body)
    meta = {"name": name, "ext": ext}
    if source:
        meta["source"] = source
    with open(meta_path_for(file_id), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False)
    return file_id


def clean_uploads() -> None:
    now = time.time()
    for name in os.listdir(UPLOAD_DIR):
        p = os.path.join(UPLOAD_DIR, name)
        try:
            if now - os.path.getmtime(p) > UPLOAD_TTL:
                os.remove(p)
        except OSError:
            pass


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SITE_DIR, **kwargs)

    def end_headers(self):
        # Dev server: never let the browser reuse an old CSS/JS/HTML file.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file_from_body(self):
        """Read a model file from the request body. Returns (name, ext, bytes) or an error tuple."""
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length <= 0:
            return None, (400, "Файл порожній")
        if length > MAX_BYTES:
            return None, (413, "Файл більший за 50 МБ")
        # The browser sends the name URL-encoded, so Cyrillic names survive the header.
        name = os.path.basename(unquote(self.headers.get("X-Filename", "")))[:200]
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ALLOWED_EXT:
            return None, (400, "Дозволено STL, 3MF, OBJ")
        return (name, ext, self.rfile.read(length)), None

    def _read_json(self, limit: int = 64 * 1024) -> dict | None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not 0 < length <= limit:
            return None
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/view/"):
            return self._view(path[len("/api/view/"):])
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/quote":
            return self._quote()
        if path == "/api/upload":
            return self._upload()
        if path == "/api/chat":
            return self._chat()
        if path == "/api/requote":
            return self._requote()
        if path == "/api/import":
            return self._import()
        return self._json(404, {"error": "Не знайдено"})

    def _view(self, file_id: str):
        info = resolve_upload(file_id)
        view = view_path_for(info["path"]) if info else None
        if not view or not os.path.exists(view):
            return self._json(404, {"error": "3D-перегляд недоступний"})
        with open(view, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "model/stl")
        self.send_header("Content-Encoding", "gzip")   # stored gzipped; every browser accepts it
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _options(self, data: dict) -> tuple[str, str, int] | str:
        """material, quality, qty from a request, or an error message."""
        material, quality, qty = data.get("material", "pla"), data.get("quality", "standard"), data.get("qty", 1)
        if material not in MATERIALS:
            return "Невідомий матеріал"
        if quality not in slicer.QUALITY_PROFILES:
            return "Невідома якість"
        if not isinstance(qty, int) or not 1 <= qty <= MAX_QTY:
            return f"Кількість від 1 до {MAX_QTY}"
        return material, quality, qty

    def _requote(self):
        """Price card again with another plastic or quality (the card's selectors)."""
        data = self._read_json()
        if data is None:
            return self._json(400, {"error": "Некоректний запит"})
        opts = self._options(data)
        if isinstance(opts, str):
            return self._json(400, {"error": opts})
        card, problem = quote_upload(str(data.get("file_id", "")), *opts)
        if not card:
            return self._json(422, {"error": problem})
        self._json(200, {"quote": card})

    def _import(self):
        """«Порахувати» on a Printables model card: take the file and price it (PLA, standard, 1 pc.)."""
        data = self._read_json()
        if data is None:
            return self._json(400, {"error": "Некоректний запит"})
        try:
            m = printables_model(str(data.get("model_id", "")))
            file_ref = data.get("file_id")
            if not file_ref:
                if len(m["files"]) > 1:
                    return self._json(200, {"model": m, "files": m["files"]})
                file_ref = m["files"][0]["id"]
            file_id = import_printables_file(m, str(file_ref))
        except ImportProblem as e:
            return self._json(422, {"error": str(e)})
        card, problem = quote_upload(file_id, "pla", "standard", 1)
        if not card:
            return self._json(422, {"error": problem})
        self._json(200, {"quote": card})

    def _quote(self):
        params = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
        material = params.get("material", "pla")
        quality = params.get("quality", "standard")
        try:
            qty = int(params.get("qty", "1"))
        except ValueError:
            return self._json(400, {"error": "Некоректна кількість"})
        if material not in MATERIALS:
            return self._json(400, {"error": "Невідомий матеріал"})
        if quality not in slicer.QUALITY_PROFILES:
            return self._json(400, {"error": "Невідома якість"})
        if not 1 <= qty <= MAX_QTY:
            return self._json(400, {"error": f"Кількість від 1 до {MAX_QTY}"})

        got, err = self._file_from_body()
        if err:
            return self._json(err[0], {"error": err[1]})
        name, ext, body = got
        tmp = tempfile.mkdtemp(prefix="upload_")
        try:
            model = os.path.join(tmp, "model." + ext)
            with open(model, "wb") as f:
                f.write(body)
            result = quote_path(model, material, quality, qty)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        if not result["ok"]:
            status = {"busy": 503, "timeout": 504}.get(result["reason"], 422)
            return self._json(status, {"error": result["error"], "reason": result["reason"]})
        result.pop("ok")
        self._json(200, result)

    def _upload(self):
        got, err = self._file_from_body()
        if err:
            return self._json(err[0], {"error": err[1]})
        name, ext, body = got
        file_id = save_upload(name, ext, body)
        self._json(200, {"file_id": file_id, "name": name})

    def _chat(self):
        data = self._read_json()
        if data is None:
            return self._json(400, {"error": "Некоректний запит"})
        text = str(data.get("text", ""))[:MAX_CHAT_TEXT]
        file_ids = [str(x) for x in (data.get("file_ids") or [])][:MAX_CHAT_FILES]
        conversation_id = data.get("conversation_id")
        conversation_id = str(conversation_id) if conversation_id else None

        if assistant is None:
            # No API key yet: basic mode still prices files and gives search links.
            if not text.strip() and not file_ids:
                return self._json(400, {"error": "Напишіть, що потрібно, або прикріпіть файл."})
            return self._json(200, basic_chat(text, file_ids))

        from assistant import AssistantError
        try:
            result = assistant.chat(conversation_id, text, file_ids)
        except AssistantError as e:
            return self._json(e.status, {"error": str(e)})
        except Exception:
            log.exception("chat failed")
            return self._json(500, {"error": "Щось пішло не так. Спробуйте ще раз."})
        self._json(200, result)

    def log_message(self, fmt, *args):
        # Keep the console quiet; errors are logged separately.
        pass


def setup_assistant() -> None:
    global assistant, assistant_problem
    try:
        import assistant as assistant_module
    except ImportError:
        assistant_problem = "Помічник не запущений: запустіть сервер через server/.venv/bin/python."
        log.warning("anthropic SDK not found; start the server with server/.venv/bin/python")
        return
    key = assistant_module.load_api_key(ENV_FILE)
    if not key:
        assistant_problem = "Помічник не налаштований: додайте ANTHROPIC_API_KEY у server/.env."
        log.warning("no ANTHROPIC_API_KEY; the assistant is off")
        return
    assistant = assistant_module.Assistant(
        api_key=key, resolve_file=resolve_upload, quote=quote_path, make_card=make_card,
        search_models=lambda query: model_search.find(query)[0], import_model=import_model)
    log.info("assistant is on (%s)", assistant_module.MODEL)


def import_model(model_id: str, printables_file_id: str) -> tuple[str | None, str]:
    """For the assistant's import tool: (our file_id, "") or (None, message)."""
    try:
        return import_printables_file(printables_model(model_id), printables_file_id), ""
    except ImportProblem as e:
        return None, str(e)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not os.path.exists(slicer.SLICER_BIN):
        print(f"Слайсер не знайдено: {slicer.SLICER_BIN}")
        sys.exit(1)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    clean_uploads()
    setup_assistant()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Сайт: http://{HOST}:{PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
