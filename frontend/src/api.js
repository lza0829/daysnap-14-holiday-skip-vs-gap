async function 请求(path, opts = {}) {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const text = await r.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!r.ok) {
    const msg = (data && data.detail) || text || r.statusText;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

export const api = {
  健康: () => 请求("/健康"),
  总览: () => 请求("/总览"),
  台参: () => 请求("/台参"),
  账户: () => 请求("/账户"),
  流水: (q = "") => 请求(`/流水${q}`),
  快照: (q = "") => 请求(`/快照${q}`),
  差额: (q = "") => 请求(`/差额${q}`),
  断档: () => 请求("/断档"),
  跳变: () => 请求("/跳变"),
  旁置: () => 请求("/旁置"),
  夹具: () => 请求("/夹具"),
  装载批次: () => 请求("/装载批次"),
  抽取批次: () => 请求("/抽取批次"),
  回放批次: () => 请求("/回放批次"),
  装载夹具: (名) => 请求("/装载夹具", { method: "POST", body: JSON.stringify({ 名 }) }),
  抽取: (营业日) => 请求("/抽取", { method: "POST", body: JSON.stringify({ 营业日 }) }),
  回放: (营业日) => 请求("/回放", { method: "POST", body: JSON.stringify({ 营业日 }) }),
  日历: (q = "") => 请求(`/日历${q}`),
  日历变更: () => 请求("/日历变更"),
  改日历日: (日期, 是否营业, 类型 = "", 说明 = "") =>
    请求("/日历/改日", { method: "POST", body: JSON.stringify({ 日期, 是否营业, 类型, 说明 }) }),
  清占位: (日期) => 请求("/日历/清占位", { method: "POST", body: JSON.stringify({ 日期 }) }),
  核证: (营业日, 账户键 = "") =>
    请求(`/核证?营业日=${encodeURIComponent(营业日)}${账户键 ? `&账户键=${encodeURIComponent(账户键)}` : ""}`),
  重置: (含日历 = false) => 请求(`/重置业务库?含日历=${含日历}`, { method: "POST", body: "{}" }),
};
