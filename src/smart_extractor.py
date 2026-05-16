import re
from typing import Dict

def parse_supplier_name(supplier_raw_name: str) -> Dict[str, str]:
    """
    {{...}} → part_type (Тип детали)
    [[...]] → brand (Бренд)
    <...> → applicability (Марка и модель)
    (...) → color (Цвет)
    [...] → characteristics (Свойства)
    ВНЕ скобок → article (Артикул)
    """
    result = {
        "part_type": "",
        "brand": "",
        "applicability": "",
        "color": "",
        "characteristics": "",
        "article": ""
    }
    if not supplier_raw_name:
        return result

    s = supplier_raw_name

    # {{...}} -> part_type
    m_pt = re.search(r'\{\{(.*?)\}\}', s)
    if m_pt:
        result["part_type"] = m_pt.group(1).strip()
        s = s.replace(m_pt.group(0), ' ')

    # [[...]] -> brand
    m_br = re.search(r'\[\[(.*?)\]\]', s)
    if m_br:
        brand = m_br.group(1).strip()
        if brand.upper() in ('NON', '?'):
            brand = 'Unknown'
        result["brand"] = brand
        s = s.replace(m_br.group(0), ' ')

    # <...> -> applicability
    m_app = re.search(r'\<(.*?)\>', s)
    if m_app:
        result["applicability"] = m_app.group(1).strip()
        s = s.replace(m_app.group(0), ' ')

    # (...) -> color
    m_col = re.search(r'\((.*?)\)', s)
    if m_col:
        result["color"] = m_col.group(1).strip()
        s = s.replace(m_col.group(0), ' ')

    # [...] -> characteristics
    m_char = re.search(r'\[(.*?)\]', s)
    if m_char:
        result["characteristics"] = m_char.group(1).strip()
        s = s.replace(m_char.group(0), ' ')

    # Clean up and everything else is article
    result["article"] = " ".join(s.split())
    return result


class AttributeStandardizer:
    @staticmethod
    def parse_characteristics(chars: str) -> dict:
        res = {"side": "", "axis": "", "engine": "", "line": "", "is_eco": False, "other": []}
        
        c = chars.lower()
        if 'по дешевле' in c or 'эко' in c:
            res["line"] = 'ЭКО'
            res["is_eco"] = True
            c = c.replace('по дешевле', '').replace('эко', '')
            
        parts = re.split(r'[, ]+', c)
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if p in ('лев', 'l', 'lh', 'левый'):
                res["side"] = 'левые' if not res["side"] else res["side"]
            elif p in ('прав', 'r', 'rh', 'правый'):
                res["side"] = 'правые' if not res["side"] else res["side"]
            elif p in ('перед', 'fr', 'передний'):
                res["axis"] = 'передние' if not res["axis"] else res["axis"]
            elif p in ('зад', 'rr', 'задний'):
                res["axis"] = 'задние' if not res["axis"] else res["axis"]
            elif p in ('16кл', '16v'):
                res["engine"] = '16V'
            elif p in ('8кл', '8v'):
                res["engine"] = '8V'
            else:
                res["other"].append(p)
                
        # For grammatically correct formula (передние левые) let's standardize words
        # "левый" -> "левые", "передний" -> "передние" based on typical naming.
        return res

def get_target_folder(part_type: str) -> str:
    """Resolve folder path via ``src.category_mapper``; fallback to unsorted bucket."""
    if not part_type:
        return '!_НЕРАЗОБРАННОЕ'

    try:
        from src.category_mapper import resolve_folder
        folder = resolve_folder(part_type)
    except Exception:
        folder = None

    return folder or '!_НЕРАЗОБРАННОЕ'
