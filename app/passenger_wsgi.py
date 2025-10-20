# passenger_wsgi.py - Fixed for Passenger
import sys
import os

# Environment setup
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['PYTHONIOENCODING'] = 'utf-8:replace'
os.environ['FLASK_ENV'] = 'production'
os.environ['FLASK_DEBUG'] = '0'

# Virtual environment activation
activate_this = '/home/woodpower/virtualenv/domains/crm.woodpower.pl/public_html/3.9/bin/activate_this.py'

if os.path.exists(activate_this):
    print(">>> [Passenger] Activating virtualenv", file=sys.stderr)
    with open(activate_this) as f:
        exec(f.read(), {'__file__': activate_this})
    print(">>> [Passenger] Virtualenv activated", file=sys.stderr)
else:
    print(">>> [Passenger] WARNING: virtualenv activation file not found!", file=sys.stderr)

# Import and create application IMMEDIATELY (not in function)
print(">>> [Passenger] Loading Flask application...", file=sys.stderr)

try:
    from app import app as application
    
    if application is None:
        raise RuntimeError("Flask app is None!")
    
    print(">>> [Passenger] Flask application loaded successfully", file=sys.stderr)
    print(f">>> [Passenger] Debug mode: {application.debug}", file=sys.stderr)
    print(f">>> [Passenger] Environment: {application.config.get('ENV', 'unknown')}", file=sys.stderr)
    
except Exception as e:
    print(f">>> [Passenger] CRITICAL ERROR loading application: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    raise

print(">>> [Passenger] passenger_wsgi.py loaded", file=sys.stderr)
print(f">>> [Passenger] Python version: {sys.version}", file=sys.stderr)
print(f">>> [Passenger] Working directory: {os.getcwd()}", file=sys.stderr)