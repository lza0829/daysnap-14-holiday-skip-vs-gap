import json
import uuid
from typing import Any

from app.db import 连接, 写事务
from app.services import 日历, 日期核证
from app.services.时间 import 此刻, 标准化营业日


def 回放核对(营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """用「上一营业日有效镜 + 归属窗口流水净额」重算，对照当日有效镜。

    - 非营业日：不重算、不写差额；报告 ``跳过=True``，占位行绝不作为有效镜通过。
    - 营业日：开端只取上一营业日*有效*镜；占位行不被读取为开端。
    """
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"回放-{日}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        with 写事务(conn):
            参 = {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
            try:
                阈值 = int(参.get("跳变阈值分", "0") or "0")
            except ValueError:
                阈值 = 0
            营业 = 日历.是否营业(conn, 日)
            上营业 = 日历.上一营业日(conn, 日)
            报告 = {
                "营业日": 日,
                "是否营业": 营业,
                "上一营业日": 上营业,
                "跳过": not 营业,
                "相符": 0,
                "差额": 0,
                "跳变": 0,
                "无快照": 0,
                "占位忽略": 0,
                "通过": False,
            }
            if not 营业:
                # 假期：只统计忽略的占位行，不写差额/跳变，也不判通过。
                报告["占位忽略"] = int(
                    conn.execute(
                        "SELECT COUNT(*) AS c FROM 周期快照 WHERE 营业日=? AND 状态=?",
                        (日, 日历.占位状态),
                    ).fetchone()["c"]
                )
                conn.execute(
                    "INSERT INTO 回放批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
                    (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
                )
                return {"批次编号": 批, **报告}
            账户们 = [
                dict(r)
                for r in conn.execute("SELECT * FROM 账户 WHERE 状态='正常' ORDER BY 账户键")
            ]
            for 户 in 账户们:
                账户键 = 户["账户键"]
                if 日 < 户["开户营业日"]:
                    continue
                快照 = conn.execute(
                    "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态=?",
                    (账户键, 日, 日历.有效状态),
                ).fetchone()
                if not 快照:
                    报告["无快照"] += 1
                    原因 = "缺当日有效镜"
                    conn.execute(
                        "INSERT INTO 差额行(回放批次编号, 账户键, 营业日, 快照余额, 回放余额, 差额, 原因, 时刻) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (批, 账户键, 日, None, None, 0, 原因, 此刻()),
                    )
                    报告["差额"] += 1
                    continue
                开端 = 0
                if 上营业 is not None and 上营业 >= 户["开户营业日"]:
                    前日快照 = conn.execute(
                        "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态=?",
                        (账户键, 上营业, 日历.有效状态),
                    ).fetchone()
                    开端 = 0 if 前日快照 is None else int(前日快照["余额"])
                净额 = 日期核证.归属净额(conn, 账户键, 日)
                回放余额 = 开端 + 净额
                快照余额 = int(快照["余额"])
                差额 = 快照余额 - 回放余额
                if 差额 == 0:
                    报告["相符"] += 1
                else:
                    conn.execute(
                        "INSERT INTO 差额行(回放批次编号, 账户键, 营业日, 快照余额, 回放余额, 差额, 原因, 时刻) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (批, 账户键, 日, 快照余额, 回放余额, 差额, "快照与回放不一致", 此刻()),
                    )
                    报告["差额"] += 1
                偏离 = abs(差额)
                if 阈值 > 0 and 偏离 >= 阈值:
                    conn.execute(
                        "INSERT INTO 跳变记录(账户键, 营业日, 前日余额, 当日余额, 流水净额, 偏离, 检出批次编号, 时刻) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (账户键, 日, 开端, 快照余额, 净额, 偏离, 批, 此刻()),
                    )
                    报告["跳变"] += 1
            报告["通过"] = 报告["差额"] == 0 and 报告["无快照"] == 0
            conn.execute(
                "INSERT INTO 回放批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
                (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
            )
        return {"批次编号": 批, **报告}
    finally:
        conn.close()
