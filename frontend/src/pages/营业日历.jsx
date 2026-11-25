import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const 日验证 = (文本) => /^\d{4}-\d{2}-\d{2}$/.test((文本 || "").trim());

export default function 营业日历() {
  const [数据, set数据] = useState({ 版本: 0, 条目: [] });
  const [改, set改] = useState([]);
  const [日, set日] = useState("2026-11-21");
  const [备注, set备注] = useState("");
  const [核日, set核日] = useState("2026-11-21");
  const [核户, set核户] = useState("");
  const [核, set核] = useState(null);
  const [讯, set讯] = useState("");
  const [错误, set错误] = useState("");

  const 刷新 = async () => {
    set数据(await api.日历());
    set改(await api.日历变更());
  };

  useEffect(() => {
    刷新().catch((e) => set讯(String(e.message || e)));
  }, []);

  const 执行改日 = async (是否营业) => {
    set错误("");
    set讯("");
    if (!日验证(日)) {
      set错误("日期须为 YYYY-MM-DD");
      return;
    }
    try {
      const r = await api.改日历日(日, 是否营业, 是否营业 ? "营业" : "假期", 备注);
      set讯(`${r.日期} → ${r.是否营业 ? "营业" : "假期"}（版本 ${r.版本}）`);
      await 刷新();
    } catch (e) {
      set错误(String(e.message || e));
    }
  };

  const 执行清占位 = async () => {
    set错误("");
    set讯("");
    if (!日验证(日)) {
      set错误("日期须为 YYYY-MM-DD");
      return;
    }
    try {
      const r = await api.清占位(日);
      set讯(`${r.日期} 清占位 ${r.删除占位} 行`);
      await 刷新();
    } catch (e) {
      set错误(String(e.message || e));
    }
  };

  const 执行核证 = async () => {
    set错误("");
    set核(null);
    if (!日验证(核日)) {
      set错误("核证营业日须为 YYYY-MM-DD");
      return;
    }
    try {
      set核(await api.核证(核日, 核户.trim()));
    } catch (e) {
      set错误(String(e.message || e));
    }
  };

  const 假日 = 数据.条目.filter((r) => !r.是否营业);

  return (
    <div>
      <h1 className="题">营业日历 · 假期跳日</h1>
      <p className="述">
        非营业日只落「假期占位」非有效镜（余额空、仅继承标记），下一营业日开端直接取上一营业日有效镜；
        抽取、断档、回放与台面共用此日历。
      </p>
      <div className="提示条">
        当前日历版本 <b>{数据.版本}</b> · 已登记假日 <b>{假日.length}</b> 天 · 缺省为营业日。
        改日与抽取交错时二者失败闭：既不能写出假期有效镜，也不能把已有有效镜的日子改成假期。
        若某假期仍有占位而需恢复营业，先「清理该日占位」再「恢复营业」。
      </div>

      <div className="段">
        <h2 className="段题">改日 / 恢复营业</h2>
        <div className="行">
          <input value={日} onChange={(e) => set日(e.target.value)} placeholder="YYYY-MM-DD" />
          <input value={备注} onChange={(e) => set备注(e.target.value)} placeholder="说明，可空" />
          <button onClick={() => 执行改日(false)}>登记为假期</button>
          <button className="水" onClick={() => 执行改日(true)}>恢复营业</button>
          <button className="次" onClick={执行清占位}>清理该日占位</button>
          <button className="次" onClick={() => 刷新().catch((e) => set讯(String(e.message || e)))}>刷新</button>
        </div>
        {讯 ? <p className="讯">{讯}</p> : null}
        {错误 ? <p className="讯" style={{ color: "var(--败)" }}>{错误}</p> : null}
      </div>

      <div className="段">
        <h2 className="段题">跳日核证</h2>
        <div className="行">
          <input value={核日} onChange={(e) => set核日(e.target.value)} placeholder="营业日 YYYY-MM-DD" />
          <input value={核户} onChange={(e) => set核户(e.target.value)} placeholder="账户键，可空" />
          <button className="水" onClick={执行核证}>核证</button>
        </div>
        {核 ? (
          <>
            <p className="讯">
              是否营业=<b>{核.是否营业 ? "是" : "否"}</b> · 有行=<b>{核.形态.有行 ? "有" : "无"}</b> ·
              占位有无=<b>{核.形态.占位有无 ? "有" : "无"}</b> · valid=
              <span className={`徽章 ${核.形态.valid ? "通" : "败"}`}>{核.形态.valid ? "有效" : "非有效"}</span>
              {" · "}上一营业日=<b>{核.上一营业日 || "—"}</b> · 下一营业日=<b>{核.下一营业日 || "—"}</b>
            </p>
            {核.账户 ? (
              <table>
                <thead>
                  <tr><th>账户键</th><th>营业日</th><th>有行</th><th>占位有无</th><th>valid</th><th>余额</th><th>开端来源日</th></tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{核.账户.账户键}</td>
                    <td>{核.账户.营业日}</td>
                    <td>{核.账户.有行 ? "有" : "无"}</td>
                    <td>{核.账户.占位有无 ? "有" : "无"}</td>
                    <td><span className={`徽章 ${核.账户.valid ? "通" : "败"}`}>{核.账户.valid ? "有效" : "非有效"}</span></td>
                    <td>{核.账户.余额 ?? "—"}</td>
                    <td>{核.账户.开端来源日 || "—"}</td>
                  </tr>
                </tbody>
              </table>
            ) : null}
          </>
        ) : (
          <div className="空态">填营业日（可加账户键）后点「核证」</div>
        )}
      </div>

      <div className="段">
        <h2 className="段题">已登记日历条目</h2>
        {!数据.条目.length ? (
          <div className="空态">尚未登记任何假日，全部日期按营业日处理</div>
        ) : (
          <table>
            <thead><tr><th>日期</th><th>是否营业</th><th>类型</th><th>说明</th><th>更新时刻</th></tr></thead>
            <tbody>
              {数据.条目.map((r) => (
                <tr key={r.日期}>
                  <td>{r.日期}</td>
                  <td><span className={`徽章 ${r.是否营业 ? "通" : "败"}`}>{r.是否营业 ? "营业" : "假期"}</span></td>
                  <td>{r.类型 || "—"}</td>
                  <td>{r.说明 || "—"}</td>
                  <td>{r.更新时刻}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="段">
        <h2 className="段题">日历变更记录</h2>
        {!改.length ? (
          <div className="空态">尚无变更</div>
        ) : (
          <table>
            <thead><tr><th>版本</th><th>动作</th><th>日期</th><th>是否营业</th><th>说明</th><th>时刻</th></tr></thead>
            <tbody>
              {改.map((r) => (
                <tr key={r.编号}>
                  <td>{r.版本}</td><td>{r.动作}</td><td>{r.日期}</td>
                  <td>{r.是否营业 ? "营业" : "假期"}</td><td>{r.说明 || "—"}</td><td>{r.时刻}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
