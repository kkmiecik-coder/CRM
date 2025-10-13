# app/modules/users/decorators/__init__.py
"""
Dekoratory kontroli dostępu
"""

from .access_control import access_control
from .permission_required import require_module_access, require_any_module_access, require_all_modules_access

__all__ = [
    'access_control',
    'require_module_access',
    'require_any_module_access', 
    'require_all_modules_access'
]