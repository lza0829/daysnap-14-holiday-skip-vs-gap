import os
import tempfile

# 每个测试会话独立库，避免污染开发库。
os.environ.setdefault("数据目录", tempfile.mkdtemp(prefix="daysnap-test-"))
os.environ.setdefault("夹具目录", os.path.join(os.path.dirname(__file__), "..", "..", "fixtures"))

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app import seed


@pytest.fixture(scope="session", autouse=True)
def _库():
    seed.初始化库()
    yield


@pytest.fixture()
def 客户端():
    c = TestClient(app)
    c.post("/api/重置业务库", params={"含日历": True})
    conn = __import__("app.db", fromlist=["连接"]).连接()
    try:
        for 键 in ("户甲", "户乙", "户丙"):
            conn.execute(
                "UPDATE 账户 SET 开户营业日='2026-11-01', 状态='正常' WHERE 账户键=?", (键,)
            )
        conn.execute("UPDATE 台参 SET 值='以零为开端' WHERE 键='缺前日策略'")
        conn.commit()
    finally:
        conn.close()
    return c


def 日历(日):
    return {"日期": 日, "是否营业": False, "类型": "假期", "说明": "测试假期"}


def 抽(c, 日):
    r = c.post("/api/抽取", json={"营业日": 日})
    assert r.status_code == 200, r.text
    return r.json()


def 核(c, 日, 户=""):
    r = c.get("/api/核证", params={"营业日": 日, "账户键": 户})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- 假期中日

def test_假期中日抽假期形态(客户端):
    c = 客户端
    assert c.post("/api/日历/改日", json=日历("2026-11-21")).status_code == 200
    assert c.post("/api/装载夹具", json={"名": "假期中日夹具.json"}).status_code == 200
    抽(c, "2026-11-20")
    抽(c, "2026-11-21")
    甲 = 核(c, "2026-11-21", "户甲")["账户"]
    乙 = 核(c, "2026-11-21", "户乙")["账户"]
    # 甲无假期流水：假期无任何行。
    assert 甲["有行"] is False and 甲["占位有无"] is False and 甲["valid"] is False
    # 乙有假期流水：非有效占位，余额空，继承标记指向上一营业日。
    assert 乙["有行"] is True and 乙["占位有无"] is True and 乙["valid"] is False
    assert 乙["余额"] is None
    assert 乙["开端来源日"] == "2026-11-20"


def test_假期下一营业日开端连线并三日守恒(客户端):
    c = 客户端
    c.post("/api/日历/改日", json=日历("2026-11-21"))
    c.post("/api/装载夹具", json={"名": "假期中日夹具.json"})
    for 日 in ("2026-11-20", "2026-11-21", "2026-11-22"):
        抽(c, 日)
    甲 = 核(c, "2026-11-22", "户甲")["账户"]
    乙 = 核(c, "2026-11-22", "户乙")["账户"]
    assert 甲["valid"] is True and 乙["valid"] is True
    assert 甲["开端来源日"] == "2026-11-20"
    assert 乙["开端来源日"] == "2026-11-20"
    # 乙在 11-20=5000，11-21 假期 -1000 归到 11-22，11-22 +2000 → 6000。
    assert 乙["余额"] == 6000
    # 甲 11-20=7500，11-22 -1500 → 6000。
    assert 甲["余额"] == 6000
    # 三日回放守恒：对下一营业日回放通过，且 11-21 回放被跳过不判通过。
    r = c.post("/api/回放", json={"营业日": "2026-11-22"}).json()
    assert r["通过"] is True and r["差额"] == 0 and r["无快照"] == 0
    j = c.post("/api/回放", json={"营业日": "2026-11-21"}).json()
    assert j["跳过"] is True and j["通过"] is False
    assert j["差额"] == 0


def test_断档页不得把假日列待补(客户端):
    c = 客户端
    c.post("/api/日历/改日", json=日历("2026-11-21"))
    c.post("/api/装载夹具", json={"名": "假期中日夹具.json"})
    抽(c, "2026-11-20")
    抽(c, "2026-11-21")
    断档 = c.get("/api/断档").json()
    assert all(r["缺营业日"] != "2026-11-21" for r in 断档)
    # 直接对假期触发回放也不得记断档。
    c.post("/api/回放", json={"营业日": "2026-11-21"})
    assert all(r["缺营业日"] != "2026-11-21" for r in c.get("/api/断档").json())


# ---------------------------------------------------------------- 迟到装载

def test_假期日迟到装载不得写有效镜(客户端):
    c = 客户端
    c.post("/api/日历/改日", json=日历("2026-11-21"))
    # 先按无假期流水抽 11-20、11-21（甲在 11-21 无流水则无行）。
    c.post("/api/装载", json={"流水": [
        {"流水号": "t-甲-20", "账户键": "户甲", "营业日": "2026-11-20", "变动额": 1000},
    ]})
    抽(c, "2026-11-20")
    抽(c, "2026-11-21")
    assert 核(c, "2026-11-21", "户甲")["账户"]["有行"] is False
    # 迟到装载：营业日落在假期 11-21。
    c.post("/api/装载", json={"流水": [
        {"流水号": "t-甲-迟到", "账户键": "户甲", "营业日": "2026-11-21", "变动额": -200},
    ]})
    r = 抽(c, "2026-11-21")
    assert r["是否营业"] is False
    甲 = 核(c, "2026-11-21", "户甲")["账户"]
    assert 甲["占位有无"] is True and 甲["valid"] is False
    # 迟到流水归到下一营业日 11-22：开端仍是 11-20 有效镜 1000，再 -200。
    抽(c, "2026-11-22")
    甲22 = 核(c, "2026-11-22", "户甲")["账户"]
    assert 甲22["valid"] is True and 甲22["开端来源日"] == "2026-11-20"
    assert 甲22["余额"] == 800
    r = c.post("/api/回放", json={"营业日": "2026-11-22"}).json()
    assert r["通过"] is True


def test_假期日迟到夹具(客户端):
    c = 客户端
    c.post("/api/装载夹具", json={"名": "假期中日夹具.json"})
    for 日 in ("2026-11-20", "2026-11-21", "2026-11-22"):
        抽(c, 日)
    c.post("/api/装载夹具", json={"名": "假期迟到夹具.json"})
    抽(c, "2026-11-21")
    甲 = 核(c, "2026-11-21", "户甲")["账户"]
    assert 甲["占位有无"] is True and 甲["valid"] is False
    assert 甲["余额"] is None


# ---------------------------------------------------------------- 改日历并发

def test_改日历与抽取并发不得写出假期有效镜(客户端):
    c = 客户端
    c.post("/api/装载夹具", json={"名": "改日历并发夹具.json"})
    # 构造并发：先改日历成功，再抽取必须落占位（不写有效镜）。
    assert c.post("/api/日历/改日", json=日历("2026-11-23")).status_code == 200
    r = 抽(c, "2026-11-23")
    assert r["是否营业"] is False
    快照 = c.get("/api/快照", params={"营业日": "2026-11-23", "含占位": True}).json()
    assert all(行["状态"] != "有效" for 行 in 快照)
    # 反向：已有有效镜的营业日不能被事后改为假期（409）。
    c.post("/api/重置业务库", params={"含日历": True})
    c.post("/api/装载", json={"流水": [
        {"流水号": "t-乙-23", "账户键": "户乙", "营业日": "2026-11-23", "变动额": 10},
    ]})
    抽(c, "2026-11-23")
    r = c.post("/api/日历/改日", json=日历("2026-11-23"))
    assert r.status_code == 409


def test_并发线程交替不产生假期有效镜(客户端):
    """真正双线程交错：无论谁先，终态都不得存在假期有效镜。"""
    import threading
    c = 客户端
    c.post("/api/装载", json={"流水": [
        {"流水号": "t-丙-24", "账户键": "户丙", "营业日": "2026-11-24", "变动额": 50},
    ]})
    错 = []

    def 改():
        try:
            r = c.post("/api/日历/改日", json=日历("2026-11-24"))
            if r.status_code not in (200, 409):
                错.append(("改", r.status_code, r.text))
        except Exception as e:  # noqa
            错.append(("改", repr(e)))

    def 抽日():
        try:
            r = c.post("/api/抽取", json={"营业日": "2026-11-24"})
            if r.status_code not in (200, 409):
                错.append(("抽", r.status_code, r.text))
        except Exception as e:  # noqa
            错.append(("抽", repr(e)))

    线程 = [threading.Thread(target=改), threading.Thread(target=抽日)]
    for t in 线程:
        t.start()
    for t in 线程:
        t.join()
    assert not 错, 错
    有效 = c.get("/api/快照", params={"营业日": "2026-11-24", "状态": "有效"}).json()
    # 若日历最终为假期，则不得有有效镜；若为营业则允许有效镜。
    核日 = 核(c, "2026-11-24")
    if not 核日["是否营业"]:
        assert 有效 == []


# ---------------------------------------------------------------- 数据库级失败闭

def test_数据库触发器拒绝假期有效镜(客户端):
    from app.db import 连接

    c = 客户端
    c.post("/api/日历/改日", json=日历("2026-12-05"))
    conn = 连接()
    try:
        with pytest.raises(Exception) as ei:
            conn.execute(
                "INSERT INTO 周期快照(快照键,账户键,营业日,余额,抽取批次编号,来源,开端来源日,状态) "
                "VALUES ('x','户甲','2026-12-05',1,'b','日终抽取','','有效')"
            )
        assert "非营业日" in str(ei.value)
        # 占位允许写入
        conn.execute(
            "INSERT INTO 周期快照(快照键,账户键,营业日,余额,抽取批次编号,来源,开端来源日,状态) "
            "VALUES ('p','户甲','2026-12-05',NULL,'b','假期占位','2026-12-04','假期占位')"
        )
        conn.commit()
        # 仍有占位时恢复营业被拒
        with pytest.raises(Exception) as ei2:
            conn.execute("UPDATE 营业日历 SET 是否营业=1 WHERE 日期='2026-12-05'")
        assert "占位" in str(ei2.value)
    finally:
        conn.rollback()
        conn.close()


def test_恢复营业须先清占位(客户端):
    c = 客户端
    c.post("/api/日历/改日", json=日历("2026-12-06"))
    c.post("/api/装载", json={"流水": [
        {"流水号": "t-甲-06", "账户键": "户甲", "营业日": "2026-12-06", "变动额": 33},
    ]})
    抽(c, "2026-12-06")
    assert 核(c, "2026-12-06", "户甲")["账户"]["占位有无"] is True
    # 服务层恢复营业：触发器拒绝 → 409
    r = c.post("/api/日历/改日", json={"日期": "2026-12-06", "是否营业": True, "类型": "营业"})
    assert r.status_code == 409


def test_清占位后恢复营业(客户端):
    c = 客户端
    c.post("/api/日历/改日", json=日历("2026-12-07"))
    c.post("/api/装载", json={"流水": [
        {"流水号": "t-甲-07", "账户键": "户甲", "营业日": "2026-12-07", "变动额": 12},
    ]})
    抽(c, "2026-12-07")
    assert 核(c, "2026-12-07", "户甲")["账户"]["占位有无"] is True
    # 先清占位，再恢复营业应成功。
    r = c.post("/api/日历/清占位", json={"日期": "2026-12-07"})
    assert r.status_code == 200 and r.json()["删除占位"] >= 1
    r = c.post("/api/日历/改日", json={"日期": "2026-12-07", "是否营业": True, "类型": "营业"})
    assert r.status_code == 200
    assert 核(c, "2026-12-07")["是否营业"] is True


# ---------------------------------------------------------------- 性质守恒

def test_混合日历逐日抽取回放守恒(客户端):
    """随机混合日历：每个营业日快照=上一营业日有效镜+窗口净额；假期永无有效镜。"""
    import random
    c = 客户端
    random.seed(20261125)
    起, 天数 = "2026-10-01", 30
    from datetime import date, timedelta
    基 = date.fromisoformat(起)
    日们 = [(基 + timedelta(days=i)).isoformat() for i in range(天数)]
    假日 = set(d for d in 日们 if random.random() < 0.3)
    for d in 假日:
        assert c.post("/api/日历/改日", json=日历(d)).status_code == 200
    # 每个账户每日随机流水（含假期）
    流水 = []
    n = 0
    for i, d in enumerate(日们):
        for 户 in ("户甲", "户乙"):
            if random.random() < 0.6:
                n += 1
                流水.append({
                    "流水号": f"p-{n}", "账户键": 户, "营业日": d,
                    "变动额": random.randint(-500, 800),
                })
    assert c.post("/api/装载", json={"流水": 流水}).status_code == 200
    for d in 日们:
        c.post("/api/抽取", json={"营业日": d})
    # 逐营业日回放必须全通过（守恒）。
    for d in 日们:
        if d in 假日:
            r = c.post("/api/回放", json={"营业日": d}).json()
            assert r["跳过"] is True and r["差额"] == 0
        else:
            r = c.post("/api/回放", json={"营业日": d}).json()
            assert r["通过"] is True, (d, r)
    # 假期永无有效镜。
    for d in 假日:
        形 = 核(c, d)["形态"]
        assert 形["有效数"] == 0
    # 断档里没有假期。
    for r in c.get("/api/断档").json():
        assert r["缺营业日"] not in 假日


# ---------------------------------------------------------------- 尾部假期

def test_尾部假期流水在下一营业日才归属(客户端):
    """最后一个营业日之后的假期流水，不得提前被上一营业日吸走，须等下一营业日归属。"""
    c = 客户端
    for d in ("2026-11-21", "2026-11-22"):
        c.post("/api/日历/改日", json=日历(d))
    c.post("/api/装载", json={"流水": [
        {"流水号": "t-20", "账户键": "户甲", "营业日": "2026-11-20", "变动额": 1000},
        {"流水号": "t-21", "账户键": "户甲", "营业日": "2026-11-21", "变动额": -100},
        {"流水号": "t-22", "账户键": "户甲", "营业日": "2026-11-22", "变动额": 200},
    ]})
    抽(c, "2026-11-20")
    r = c.post("/api/回放", json={"营业日": "2026-11-20"}).json()
    assert r["通过"] is True and r["差额"] == 0
    for d in ("2026-11-21", "2026-11-22"):
        assert 抽(c, d)["占位"] == 1
        assert 核(c, d, "户甲")["账户"]["valid"] is False
    抽(c, "2026-11-23")
    a = 核(c, "2026-11-23", "户甲")["账户"]
    assert a["余额"] == 1100 and a["开端来源日"] == "2026-11-20"
    assert c.post("/api/回放", json={"营业日": "2026-11-23"}).json()["通过"] is True
