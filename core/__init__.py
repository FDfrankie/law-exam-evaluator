"""
Core Engine Compatibility Forwarder
Allows `from core.module_name import ...` to transparently load modules located in the `code/` root directory.
"""
import sys
from pathlib import Path

_cur_dir = str(Path(__file__).resolve().parent)
_code_dir = str(Path(__file__).resolve().parent.parent)

if _code_dir not in sys.path:
    sys.path.insert(0, _code_dir)

# Extend package search path so Python automatically finds any module in code/
__path__ = [_cur_dir, _code_dir]
