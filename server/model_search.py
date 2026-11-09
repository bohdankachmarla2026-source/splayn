"""Model search for customers who write in Ukrainian or Russian.

Model sites name almost everything in English, and Printables returns a model only when every
word of the query matches. So "Мені потрібна шестерня для міксера Bosch" finds nothing, while
"gear mixer bosch" finds the right part. Without the AI assistant we translate with a dictionary
of word stems (both languages, any case ending), drop filler words, and run a few searches at once:

  1. the English query ("gear mixer bosch") and the customer's own words (some models are
     named in Ukrainian or Russian);
  2. if that gives too little: pairs of the main English words ("gear mixer", "gear bosch", ...).
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from itertools import combinations

import printables

MAX_TERMS = 5

# English term -> stems in Ukrainian and Russian. A word matches a stem it starts with
# (the longest stem wins), so one stem covers every case ending: шестерня, шестерню, шестерні...
_DICTIONARY = {
    # mechanics and spare parts
    "gear": ["шестер", "зубчат", "зубчаст", "зубчик"],
    "gearbox": ["редуктор"],
    "planetary": ["планетар"],
    "teeth": ["зубів", "зубьев", "зубц", "зуба", "зубы", "зуби"],
    "bracket": ["кронштейн", "уголок", "кутник", "куточ"],
    "mount": ["кріплен", "креплен", "кріпил", "крепёж", "крепеж", "кріпле", "монтаж"],
    "holder": ["тримач", "тримал", "держател", "держалк", "утримувач", "фіксатор", "фиксатор"],
    "stand": ["підставк", "подставк", "стійк", "стойк", "постамент"],
    "hook": ["гачок", "гачк", "крючок", "крючк", "крюч"],
    "hanger": ["вішалк", "вешалк", "плечик"],
    "clip": ["кліпс", "клипс", "прищепк", "защіпк"],
    "clamp": ["затиск", "зажим", "струбцин", "хомут"],
    "latch": ["засув", "задвижк", "щеколд", "защелк", "клямк"],
    "hinge": ["шарнір", "шарнир", "петл", "завіс", "навес"],
    "knob": ["регулятор", "крутилк", "перемикача", "переключателя"],
    "handle": ["ручк", "рукоятк", "рукоят"],
    "button": ["кнопк", "клавіш", "клавиш"],
    "lid": ["кришк", "крышк", "накривк"],
    "cap": ["ковпач", "колпач", "заглушк", "наконечник"],
    "plug": ["пробк", "затичк", "чопик"],
    "bushing": ["втулк"],
    "bearing": ["підшипник", "подшипник"],
    "roller": ["ролик", "валик"],
    "wheel": ["колес", "колёс", "коліщат", "колесик"],
    "pulley": ["шків", "шкив"],
    "coupling": ["муфт"],
    "spring": ["пружин"],
    "screw": ["гвинт", "винт", "шуруп", "саморіз", "саморез"],
    "bolt": ["болт"],
    "nut": ["гайк"],
    "washer": ["шайб"],
    "spacer": ["проставк", "дистанц"],
    "adapter": ["адаптер", "перехідник", "переходник"],
    "attachment": ["насадк"],
    "nozzle": ["сопл", "форсунк"],
    "shaft": ["вала", "валу", "осі", "ось"],
    "lever": ["важіль", "важел", "рычаг"],
    "replacement part": ["запчаст", "запасн"],
    "repair": ["ремонт", "полаго", "почин"],
    "case": ["корпус", "чохол", "чехол", "футляр", "кейс"],
    "box": ["коробк", "короб", "скриньк", "шкатулк", "ящик", "ящичок", "бокс"],
    "drawer": ["шухляд", "выдвижн"],
    "organizer": ["органайзер", "сортер", "розділювач", "разделител"],
    "container": ["контейнер", "ємніст", "емкост", "банк"],
    "tray": ["лоток", "лотк", "піддон", "поддон"],
    "cover": ["накладк", "кожух", "захист", "защит"],
    "bumper": ["бампер"],
    "frame": ["рамк", "рама", "рами", "рамы"],
    "sign": ["табличк", "вивіск", "вывеск", "знак"],
    "tag": ["бирк", "бірк"],
    "funnel": ["лійк", "воронк"],
    "scoop": ["совок", "совк"],
    "template": ["шаблон", "трафарет"],
    "tool": ["інструмент", "инструмент"],
    "wrench": ["ключ гайк", "гайков"],
    "key": ["ключ"],
    "key holder": ["ключниц"],
    "keychain": ["брелок", "брелк"],
    # home and kitchen
    "shelf": ["полиц", "полк", "поличк"],
    "rack": ["стелаж", "стеллаж"],
    "table": ["стол", "столик"],
    "chair": ["стільц", "стілец", "стул"],
    "leg": ["ніжк", "ножк"],
    "door": ["двер", "дверн"],
    "cabinet": ["шафк", "шкаф", "тумб", "комод"],
    "flower": ["квіт", "цветы", "цветок", "цветк", "цветов", "букет"],
    "window": ["вікн", "вікон", "окн", "окон"],
    "wall": ["стін", "стен", "настін", "настен"],
    "lamp": ["ламп", "світильник", "светильник", "торшер", "бра"],
    "lampshade": ["абажур", "плафон"],
    "night light": ["нічник", "ночник"],
    "vase": ["вазочк", "вазон"],
    "planter": ["горщик", "горшок", "горшк", "кашпо"],
    "kitchen": ["кухон", "кухн"],
    "cup": ["чашк", "стакан", "склянк"],
    "mug": ["кружк", "горнят"],
    "plate": ["тарілк", "тарелк"],
    "bowl": ["миск", "піал", "пиал"],
    "spoon": ["ложк"],
    "cookie cutter": ["формочк", "вирубк", "вырубк"],
    "mold": ["форма для", "молд"],
    "soap dish": ["мильниц", "мыльниц"],
    "toothbrush": ["зубн", "щітк", "щетк"],
    "towel": ["рушник", "полотенц"],
    "bathroom": ["ванн", "душ"],
    "toilet": ["туалет", "унітаз", "унитаз"],
    "mirror": ["дзеркал", "зеркал"],
    "clock": ["годинник", "часы", "часов"],
    "pen": ["ручок для", "ручку для письм"],
    "pencil": ["олів", "карандаш"],
    "cable": ["кабел", "провід", "провод", "дріт", "шнур"],
    "charger": ["зарядк", "зарядн"],
    "socket": ["розетк"],
    "switch": ["вимикач", "выключател", "перемикач", "переключател"],
    "fan": ["вентилятор", "кулер"],
    "duct": ["повітропровід", "воздуховод"],
    "filter": ["фільтр", "фильтр"],
    "remote": ["пульт"],
    "garden": ["садов", "городн", "грядк"],
    "outdoor": ["вуличн", "уличн", "надвір"],
    "christmas": ["новорічн", "новогодн", "різдв", "рождеств"],
    "christmas tree": ["ялинк", "ёлк", "елк"],
    "ornament": ["прикрас", "украшен", "іграшка на ялин"],
    "snowflake": ["сніжинк", "снежинк"],
    # appliances and devices
    "mixer": ["міксер", "миксер"],
    "blender": ["блендер"],
    "coffee machine": ["кавомашин", "кофемашин", "кавоварк", "кофеварк"],
    "vacuum": ["пилосос", "пылесос"],
    "washing machine": ["пральн", "стиральн"],
    "dishwasher": ["посудомий", "посудомо"],
    "fridge": ["холодильник"],
    "oven": ["духовк", "плит"],
    "kettle": ["чайник"],
    "hand": ["ручн"],
    "phone": ["телефон", "смартфон", "мобіл", "мобил"],
    "tablet": ["планшет"],
    "laptop": ["ноутбук", "ноута"],
    "monitor": ["монітор", "монитор"],
    "keyboard": ["клавіатур", "клавиатур"],
    "mouse": ["мишк", "мышк", "миша", "мышь"],
    "headphone": ["навушник", "наушник"],
    "speaker": ["колонк", "динамік", "динамик"],
    "camera": ["камер", "фотоапарат"],
    "drone": ["дрон", "квадрокоптер", "коптер"],
    "controller": ["джойстик", "геймпад", "контролер", "контроллер"],
    "console": ["приставк", "консол"],
    "router": ["роутер", "маршрутизатор"],
    "antenna": ["антен"],
    "battery": ["батаре", "акумулятор", "аккумулятор", "батарейк"],
    "printer": ["принтер"],
    "spool": ["котушк", "катушк"],
    "filament": ["філамент", "филамент", "пластик для друку"],
    "extruder": ["екструдер", "экструдер"],
    "glasses": ["окуляр", "очк"],
    "watch": ["годинник наруч", "наручн"],
    "strap": ["ремінц", "ремешк", "ремін", "ремен"],
    # transport
    "car": ["автомоб", "машин", "авто"],
    "bike": ["велосипед", "вело"],
    "scooter": ["самокат", "скутер"],
    "motorcycle": ["мотоцикл"],
    "airplane": ["літак", "літач", "самолет", "самольот"],
    "ship": ["корабел", "корабл", "кораб", "човен", "лодк"],
    "train": ["потяг", "поїзд", "поезд", "паровоз"],
    "tank": ["танк"],
    "truck": ["вантажівк", "грузовик"],
    # toys and decor
    "toy": ["іграшк", "игрушк"],
    "figurine": ["фігурк", "фигурк", "статуетк", "статуэтк", "статуя"],
    "miniature": ["мініатюр", "миниатюр"],
    "toy car": ["машинк"],
    "robot": ["робот"],
    "dragon": ["дракон"],
    "dinosaur": ["динозавр", "дінозавр"],
    "cat": ["котик", "кошк", "кошен", "котен"],
    "dog": ["собак", "собач", "песик", "щен"],
    "bear": ["ведмед", "медвед"],
    "turtle": ["черепах"],
    "octopus": ["восьминіг", "осьминог"],
    "fish": ["рибк", "рыбк"],
    "bird": ["пташ", "птах", "птиц"],
    "owl": ["сова", "сови", "совы", "совен", "сову"],
    "fox": ["лисиц", "лиса", "лиси", "лисичк"],
    "rabbit": ["кролик", "заєць", "заяц", "зайч", "зайц"],
    "horse": ["кінь", "коня", "конь", "лошад", "конячк"],
    "elephant": ["слон"],
    "unicorn": ["єдиноріг", "единорог"],
    "skull": ["череп"],
    "sword": ["меча", "мечі"],
    "shield": ["щита"],
    "helmet": ["шолом", "шлем"],
    "mask": ["маск"],
    "chess": ["шах", "шахмат"],
    "puzzle": ["пазл", "головоломк"],
    "dice": ["кубик", "кості", "кости"],
    "cube": ["куб"],
    "fidget": ["антистрес", "антистресс", "фіджет", "фиджет", "спінер", "спиннер"],
    "whistle": ["свисток", "свистк"],
    "flexi": ["гнучк", "гибк"],
    "ring": ["кільц", "кольц", "каблучк", "перстен"],
    "bracelet": ["браслет"],
    "earring": ["сережк", "серьг"],
    "pendant": ["кулон", "підвіск", "подвеск"],
    "logo": ["логотип", "лого"],
    "name": ["ім'я", "імен", "имя", "имен"],
    "lithophane": ["літофан", "литофан"],
    "cosplay": ["косплей"],
    "gift": ["подарун", "подарок", "подарк"],
    # size and shape
    "small": ["маленьк", "малий", "мала", "мале", "малый", "малая", "крихітн", "крошечн"],
    "large": ["великий", "велика", "велике", "великі", "большой", "большая", "большое", "большие", "величезн", "огромн"],
    "mini": ["міні", "мини"],
    "round": ["кругл"],
    "square": ["квадрат"],
    "hexagon": ["шестигран", "шестикутн"],
    "spiral": ["спірал", "спирал"],
    "articulated": ["рухом", "подвижн", "шарнірн", "шарнирн"],
    "print in place": ["без збирання", "без сборки"],
}

# Short words that would clash as stems: matched only whole.
_EXACT = {
    "кіт": "cat", "кот": "cat", "коти": "cat", "коты": "cat", "кота": "cat",
    "пес": "dog", "пса": "dog",
    "вал": "shaft", "вали": "shaft",
    "ваза": "vase", "вазу": "vase", "вази": "vase", "вазы": "vase",
    "меч": "sword", "щит": "shield", "кит": "whale", "кита": "whale",
    "сад": "garden", "саду": "garden",
    "миша": "mouse", "мишу": "mouse", "мышь": "mouse",
    "лев": "lion", "лева": "lion",
    "оса": "wasp",
    "бра": "lamp",
    "мяч": "ball", "м'яч": "ball", "кулька": "ball", "шар": "ball", "шарик": "ball",
    "ось": "shaft", "осі": "shaft",
    "куб": "cube", "куба": "cube",
    "стіл": "desk", "шафа": "cabinet", "шафи": "cabinet", "шафу": "cabinet", "шафі": "cabinet",
}

# Brands written in Cyrillic.
_BRANDS = {
    "бош": "bosch", "бош'": "bosch", "дайсон": "dyson", "ікеа": "ikea", "икеа": "ikea", "ікея": "ikea", "икея": "ikea",
    "сяомі": "xiaomi", "сяоми": "xiaomi", "ксіомі": "xiaomi", "ксиоми": "xiaomi", "самсунг": "samsung",
    "айфон": "iphone", "айпад": "ipad", "епл": "apple", "эпл": "apple", "лего": "lego", "бамбу": "bambu",
    "ендер": "ender", "эндер": "ender", "пруша": "prusa", "прюша": "prusa", "гоупро": "gopro",
    "плейстейшн": "playstation", "нінтендо": "nintendo", "нинтендо": "nintendo", "свіч": "switch",
    "тесла": "tesla", "мерседес": "mercedes", "тойота": "toyota", "фольксваген": "volkswagen",
    "шкода": "skoda", "рено": "renault", "ауді": "audi", "ауди": "audi", "бмв": "bmw", "форд": "ford",
    "опель": "opel", "хонда": "honda", "мазда": "mazda", "ніссан": "nissan", "ниссан": "nissan",
    "філіпс": "philips", "филипс": "philips", "браун": "braun", "мулінекс": "moulinex", "мулинекс": "moulinex",
    "тефаль": "tefal", "кенвуд": "kenwood", "делонгі": "delonghi", "делонги": "delonghi", "ровента": "rowenta",
    "керхер": "karcher", "макіта": "makita", "макита": "makita", "девольт": "dewalt", "мілуокі": "milwaukee",
    "раптор": "raptor", "покемон": "pokemon", "пікачу": "pikachu", "пикачу": "pikachu", "мінекрафт": "minecraft",
    "майнкрафт": "minecraft", "варгеймер": "wargame", "вархаммер": "warhammer", "зельда": "zelda", "маріо": "mario",
    "марио": "mario", "грут": "groot", "йода": "yoda", "бетмен": "batman", "спайдермен": "spiderman",
}

# Filler words of both languages: they only make a search miss.
_STOP = set("""
я мені мене мне меня мій моя моє мої мой мое мои мого моего моєї моей свій своя своє свої свой свое свои
ми нам нас мы ви вам вас вы ти тобі тебе ты тебе він вона воно вони он она оно они його її їх его ее их
потрібно потрібна потрібен потрібні потрібне треба нужно нужна нужен нужны нужное надо необхідно необходимо
хочу хотів хотіла хотіли хотел хотела хотели хотілось хотелось бажаю желаю шукаю ищу шукати искать
будь ласка пожалуйста прошу дякую спасибо привіт привет добрий добрый день вечір вечер здравствуйте вітаю
для на в у з с із зі со и і й та а але но або или чи ли до від от по при про о об к к під под над за між между
щоб чтобы що что як как який яка яке які какой какая какое какие такий такая такое такие цей ця це ці этот эта это эти
той та те ті тот те там тут здесь є есть буде будет був была було было можна можно можете можеш могли
зробити сделать зробіть сделайте надрукувати надрукуйте роздрукувати распечатать распечатайте напечатать напечатайте
друк друку печать печати друкувати печатать 3д 3d модель моделі модели модельку деталь деталі детали детальку
файл файли файлы stl знайти найти знайдіть найдите знайди найди підберіть подберите порахувати посчитать
порахуйте посчитайте ціна ціну цена цену вартість стоимость скільки сколько коштує стоит коштуватиме
дуже очень трохи немного щось что-то якийсь какой-то якусь какую-то будь-який любой новий новая новый нове новое
шт штук штуки штука копій копии екземпляр pcs
a an the for of to with and or in on at by from my me i we need want looking please print printed printing
model models file files stl 3mf obj find search some any
""".split())

_TOKEN_RE = re.compile(r"[0-9a-zа-яіїєґё][0-9a-zа-яіїєґё'’ʼ\-]*", re.I)
_CYRILLIC_RE = re.compile(r"[а-яіїєґё]", re.I)
_STEMS = sorted(((stem, en) for en, stems in _DICTIONARY.items() for stem in stems if " " not in stem),
                key=lambda p: -len(p[0]))
_PHRASES = sorted(((stem, en) for en, stems in _DICTIONARY.items() for stem in stems if " " in stem),
                  key=lambda p: -len(p[0]))
_UNITS = {"мм": "mm", "mm": "mm", "см": "cm", "cm": "cm"}


def _tokens(text: str) -> list[str]:
    text = text.lower().replace("ё", "е")
    return [t.replace("’", "'").replace("ʼ", "'").strip("-'") for t in _TOKEN_RE.findall(text)]


def translate(text: str) -> tuple[list[str], list[str]]:
    """English search terms for a Ukrainian/Russian request, and the words that stayed unknown.

    >>> translate("Мені потрібна шестерня для міксера Bosch")
    (['gear', 'mixer', 'bosch'], [])
    """
    low = " " + " ".join(_tokens(text)) + " "
    terms: list[str] = []
    for phrase, en in _PHRASES:              # two-word stems first: "ручки двер" -> handle
        if " " + phrase in low:
            terms.append(en)
            low = low.replace(" " + phrase, " ", 1)
    tokens = low.split()
    unknown: list[str] = []
    skip_next = False
    for i, tok in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if tok.isdigit():
            if nxt in _UNITS:                # 20 мм -> 20mm
                terms.append(tok + _UNITS[nxt])
                skip_next = True
            elif nxt in ("шт", "штук", "штуки", "pcs", "копій", "копии"):
                skip_next = True             # a quantity, not a size
            continue
        if re.fullmatch(r"[мm]\d{1,2}", tok):  # м3 / M3 bolts
            terms.append("m" + tok[1:])
            continue
        if tok in _STOP or len(tok) < 2:
            continue
        if not _CYRILLIC_RE.search(tok):     # brand, model number, English word
            terms.append(tok)
            continue
        en = _EXACT.get(tok) or _BRANDS.get(tok)
        if not en:
            en = next((e for stem, e in _STEMS if len(stem) >= 4 and tok.startswith(stem)), None)
        if en:
            terms.append(en)
        else:
            unknown.append(tok)
    out: list[str] = []
    for t in terms:
        if t not in out:
            out.append(t)
    return out[:MAX_TERMS], unknown


def native_query(text: str) -> str:
    """The customer's own words without filler words (some models are named in Ukrainian or Russian)."""
    words = [t for t in _tokens(text) if t not in _STOP and not t.isdigit() and len(t) > 1]
    return " ".join(words[:6])


# ---------- ranking: show only models that fit the request ----------
#
# Printables' own order is loose: for "holder phone magsafe" it also returns holders made for one
# car model or holders without MagSafe at all. Every candidate is checked against the request:
#   - names the customer gave (MagSafe, Bosch, GoPro...) must be in the model's name, tags or text;
#   - the object (holder, gear...) should be there, synonyms count ("stand", "mount", "dock");
#   - a car or a brand the customer did not mention lowers the score.

POOL = 16   # candidates taken from each search before ranking

# Words that name the same thing in model titles.
SYNONYMS = {
    "holder": ["holder", "stand", "mount", "dock", "cradle", "clip", "grip", "bracket"],
    "stand": ["stand", "holder", "dock", "base", "rest", "cradle"],
    "mount": ["mount", "holder", "bracket", "adapter", "clamp"],
    "bracket": ["bracket", "mount", "support", "holder"],
    "phone": ["phone", "smartphone", "iphone", "mobile", "cellphone"],
    "tablet": ["tablet", "ipad"],
    "headphone": ["headphone", "headset", "earphone", "earbud", "airpods"],
    "car": ["car", "vehicle", "auto", "automotive", "vent", "dashboard"],
    "bike": ["bike", "bicycle", "cycling", "handlebar"],
    "case": ["case", "cover", "enclosure", "housing", "shell", "sleeve"],
    "box": ["box", "container", "storage", "bin", "crate"],
    "container": ["container", "box", "jar", "canister", "storage"],
    "lid": ["lid", "cap", "cover", "top"],
    "cap": ["cap", "lid", "cover", "plug", "foot", "feet", "glide"],
    "hook": ["hook", "hanger"],
    "hanger": ["hanger", "hook"],
    "organizer": ["organizer", "organiser", "storage", "tray", "caddy"],
    "gear": ["gear", "cog", "sprocket", "pinion"],
    "knob": ["knob", "dial"],
    "handle": ["handle", "grip", "knob", "pull"],
    "cable": ["cable", "cord", "wire"],
    "figurine": ["figurine", "figure", "statue", "sculpture", "bust"],
    "toy": ["toy", "fidget", "game"],
    "planter": ["planter", "pot", "flowerpot"],
    "lamp": ["lamp", "light", "lampshade"],
    "shelf": ["shelf", "shelves"],
    "keychain": ["keychain", "keyring", "key chain", "key ring", "keyfob"],
    "vacuum": ["vacuum", "hoover"],
    "replacement part": ["replacement", "spare", "part", "repair"],
    "leg": ["leg", "foot", "feet"],
    "chair": ["chair", "stool", "seat"],
    "table": ["table", "desk"],
    "desk": ["desk", "table"],
    "cabinet": ["cabinet", "cupboard", "drawer", "wardrobe", "furniture"],
    "drawer": ["drawer", "cabinet"],
}

# Words that only refine a request: they help when found and do not exclude a model when missing.
MODIFIERS = {"small", "large", "mini", "round", "square", "hexagon", "spiral", "articulated", "print in place",
             "outdoor", "garden", "kitchen", "bathroom", "christmas", "flower", "hand", "wall", "desk",
             "replacement part", "repair"}

# A model made for a car the customer did not mention is the wrong context for them.
CAR_WORDS = {"car", "cars", "vehicle", "automotive", "auto", "bmw", "audi", "skoda", "škoda", "porsche", "ford",
             "tesla", "toyota", "honda", "mazda", "mx5", "miata", "volkswagen", "vw", "mercedes", "opel",
             "renault", "nissan", "kia", "hyundai", "subaru", "volvo", "jeep", "peugeot", "citroen", "fiat",
             "lexus", "octavia", "enyaq", "golf", "passat", "taycan", "transit", "dacia", "seat", "mini cooper"}
# Devices and brands: a model made for one of them fits a general request worse.
BRANDS = {"dji", "ps5", "ps4", "playstation", "xbox", "nintendo", "dualsense", "garmin", "concept2", "simucube",
          "ipod", "pixel", "samsung", "galaxy", "xiaomi", "dyson", "ikea", "gopro", "raspberry", "arduino",
          "ender", "prusa", "bambu", "voron", "creality", "lego", "warhammer", "steam", "oculus", "quest",
          "kindle", "logitech", "anker", "makita", "dewalt", "milwaukee", "ryobi", "bosch", "apple", "google",
          "huawei", "oneplus", "sony", "canon", "nikon", "fujifilm", "insta360", "airtag", "macbook", "ipad"}

# Product names customers misspell ("magsefe"); a near miss is corrected before searching.
KNOWN_NAMES = sorted(set(_BRANDS.values()) | BRANDS | {
    "magsafe", "iphone", "airpods", "android", "qi", "usb", "hdmi", "nerf", "pokemon", "minecraft"})

_DICT_VALUES = set(_DICTIONARY) | set(_EXACT.values())
_WORD_RE = re.compile(r"[0-9a-zа-яіїєґёš]+", re.I)


def _distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def fix_typo(term: str) -> str:
    """"magsefe" -> "magsafe": a near miss of a known product name (same first letter)."""
    if len(term) < 4 or term in KNOWN_NAMES or term in _DICT_VALUES or not term.isalpha():
        return term
    allowed = 1 if len(term) < 7 else 2
    best = min((n for n in KNOWN_NAMES if n[0] == term[0] and abs(len(n) - len(term)) <= allowed),
               key=lambda n: _distance(term, n), default=None)
    return best if best and _distance(term, best) <= allowed else term


def _kind(term: str) -> str:
    if term in MODIFIERS:
        return "modifier"
    if re.fullmatch(r"\d+(mm|cm)|m\d{1,2}", term):
        return "size"
    if term in _DICT_VALUES or term in SYNONYMS:
        return "object"
    return "name"          # brand, product or a word we do not know: the customer asked for exactly this


WEIGHT = {"name": 3.0, "object": 2.0, "modifier": 1.0, "size": 1.0}


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]


_NEGATIONS = {"non", "no", "without", "not", "без", "не"}


def _hit(words: list[str], text: str, syn: str) -> bool:
    if " " in syn:
        return syn in text
    for i, w in enumerate(words):
        same = w == syn or w == syn + "s" or w == syn + "es" or (len(syn) >= 5 and w.startswith(syn))
        if not syn.isascii() and w.startswith(syn):   # Ukrainian/Russian stems
            same = True
        # "Non-MagSafe holder" is exactly not what was asked for; "vase mode" is a way to print, not a vase.
        negated = i > 0 and words[i - 1] in _NEGATIONS
        print_mode = syn == "vase" and i + 1 < len(words) and words[i + 1] == "mode"
        if same and not negated and not print_mode:
            return True
    return False


def _relevance(m: dict, terms: list[str]) -> tuple[float, bool]:
    """(score 0..1 minus penalties, whether the model has what the customer must get).

    Must have: every name they gave (MagSafe, Bosch) and at least half of the objects
    (for "holder phone": a holder or a phone; for "vacuum": the vacuum itself).
    """
    fields = [(m["name"], 1.0), (" ".join(m.get("tags") or []), 0.7),
              (m.get("summary", "") + " " + " ".join(m.get("category") or []), 0.5)]
    fields = [(_words(t), t.lower(), w) for t, w in fields]
    total = got = 0.0
    names_ok = True
    objects = objects_hit = 0
    for term in terms:
        kind = _kind(term)
        weight = WEIGHT[kind]
        syns = SYNONYMS.get(term, [term]) + [s for s in _DICTIONARY.get(term, []) if " " not in s]
        strength = max((w for words, text, w in fields if any(_hit(words, text, s) for s in syns)), default=0.0)
        total += weight
        got += weight * strength
        if kind == "name" and strength == 0:
            names_ok = False
        if kind == "object":
            objects += 1
            objects_hit += strength > 0
    if objects and objects_hit * 2 < objects:
        names_ok = False
    score = got / total if total else 0.0

    # Context the customer did not ask for.
    asked = set(terms) | {s for t in terms for s in SYNONYMS.get(t, [])}
    name_words = set(_words(m["name"]) + [t.lower() for t in m.get("tags") or []])
    automotive = "Automotive" in (m.get("category") or []) or bool(name_words & CAR_WORDS)
    if automotive and not (asked & CAR_WORDS):
        score -= 0.35
    foreign = [b for b in name_words & BRANDS if b not in asked]
    score -= min(0.3, 0.15 * len(foreign))
    return score, names_ok


def _search(query: str, limit: int) -> list[dict]:
    try:
        return printables.search(query, limit)
    except printables.PrintablesError:
        return []


def _rank(pool: list[dict], terms: list[str]) -> tuple[list[dict], list[tuple[float, int, dict]]]:
    scored = []
    for i, m in enumerate(pool):
        score, names_ok = _relevance(m, terms)
        scored.append((score if names_ok else score - 1.0, i, m))
    scored.sort(key=lambda s: (-s[0], s[1]))
    good = [m for score, _, m in scored if score >= 0.55]
    return good, scored


def find(text: str, limit: int = 6) -> tuple[list[dict], str, list[str], bool]:
    """Printables models for a request in any of the three languages.

    Returns (models, the English query used or "", words the dictionary did not know,
    whether the models fit the request exactly; False means "closest we have").
    """
    terms, unknown = translate(text)
    terms = [fix_typo(t) for t in terms]
    english = " ".join(terms)
    native = native_query(text)

    first = []
    if english:
        first.append(english)
    if native and _CYRILLIC_RE.search(native) and native != english:
        first.append(native)
    if not first:
        return [], "", unknown, False
    if not terms:   # nothing translated: the site's own order is all we have
        return [printables.public(m) for m in _search(native, limit)], "", unknown, False

    with ThreadPoolExecutor(max_workers=4) as pool:
        found = _merge(list(pool.map(lambda q: _search(q, POOL), first)))
        good, scored = _rank(found, terms)
        # Too little: the main English words in pairs ("gear mixer", "gear bosch", "mixer bosch").
        if len(good) < limit and len(terms) >= 3:
            pairs = [" ".join(p) for p in combinations(terms[:3], 2)]
            found = _merge([found] + list(pool.map(lambda q: _search(q, POOL), pairs)))
            good, scored = _rank(found, terms)

    if good:
        return [printables.public(m) for m in good[:limit]], english, unknown, True
    closest = [m for score, _, m in scored if score >= 0.3][:limit]
    return [printables.public(m) for m in closest], english, unknown, False


def _merge(lists: list[list[dict]]) -> list[dict]:
    out, seen = [], set()
    for lst in lists:
        for m in lst:
            if m["id"] not in seen:
                seen.add(m["id"])
                out.append(m)
    return out
