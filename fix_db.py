import sqlite3
import os

db_path = os.path.join("data", "autoname.db")
with sqlite3.connect(db_path) as conn:
    conn.execute("UPDATE products SET generation_status = 'review', error_message = NULL WHERE generation_status = 'error' AND error_message LIKE '%productFolder%';")
    conn.commit()

    cur = conn.cursor()
    cur.execute("SELECT DISTINCT product_folder FROM products WHERE product_folder IS NOT NULL LIMIT 10")
    print("Folders:")
    for row in cur.fetchall():
        print(row)
