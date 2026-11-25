"""日历跳日核证：是否营业 / 占位有无 / 开端来源日 / valid 逐项可区分。"""

from __future__ import annotations

from typing import Any

from app.services import 日历
from app.services.时间 import 标准化营业日

有效状态 = 日历.有效状态
占位状态 = 日历.占位状态


def 快照日态(conn, 营业日: str) -> dict[str, Any]:
    """按快照行判定某日的形态；假期无行、占位、有效三者分明。"""
    日 = 标准化营业日(营业日)
    rows = conn.execute(
        "SELECT 账户键, 余额, 状态, 来源 FROM 周期快照 WHERE 营业日=? ORDER BY 账户键",
        (日,),
    ).fetchall()
    有效行 = [r for r in rows if r["状态"] == 有效状态]
    占位行 = [r for r in rows if r["状态"] == 占位状态]
    return {
        "有行": len(rows) > 0,
        "行数": len(rows),
        "有效数": len(有效行),
        "占位有无": len(占位行) > 0,
        "占位数": len(占位行),
        "valid": len(有效行) > 0 and len(占位行) == 0,
    }


def 核证(conn, 账户键: str, 营业日: str) -> dict[str, Any]:
    """单个账户在某日的完整核证，供核证接口与测试断言使用。

    返回字段固定：是否营业 / 有行 / 占位有无 / valid / 开端来源日 / 来源。
    """
    日 = 标准化营业日(营业日)
    营业 = 日历.是否营业(conn, 日)
    row = conn.execute(
        "SELECT * FROM 周期快照 WHERE 账户键=? AND 营业日=?",
        (账户键, 日),
    ).fetchone()
    有行 = row is not None
    是否占位 = bool(row and row["状态"] == 占位状态)
    valid = bool(row and row["状态"] == 有效状态)
    # 占位行与有效镜都把「开端来源日」记在独立列；无行则为 None。
    来源日 = (row["开端来源日"] or None) if 有行 else None
    return {
        "账户键": 账户键,
        "营业日": 日,
        "是否营业": 营业,
        "有行": 有行,
        "占位有无": 是否占位,
        "valid": valid,
        "余额": None if (row is None or row["余额"] is None) else int(row["余额"]),
        "开端来源日": 来源日,
        "状态": (row["状态"] if 有行 else None),
        "来源": (row["来源"] if 有行 else None),
    }


def 日核证(conn, 营业日: str, 账户键: str = "") -> dict[str, Any]:
    """按日或按账户返回核证视图；不传账户键则汇总全日。"""
    日 = 标准化营业日(营业日)
    营业 = 日历.是否营业(conn, 日)
    形 = 快照日态(conn, 日)
    if 账户键:
        行 = 核证(conn, 账户键, 日)
    else:
        行 = None
    上 = 日历.上一营业日(conn, 日)
    下 = 日历.下一营业日(conn, 日)
    return {
        "营业日": 日,
        "是否营业": 营业,
        "形态": 形,
        "上一营业日": 上,
        "下一营业日": 下,
        "账户": 行,
    }


def 开端来源日(conn, 账户键: str, 营业日: str) -> str | None:
    """营业日有效镜的开端必须来自上一营业日的有效镜。

    返回实际提供开端的营业日；找不到或来源不再有效时返回 None。
    """
    日 = 标准化营业日(营业日)
    上 = 日历.上一营业日(conn, 日)
    if 上 is None:
        return None
    row = conn.execute(
        "SELECT 营业日 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态=?",
        (账户键, 上, 有效状态),
    ).fetchone()
    return 上 if row else None


def 归属窗口(conn, 营业日: str) -> tuple[str | None, str]:
    """营业日的流水归属窗口 ``(上一营业日, 营业日]``。

    非营业日本身不进入窗口终点，调用方应先经 :func:`解析归属日`。
    """
    日 = 标准化营业日(营业日)
    上 = 日历.上一营业日(conn, 日)
    return 上, 日


def 归属净额(conn, 账户键: str, 营业日: str) -> int:
    """营业日「应计」的流水净额：窗口 (上一营业日, 营业日] 内已入账流水之和。

    假期上的流水因此自然归到下一营业日；抽取与回放共用本函数。
    """
    日 = 标准化营业日(营业日)
    上 = 日历.上一营业日(conn, 日)
    if 上 is None:
        row = conn.execute(
            "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
            "WHERE 账户键=? AND 营业日<=? AND 命运='已入账'",
            (账户键, 日),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(SUM(变动额),0) AS s FROM 变动流水 "
            "WHERE 账户键=? AND 营业日>? AND 营业日<=? AND 命运='已入账'",
            (账户键, 上, 日),
        ).fetchone()
    return int(row["s"])


def 解析归属日(conn, 营业日: str) -> str | None:
    """把任意日期映射到承载流水/快照的营业日。

    营业日返回自身；假期返回其后最近营业日（含迟到装载归位）。
    """
    日 = 标准化营业日(营业日)
    if 日历.是否营业(conn, 日):
        return 日
    return 日历.下一营业日(conn, 日)
