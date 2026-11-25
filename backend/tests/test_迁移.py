"""迁移回归：旧库（余额 NOT NULL、无营业日历、无开端来源日）须原子升级且不丢数据。"""

import os
import sqlite3
import tempfile

import pytest

from app import seed
from app.db import 库路径


def _造旧库(路径):
    c = sqlite3.connect(路径)
    c.executescript(
        """
        CREATE TABLE 台参(键 TEXT PRIMARY KEY, 值 TEXT NOT NULL);
        CREATE TABLE 账户(账户键 TEXT PRIMARY KEY, 户名 TEXT NOT NULL,
          币种 TEXT NOT NULL DEFAULT 'CNY', 开户营业日 TEXT NOT NULL, 状态 TEXT NOT NULL DEFAULT '正常');
        CREATE TABLE 周期快照(快照键 TEXT PRIMARY KEY, 账户键 TEXT NOT NULL, 营业日 TEXT NOT NULL,
          余额 INTEGER NOT NULL, 抽取批次编号 TEXT NOT NULL,
          来源 TEXT NOT NULL DEFAULT '日终抽取', 状态 TEXT NOT NULL DEFAULT '有效',
          UNIQUE(账户键, 营业日));
        INSERT INTO 账户 VALUES('户甲','甲','CNY','2026-11-01','正常');
        INSERT INTO 周期快照 VALUES('户甲|2026-11-20','户甲','2026-11-20',7500,'旧批','日终抽取','有效');
        INSERT INTO 周期快照 VALUES('户甲|2026-11-21','户甲','2026-11-21',7800,'旧批','日终抽取','有效');
        """
    )
    c.commit()
    c.close()


def test_旧库迁移保留数据并升级模式(tmp_path, monkeypatch):
    # 指向独立库文件。
    老路径 = tmp_path / "旧.db"
    _造旧库(老路径)
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "库路径", 老路径)
    monkeypatch.setattr(dbmod, "数据目录", tmp_path)
    seed.初始化库()
    c = sqlite3.connect(老路径)
    c.row_factory = sqlite3.Row
    cols = {r["name"]: r for r in c.execute("PRAGMA table_info(周期快照)")}
    assert int(cols["余额"]["notnull"]) == 0
    assert "开端来源日" in cols
    assert c.execute("SELECT COUNT(*) FROM 周期快照").fetchone()[0] == 2
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='周期快照_新'").fetchone()[0] == 0
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger'").fetchone()[0] >= 6
    c.close()
