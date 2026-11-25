import os
import sys
from pathlib import Path

# 让 `pytest` 在 backend/ 或仓库根目录运行都能 import app.*
后端 = Path(__file__).resolve().parent.parent
if str(后端) not in sys.path:
    sys.path.insert(0, str(后端))

os.environ.setdefault("夹具目录", str(后端.parent / "fixtures"))
