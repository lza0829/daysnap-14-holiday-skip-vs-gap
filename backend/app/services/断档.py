"""断档检出与过滤：假期永不出现在待补断档里。"""

from __future__ import annotations

from typing import Any

from app.services import 日历


def 列断档(conn, 限: int = 200) -> list[dict[str, Any]]:
    """返回断档记录，剔除「缺营业日」为非营业日的行。

    历史库可能残留假期行；此处按当前日历同源判定并标注 ``假期排除``，
    不作为待补断档展示。
    """
    out: list[dict[str, Any]] = []
    for r in conn.execute("SELECT * FROM 断档记录 ORDER BY 编号 DESC LIMIT ?", (限,)):
        d = dict(r)
        缺 = str(d.get("缺营业日") or "")
        if 缺 and not 日历.是否营业(conn, 缺):
            continue
        out.append(d)
    return out


def 待补断档数(conn) -> int:
    """按行计数，仅统计缺营业日仍为营业日的断档；假期行不计。"""
    n = 0
    for r in conn.execute("SELECT 缺营业日 FROM 断档记录"):
        缺 = str(r["缺营业日"] or "")
        if not 缺 or 日历.是否营业(conn, 缺):
            n += 1
    return n


def 清理假期断档(conn) -> int:
    """删除缺营业日属于非营业日的断档（用于收敛历史脏数据）。"""
    删 = 0
    for r in conn.execute("SELECT 编号, 缺营业日 FROM 断档记录").fetchall():
        缺 = str(r["缺营业日"] or "")
        if 缺 and not 日历.是否营业(conn, 缺):
            conn.execute("DELETE FROM 断档记录 WHERE 编号=?", (r["编号"],))
            删 += 1
    return 删
