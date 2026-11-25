import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

数据目录 = Path(os.environ.get("数据目录", Path(__file__).resolve().parent.parent / "data"))
夹具目录 = Path(os.environ.get("夹具目录", Path(__file__).resolve().parent.parent.parent / "fixtures"))
库路径 = 数据目录 / "日镜账.db"


def 连接() -> sqlite3.Connection:
    数据目录.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(库路径, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    c.execute("PRAGMA busy_timeout = 10000")
    c.execute("PRAGMA journal_mode = WAL")
    return c


@contextmanager
def 写事务(conn: sqlite3.Connection):
    """以 BEGIN IMMEDIATE 取写锁，保证日历、抽取、断档扫描、回放互斥。

    日历变更与抽取交错时，后到者等待；若日历已改，快照触发器拒绝有效镜；
    若有效镜已落，日历触发器拒绝改为非营业日。两端都失败闭。
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
