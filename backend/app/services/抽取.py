import json
import uuid
from typing import Any

from app.db import 连接, 写事务
from app.services import 日历, 日期核证
from app.services.时间 import 此刻, 标准化营业日


def _台参(conn) -> dict[str, str]:
    return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}


def 日终抽取(营业日: str, 批次编号: str = "") -> dict[str, Any]:
    """按营业日抽取周期快照。

    - 营业日：写有效镜，余额 = 上一营业日有效镜余额 + 窗口内流水净额。
    - 非营业日：**只**为当日/窗口内有流水的账户写 ``假期占位``（非有效、余额空），
      并记录「开端来源日 = 上一营业日」；绝不写有效镜、绝不记断档。
    """
    日 = 标准化营业日(营业日)
    批 = 批次编号.strip() or f"抽取-{日}-{uuid.uuid4().hex[:8]}"
    conn = 连接()
    try:
        with 写事务(conn):
            参 = _台参(conn)
            重复 = 参.get("重复抽取", "盖写同日快照")
            缺前日 = 参.get("缺前日策略", "以零为开端")
            营业 = 日历.是否营业(conn, 日)
            上营业 = 日历.上一营业日(conn, 日)
            账户们 = [
                dict(r)
                for r in conn.execute("SELECT * FROM 账户 WHERE 状态='正常' ORDER BY 账户键")
            ]
            报告 = {
                "营业日": 日,
                "是否营业": 营业,
                "上一营业日": 上营业,
                "写入": 0,
                "盖写": 0,
                "占位": 0,
                "占位盖写": 0,
                "旁置": 0,
                "断档": 0,
                "账户扫描": len(账户们),
            }
            for 户 in 账户们:
                账户键 = 户["账户键"]
                开户日 = 户["开户营业日"]
                if 日 < 开户日:
                    continue
                if 营业:
                    _抽营业日(conn, 户, 日, 上营业, 批, 重复, 缺前日, 报告)
                else:
                    _抽非营业日(conn, 户, 日, 上营业, 批, 报告)
            conn.execute(
                "INSERT INTO 抽取批次(编号, 营业日, 时刻, 报告) VALUES (?,?,?,?)",
                (批, 日, 此刻(), json.dumps(报告, ensure_ascii=False)),
            )
        return {"批次编号": 批, **报告}
    finally:
        conn.close()


def _现有行(conn, 账户键: str, 日: str):
    return conn.execute(
        "SELECT * FROM 周期快照 WHERE 账户键=? AND 营业日=?", (账户键, 日)
    ).fetchone()


def _抽营业日(conn, 户: dict, 日: str, 上营业: str | None, 批: str, 重复: str, 缺前日: str, 报告: dict) -> None:
    账户键 = 户["账户键"]
    开户日 = 户["开户营业日"]
    if 上营业 is None or 上营业 < 开户日:
        # 开户首日（或日历起点）没有前营业日，按零开端。
        开端 = 0
        来源日 = ""
        缺前日标记 = False
    else:
        前 = conn.execute(
            "SELECT 余额 FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态=?",
            (账户键, 上营业, 日历.有效状态),
        ).fetchone()
        if 前 is None:
            # 只有非「以零为开端」策略、且非开户首日时才记真断档；
            # 与主链原有语义一致，且上一营业日已按日历跳日求取。
            缺前日标记 = not (日 == 开户日 or 缺前日 == "以零为开端")
            开端 = 0
            来源日 = ""
        else:
            缺前日标记 = False
            开端 = int(前["余额"])
            来源日 = 上营业
    净额 = 日期核证.归属净额(conn, 账户键, 日)
    余额 = 开端 + 净额
    旧 = _现有行(conn, 账户键, 日)
    if 旧 is not None and 旧["状态"] == 日历.占位状态:
        # 日历改口后营业日仍有占位：属于失败闭缺陷，拒绝继续写有效镜。
        raise 日历.日历冲突(f"{账户键} {日} 存在假期占位，不得写有效镜")
    if 旧 is not None:
        if 重复 != "盖写同日快照":
            conn.execute(
                "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                ("同日已有快照", 账户键, 日, json.dumps({"余额": 余额}, ensure_ascii=False), 此刻()),
            )
            报告["旁置"] += 1
            return
        conn.execute(
            "UPDATE 周期快照 SET 余额=?, 抽取批次编号=?, 来源='日终抽取', 开端来源日=?, 状态=? "
            "WHERE 账户键=? AND 营业日=?",
            (余额, 批, 来源日, 日历.有效状态, 账户键, 日),
        )
        报告["盖写"] += 1
    else:
        conn.execute(
            "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 开端来源日, 状态) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (f"{账户键}|{日}", 账户键, 日, 余额, 批, "日终抽取", 来源日, 日历.有效状态),
        )
        报告["写入"] += 1
    if 缺前日标记:
        conn.execute(
            "INSERT INTO 断档记录(账户键, 缺营业日, 检出批次编号, 处置, 时刻) VALUES (?,?,?,?,?)",
            (账户键, 上营业, 批, "记断档并继续", 此刻()),
        )
        报告["断档"] += 1


def _抽非营业日(conn, 户: dict, 日: str, 上营业: str | None, 批: str, 报告: dict) -> None:
    """非营业日只落占位。

    占位 semantics：
    - 假期当日**本身**有流水 → 落占位（非有效、余额空、继承标记指向上一营业日）；
    - 假期当日无流水（即便窗口里更早的假期有流水）→ 假期无任何行。

    这样「假期日快照表是否有行」严格由当日流水决定，与「以假日占位非有效镜为准」
    的口径一致：无流的假日干净无行，有流的假日留可审计占位。
    """
    账户键 = 户["账户键"]
    当日流水 = conn.execute(
        "SELECT COUNT(*) AS c FROM 变动流水 WHERE 账户键=? AND 营业日=? AND 命运='已入账'",
        (账户键, 日),
    ).fetchone()
    有流水 = int(当日流水["c"]) > 0
    旧 = _现有行(conn, 账户键, 日)
    if 旧 is not None and 旧["状态"] == 日历.有效状态:
        raise 日历.日历冲突(f"{账户键} {日} 已是非营业日却存在有效镜")
    if not 有流水:
        # 无假期流水的账户：假期无任何行（可区分于占位）。
        if 旧 is not None and 旧["状态"] == 日历.占位状态:
            conn.execute(
                "DELETE FROM 周期快照 WHERE 账户键=? AND 营业日=? AND 状态=?",
                (账户键, 日, 日历.占位状态),
            )
            conn.execute(
                "INSERT INTO 旁置簿(原因, 账户键, 营业日, 载荷, 时刻) VALUES (?,?,?,?,?)",
                ("假期占位回收", 账户键, 日, "{}", 此刻()),
            )
            报告["旁置"] += 1
        return
    来源日 = 上营业 or ""
    # 开户日不晚于上一营业日时，「开端来源日」才有意义；否则（假期当日/之后开户）
    # 上一营业日的有效镜并不属于该户，不能标成继承来源。
    if 来源日 and 来源日 < 户["开户营业日"]:
        来源日 = ""
    if 旧 is not None:
        conn.execute(
            "UPDATE 周期快照 SET 余额=NULL, 抽取批次编号=?, 来源=?, 开端来源日=?, 状态=? "
            "WHERE 账户键=? AND 营业日=?",
            (批, "假期占位", 来源日, 日历.占位状态, 账户键, 日),
        )
        报告["占位盖写"] += 1
    else:
        conn.execute(
            "INSERT INTO 周期快照(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 开端来源日, 状态) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (f"{账户键}|{日}", 账户键, 日, None, 批, "假期占位", 来源日, 日历.占位状态),
        )
        报告["占位"] += 1
