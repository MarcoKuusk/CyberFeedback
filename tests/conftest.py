"""Test configuration: put src/ on the import path.

The app modules import each other as top-level names (e.g. `import campaign_store`,
`from main import ...`) and run with src/ as the root. Mirror that for tests.
"""

import os
import sys

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
