import sqlite3
from pathlib import Path

c = sqlite3.connect(Path(__file__).resolve().parent.parent / "data" / "autoname.db")
c.execute(
    "UPDATE products SET brand='FLAMINGO', applicability_type='fitment', "
    "template_key='fitment_base', generation_status='new', error_message=NULL WHERE id=10"
)
c.execute(
    "UPDATE products SET generation_status='new' WHERE id=5"
)
c.execute(
    "UPDATE products SET generation_status='review', error_message=NULL WHERE id=1"
)
c.commit()
c.close()
print("restored rows 1,5,10 baseline")
