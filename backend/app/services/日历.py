"""营业日历与假期跳日核心。

全局只贯彻一种口径：**假日占位非有效镜**。

- 非营业日抽取只写 ``状态='假期占位'`` 的快照行，余额为空（NULL），
  只保留「开端来源日 = 上一营业日」的继承标记，绝不写有效镜。
- 营业日有效镜的开端一律取「上一营业日*有效*镜」，不取日历前一日。
- 流动水的归属窗口为 ``(上一营业日, 营业日]``，抽取与回放共用同一函数，
  因此落在假期上的流水会归到下一营业日。
- 断档只针对营业日；非营业日即使无快照也不得记录待补断档。
- 日历、抽取、回放、断档扫描、快照读模型全部经本模块取数。

快照表上的可区分性（核证接口逐项返回）：

- 假期无任何行：``有行=False / 占位有无=False / valid=False``
- 假期占位行：``有行=True / 占位有无=True / valid=False``
- 营业有效镜：``有行=True / 占位有无=False / valid=True``
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.services.时间 import 标准化营业日

启用 = True

有效状态 = "有效"
占位状态 = "假期占位"

# 日历缺省为营业日；只有显式登记为假的条目才是假期。
缺省营业 = True
步进上限 = 3660


class 日历冲突(Exception):
    """日历与抽取/断档扫描/快照交错时的失败闭拒绝，路由层映射为 409。"""


建表 = """
CREATE TABLE IF NOT EXISTS 营业日历 (
  日期 TEXT PRIMARY KEY,
  是否营业 INTEGER NOT NULL,
  类型 TEXT NOT NULL DEFAULT '',
  说明 TEXT NOT NULL DEFAULT '',
  更新时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 日历变更记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  版本 INTEGER NOT NULL,
  时刻 TEXT NOT NULL,
  动作 TEXT NOT NULL,
  日期 TEXT NOT NULL,
  是否营业 INTEGER NOT NULL,
  说明 TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS 营业日历纪元 (
  键 TEXT PRIMARY KEY,
  版本 INTEGER NOT NULL DEFAULT 0,
  更新时刻 TEXT NOT NULL
);
"""

# 触发器是最后一道失败闭：即便绕过服务层，也不能在非营业日写出有效镜，
# 也不能把已有有效镜的营业日事后改成假期。
触发器 = """
DROP TRIGGER IF EXISTS 假期写闸_新增;
DROP TRIGGER IF EXISTS 假期写闸_改写;
DROP TRIGGER IF EXISTS 日历改闸_新增;
DROP TRIGGER IF EXISTS 日历改闸_更新;
DROP TRIGGER IF EXISTS 日历恢复闸_新增;
DROP TRIGGER IF EXISTS 日历恢复闸_更新;

CREATE TRIGGER 假期写闸_新增
BEFORE INSERT ON 周期快照
WHEN NEW.状态 = '有效'
 AND EXISTS (SELECT 1 FROM 营业日历 WHERE 日期 = NEW.营业日 AND 是否营业 = 0)
BEGIN
  SELECT RAISE(ABORT, '非营业日不得写有效镜');
END;

CREATE TRIGGER 假期写闸_改写
BEFORE UPDATE OF 营业日, 状态 ON 周期快照
WHEN NEW.状态 = '有效'
 AND EXISTS (SELECT 1 FROM 营业日历 WHERE 日期 = NEW.营业日 AND 是否营业 = 0)
BEGIN
  SELECT RAISE(ABORT, '非营业日不得写有效镜');
END;

CREATE TRIGGER 日历改闸_新增
BEFORE INSERT ON 营业日历
WHEN NEW.是否营业 = 0
 AND EXISTS (SELECT 1 FROM 周期快照 WHERE 营业日 = NEW.日期 AND 状态 = '有效')
BEGIN
  SELECT RAISE(ABORT, '该日已有有效镜，不得改为非营业日');
END;

CREATE TRIGGER 日历改闸_更新
BEFORE UPDATE OF 是否营业 ON 营业日历
WHEN NEW.是否营业 = 0
 AND EXISTS (SELECT 1 FROM 周期快照 WHERE 营业日 = NEW.日期 AND 状态 = '有效')
BEGIN
  SELECT RAISE(ABORT, '该日已有有效镜，不得改为非营业日');
END;

CREATE TRIGGER 日历恢复闸_更新
BEFORE UPDATE OF 是否营业 ON 营业日历
WHEN NEW.是否营业 = 1
 AND EXISTS (SELECT 1 FROM 周期快照 WHERE 营业日 = NEW.日期 AND 状态 = '假期占位')
BEGIN
  SELECT RAISE(ABORT, '该日仍有假期占位，须先清理占位再恢复营业');
END;

CREATE TRIGGER 日历恢复闸_新增
BEFORE INSERT ON 营业日历
WHEN NEW.是否营业 = 1
 AND EXISTS (SELECT 1 FROM 周期快照 WHERE 营业日 = NEW.日期 AND 状态 = '假期占位')
BEGIN
  SELECT RAISE(ABORT, '该日仍有假期占位，须先清理占位再恢复营业');
END;
"""


def 取纪元(conn) -> int:
    """返回日历版本号；行缺失时补 0。"""
    row = conn.execute("SELECT 版本 FROM 营业日历纪元 WHERE 键='日历'").fetchone()
    if row is None:
        conn.execute(
            "INSERT OR IGNORE INTO 营业日历纪元(键, 版本, 更新时刻) VALUES ('日历', 0, '')"
        )
        return 0
    return int(row["版本"])


def _减日(日: str) -> str:
    y, m, d = map(int, 日.split("-"))
    return (date(y, m, d) - timedelta(days=1)).isoformat()


def _加日(日: str) -> str:
    y, m, d = map(int, 日.split("-"))
    return (date(y, m, d) + timedelta(days=1)).isoformat()


def 是否营业(conn, 营业日: str) -> bool:
    """日历为空视为营业日；显式登记为 0 才是假期。"""
    日 = 标准化营业日(营业日)
    row = conn.execute("SELECT 是否营业 FROM 营业日历 WHERE 日期=?", (日,)).fetchone()
    if row is None:
        return 缺省营业
    return bool(int(row["是否营业"]))


def 上一营业日(conn, 营业日: str, 含当日: bool = False) -> str | None:
    """从 营业日 往前找最近一个营业日；``含当日=True`` 时从当日开始算。

    若在步进上限内找不到，返回 None（调用方据此按开户/缺前日策略处理）。
    """
    日 = 标准化营业日(营业日)
    if not 含当日:
        日 = _减日(日)
    for _ in range(步进上限):
        if 是否营业(conn, 日):
            return 日
        日 = _减日(日)
    return None


def 下一营业日(conn, 营业日: str, 含当日: bool = False) -> str | None:
    日 = 标准化营业日(营业日)
    if not 含当日:
        日 = _加日(日)
    for _ in range(步进上限):
        if 是否营业(conn, 日):
            return 日
        日 = _加日(日)
    return None


def 日历区间(conn, 起: str, 止: str) -> list[dict[str, Any]]:
    """返回 [起, 止] 内显式登记的日历条目。"""
    rows = conn.execute(
        "SELECT * FROM 营业日历 WHERE 日期 >= ? AND 日期 <= ? ORDER BY 日期",
        (起, 止),
    )
    return [dict(r) for r in rows]
