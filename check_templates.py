import sqlite3

def check_templates():
    conn = sqlite3.connect('data/autoname.db')
    cursor = conn.cursor()
    cursor.execute("SELECT template_key, applicability_type, is_active FROM templates")
    print("Available templates:")
    for row in cursor.fetchall():
        print(row)

if __name__ == "__main__":
    check_templates()
