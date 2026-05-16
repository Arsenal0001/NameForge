"""
Seed per-``part_type`` templates (``part_type_trigger``) and MoySklad folder paths.

Run from project root:
    python scripts/seed_category_mapping.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import sqlite3  # noqa: E402

from src.db import get_conn, init_db  # noqa: E402


def slugify(part_type: str) -> str:
    s = (part_type or "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    return s


PART_TYPE_TEMPLATES: dict[str, tuple[str, str]] = {
    # Brakes
    "Колодки тормозные Передние": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Колодки тормозные Задние": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Диск тормозной Передний": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    # Suspension
    "Амортизатор Передний": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years} {engine}",
    ),
    "Амортизатор Задний": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years} {engine}",
    ),
    # Engine
    "Патрубок охлаждения": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years} {engine}",
    ),
    "Патрубок Отопителя / Печки": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Ремень генератора": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {years} {engine}",
    ),
    "Свеча зажигания": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {years} {engine}",
    ),
    "Поршень двигателя": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {years} {engine}",
    ),
    "Поршень двигателя с пальцами": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {years} {engine}",
    ),
    "Поршень двигателя с пальцами и кольцами": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {years} {engine}",
    ),
    # Body / lights
    "Фара противотуманная": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Фара противотуманная модельная галогенная": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Фара (блок) Правая": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Фара (блок) Левая": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Фонарь Задний": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Бампер Передний": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Бампер Задний": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Решетка радиатора": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Радиатор охлаждения": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years} {engine}",
    ),
    "Зеркало наружное (комплект) / Боковое": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Стеклоподъемник электрический": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Дефлектор окна двери / Ветровик": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Глушитель Задний / Основной": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years} {engine}",
    ),
    "Глушитель средний / Резонатор": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years} {engine}",
    ),
    # Electrics / multimedia
    "Линза светодиодная BI-LED": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Линза светодиодная": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Рамка-адаптер магнитолы Андроид": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Магнитола Андроид, монитор": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    "Магнитола 1 DIN": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Лампа светодиодная габаритная": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Лампа H7 светодиодная": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Лампа H4 светодиодная": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Лампа габаритная": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Бленда линзы / Маска": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Стекло фары Правое": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body} {years}",
    ),
    # Interior
    "Чехлы сидений": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {characteristics}",
    ),
    "Чехлы сидений 1-2 ряд": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {characteristics}",
    ),
    "Коврик салона резиновый": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body}",
    ),
    "Коврик салона EVA": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body}",
    ),
    "Коврик на панель солнцезащитный": (
        "fitment",
        "{part_type} {brand} {article} {make} {model}",
    ),
    "Коврик багажника": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body}",
    ),
    "Полка багажника деревянная": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body}",
    ),
    "Шторка Бокового Переднего стекла": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body}",
    ),
    "Шторка Бокового Заднего стекла": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body}",
    ),
    "Шторка Заднего стекла": (
        "fitment",
        "{part_type} {brand} {article} {make} {model} {body}",
    ),
    "Накидка на сиденье Переднее": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Накидка на сиденье (комплект)": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Оплетка руля вшиваемая": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Ручка на рычаг КПП переключения передач": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Чехол рычага КПП / Юбка": (
        "fitment",
        "{part_type} {brand} {article} {make} {model}",
    ),
    "Пленка тонировочная": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Ароматизатор подвесной": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Хомут-стяжка нейлоновый": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Разъем": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Рамка знака номерного пластиковая": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Колпаки колеса": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
    "Насадка на глушитель": (
        "universal",
        "{part_type} {brand} {article} {characteristics}",
    ),
}

FOLDER_MAPPING: dict[str, str] = {
    "Колодки тормозные Передние": "Тормозная система/Колодки",
    "Колодки тормозные Задние": "Тормозная система/Колодки",
    "Диск тормозной Передний": "Тормозная система/Диски",
    "Амортизатор Передний": "Подвеска/Амортизаторы",
    "Амортизатор Задний": "Подвеска/Амортизаторы",
    "Патрубок охлаждения": "Двигатель/Патрубки",
    "Патрубок Отопителя / Печки": "Двигатель/Патрубки",
    "Ремень генератора": "Двигатель/Ремни",
    "Свеча зажигания": "Двигатель/Свечи",
    "Поршень двигателя": "Двигатель/Поршни",
    "Поршень двигателя с пальцами": "Двигатель/Поршни",
    "Поршень двигателя с пальцами и кольцами": "Двигатель/Поршни",
    "Радиатор охлаждения": "Двигатель/Радиаторы",
    "Глушитель Задний / Основной": "Выхлопная система/Глушители",
    "Глушитель средний / Резонатор": "Выхлопная система/Резонаторы",
    "Фара противотуманная": "Кузов и оптика/Фары ПТФ",
    "Фара противотуманная модельная галогенная": "Кузов и оптика/Фары ПТФ",
    "Фара (блок) Правая": "Кузов и оптика/Фары",
    "Фара (блок) Левая": "Кузов и оптика/Фары",
    "Фонарь Задний": "Кузов и оптика/Фонари",
    "Стекло фары Правое": "Кузов и оптика/Стёкла фар",
    "Бампер Передний": "Кузов и оптика/Бамперы",
    "Бампер Задний": "Кузов и оптика/Бамперы",
    "Решетка радиатора": "Кузов и оптика/Решётки",
    "Зеркало наружное (комплект) / Боковое": "Кузов и оптика/Зеркала",
    "Дефлектор окна двери / Ветровик": "Кузов и оптика/Дефлекторы",
    "Стеклоподъемник электрический": "Электрика/Стеклоподъёмники",
    "Линза светодиодная BI-LED": "Электрика/Оптика тюнинг",
    "Линза светодиодная": "Электрика/Оптика тюнинг",
    "Бленда линзы / Маска": "Электрика/Оптика тюнинг",
    "Рамка-адаптер магнитолы Андроид": "Мультимедиа/Рамки адаптеры",
    "Магнитола Андроид, монитор": "Мультимедиа/Магнитолы Андроид",
    "Магнитола 1 DIN": "Мультимедиа/Магнитолы",
    "Лампа светодиодная габаритная": "Электрика/Лампы",
    "Лампа H7 светодиодная": "Электрика/Лампы",
    "Лампа H4 светодиодная": "Электрика/Лампы",
    "Лампа габаритная": "Электрика/Лампы",
    "Разъем": "Электрика/Разъёмы",
    "Чехлы сидений": "Салон/Чехлы",
    "Чехлы сидений 1-2 ряд": "Салон/Чехлы",
    "Накидка на сиденье Переднее": "Салон/Накидки",
    "Накидка на сиденье (комплект)": "Салон/Накидки",
    "Оплетка руля вшиваемая": "Салон/Оплётки руля",
    "Ручка на рычаг КПП переключения передач": "Салон/Тюнинг салона",
    "Чехол рычага КПП / Юбка": "Салон/Тюнинг салона",
    "Коврик салона резиновый": "Салон/Коврики",
    "Коврик салона EVA": "Салон/Коврики",
    "Коврик на панель солнцезащитный": "Салон/Коврики на панель",
    "Коврик багажника": "Салон/Коврики",
    "Полка багажника деревянная": "Салон/Полки багажника",
    "Шторка Бокового Переднего стекла": "Салон/Шторки",
    "Шторка Бокового Заднего стекла": "Салон/Шторки",
    "Шторка Заднего стекла": "Салон/Шторки",
    "Пленка тонировочная": "Аксессуары/Тонировка",
    "Ароматизатор подвесной": "Аксессуары/Ароматизаторы",
    "Хомут-стяжка нейлоновый": "Аксессуары/Крепёж",
    "Рамка знака номерного пластиковая": "Аксессуары/Рамки номеров",
    "Колпаки колеса": "Аксессуары/Колпаки",
    "Насадка на глушитель": "Аксессуары/Тюнинг кузова",
}

_INSERT_TEMPLATE_SQL = """
    INSERT OR IGNORE INTO templates (
        template_key, version, applicability_type,
        name_pattern, is_active, part_type_trigger
    )
    VALUES (?, 'v1', ?, ?, 1, ?)
"""


def seed_category_mapping(conn: sqlite3.Connection) -> tuple[int, int]:
    triggers_before = {
        str(r[0])
        for r in conn.execute(
            "SELECT part_type_trigger FROM templates WHERE part_type_trigger IS NOT NULL"
        ).fetchall()
    }
    for part_type, (applicability_type, name_pattern) in PART_TYPE_TEMPLATES.items():
        conn.execute(
            _INSERT_TEMPLATE_SQL,
            (slugify(part_type), applicability_type, name_pattern, part_type),
        )
    triggers_after = {
        str(r[0])
        for r in conn.execute(
            "SELECT part_type_trigger FROM templates WHERE part_type_trigger IS NOT NULL"
        ).fetchall()
    }
    templates_added = len(triggers_after - triggers_before)

    folders_before = {
        str(r[0])
        for r in conn.execute("SELECT part_type FROM part_type_folder_map").fetchall()
    }
    for part_type, path in FOLDER_MAPPING.items():
        conn.execute(
            """
            INSERT OR REPLACE INTO part_type_folder_map
                (part_type, ms_folder_path)
            VALUES (?, ?)
            """,
            (part_type, path),
        )
    folders_after = {
        str(r[0])
        for r in conn.execute("SELECT part_type FROM part_type_folder_map").fetchall()
    }
    folders_added = len(folders_after - folders_before)

    return templates_added, folders_added


def main() -> int:
    init_db()
    with get_conn() as conn:
        templates_count, folders_count = seed_category_mapping(conn)
    print(f"Шаблонов добавлено: {templates_count}")
    print(f"Маппингов папок: {folders_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
