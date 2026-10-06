"""Fix Python path for tests."""
import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
root = Path(__file__).parent.parent.resolve()
if str(root) not in sys.path:
    sys.path.insert(0, str(root))
