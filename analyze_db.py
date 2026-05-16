import sqlite3
import json

def check_db():
    conn = sqlite3.connect('data/autoname.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM products WHERE generation_status = 'review'")
    review_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT error_message, count(*) FROM products WHERE generation_status = 'error' GROUP BY error_message")
    errors = cursor.fetchall()
        
    cursor.execute("""
        SELECT part_type, count(*) as cnt 
        FROM products 
        WHERE part_type NOT IN (
            SELECT part_type FROM category_mapping WHERE folder_path != '!_НЕРАЗОБРАННОЕ'
        ) 
        GROUP BY part_type 
        ORDER BY cnt DESC 
        LIMIT 10
    """)
    top_missing = cursor.fetchall()

    with open('analysis_output.json', 'w', encoding='utf-8') as f:
        json.dump({
            "review_count": review_count,
            "errors": errors,
            "top_missing": top_missing
        }, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    check_db()
