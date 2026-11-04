"""Иконки ингредиентов: по названию продукта подбираем картинку из набора webapp/icons.

Набор — Microsoft Fluent Emoji (лицензия MIT), плюс несколько своих
(beet, smetana, cream_cheese, sesame), собранных из деталей того же набора.
Чтобы добавить свою иконку, положи SVG в icons/flat/<ключ>.svg (размер 32×32)
и допиши строчку в STEMS.
"""
import re

from . import config

FALLBACK = "jar"

# Начало слова в названии продукта -> ключ иконки. Порядок важен: сверху более точные.
STEMS: list[tuple[str, str]] = [
    # молочное
    ("сметан", "smetana"), ("йогурт", "smetana"), ("творожн", "cream_cheese"),
    ("сливочный сыр", "cream_cheese"), ("крем-чиз", "cream_cheese"), ("филадельф", "cream_cheese"),
    ("маскарпоне", "cream_cheese"), ("рикотт", "cream_cheese"), ("творог", "cream_cheese"),
    ("сыр", "cheese_wedge"), ("пармезан", "cheese_wedge"), ("моцарел", "cheese_wedge"),
    ("сливочное масло", "butter"), ("масло сливочн", "butter"), ("маргарин", "butter"),
    ("молок", "glass_of_milk"), ("кефир", "glass_of_milk"), ("ряженк", "glass_of_milk"),
    ("сливки", "glass_of_milk"), ("сливок", "glass_of_milk"), ("сгущ", "jar"),
    ("яйц", "egg"), ("яиц", "egg"), ("желтк", "egg"), ("белк", "egg"),
    # соусы и консервы
    ("томатная паста", "canned_food"), ("томатной пасты", "canned_food"), ("томатный соус", "canned_food"),
    ("кетчуп", "canned_food"), ("консерв", "canned_food"), ("пассата", "canned_food"),
    ("майонез", "jar"), ("горчиц", "jar"), ("джем", "jar"), ("варень", "jar"), ("соус", "jar"),
    # мясо и рыба
    ("бекон", "bacon"), ("ветчин", "bacon"), ("колбас", "hot_dog"), ("сосиск", "hot_dog"),
    ("баранин", "meat_on_bone"), ("ребр", "meat_on_bone"),
    ("говяд", "cut_of_meat"), ("свин", "cut_of_meat"), ("телят", "cut_of_meat"),
    ("фарш", "cut_of_meat"), ("мяс", "cut_of_meat"), ("стейк", "cut_of_meat"), ("печень", "cut_of_meat"),
    ("куркум", "salt"), ("кур", "poultry_leg"), ("цыпл", "poultry_leg"), ("индей", "poultry_leg"), ("утк", "poultry_leg"),
    ("креветк", "shrimp"), ("кальмар", "squid"),
    ("рыб", "fish"), ("лосос", "fish"), ("сёмг", "fish"), ("семг", "fish"), ("треск", "fish"),
    ("тунц", "fish"), ("тунец", "fish"), ("форел", "fish"), ("скумбри", "fish"), ("сельд", "fish"),
    # овощи
    ("свёкл", "beet"), ("свекл", "beet"), ("картоф", "potato"), ("картош", "potato"),
    ("морков", "carrot"), ("лук", "onion"), ("чеснок", "garlic"), ("чесноч", "garlic"),
    ("капуст", "leafy_green"), ("шпинат", "leafy_green"), ("руккол", "leafy_green"),
    ("брокколи", "broccoli"), ("цветная", "broccoli"),
    ("огур", "cucumber"), ("кабач", "cucumber"), ("цукин", "cucumber"),
    ("помидор", "tomato"), ("томат", "tomato"), ("черри", "tomato"),
    ("болгарск", "bell_pepper"), ("сладкий перец", "bell_pepper"), ("перец чили", "hot_pepper"),
    ("чили", "hot_pepper"), ("острый перец", "hot_pepper"), ("паприк", "hot_pepper"),
    ("баклажан", "eggplant"), ("кукуруз", "ear_of_corn"), ("гриб", "mushroom"), ("шампиньон", "mushroom"),
    ("авокадо", "avocado"), ("имбир", "ginger_root"), ("тыкв", "melon"),
    ("фасол", "beans"), ("нут", "beans"), ("чечевиц", "beans"),
    ("горох", "pea_pod"), ("горош", "pea_pod"), ("эдамаме", "pea_pod"), ("стручк", "pea_pod"),
    ("маслин", "olive"), ("олив", "olive"),
    ("салат", "green_salad"),
    ("зелен", "herb"), ("укроп", "herb"), ("петрушк", "herb"), ("кинз", "herb"), ("базилик", "herb"),
    ("мят", "herb"), ("розмарин", "herb"), ("тимьян", "herb"), ("орегано", "herb"), ("лавров", "herb"),
    # фрукты и ягоды
    ("яблок", "red_apple"), ("груш", "pear"), ("мандарин", "tangerine"), ("апельсин", "tangerine"),
    ("лимон", "lemon"), ("лайм", "lemon"), ("банан", "banana"), ("арбуз", "watermelon"),
    ("виноград", "grapes"), ("изюм", "grapes"), ("клубник", "strawberry"), ("земляник", "strawberry"),
    ("малин", "strawberry"), ("черник", "blueberries"), ("голубик", "blueberries"), ("ягод", "blueberries"),
    ("смородин", "blueberries"), ("вишн", "cherries"), ("черешн", "cherries"), ("дын", "melon"),
    ("персик", "peach"), ("абрикос", "peach"), ("кураг", "peach"), ("манго", "mango"),
    ("ананас", "pineapple"), ("кокос", "coconut"), ("киви", "kiwi_fruit"),
    # крупы, мука, хлеб
    ("мук", "sheaf_of_rice"), ("крахмал", "sheaf_of_rice"), ("манк", "sheaf_of_rice"),
    ("овся", "sheaf_of_rice"), ("пшен", "sheaf_of_rice"), ("круп", "sheaf_of_rice"),
    ("хлопь", "sheaf_of_rice"), ("отруб", "sheaf_of_rice"), ("булгур", "sheaf_of_rice"), ("кускус", "sheaf_of_rice"),
    ("рис", "cooked_rice"), ("гречк", "cooked_rice"), ("киноа", "cooked_rice"),
    ("макарон", "spaghetti"), ("спагетти", "spaghetti"), ("паст", "spaghetti"), ("лапш", "spaghetti"),
    ("батон", "baguette_bread"), ("багет", "baguette_bread"), ("хлеб", "bread"), ("тост", "bread"),
    ("лаваш", "flatbread"), ("тортиль", "flatbread"), ("пита", "flatbread"), ("круассан", "croissant"),
    ("печенье", "cookie"), ("тесто", "pie"),
    # орехи и семена
    ("кунжут", "sesame"), ("семечк", "sesame"), ("семен", "sesame"), ("чиа", "sesame"), ("льнян", "sesame"),
    ("орех", "peanuts"), ("арахис", "peanuts"), ("миндал", "peanuts"), ("фундук", "peanuts"),
    ("кешью", "peanuts"), ("каштан", "chestnut"),
    # сладкое, напитки, специи
    ("сахар", "jar"), ("мёд", "honey_pot"), ("мед", "honey_pot"), ("шоколад", "chocolate_bar"),
    ("какао", "hot_beverage"), ("кофе", "hot_beverage"), ("чай", "hot_beverage"),
    ("сок", "tumbler_glass"), ("вин", "wine_glass"),
    ("вод", "droplet"), ("бульон", "droplet"), ("уксус", "droplet"), ("соев", "droplet"), ("лёд", "ice"),
    ("масл", "olive"),  # растительное, оливковое и т. п.
    ("соль", "salt"), ("соли", "salt"), ("перец", "salt"), ("специ", "salt"), ("приправ", "salt"),
    ("корица", "jar"), ("ванил", "jar"), ("разрыхл", "jar"), ("сода", "jar"), ("дрожж", "jar"),
    ("желатин", "jar"),
]

_KEYS: set[str] | None = None


def keys() -> set[str]:
    """Какие иконки реально лежат в папке."""
    global _KEYS
    if _KEYS is None:
        _KEYS = {p.stem for p in (config.WEBAPP_DIR / "icons" / "flat").glob("*.svg")}
    return _KEYS


def from_name(name: str) -> str | None:
    low = name.lower().replace("ё", "е")
    for stem, key in STEMS:
        if re.search(r"(?<![а-яa-z])" + re.escape(stem.replace("ё", "е")), low):
            return key
    return None


def pick(name: str, suggested: str | None = None) -> str:
    """Иконка для продукта: сначала словарь, потом подсказка ИИ, иначе баночка."""
    k = from_name(name)
    if k and k in keys():
        return k
    if suggested and suggested in keys():
        return suggested
    return FALLBACK


def key_list() -> str:
    return ", ".join(sorted(keys()))
