from datetime import datetime, timezone

from app.db import 连接
from app.services import 日历

建表 = """
CREATE TABLE IF NOT EXISTS 台参 (
  键 TEXT PRIMARY KEY,
  值 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 账户 (
  账户键 TEXT PRIMARY KEY,
  户名 TEXT NOT NULL,
  币种 TEXT NOT NULL DEFAULT 'CNY',
  开户营业日 TEXT NOT NULL,
  状态 TEXT NOT NULL DEFAULT '正常'
);
CREATE TABLE IF NOT EXISTS 变动流水 (
  流水号 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  发生时 TEXT NOT NULL,
  变动额 INTEGER NOT NULL,
  摘要 TEXT NOT NULL DEFAULT '',
  批次编号 TEXT NOT NULL DEFAULT '',
  命运 TEXT NOT NULL DEFAULT '已入账'
);
CREATE TABLE IF NOT EXISTS 抽取批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 周期快照 (
  快照键 TEXT PRIMARY KEY,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  余额 INTEGER,
  抽取批次编号 TEXT NOT NULL,
  来源 TEXT NOT NULL DEFAULT '日终抽取',
  开端来源日 TEXT NOT NULL DEFAULT '',
  状态 TEXT NOT NULL DEFAULT '有效',
  UNIQUE(账户键, 营业日)
);
CREATE TABLE IF NOT EXISTS 回放批次 (
  编号 TEXT PRIMARY KEY,
  营业日 TEXT NOT NULL,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS 差额行 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  回放批次编号 TEXT NOT NULL,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  快照余额 INTEGER,
  回放余额 INTEGER,
  差额 INTEGER NOT NULL,
  原因 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 断档记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  缺营业日 TEXT NOT NULL,
  检出批次编号 TEXT NOT NULL,
  处置 TEXT NOT NULL DEFAULT '待处理',
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 跳变记录 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  账户键 TEXT NOT NULL,
  营业日 TEXT NOT NULL,
  前日余额 INTEGER,
  当日余额 INTEGER,
  流水净额 INTEGER,
  偏离 INTEGER NOT NULL,
  检出批次编号 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 旁置簿 (
  编号 INTEGER PRIMARY KEY AUTOINCREMENT,
  原因 TEXT NOT NULL,
  账户键 TEXT NOT NULL DEFAULT '',
  营业日 TEXT NOT NULL DEFAULT '',
  载荷 TEXT NOT NULL,
  时刻 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS 装载批次 (
  编号 TEXT PRIMARY KEY,
  时刻 TEXT NOT NULL,
  报告 TEXT NOT NULL DEFAULT '{}'
);
"""

索引 = """
CREATE INDEX IF NOT EXISTS 快照_日态 ON 周期快照(营业日, 状态);
CREATE INDEX IF NOT EXISTS 快照_户日 ON 周期快照(账户键, 营业日);
CREATE INDEX IF NOT EXISTS 流水_户日 ON 变动流水(账户键, 营业日);
CREATE INDEX IF NOT EXISTS 断档_日 ON 断档记录(缺营业日);
"""

空桩模块 = [
    "开户首日无前日",
    "同日重复抽取幂等",
    "流水迟到补抽",
    "销户终镜",
    "负余额闸",
    "币种隔离",
    "半截抽取回滚",
    "快照封印写闸",
    "回放权威择定",
    "断档补齐",
    "断档旁置",
    "跳变阈值",
    "账户分片抽取",
    "抽取时钟漂移",
    "流水序缺口",
    "并户继承镜",
    "子户汇总镜",
    "日期间隙核证",
    "差额分桶",
    "三日连环守恒",
    "抽取重试预算",
    "跨日切点策略",
]


def 此刻() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _迁移快照(conn) -> None:
    """旧库余额列是 NOT NULL；占位行需要空余额，故一次性重建。

    重建须原子：``executescript`` 会先隐式提交并逐句自动提交，中途崩溃会留下
    原表已删、新表残留的坏库。这里用显式事务包裹，崩溃则整体回滚保持旧表。
    """
    cols = {r["name"]: r for r in conn.execute("PRAGMA table_info(周期快照)")}
    if not cols:
        return
    if int(cols["余额"]["notnull"]):
        conn.executescript(
            """
            DROP TRIGGER IF EXISTS 假期写闸_新增;
            DROP TRIGGER IF EXISTS 假期写闸_改写;
            DROP TRIGGER IF EXISTS 营业占位闸_新增;
            DROP TRIGGER IF EXISTS 营业占位闸_改写;
            DROP TRIGGER IF EXISTS 日历改闸_新增;
            DROP TRIGGER IF EXISTS 日历改闸_更新;
            DROP TRIGGER IF EXISTS 日历恢复闸_更新;
            """
        )
        conn.execute("BEGIN IMMEDIATE")
        try:
            cols新 = {r["name"] for r in conn.execute("PRAGMA table_info(周期快照_新)")}
            if not cols新:
                conn.execute(
                    """
                    CREATE TABLE 周期快照_新 (
                      快照键 TEXT PRIMARY KEY,
                      账户键 TEXT NOT NULL,
                      营业日 TEXT NOT NULL,
                      余额 INTEGER,
                      抽取批次编号 TEXT NOT NULL,
                      来源 TEXT NOT NULL DEFAULT '日终抽取',
                      开端来源日 TEXT NOT NULL DEFAULT '',
                      状态 TEXT NOT NULL DEFAULT '有效',
                      UNIQUE(账户键, 营业日)
                    )
                    """
                )
            conn.execute(
                "INSERT INTO 周期快照_新(快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, 开端来源日, 状态) "
                "SELECT 快照键, 账户键, 营业日, 余额, 抽取批次编号, 来源, '', 状态 FROM 周期快照"
            )
            conn.execute("DROP TABLE 周期快照")
            conn.execute("ALTER TABLE 周期快照_新 RENAME TO 周期快照")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(周期快照)")}
    if "开端来源日" not in cols:
        conn.execute("ALTER TABLE 周期快照 ADD COLUMN 开端来源日 TEXT NOT NULL DEFAULT ''")


def 初始化库() -> None:
    conn = 连接()
    try:
        conn.executescript(建表)
        _迁移快照(conn)
        conn.executescript(索引)
        conn.executescript(日历.建表)
        conn.executescript(日历.触发器)
        conn.execute(
            "INSERT OR IGNORE INTO 营业日历纪元(键, 版本, 更新时刻) VALUES ('日历', 0, ?)",
            (此刻(),),
        )
        if conn.execute("SELECT COUNT(*) AS c FROM 台参").fetchone()["c"] == 0:
            for k, v in {
                "站名": "日镜账",
                "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
                "跳变阈值分": "0",
                "断档处置": "记断档并继续",
                "缺前日策略": "以零为开端",
                "重复抽取": "盖写同日快照",
                "假期行形态": "有假期流水才落占位",
            }.items():
                conn.execute("INSERT INTO 台参(键, 值) VALUES (?, ?)", (k, v))
        if conn.execute("SELECT COUNT(*) AS c FROM 账户").fetchone()["c"] == 0:
            for 键, 名, 日 in [
                ("户甲", "甲收单户", "2026-11-01"),
                ("户乙", "乙结算户", "2026-11-01"),
                ("户丙", "丙备用户", "2026-11-05"),
            ]:
                conn.execute(
                    "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态) VALUES (?,?,?,?,?)",
                    (键, 名, "CNY", 日, "正常"),
                )
        conn.commit()
    finally:
        conn.close()
