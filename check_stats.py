import sqlite3
import sys

# Ensure stdout uses utf-8
sys.stdout.reconfigure(encoding='utf-8')

with sqlite3.connect('data/autoname.db') as conn:
    print('--- Status Counts ---')
    cur = conn.execute('SELECT generation_status, count(*) FROM products GROUP BY generation_status;')
    for r in cur.fetchall():
        print(f'{r[0]}: {r[1]}')
        
    print('\n--- Error Messages ---')
    cur = conn.execute('SELECT error_message, count(*) FROM products WHERE generation_status="error" GROUP BY error_message;')
    for r in cur.fetchall():
        msg = r[0][:100] + '...' if len(r[0]) > 100 else r[0]
        print(f'{msg}: {r[1]}')
        
    print('\n--- Error Part Types ---')
    cur = conn.execute('SELECT part_type, count(*) FROM products WHERE generation_status="error" GROUP BY part_type;')
    for r in cur.fetchall():
        print(f'{r[0]}: {r[1]}')
