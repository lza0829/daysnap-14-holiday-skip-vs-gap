"""营业日历变更：改日 / 恢复营业，带版本号与失败闭守卫。

与抽取、断档扫描、回放共用 ``BEGIN IMMEDIATE`` 写锁：
- 日历先改 → 抽取写有效镜被快照触发器拒绝；
- 抽取先落有效镜 → 改非营业日被日历触发器拒绝；
- 任一方向都不会写出「假期有效镜」。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from app.db import 连接, 写事务
from app.services import 日历
from app.services.时间 import 此刻, 标准化营业日


def _装状态(是否营业: bool, 类型: str, 说明: str) -> tuple[int, str, str]:
    return (1 if 是否营业 else 0, 类型 or ("营业" if 是否营业 else "假期"), 说明)


def 改日(日期: str, 是否营业: bool, 类型: str = "", 说明: str = "") -> dict[str, Any]:
    """登记/覆盖某日营业状态。若与已有有效镜或占位冲突，抛 :class:`日历冲突`。"""
    日 = 标准化营业日(日期)
    标 = 1 if 是否营业 else 0
    类 = 类型 or ("营业" if 是否营业 else "假期")
    conn = 连接()
    try:
        try:
            with 写事务(conn):
                版本 = 日历.取纪元(conn) + 1
                conn.execute(
                    "UPDATE 营业日历纪元 SET 版本=?, 更新时刻=? WHERE 键='日历'",
                    (版本, 此刻()),
                )
                conn.execute(
                    "INSERT INTO 营业日历(日期, 是否营业, 类型, 说明, 更新时刻) "
                    "VALUES (?,?,?,?,?) "
                    "ON CONFLICT(日期) DO UPDATE SET "
                    "是否营业=excluded.是否营业, 类型=excluded.类型, "
                    "说明=excluded.说明, 更新时刻=excluded.更新时刻",
                    (日, 标, 类, 说明, 此刻()),
                )
                conn.execute(
                    "INSERT INTO 日历变更记录(版本, 时刻, 动作, 日期, 是否营业, 说明) "
                    "VALUES (?,?,?,?,?,?)",
                    (版本, 此刻(), "改日", 日, 标, 说明),
                )
        except sqlite3.IntegrityError as e:
            raise 日历.日历冲突(str(e)) from e
        except sqlite3.OperationalError as e:
            if "非营业日" in str(e) or "有效镜" in str(e) or "占位" in str(e):
                raise 日历.日历冲突(str(e)) from e
            raise
        form = _摘要(conn, 日)
        return {"日期": 日, "版本": 版本, **form}
    finally:
        conn.close()


def _摘要(conn, 日: str) -> dict[str, Any]:
    from app.services import 日期核证

    return {
        "是否营业": 日历.是否营业(conn, 日),
        "形态": 日期核证.快照日态(conn, 日),
        "上一营业日": 日历.上一营业日(conn, 日),
        "下一营业日": 日历.下一营业日(conn, 日),
    }


def 批量改日(条目: list[dict[str, Any]]) -> dict[str, Any]:
    完成 = []
    for raw in 条目:
        完成.append(
            改日(
                str(raw.get("日期") or raw.get("营业日") or ""),
                bool(raw.get("是否营业", True)),
                str(raw.get("类型") or ""),
                str(raw.get("说明") or ""),
            )
        )
    return {"条目": 完成, "版本": 当前版本()}


def 当前版本() -> int:
    conn = 连接()
    try:
        return 日历.取纪元(conn)
    finally:
        conn.close()


def 清占位(日期: str) -> dict[str, Any]:
    """删除某日的假期占位行，供「改回营业」前置清理。

    只删 ``状态='假期占位'`` 的非有效行；有效镜绝不动，因而不会制造假期有效镜。
    """
    日 = 标准化营业日(日期)
    conn = 连接()
    try:
        with 写事务(conn):
            删 = conn.execute(
                "DELETE FROM 周期快照 WHERE 营业日=? AND 状态=?",
                (日, 日历.占位状态),
            ).rowcount
        return {"日期": 日, "删除占位": int(删 or 0), **_摘要(conn, 日)}
    finally:
        conn.close()


def 列日历(起: str = "", 止: str = "") -> list[dict[str, Any]]:
    conn = 连接()
    try:
        if 起 and 止:
            return 日历.日历区间(conn, 标准化营业日(起), 标准化营业日(止))
        return [
            dict(r)
            for r in conn.execute("SELECT * FROM 营业日历 ORDER BY 日期")
        ]
    finally:
        conn.close()


def 列变更(限: int = 100) -> list[dict[str, Any]]:
    conn = 连接()
    try:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM 日历变更记录 ORDER BY 编号 DESC LIMIT ?", (限,)
            )
        ]
    finally:
        conn.close()
