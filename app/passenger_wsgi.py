# passenger_wsgi.py
import sys
import os

# ⚠️ KRYTYCZNE - MUSI BYĆ PRZED import app!
# Fix OpenBLAS threading issues
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'

import importlib

# Aktywacja venv
activate_this = '/home/woodpower/virtualenv/domains/crm.woodpower.pl/public_html/3.9/bin/activate_this.py'
if os.path.exists(activate_this):
    print(">>> passenger_wsgi.py: found activate_this.py, activating venv")
    with open(activate_this) as f:
        exec(f.read(), {'__file__': activate_this})
    print(">>> passenger_wsgi.py: venv activated")
else:
    print(">>> passenger_wsgi.py: activate_this.py NOT FOUND")

print(">>> Loading app.py")
wsgi = importlib.import_module('app')
application = wsgi.app