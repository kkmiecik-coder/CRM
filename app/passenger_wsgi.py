import importlib
import os
import sys

# Aktywacja virtualenv
activate_this = '/home/woodpower/virtualenv/domains/crm.woodpower.pl/public_html/3.9/bin/activate_this.py'
if os.path.exists(activate_this):
    print(">>> passenger_wsgi.py: found activate_this.py, activating venv")
    exec(open(activate_this).read(), {'__file__': activate_this})
    print(">>> passenger_wsgi.py: venv activated")
else:
    print(f">>> passenger_wsgi.py: activate_this.py not found at {activate_this}")

# Dodaj katalog app do sys.path
app_dir = os.path.dirname(__file__)
if app_dir not in sys.path:
    sys.path.insert(0, app_dir)
print(">>> Loading app.py")
wsgi = importlib.import_module('app')
application = wsgi.app