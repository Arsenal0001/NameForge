import sys
from pathlib import Path

# Add root project dir to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.db import get_conn
from src.smart_extractor import parse_supplier_name

def main():
    print("Starting smart re-parsing for 'error' products...")
    
    # Initialize folder mapping for "Фильтр"
    with get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS category_mapping ("
            "id INTEGER PRIMARY KEY, "
            "part_type TEXT UNIQUE NOT NULL, "
            "folder_path TEXT NOT NULL"
            ")"
        )
        conn.execute(
            "INSERT OR IGNORE INTO category_mapping (part_type, folder_path) "
            "VALUES (?, ?)",
            ("Фильтр", "Расходники / Фильтры")
        )
        
    saved_count = 0
    models_recognized = 0
    total_errors = 0
    not_saved_count = 0
    
    with get_conn() as conn:
        cursor = conn.execute(
            "SELECT id, supplier_raw_name, article, external_code "
            "FROM products "
            "WHERE generation_status = 'error'"
        )
        rows = cursor.fetchall()
        total_errors = len(rows)
        
        for row in rows:
            prod_id, raw_name, current_article, barcode = row
            if not raw_name:
                continue
                
            parsed = parse_supplier_name(raw_name)
            
            part_type = parsed.get("part_type", "").strip()
            article = parsed.get("article", "").strip() or current_article.strip() or barcode.strip()
            
            if not article:
                conn.execute(
                    "UPDATE products SET error_message = ? WHERE id = ?",
                    ("Артикул не найден", prod_id)
                )
                not_saved_count += 1
                continue
                
            if part_type and article:
                brand = parsed.get("brand", "").strip()
                
                # Assuming model/make was extracted into applicability
                app = parsed.get("applicability", "").strip()
                make = ""
                model = ""
                if app:
                    parts = app.split(" ", 1)
                    make = parts[0]
                    if len(parts) > 1:
                        model = parts[1]
                        
                if make or model:
                    models_recognized += 1

                app_type = 'fitment' if make or model else 'universal'
                template_key = 'fitment_base' if app_type == 'fitment' else 'universal_base'

                conn.execute(
                    """
                    UPDATE products 
                    SET part_type = ?, 
                        article = ?, 
                        brand = ?,
                        primary_make = ?,
                        primary_model = ?,
                        applicability_type = ?,
                        template_key = ?,
                        generation_status = 'new', 
                        error_message = NULL
                    WHERE id = ?
                    """,
                    (part_type, article, brand, make, model, app_type, template_key, prod_id)
                )
                saved_count += 1
            else:
                not_saved_count += 1
                
    print(f"Total products in error status: {total_errors}")
    print(f"Products rescued (saved): {saved_count}")
    print(f"Models recognized: {models_recognized}")
    print(f"Products not rescued: {not_saved_count}")

if __name__ == "__main__":
    main()
