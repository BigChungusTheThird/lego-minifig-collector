import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DC_CHECKLIST_HOME", tempfile.mkdtemp(prefix="dc-checklist-test-"))
