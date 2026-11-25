import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.db import 夹具目录, 连接
from app.services import 回放, 抽取, 目录, 装载, 日历, 日历变更, 日期核证, 断档 as 断档服务

路由 = APIRouter(prefix="/api")


class 装载请求(BaseModel):
    批次编号: str = ""
    流水: list = Field(default_factory=list)


class 营业日请求(BaseModel):
    营业日: str
    批次编号: str = ""
    账户键: str = ""


class 日历日请求(BaseModel):
    日期: str = ""
    营业日: str = ""
    是否营业: bool = True
    类型: str = ""
    说明: str = ""


class 日历批量请求(BaseModel):
    条目: list = Field(default_factory=list)


@路由.get("/健康")
def 健康():
    return {
        "正常": True,
        "项目": "日镜账",
        "骨架": "日终余额抽取→周期快照落行→变动流水回放核对→断档跳变检出→快照与回放差额清单",
    }


@路由.get("/总览")
def 取总览():
    return 目录.总览()


@路由.get("/台参")
def 取台参():
    conn = 连接()
    try:
        return {r["键"]: r["值"] for r in conn.execute("SELECT 键, 值 FROM 台参")}
    finally:
        conn.close()


@路由.get("/账户")
def 列账户():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 账户 ORDER BY 账户键")]
    finally:
        conn.close()


@路由.get("/流水")
def 列流水(营业日: str = "", 账户键: str = ""):
    conn = 连接()
    try:
        sql = "SELECT * FROM 变动流水 WHERE 1=1"
        args: list = []
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        sql += " ORDER BY 营业日 DESC, 发生时 DESC LIMIT 300"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@路由.get("/快照")
def 列快照(营业日: str = "", 账户键: str = "", 含占位: bool = False, 状态: str = ""):
    conn = 连接()
    try:
        if 状态:
            sql = "SELECT * FROM 周期快照 WHERE 状态=?"
            args: list = [状态]
        elif 含占位:
            sql = "SELECT * FROM 周期快照 WHERE 状态 IN ('有效','假期占位')"
            args = []
        else:
            sql = "SELECT * FROM 周期快照 WHERE 状态='有效'"
            args = []
        if 营业日:
            sql += " AND 营业日=?"
            args.append(营业日)
        if 账户键:
            sql += " AND 账户键=?"
            args.append(账户键)
        sql += " ORDER BY 营业日 DESC, 账户键 LIMIT 300"
        return [dict(r) for r in conn.execute(sql, args)]
    finally:
        conn.close()


@路由.get("/差额")
def 列差额(回放批次编号: str = ""):
    conn = 连接()
    try:
        if 回放批次编号:
            rows = conn.execute(
                "SELECT * FROM 差额行 WHERE 回放批次编号=? ORDER BY 编号 DESC",
                (回放批次编号,),
            )
        else:
            rows = conn.execute("SELECT * FROM 差额行 ORDER BY 编号 DESC LIMIT 200")
        return [dict(r) for r in rows]
    finally:
        conn.close()


@路由.get("/断档")
def 列断档():
    conn = 连接()
    try:
        return 断档服务.列断档(conn, 200)
    finally:
        conn.close()


@路由.get("/跳变")
def 列跳变():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 跳变记录 ORDER BY 编号 DESC LIMIT 200")]
    finally:
        conn.close()


@路由.get("/旁置")
def 列旁置():
    conn = 连接()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM 旁置簿 ORDER BY 编号 DESC LIMIT 100")]
    finally:
        conn.close()


def _列批(表: str):
    conn = 连接()
    try:
        out = []
        for r in conn.execute(f"SELECT * FROM {表} ORDER BY 时刻 DESC LIMIT 40"):
            d = dict(r)
            try:
                d["报告"] = json.loads(d.get("报告") or "{}")
            except Exception:
                pass
            out.append(d)
        return out
    finally:
        conn.close()


@路由.get("/装载批次")
def 列装载批():
    return _列批("装载批次")


@路由.get("/抽取批次")
def 列抽取批():
    return _列批("抽取批次")


@路由.get("/回放批次")
def 列回放批():
    return _列批("回放批次")


@路由.get("/夹具")
def 列夹具():
    if not 夹具目录.exists():
        return []
    return sorted(p.name for p in 夹具目录.glob("*.json"))


@路由.post("/装载")
def 执行装载(体: 装载请求):
    try:
        return 装载.装载流水(体.流水, 体.批次编号)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


class 夹具请求(BaseModel):
    名: str


@路由.post("/装载夹具/{名}")
def 装载夹具路径(名: str):
    return _装载夹具文件(名)


@路由.post("/装载夹具")
def 装载夹具体(体: 夹具请求):
    return _装载夹具文件(体.名)


def _装载夹具文件(名: str):
    path = 夹具目录 / 名
    if not path.exists():
        raise HTTPException(404, f"夹具不存在: {名}")
    data = json.loads(path.read_text(encoding="utf-8"))
    摘要 = 应用夹具声明(data)
    流水 = data.get("流水") or data.get("事件") or []
    try:
        结果 = 装载.装载流水(流水, str(data.get("批次编号") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {**结果, "夹具声明": 摘要}


def 应用夹具声明(data: dict) -> dict:
    """夹具可声明营业日历与账户；幂等 upsert，便于假期夹具一键应用。"""
    摘要 = {"日历": 0, "账户": 0}
    for c in data.get("日历") or []:
        try:
            日历变更.改日(
                str(c.get("日期") or c.get("营业日") or ""),
                bool(c.get("是否营业", True)),
                str(c.get("类型") or ""),
                str(c.get("说明") or ""),
            )
            摘要["日历"] += 1
        except 日历.日历冲突:
            摘要["日历冲突"] = 摘要.get("日历冲突", 0) + 1
    for a in data.get("账户") or []:
        账户键 = str(a.get("账户键") or "").strip()
        if not 账户键:
            continue
        conn = 连接()
        try:
            conn.execute(
                "INSERT INTO 账户(账户键, 户名, 币种, 开户营业日, 状态) VALUES (?,?,?,?,?) "
                "ON CONFLICT(账户键) DO UPDATE SET 户名=excluded.户名, 币种=excluded.币种, "
                "开户营业日=excluded.开户营业日, 状态=excluded.状态",
                (
                    账户键,
                    str(a.get("户名") or 账户键),
                    str(a.get("币种") or "CNY"),
                    str(a.get("开户营业日") or "2026-11-01"),
                    str(a.get("状态") or "正常"),
                ),
            )
            conn.commit()
            摘要["账户"] += 1
        finally:
            conn.close()
    return 摘要


@路由.post("/抽取")
def 执行抽取(体: 营业日请求):
    try:
        return 抽取.日终抽取(体.营业日, 体.批次编号)
    except 日历.日历冲突 as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/回放")
def 执行回放(体: 营业日请求):
    try:
        return 回放.回放核对(体.营业日, 体.批次编号)
    except 日历.日历冲突 as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ---------- 营业日历 / 假期跳日 ----------

@路由.get("/日历")
def 取日历(起: str = "", 止: str = ""):
    try:
        return {
            "版本": 日历变更.当前版本(),
            "条目": 日历变更.列日历(起, 止),
        }
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/日历/清占位")
def 执行清占位(体: 日历日请求):
    日 = 体.日期 or 体.营业日
    try:
        return 日历变更.清占位(日)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.get("/日历变更")
def 取日历变更():
    return 日历变更.列变更(100)


@路由.post("/日历/改日")
def 执行改日(体: 日历日请求):
    日 = 体.日期 or 体.营业日
    try:
        return 日历变更.改日(日, 体.是否营业, 体.类型, 体.说明)
    except 日历.日历冲突 as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.post("/日历/批量")
def 执行批量改日(体: 日历批量请求):
    try:
        return 日历变更.批量改日(体.条目)
    except 日历.日历冲突 as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@路由.get("/核证")
def 取核证(营业日: str, 账户键: str = ""):
    conn = 连接()
    try:
        return 日期核证.日核证(conn, 营业日, 账户键)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    finally:
        conn.close()


@路由.post("/重置业务库")
def 重置(含日历: bool = False):
    """开发冒烟用：清业务表并保留账户与台参；含日历=True 时连营业日历一并清空。"""
    conn = 连接()
    try:
        for t in (
            "变动流水",
            "抽取批次",
            "周期快照",
            "回放批次",
            "差额行",
            "断档记录",
            "跳变记录",
            "旁置簿",
            "装载批次",
            "日历变更记录",
        ):
            conn.execute(f"DELETE FROM {t}")
        if 含日历:
            conn.execute("DELETE FROM 营业日历")
            conn.execute("UPDATE 营业日历纪元 SET 版本=0 WHERE 键='日历'")
        conn.commit()
        return {"完成": True, **目录.总览()}
    finally:
        conn.close()
