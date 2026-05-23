import sys
import os
import unittest.mock as mock

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Mock heavy dependencies before any test file imports botpage
for _mod in [
    "streamlit",
    "openai",
    "bs4",
    "requests",
    "markdownify",
    "st_copy_to_clipboard",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = mock.MagicMock()
