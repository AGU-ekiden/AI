"use strict";
// 特徴量ラボ UI。データは textContent でのみ描画する（innerHTML は使わない）。

const main = document.getElementById("main");
const state = { user: null, view: "research", overview: null, selected: new Set(), resultRun: null, pollTimer: null };

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json", "X-Labo-Request": "1" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, { credentials: "same-origin", ...opt });
  let data = null;
  try { data = await res.json(); } catch (_) { /* 非JSON */ }
  if (res.status === 401 && path !== "/api/login") { showLogin(); throw new Error("ログインが必要です"); }
  if (!res.ok) throw new Error((data && data.error) || `エラー (${res.status})`);
  return data;
}

function readOnlyNotice() {
  return state.user && !state.user.can_write
    ? h("div", { class: "notice" }, "閲覧のみの権限です。保存・状態変更・計算実行はできません。") : null;
}
function render(...nodes) { main.replaceChildren(...nodes.filter((n) => n !== null && n !== undefined)); main.focus(); }
function loading(msg) { render(h("p", { class: "loading", role: "status" }, msg || "読み込み中…")); }
function errorBox(e) { return h("div", { class: "error", role: "alert" }, String(e.message || e)); }
function empty(msg) { return h("div", { class: "empty" }, msg); }
function fmt(v, unit) {
  if (v === null || v === undefined) return "—";
  if (unit === "秒" && typeof v === "number") {
    const m = Math.floor(v / 60), s = (v - m * 60).toFixed(2).padStart(5, "0");
    return `${v}（${m}:${s}）`;
  }
  return String(v);
}
function statusTag(s) {
  const cls = { "計算可能": "ok", "研究で採用": "ok", "提案": "warn", "定義確認": "warn",
    "テスト済み": "warn", "保留": "bad", "廃止": "bad" }[s] || "";
  return h("span", { class: `tag ${cls}` }, s);
}
function table(headers, rows) {
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, headers.map((x) => h("th", { scope: "col" }, x)))),
    h("tbody", {}, rows)));
}

// ---------- ログイン ----------
function showLogin() {
  document.getElementById("nav").hidden = true;
  document.getElementById("who").textContent = "";
  const input = h("input", { type: "password", id: "token", autocomplete: "off", required: true });
  const msg = h("div", { "aria-live": "polite" });
  const form = h("form", {
    class: "card", onsubmit: async (ev) => {
      ev.preventDefault();
      msg.replaceChildren();
      try { await api("/api/login", { token: input.value }); input.value = ""; start(); }
      catch (e) { msg.replaceChildren(errorBox(e)); }
    },
  },
  h("h1", {}, "ログイン"),
  h("p", { class: "muted" }, "管理者から受け取った個人用トークンを入力してください（初回の管理者は data/.token）。トークンは他の人と共有しないでください。"),
  h("label", { for: "token" }, "アクセストークン"), input,
  h("div", { class: "row" }, h("button", { class: "primary", type: "submit" }, "ログイン")), msg);
  render(form);
  input.focus();
}

// ---------- 研究トップ ----------
async function viewHome() {
  loading();
  const o = await api("/api/overview");
  state.overview = o;
  setBadge(o.dataset);
  const stat = (num, lbl) => h("div", { class: "card stat" }, h("div", { class: "num" }, num), h("div", { class: "lbl" }, lbl));
  const lr = o.latest_run;
  render(
    h("h1", {}, "研究トップ"),
    o.dataset.is_synthetic ? h("div", { class: "notice" }, "現在は合成データ（架空）で動作しています。値は実在選手のものではなく、予測力も実証されていません。") : null,
    h("div", { class: "grid" },
      stat(o.dataset.athletes, "人物数（データ版）"), stat(o.dataset.results, "結果行数"),
      stat(o.features.total, "特徴量定義数"), stat(o.runs, "計算実行数"),
      stat(o.quality.held_rows, "保留中の行（既定締切基準）"), stat(o.quality.entry_unknown, "入学年度不明の人物")),
    h("div", { class: "card" }, h("dl", { class: "kv" },
      h("dt", {}, "データ"), h("dd", {}, o.dataset.label),
      h("dt", {}, "データ版ハッシュ"), h("dd", { class: "mono" }, o.dataset.hash),
      h("dt", {}, "コード版"), h("dd", { class: "mono" }, o.code_version),
      h("dt", {}, "観測締切（既定）"), h("dd", {}, o.cutoffs[o.default_cutoff] + "（2026-10-18 利用者決定）"),
      h("dt", {}, "時点の扱い"), h("dd", {}, o.time_basis),
      h("dt", {}, "対象集団"), h("dd", {}, o.cohorts.map((c) => h("div", {}, `${c.label}（${c.ref}）— ${c.generalization_note}`))),
      h("dt", {}, "状態別の定義数"), h("dd", {}, Object.entries(o.features.by_status).map(([k, v]) => h("span", {}, statusTag(k), ` ${v} `))),
      h("dt", {}, "最新の計算"), h("dd", {}, lr ? `${lr.run_id}（${lr.cohort} / ${lr.cutoff} / ${lr.done}人）` : "まだありません"),
    )),
    h("h2", {}, "前回からの変更"),
    o.changes ? changesSummary(o.changes) : empty("比較できる完了済みの実行が2件以上ありません。"),
  );
}

function changesSummary(c) {
  const diffs = Object.entries(c.param_diff).map(([k, v]) => h("li", {}, `${k}: ${JSON.stringify(v[0])} → ${JSON.stringify(v[1])}`));
  const changed = c.per_feature.filter((f) => f.changed > 0 || f.spec_changed);
  return h("div", { class: "card" },
    h("p", {}, `比較: ${c.a} → ${c.b}`),
    diffs.length ? h("ul", {}, diffs) : h("p", { class: "muted" }, "データ版・コード版・締切・母集団は同一"),
    changed.length ? h("ul", {}, changed.map((f) => h("li", {}, `${f.a_ref} → ${f.b_ref}: ${f.changed}人の値が変化${f.spec_changed ? "（定義変更あり）" : ""}`)))
      : h("p", { class: "muted" }, "値の変化なし"),
    c.only_in_b.length ? h("p", {}, "新しく追加: " + c.only_in_b.join(", ")) : null);
}

function setBadge(ds) {
  const b = document.getElementById("data-badge");
  b.className = "badge " + (ds.is_synthetic ? "synthetic" : "real");
  b.textContent = ds.is_synthetic ? "合成データ（架空）" : "実データ（非公開）";
}

// ---------- ファクター一覧 ----------
async function viewFeatures() {
  loading();
  const data = await api("/api/features");
  const q = h("input", { type: "text", id: "fq", placeholder: "名前・仮説・IDで検索" });
  const cat = h("select", { id: "fcat" }, h("option", { value: "" }, "すべて"),
    [...new Set(data.features.map((f) => f.category))].map((c) => h("option", { value: c }, c)));
  const st = h("select", { id: "fst" }, h("option", { value: "" }, "すべて"), data.statuses.map((s) => h("option", { value: s }, s)));
  const list = h("div", {});
  const draw = () => {
    const kw = q.value.trim();
    const rows = data.features.filter((f) =>
      (!kw || [f.feature_id, f.display_name, f.hypothesis].some((x) => x.includes(kw))) &&
      (!cat.value || f.category === cat.value) && (!st.value || f.review_status === st.value));
    list.replaceChildren(rows.length ? h("div", {}, rows.map((f) => featureCard(f, data))) : empty("該当する特徴量がありません。"));
  };
  [q, cat, st].forEach((el) => el.addEventListener("input", draw));
  render(h("h1", {}, "ファクター一覧"),
    h("p", { class: "muted" }, "チェックした特徴量は「計算実行」で選択済みになります。重要度だけで自動採用はしません。利用者が作った定義を「計算可能」「研究で採用」にするのは、作成者以外のメンバーです。"),
    h("div", { class: "row" }, h("div", {}, h("label", { for: "fq" }, "検索"), q),
      h("div", {}, h("label", { for: "fcat" }, "カテゴリ"), cat), h("div", {}, h("label", { for: "fst" }, "状態"), st)),
    list);
  draw();
}

function featureCard(f, data) {
  const id = "sel-" + f.ref;
  const cb = h("input", { type: "checkbox", id, checked: state.selected.has(f.ref) });
  cb.addEventListener("change", () => { cb.checked ? state.selected.add(f.ref) : state.selected.delete(f.ref); });
  const miss = f.missing ? `欠損率 ${(f.missing.missing_rate * 100).toFixed(1)}%（${f.missing.n}人, 実行 ${f.missing.run_id}）` : "欠損率：未計算";
  const next = (data.transitions[f.review_status] || []);
  const toSel = h("select", { id: "to-" + f.ref }, next.map((s) => h("option", { value: s }, s)));
  const comment = h("input", { type: "text", id: "cm-" + f.ref, placeholder: "判断理由（必須）" });
  const msg = h("div", { "aria-live": "polite" });
  const reviewBox = next.length ? h("div", { class: "row" },
    h("label", { for: "to-" + f.ref }, "状態を変更"), toSel,
    h("label", { for: "cm-" + f.ref, class: "muted" }, "理由"), comment,
    h("button", { type: "button", onclick: async () => {
      if (!comment.value.trim()) { msg.replaceChildren(errorBox(new Error("判断理由を入力してください"))); return; }
      try { await api("/api/features/status", { ref: f.ref, to: toSel.value, comment: comment.value }); viewFeatures(); }
      catch (e) { msg.replaceChildren(errorBox(e)); }
    } }, "記録")) : null;
  const prev = h("div", {});
  return h("div", { class: "card" },
    h("div", { class: "row" }, h("label", { class: "check", for: id }, cb, h("span", {}, h("strong", {}, f.display_name), " ", h("code", {}, f.ref))),
      statusTag(f.review_status), h("span", { class: "tag" }, f.category),
      f.model_input_allowed ? null : h("span", { class: "tag warn" }, "品質表示専用（モデル入力外）")),
    h("p", {}, f.hypothesis),
    h("p", { class: "muted" }, miss),
    h("details", {}, h("summary", {}, "定義の詳細"),
      h("dl", { class: "kv" },
        h("dt", {}, "数式"), h("dd", {}, f.formula), h("dt", {}, "窓"), h("dd", {}, f.window),
        h("dt", {}, "必要件数"), h("dd", {}, f.min_n), h("dt", {}, "単位"), h("dd", {}, f.unit),
        h("dt", {}, "向き"), h("dd", {}, f.direction), h("dt", {}, "対象種目"), h("dd", {}, f.event),
        h("dt", {}, "必要カラム"), h("dd", {}, f.required_columns.join("、") || "—"),
        h("dt", {}, "欠損処理"), h("dd", {}, f.missing_policy), h("dt", {}, "除外条件"), h("dd", {}, f.exclusion),
        h("dt", {}, "時点制約"), h("dd", {}, f.time_constraint), h("dt", {}, "注意"), h("dd", {}, f.caution || "—"),
        h("dt", {}, "出典"), h("dd", {}, f.source), h("dt", {}, "作成"), h("dd", {}, `${f.author} / ${f.created_at}`),
        h("dt", {}, "テスト"), h("dd", {}, f.tests.join(", ") || "なし"),
        h("dt", {}, "宣言的定義"), h("dd", { class: "mono" }, JSON.stringify(f.spec)),
        h("dt", {}, "定義ハッシュ"), h("dd", { class: "mono" }, f.spec_hash),
        f.deprecation_reason ? [h("dt", {}, "廃止理由"), h("dd", {}, f.deprecation_reason)] : null),
      f.review_history.length ? h("ul", {}, f.review_history.map((r) => h("li", {}, `${r.at} ${r.from}→${r.to}：${r.comment}`))) : null),
    reviewBox, msg,
    h("div", { class: "row" }, h("button", { type: "button", onclick: async () => {
      prev.replaceChildren(h("p", { class: "loading" }, "合成データでプレビュー中…"));
      try { const p = await api("/api/features/preview", { ref: f.ref }); prev.replaceChildren(previewTable(p)); }
      catch (e) { prev.replaceChildren(errorBox(e)); }
    } }, "合成データでプレビュー")), prev);
}

function previewTable(p) {
  return h("div", {}, h("p", { class: "muted" }, p.dataset_label),
    table(["人物", "値", "理由", "件数", "期間"], p.rows.map((r) => h("tr", {},
      h("td", {}, r.name), h("td", { class: "num" }, fmt(r.value, r.unit)), h("td", {}, r.reason),
      h("td", { class: "num" }, r.evidence_count), h("td", {}, `${r.period_start || "—"}〜${r.period_end || "—"}`)))));
}

// ---------- 特徴量作成 ----------
async function viewCreate() {
  loading();
  const data = await api("/api/features");
  const refs = data.features.filter((f) => f.review_status !== "廃止").map((f) => f.ref);
  const fld = (id, label, el) => h("div", {}, h("label", { for: id }, label), el);
  const fid = h("input", { type: "text", id: "c-id", required: true, placeholder: "例: best_1500_s" });
  const name = h("input", { type: "text", id: "c-name", placeholder: "表示名" });
  const hyp = h("textarea", { id: "c-hyp", placeholder: "例：高1から高2の伸びが大学での伸びと関係する" });
  const op = h("select", { id: "c-op" }, data.allowed_ops.map((o) => h("option", { value: o }, o)));
  const ev = h("select", { id: "c-ev" }, data.allowed_events.map((e) => h("option", { value: e }, e)));
  const wk = h("select", { id: "c-wk" }, h("option", { value: "hs" }, "H（高1の4/1〜締切）"),
    h("option", { value: "recent_days" }, "直近N日"), h("option", { value: "grade" }, "学年"),
    h("option", { value: "junior" }, "J（中1の4/1〜中3の3/31）"), h("option", { value: "junior_grade" }, "中学の学年"));
  const days = h("input", { type: "number", id: "c-days", min: 1, max: 1095, value: 365 });
  const grade = h("select", { id: "c-grade" }, h("option", { value: "1" }, "高1"), h("option", { value: "2" }, "高2"));
  const jgrade = h("select", { id: "c-jgrade" }, ["1", "2", "3"].map((g) => h("option", { value: g }, `中${g}`)));
  const race = h("select", { id: "c-race" }, Object.entries(data.allowed_races).map(([k, v]) => h("option", { value: k }, v)));
  const n = h("input", { type: "number", id: "c-n", min: 2, max: 10, value: 3 });
  const minN = h("input", { type: "number", id: "c-minn", min: 1, max: 20, value: 1 });
  const inA = h("select", { id: "c-a" }, refs.map((r) => h("option", { value: r }, r)));
  const inB = h("select", { id: "c-b" }, refs.map((r) => h("option", { value: r }, r)));
  const unit = h("input", { type: "text", id: "c-unit", value: "秒" });
  const formula = h("input", { type: "text", id: "c-formula", placeholder: "数式の説明（表示用）" });
  const missing = h("input", { type: "text", id: "c-missing", placeholder: "欠損時の扱い（表示用）" });
  const qualityOnly = h("input", { type: "checkbox", id: "c-qonly" });
  const msg = h("div", { "aria-live": "polite" });
  const specOut = h("pre", { class: "card mono" });
  const buildSpec = () => {
    if (op.value === "diff" || op.value === "pct_change") return { op: op.value, inputs: [inA.value, inB.value] };
    const window = wk.value === "hs" ? { kind: "hs" } : wk.value === "recent_days"
      ? { kind: "recent_days", days: Number(days.value) } : wk.value === "junior" ? { kind: "junior" }
      : wk.value === "junior_grade" ? { kind: "junior_grade", grade: Number(jgrade.value) }
      : { kind: "grade", grade: Number(grade.value) };
    if (op.value === "ekiden_count" || op.value === "ekiden_best_rank") return { op: op.value, race: race.value, window };
    const spec = { op: op.value, event: ev.value, window, min_n: Number(minN.value) };
    if (op.value === "median_latest_n") spec.n = Number(n.value);
    if (op.value === "iqr") spec.min_competitions = 2;
    if (op.value === "median_gap") { delete spec.min_n; spec.min_dates = 3; }
    return spec;
  };
  const refresh = () => { specOut.textContent = JSON.stringify(buildSpec(), null, 1); };
  [op, ev, wk, days, grade, jgrade, race, n, minN, inA, inB].forEach((el) => el.addEventListener("input", refresh));
  const form = h("form", { class: "card", onsubmit: async (e) => {
    e.preventDefault();
    msg.replaceChildren();
    try {
      const d = await api("/api/features", {
        feature_id: fid.value.trim(), display_name: name.value, hypothesis: hyp.value, spec: buildSpec(),
        unit: unit.value, formula: formula.value, missing_policy: missing.value,
        model_input_allowed: !qualityOnly.checked, category: "利用者定義",
      });
      msg.replaceChildren(h("div", { class: "notice" }, `${d.ref} を「提案」として保存しました。ファクター一覧で定義確認後に合成データでプレビューできます。計算は「計算可能」になるまで実行されません。`));
    } catch (err) { msg.replaceChildren(errorBox(err)); }
  } },
  h("h2", {}, "手動フォーム（許可済み演算のみ）"),
  fld("c-id", "特徴量ID（英数字と_）", fid), fld("c-name", "表示名", name), fld("c-hyp", "仮説（日本語）", hyp),
  fld("c-op", "演算", op), fld("c-ev", "種目（3000mSCは3000mと別）", ev), fld("c-wk", "窓", wk),
  fld("c-days", "直近N日（窓=直近N日のとき）", days), fld("c-grade", "学年（窓=学年のとき）", grade),
  fld("c-jgrade", "中学の学年（窓=中学の学年のとき）", jgrade),
  fld("c-race", "駅伝の大会（ekiden_count / ekiden_best_rank）", race),
  fld("c-n", "直近N出走（median_latest_n）", n), fld("c-minn", "最小件数", minN),
  fld("c-a", "比較元（diff / pct_change）", inA), fld("c-b", "比較先（diff / pct_change）", inB),
  fld("c-unit", "単位", unit), fld("c-formula", "数式の説明", formula), fld("c-missing", "欠損処理", missing),
  h("label", { class: "check", for: "c-qonly" }, qualityOnly, "品質表示専用（将来のモデル入力から外す）"),
  h("h3", {}, "保存される宣言的定義"), specOut,
  h("div", { class: "row" }, h("button", { class: "primary", type: "submit" }, "提案として保存")), msg);
  render(h("h1", {}, "特徴量作成"), readOnlyNotice(),
    h("div", { class: "card" }, h("h2", {}, "AIによる定義案"),
      h("p", {}, "未実装（段階4）。外部AIへの送信は既定で無効で、実在選手のデータは送信しません。"),
      h("p", { class: "muted" }, "AIの案も、この手動フォームと同じ許可済み演算の定義に変換され、利用者確認を経るまで実行されません。")),
    form);
  refresh();
}

// ---------- 計算実行 ----------
async function viewRun() {
  loading();
  const [o, fdata] = await Promise.all([api("/api/overview"), api("/api/features")]);
  const runnable = fdata.features.filter((f) => ["計算可能", "研究で採用"].includes(f.review_status));
  const cohort = h("select", { id: "r-cohort" }, o.cohorts.map((c) => h("option", { value: c.ref }, c.label)));
  const cutoff = h("select", { id: "r-cutoff" }, Object.entries(o.cutoffs).map(([k, v]) => h("option", { value: k }, v)));
  const strict = h("input", { type: "checkbox", id: "r-strict" });
  if (state.selected.size === 0) runnable.forEach((f) => state.selected.add(f.ref));
  const boxes = runnable.map((f) => {
    const cb = h("input", { type: "checkbox", id: "r-" + f.ref, checked: state.selected.has(f.ref) });
    cb.addEventListener("change", () => { cb.checked ? state.selected.add(f.ref) : state.selected.delete(f.ref); });
    return h("label", { class: "check", for: "r-" + f.ref }, cb, `${f.display_name}（${f.ref}）`);
  });
  const planBox = h("div", { "aria-live": "polite" });
  const body = () => ({ cohort: cohort.value, cutoff: cutoff.value, strict_publication: strict.checked,
    features: [...state.selected].filter((r) => runnable.some((f) => f.ref === r)) });
  const doPlan = async () => {
    planBox.replaceChildren(h("p", { class: "loading" }, "計算対象を確認中…"));
    try {
      const p = await api("/api/runs/plan", body());
      const ex = Object.entries(p.excluded);
      planBox.replaceChildren(h("div", { class: "card" },
        h("p", {}, `計算対象 ${p.included.length}人 / 特徴量 ${p.feature_refs.length}個（派生特徴量の参照先を含む）`),
        h("p", { class: "mono" }, `実行ID（入力のハッシュ）: ${p.run_id}`),
        ex.length ? h("ul", {}, ex.map(([k, v]) => h("li", {}, `${p.excluded_labels[k] || k}: ${v.length}人`))) : h("p", { class: "muted" }, "除外なし"),
        h("button", { class: "primary", type: "button", onclick: doRun }, "この条件で実行")));
    } catch (e) { planBox.replaceChildren(errorBox(e)); }
  };
  const doRun = async () => {
    try {
      const r = await api("/api/runs", body());
      state.resultRun = r.run_id;
      planBox.replaceChildren(h("div", { class: "notice" }, r.reused ? "同一条件の完了済み実行があるため再利用しました（重複保存しません）。" : "実行を開始しました。"));
      watchRun(r.run_id, planBox);
    } catch (e) { planBox.replaceChildren(errorBox(e)); }
  };
  render(h("h1", {}, "計算実行"), readOnlyNotice(),
    h("div", { class: "card" },
      h("label", { for: "r-cohort" }, "対象集団"), cohort,
      h("label", { for: "r-cutoff" }, "観測締切"), cutoff,
      h("label", { class: "check", for: "r-strict" }, strict, "厳密な当時再現（公表日が締切以前と確認できる結果のみ）"),
      h("h2", {}, "特徴量（計算可能・研究で採用のみ）"),
      boxes.length ? boxes : empty("計算可能な定義がありません。"),
      h("div", { class: "row" }, h("button", { type: "button", class: "primary", onclick: doPlan }, "計算対象を確認"))),
    planBox);
}

function watchRun(runId, box) {
  clearInterval(state.pollTimer); clearTimeout(state.pollTimer);
  const prog = h("progress", { max: 1, value: 0, "aria-label": "進捗" });
  const label = h("p", { "aria-live": "polite" });
  const btns = h("div", { class: "row" });
  box.append(h("div", { class: "card" }, h("p", { class: "mono" }, runId), prog, label, btns));
  const tick = async () => {
    try {
      const m = await api(`/api/runs/${runId}`);
      prog.max = Math.max(m.total, 1); prog.value = m.done;
      label.textContent = `状態: ${m.state}（${m.done}/${m.total}人）${m.error ? " エラー: " + m.error : ""}`;
      btns.replaceChildren(
        m.state === "running" || m.state === "queued" ? h("button", { type: "button", onclick: () => api(`/api/runs/${runId}/cancel`, {}) }, "取消") : null,
        ["cancelled", "failed"].includes(m.state) ? h("button", { type: "button", onclick: async () => { await api(`/api/runs/${runId}/resume`, {}); } }, "再開") : null,
        m.state === "completed" ? h("button", { type: "button", class: "primary", onclick: () => { state.resultRun = runId; go("results"); } }, "結果を見る") : null);
      if (["completed"].includes(m.state)) clearInterval(state.pollTimer);
    } catch (e) { label.textContent = e.message; clearInterval(state.pollTimer); }
  };
  tick();
  state.pollTimer = setInterval(tick, 800);
}

// ---------- 結果確認 ----------
async function viewResults() {
  loading();
  const runs = (await api("/api/runs")).runs;
  if (!runs.length) return render(h("h1", {}, "結果確認"), empty("まだ計算実行がありません。「計算実行」から実行してください。"));
  const sel = h("select", { id: "res-run" }, runs.map((r) => h("option", { value: r.run_id, selected: r.run_id === state.resultRun },
    `${r.created_at} ${r.cohort} ${r.cutoff} [${r.state}]`)));
  const out = h("div", {});
  const draw = async () => {
    state.resultRun = sel.value;
    out.replaceChildren(h("p", { class: "loading" }, "読み込み中…"));
    try {
      const d = await api(`/api/runs/${sel.value}/values`);
      out.replaceChildren(resultsTable(d));
    } catch (e) { out.replaceChildren(errorBox(e)); }
  };
  sel.addEventListener("change", draw);
  render(h("h1", {}, "結果確認"),
    h("p", { class: "muted" }, "既定の並びは人物ID順です（予測順位・ランキングではありません）。"),
    h("label", { for: "res-run" }, "実行"), sel, out);
  draw();
}

function resultsTable(d) {
  const refs = d.meta.feature_refs;
  const pick = h("select", { id: "res-feat" }, refs.map((r) => h("option", { value: r }, r)));
  const tbody = h("tbody", {});
  const detail = h("div", {});
  const draw = () => {
    tbody.replaceChildren(...d.rows.map((row) => {
      const v = row.values.find((x) => x.feature_ref === pick.value);
      return h("tr", {},
        h("td", {}, h("button", { type: "button", class: "ghost", onclick: () => showPerson(row, d, detail) }, row.person_id)),
        h("td", {}, row.name), h("td", {}, row.cutoff || "—"),
        h("td", { class: "num" }, v ? fmt(v.value, v.unit) : "—"),
        h("td", {}, v && v.reason !== "ok" ? h("span", { class: "tag warn", title: d.missing_labels[v.reason] || "" }, d.missing_labels[v.reason] || v.reason) : h("span", { class: "tag ok" }, "ok")),
        h("td", { class: "num" }, v ? v.evidence_count : "—"),
        h("td", {}, v && v.period_start ? `${v.period_start}〜${v.period_end}` : "—"));
    }));
  };
  pick.addEventListener("change", draw);
  draw();
  const p = d.meta.params;
  return h("div", {},
    p.is_synthetic ? h("div", { class: "notice" }, "合成データ（架空）の結果です。") : null,
    h("div", { class: "card" }, h("dl", { class: "kv" },
      h("dt", {}, "状態"), h("dd", {}, `${d.meta.state}（${d.meta.done}/${d.meta.total}人）`),
      h("dt", {}, "母集団"), h("dd", {}, `${p.cohort.label}（${p.cohort.ref}）`),
      h("dt", {}, "締切"), h("dd", {}, p.cutoff_label),
      h("dt", {}, "データ版 / コード版"), h("dd", { class: "mono" }, `${p.dataset_hash} / ${p.code_version}`),
      h("dt", {}, "除外"), h("dd", {}, Object.entries(d.meta.excluded).map(([k, v]) => `${k}: ${v.length}人`).join("、") || "なし")),
      h("a", { class: "btn", href: `/api/runs/${d.meta.run_id}/export.csv` }, "CSVエクスポート")),
    h("label", { for: "res-feat" }, "表示する特徴量"), pick,
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {},
      ["人物ID", "氏名", "締切日", "値", "品質・欠損理由", "根拠件数", "対象期間"].map((x) => h("th", { scope: "col" }, x)))), tbody)),
    detail);
}

async function showPerson(row, d, box) {
  box.replaceChildren(h("p", { class: "loading" }, "元記録を読み込み中…"));
  try {
    const p = await api(`/api/persons/${encodeURIComponent(row.person_id)}?cutoff=${d.meta.params.cutoff_preset}`);
    const used = new Set(row.values.flatMap((v) => v.evidence));
    box.replaceChildren(h("h2", {}, `${p.athlete.name}（${p.athlete.person_id}）の根拠`),
      h("div", { class: "card" }, h("dl", { class: "kv" },
        h("dt", {}, "高校入学年度"), h("dd", {}, `${p.athlete.hs_entry_fiscal_year ?? "不明"}（根拠: ${p.athlete.hs_entry_evidence} / 確度: ${p.athlete.hs_entry_confidence}）`),
        h("dt", {}, "取得状態"), h("dd", {}, p.athlete.coverage), h("dt", {}, "締切日"), h("dd", {}, p.cutoff || "—"))),
      h("h3", {}, "特徴量の値"),
      table(["特徴量", "値", "理由", "件数", "注記"], row.values.map((v) => h("tr", {},
        h("td", { class: "mono" }, v.feature_ref), h("td", { class: "num" }, fmt(v.value, v.unit)),
        h("td", {}, d.missing_labels[v.reason] || v.reason), h("td", { class: "num" }, v.evidence_count), h("td", {}, v.note)))),
      h("h3", {}, "元記録（原本は変更しません）"),
      table(["使用", "判定", "種目", "区分", "大会", "大会期間", "実施日", "原表記", "秒", "取得状態", "キー"], p.results.map((r) => h("tr", {},
        h("td", {}, used.has(r.key) ? h("span", { class: "tag ok" }, "根拠") : ""),
        h("td", {}, h("span", { class: "tag " + ({ used: "ok", held: "warn", excluded: "bad" }[r.decision.decision] || "") }, r.decision.label)),
        h("td", {}, r.event || "—"), h("td", {}, r.group || "—"), h("td", {}, r.competition),
        h("td", {}, `${r.competition_start || "?"}〜${r.competition_end || "?"}`), h("td", {}, r.performed_date || "未確認"),
        h("td", { class: "mono" }, r.mark_raw), h("td", { class: "num" }, r.seconds ?? "—"),
        h("td", {}, r.capture_validation_status || "—"), h("td", { class: "mono" }, r.key)))));
    box.scrollIntoView({ behavior: "smooth" });
  } catch (e) { box.replaceChildren(errorBox(e)); }
}

// ---------- 実験履歴 ----------
async function viewHistory() {
  loading();
  const runs = (await api("/api/runs")).runs;
  if (!runs.length) return render(h("h1", {}, "実験履歴"), empty("まだ計算実行がありません。"));
  const opts = () => runs.map((r) => h("option", { value: r.run_id }, `${r.created_at} ${r.run_id} ${r.cohort} ${r.cutoff}`));
  const a = h("select", { id: "h-a" }, opts()), b = h("select", { id: "h-b" }, opts());
  if (runs.length > 1) a.selectedIndex = 1;
  const out = h("div", { "aria-live": "polite" });
  render(h("h1", {}, "実験履歴"),
    h("p", { class: "muted" }, "過去の実行結果は上書きされません。同じ入力・定義・コードの再実行は同じ実行IDになり、重複保存しません。"),
    table(["作成", "実行ID", "状態", "母集団", "締切", "特徴量数", "人数", "データ"], runs.map((r) => h("tr", {},
      h("td", {}, r.created_at), h("td", { class: "mono" }, r.run_id), h("td", {}, r.state + (r.error ? `（${r.error}）` : "")),
      h("td", {}, r.cohort), h("td", {}, r.cutoff), h("td", { class: "num" }, r.features),
      h("td", { class: "num" }, `${r.done}/${r.total}`), h("td", {}, r.is_synthetic ? "合成" : "実データ")))),
    h("h2", {}, "比較"),
    h("div", { class: "row" }, h("div", {}, h("label", { for: "h-a" }, "変更前"), a), h("div", {}, h("label", { for: "h-b" }, "変更後"), b),
      h("button", { type: "button", class: "primary", onclick: async () => {
        out.replaceChildren(h("p", { class: "loading" }, "比較中…"));
        try {
          const c = await api(`/api/compare?a=${a.value}&b=${b.value}`);
          out.replaceChildren(changesSummary(c),
            c.changed_rows.length ? table(["人物", "変更前", "変更後", "値(前)", "値(後)", "理由(前)", "理由(後)"], c.changed_rows.map((r) => h("tr", {},
              h("td", {}, r.person_id), h("td", { class: "mono" }, r.a_ref), h("td", { class: "mono" }, r.b_ref),
              h("td", { class: "num" }, r.a ?? "—"), h("td", { class: "num" }, r.b ?? "—"), h("td", {}, r.a_reason), h("td", {}, r.b_reason)))) : empty("値の差分はありません。"));
        } catch (e) { out.replaceChildren(errorBox(e)); }
      } }, "比較する")), out);
}

// ---------- 品質・保留 ----------
async function viewQuality() {
  loading();
  const o = await api("/api/overview");
  const cutoffSel = h("select", { id: "q-cut" }, Object.entries(o.cutoffs).map(([k, v]) => h("option", { value: k, selected: k === o.default_cutoff }, v)));
  const out = h("div", {});
  const draw = async () => {
    out.replaceChildren(h("p", { class: "loading" }, "読み込み中…"));
    try {
      const q = await api(`/api/quality?cutoff=${cutoffSel.value}`);
      out.replaceChildren(
        h("p", { class: "muted" }, `基準: ${q.cutoff_label}。原本は修正せず、判断は履歴として残します。`),
        h("h2", {}, "内訳"),
        table(["判定", "理由", "件数"], q.summary.map((s) => h("tr", {},
          h("td", {}, h("span", { class: "tag " + (s.decision === "held" ? "warn" : "bad") }, s.decision === "held" ? "保留" : "除外")),
          h("td", {}, s.label), h("td", { class: "num" }, s.count)))),
        h("h2", {}, "人物単位の注意"),
        h("ul", {}, h("li", {}, `入学年度不明: ${q.people.hs_entry_year_unknown.join(", ") || "なし"}`),
          h("li", {}, `取得状態不明: ${q.people.coverage_unknown.join(", ") || "なし"}`)),
        h("h2", {}, "証拠に基づく統合（対応表）"),
        q.merged_duplicates.length ? table(["代表", "統合された行", "根拠"], q.merged_duplicates.map((m) => h("tr", {},
          h("td", { class: "mono" }, m.canonical), h("td", { class: "mono" }, m.duplicate), h("td", {}, m.evidence)))) : empty("なし"),
        h("h2", {}, `保留中の行（${q.held_total}件）`),
        q.held_rows.length ? table(["人物", "種目", "理由", "キー", "判断を記録"], q.held_rows.map((r) => h("tr", {},
          h("td", {}, r.person_id), h("td", {}, r.event), h("td", {}, r.label), h("td", { class: "mono" }, r.key),
          h("td", {}, decisionButton(r))))) : empty("保留中の行はありません。"),
        h("h2", {}, "判断履歴"),
        q.decisions.length ? h("ul", {}, q.decisions.map((x) => h("li", {}, `${x.at} ${x.target}: ${x.decision} — ${x.comment}`))) : empty("まだ判断履歴はありません。"));
    } catch (e) { out.replaceChildren(errorBox(e)); }
  };
  cutoffSel.addEventListener("change", draw);
  render(h("h1", {}, "品質・保留一覧"), h("label", { for: "q-cut" }, "観測締切"), cutoffSel, out);
  draw();
}

function decisionButton(r) {
  return h("button", { type: "button", onclick: async (ev) => {
    const comment = window.prompt(`${r.key} の判断メモ（原本は変更されません）`);
    if (!comment) return;
    try { await api("/api/quality/decision", { target: r.key, decision: "確認メモ", comment }); ev.target.textContent = "記録済み"; ev.target.disabled = true; }
    catch (e) { window.alert(e.message); }
  } }, "メモ");
}

// ---------- 研究状況 ----------
const num3 = (v) => (v === "" || v === null || v === undefined || Number.isNaN(Number(v))) ? "—" : Number(v).toFixed(3);
const sign3 = (v) => (v === "" || v === null || v === undefined) ? "—" : (Number(v) >= 0 ? "+" : "−") + Math.abs(Number(v)).toFixed(3);
const when = (v) => { if (!v) return "—"; const d = new Date(v); return Number.isNaN(d.getTime()) ? v : d.toLocaleString("ja-JP", { dateStyle: "short", timeStyle: "short" }); };
const pct = (v) => (v === "" || v === null || v === undefined) ? "—" : `${(Number(v) * 100).toFixed(0)}%`;

function deltaCell(v, lo, hi, scale) {
  if (v === "" || v === null || v === undefined) return h("div", { class: "muted" }, "—");
  const pos = (x) => `${Math.max(0, Math.min(100, 50 + (Number(x) / scale) * 50))}%`;
  const bar = h("span", { class: "bar" + (Number(lo) > 0 ? " sure" : Number(v) > 0 ? " pos" : "") });
  const a = Math.min(50, parseFloat(pos(v))), b = Math.max(50, parseFloat(pos(v)));
  bar.style.left = `${a}%`; bar.style.width = `${Math.max(1, b - a)}%`;
  const track = h("span", { class: "track" }, h("span", { class: "zero" }), bar);
  if (lo !== "" && hi !== "" && lo !== undefined) {
    const ci = h("span", { class: "ci" }); ci.style.left = pos(lo);
    ci.style.width = `${Math.max(1, parseFloat(pos(hi)) - parseFloat(pos(lo)))}%`; track.append(ci);
  }
  const title = lo !== "" && lo !== undefined ? `95%区間 ${sign3(lo)}〜${sign3(hi)}` : "";
  return h("div", { title }, h("div", { class: "delta" }, h("span", { class: "num small" }, sign3(v)), track),
    title ? h("div", { class: "muted small" }, title) : null);
}

async function setStatus(ref, to, comment) {
  await api("/api/features/status", { ref, to, comment });
}

async function viewResearch() {
  loading();
  const d = await api("/api/research");
  const t = d.tables, job = d.job, canWrite = state.user && state.user.can_write;
  const running = job.state === "running";
  const head = h("div", { class: "card" },
    h("div", { class: "row" },
      h("strong", {}, running ? `再計算・再評価を実行中：${job.message}` : job.state === "failed" ? job.message
        : job.state === "done" ? `前回の実行：${when(job.finished_at)} 完了` : "実データで特徴量を計算し、研究評価までまとめて実行します。"),
      canWrite && d.can_run ? h("button", { class: "primary", type: "button", disabled: running, onclick: async (e) => {
        e.target.disabled = true;
        try { await api("/api/research/run", {}); viewResearch(); } catch (err) { head.append(errorBox(err)); e.target.disabled = false; }
      } }, "実データで再計算・再評価") : null),
    !d.can_run ? h("p", { class: "muted" }, "合成データで起動中のため実行できません（チームPCで LABO_DATA_SOURCE=rkm で起動）。") : null,
    t ? h("p", { class: "muted" }, `集計 ${when(t._meta.summary_at)}／評価 ${t._meta.eval_at ? when(t._meta.eval_at) : "未実行"}／締切 ${t._meta.cutoff || ""}`) : null);
  if (running) state.pollTimer = setTimeout(() => { if (state.view === "research") viewResearch(); }, 4000);
  if (!t) {
    render(h("h1", {}, "研究状況"), readOnlyNotice(), head,
      empty("まだ集計がありません。「実データで再計算・再評価」を押すか、scripts/run_real_features.py と run_evaluation.py を実行してください。"));
    return;
  }
  const sc = Object.fromEntries((t.eval_score || []).map((r) => [r.metric, r.value]));
  const evalCard = t.eval_score ? h("div", { class: "card" },
    h("h2", {}, "研究評価（世代順の検証での PR-AUC）"),
    h("p", { class: "muted" }, "高いほど達成者を上位にまとめられる。各年度の人はそれより前の世代だけで学習。追跡中・不明は使わない。2018年度入学以降は最終確認用に取り置き。"),
    h("div", { class: "grid" },
      h("div", { class: "stat" }, h("div", { class: "lbl" }, `評価値（基準＋${Number(sc["使った特徴量の数"] || 1) - 1}件のセット）`), h("div", { class: "num" }, num3(sc["評価値（PR-AUC）"]))),
      h("div", { class: "stat" }, h("div", { class: "lbl" }, "基準（5000mベストのみ）"), h("div", { class: "num" }, num3(sc["基準（5000mベストのみ）"]))),
      h("div", { class: "stat" }, h("div", { class: "lbl" }, "上積み"), h("div", { class: "num" }, sign3(sc["上積み"])),
        h("div", { class: "ci" }, `95%区間 ${sign3(sc["上積み95%区間・下"])}〜${sign3(sc["上積み95%区間・上"])}`)),
      h("div", { class: "stat" }, h("div", { class: "lbl" }, "偶然の水準（達成者の割合）"), h("div", { class: "num" }, num3(sc["達成の割合（偶然の水準）"])),
        h("div", { class: "ci" }, `評価 ${sc["評価した人数"]}人・達成 ${sc["うち達成"]}人`)))) : null;

  // 特徴量ごとの上積みと状態
  const evalBy = new Map((t.eval_features || []).map((r) => [r.ref, r]));
  const rows = d.features.filter((f) => f.ref !== "best_5000_s@1").map((f) => ({ f, e: evalBy.get(f.ref) }));
  const key = (x) => { const e = x.e; if (!e) return -9; return Number(e.add_to_set !== "" ? e.add_to_set : e.add_to_baseline); };
  rows.sort((a, b) => key(b) - key(a));
  const scale = Math.max(0.02, ...rows.flatMap(({ e }) => e ? [e.add_low, e.add_high, e.set_low, e.set_high, e.add_to_baseline, e.add_to_set]
    .filter((x) => x !== "" && x !== undefined).map((x) => Math.abs(Number(x))) : []));
  const action = (f, e) => {
    if (!canWrite) return null;
    const btn = (label, to, comment) => h("button", { type: "button", onclick: async (ev) => {
      ev.target.disabled = true;
      try { await setStatus(f.ref, to, comment); viewResearch(); } catch (err) { ev.target.replaceWith(errorBox(err)); }
    } }, label);
    const gain = e ? (e.add_to_set !== "" ? e.add_to_set : e.add_to_baseline) : "";
    if (["提案", "定義確認", "テスト済み"].includes(f.status) && f.builtin && f.status === "テスト済み")
      return btn("計算可能にする", "計算可能", "研究状況の画面から：実データで計算する");
    if (f.status === "計算可能") return btn("研究で採用", "研究で採用", `研究状況の画面から：上積み ${sign3(gain)}`);
    if (f.status === "研究で採用") return btn("セットから外す", "保留", `研究状況の画面から：抜いたときの低下 ${sign3(e ? e.drop_from_full : "")}`);
    return h("span", { class: "muted small" }, "ファクター一覧で変更");
  };
  const pending = d.features.filter((f) => f.builtin && f.status === "テスト済み");
  const featCard = h("div", { class: "card" },
    h("h2", {}, "特徴量ごとの上積みと状態"),
    h("p", { class: "muted" }, "「いまのセットに足す」が区間ごと0より上（緑）なら「研究で採用」に。採用した特徴量は次の再評価から評価値に入る。線は95%区間。"),
    canWrite && pending.length ? h("div", { class: "row" }, h("button", { type: "button", onclick: async (ev) => {
      ev.target.disabled = true;
      try { for (const f of pending) await setStatus(f.ref, "計算可能", "研究状況の画面から：まとめて計算可能に"); viewResearch(); }
      catch (err) { ev.target.replaceWith(errorBox(err)); }
    } }, `「テスト済み」の${pending.length}件をまとめて計算可能にする`), h("span", { class: "muted small" }, "その後「再計算・再評価」で評価に入る")) : null,
    h("div", { class: "flist" },
      h("div", { class: "frow fhead" }, h("div", {}, "特徴量"), h("div", {}, "状態"), h("div", {}, "いまのセットに足す／抜くと"),
        h("div", {}, "基準に足す"), h("div", {}, "値あり"), h("div", {}, "")),
      rows.map(({ f, e }) => h("div", { class: "frow" },
        h("div", { class: "fname" }, h("strong", {}, f.name), h("div", { class: "muted small" }, `${f.category}・${f.ref}`)),
        h("div", { class: "fstat" }, statusTag(f.status), !e && f.runnable ? h("span", { class: "muted small" }, " 未評価") : null),
        h("div", { class: "fd" }, h("span", { class: "flbl" }, "いまのセットに足す"),
          e && e.role === "セット内" ? h("div", {}, h("span", { class: "muted small" }, "抜くと "), sign3(e.drop_from_full === "" ? "" : -Number(e.drop_from_full)))
            : e ? deltaCell(e.add_to_set, e.set_low, e.set_high, scale) : h("div", { class: "muted" }, "—")),
        h("div", { class: "fd" }, h("span", { class: "flbl" }, "基準に足す"), e ? deltaCell(e.add_to_baseline, e.add_low, e.add_high, scale) : h("div", { class: "muted" }, "—")),
        h("div", { class: "fcov" }, h("span", { class: "flbl" }, "値あり "), e ? pct(e.coverage) : "—"),
        h("div", { class: "fact" }, action(f, e))))));

  const hist = (t.eval_history || []).slice().reverse();
  const histCard = hist.length ? h("details", { class: "card" }, h("summary", {}, `評価値の推移（${hist.length}回）`),
    table(["日時", "特徴量", "評価値", "基準", "種類", "メモ"], hist.map((r) => h("tr", {},
      h("td", {}, when(r.at)), h("td", { class: "num" }, r.n_features), h("td", { class: "num" }, num3(r.score)),
      h("td", { class: "num" }, num3(r.baseline_score)), h("td", {}, r.kind), h("td", {}, r.note))))) : null;

  // データの状況
  const ov = t.overview || [];
  const years = [...new Set((t.outcomes || []).map((r) => r.entry_fy))].sort();
  const labels = ["達成", "未達成（確定）", "追跡中", "不明"];
  const oc = (y, l) => { const r = (t.outcomes || []).find((x) => x.entry_fy === y && x.label === l); return r ? r.count : 0; };
  const dataCard = h("div", {},
    h("details", { class: "card" }, h("summary", {}, "主な数値"),
      h("div", { class: "grid" }, ov.map((r) => h("div", { class: "stat" }, h("div", { class: "lbl" }, r.metric), h("div", { class: "num" }, r.value))))),
    h("details", { class: "card" }, h("summary", {}, "箱根の成果ラベル（高校入学年度別）"),
      table(["入学年度", ...labels], years.map((y) => h("tr", {}, h("td", {}, y), labels.map((l) => h("td", { class: "num" }, oc(y, l))))))),
    h("details", { class: "card" }, h("summary", {}, `特徴量の値あり件数（${(t.features || []).length}件）`),
      table(["特徴量", "値あり", "主な欠損理由", "中央値"], (t.features || []).map((r) => h("tr", {},
        h("td", {}, r.name, h("div", { class: "muted small" }, r.model_input)), h("td", { class: "num" }, `${r.non_null}／${r.total}`),
        h("td", {}, r.top_missing_reason || "—"), h("td", { class: "num" }, r.p50 === "" ? "—" : fmt(Number(r.p50), r.unit)))))),
    h("details", { class: "card" }, h("summary", {}, "駅伝の取り込み"),
      table(["内訳", "区間数"], Object.entries(t._meta.ekiden || {}).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", { class: "num" }, v)))),
      Object.entries(t._meta.ekiden_names || {}).map(([cls, names]) => h("details", {}, h("summary", {}, `大会名：${cls}`),
        h("ul", {}, Object.entries(names).map(([n, c]) => h("li", {}, `${n}（${c}）`)))))),
    h("details", { class: "card" }, h("summary", {}, "5000m の記録の判定・箱根の記録欠け"),
      table(["判定", "理由", "件数"], (t.decisions_5000m || []).map((r) => h("tr", {}, h("td", {}, r.decision), h("td", {}, r.reason), h("td", { class: "num" }, r.count)))),
      h("h3", {}, "箱根の記録が欠けている出走年"),
      table(["出走年", "内容", "件数"], (t.hakone_gaps || []).map((r) => h("tr", {}, h("td", {}, r.run_year), h("td", {}, r.kind), h("td", { class: "num" }, r.count))))));

  render(h("h1", {}, "研究状況"), readOnlyNotice(), head, evalCard, featCard, histCard, dataCard,
    h("p", { class: "muted small" }, "このページは集計だけを表示します（氏名・個人ごとの予測値・順位はありません）。"));
}

// ---------- ルーティング ----------
const VIEWS = { research: viewResearch, home: viewHome, features: viewFeatures, create: viewCreate, run: viewRun,
  results: viewResults, history: viewHistory, quality: viewQuality };

async function go(view) {
  clearInterval(state.pollTimer); clearTimeout(state.pollTimer);
  state.view = view;
  document.querySelectorAll("#nav [data-view]").forEach((b) => {
    if (b.dataset.view === view) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  });
  try { await VIEWS[view](); } catch (e) { if (e.message !== "ログインが必要です") render(errorBox(e)); }
}

async function start() {
  const s = await api("/api/session");
  if (!s.authenticated) return showLogin();
  state.user = s.user;
  document.getElementById("who").textContent = `${s.user.name}（${s.user.role_label}）`;
  document.getElementById("nav").hidden = false;
  if (!state.overview) { try { setBadge((await api("/api/overview")).dataset); } catch (_) { /* 表示は各画面で */ } }
  go(state.view);
}

document.getElementById("nav").addEventListener("click", (e) => {
  const b = e.target.closest("[data-view]");
  if (b) go(b.dataset.view);
});
document.getElementById("logout").addEventListener("click", async () => {
  await api("/api/logout", {}).catch(() => {});
  showLogin();
});
start();
