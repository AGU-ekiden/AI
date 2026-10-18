"""特徴量ラボ ローカルWebサーバー（標準ライブラリのみ）。

- 既定で 127.0.0.1 のみで待ち受け、トークンでログインしたセッションだけがAPIを使える。
- 計算は画面リクエストと切り離したバックグラウンドスレッドで実行し、取消・再開できる。
- 自由SQL・eval・任意コード実行の入口は存在しない。入力は検証済みの宣言的定義のみ。
"""
from __future__ import annotations

import csv
import hmac
import io
import json
import os
import re
import secrets
import threading
from collections import Counter
from datetime import date
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from . import synthetic
from .cohorts import builtin_cohorts
from .definitions import (
    ALLOWED_EVENTS, ALLOWED_OPS, PREVIEWABLE_STATUSES, STATUSES, TRANSITIONS, SpecError,
)
from .features import MISSING_LABELS, compute_person, make_context
from .model import Dataset
from .periods import CUTOFF_PRESETS
from .quality import REASON_LABELS, Options, select_runs
from .store import Store, code_version, dataset_hash

WEB = Path(__file__).parent / "web"
STATIC = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}
MAX_BODY = 64 * 1024
SESSION_COOKIE = "labo_session"


class App:
    def __init__(self, store: Store, dataset: Dataset, token: str):
        self.store = store
        self.ds = dataset
        self.token = token
        self.sessions: set[str] = set()
        self.cancel_flags: dict[str, threading.Event] = {}
        self.threads: dict[str, threading.Thread] = {}
        self.lock = threading.Lock()

    # ---- ジョブ ----
    def start_job(self, run_id: str) -> None:
        with self.lock:
            t = self.threads.get(run_id)
            if t and t.is_alive():
                return
            ev = threading.Event()
            self.cancel_flags[run_id] = ev
            t = threading.Thread(target=self.store.execute, args=(self.ds, run_id, ev.is_set),
                                 daemon=True)
            self.threads[run_id] = t
            t.start()

    # ---- 集計 ----
    def quality(self, cutoff_preset: str) -> dict:
        rule = CUTOFF_PRESETS[cutoff_preset]
        counts: Counter = Counter()
        rows = []
        people = {"hs_entry_year_unknown": [], "coverage_unknown": []}
        for pid in sorted(self.ds.athletes):
            ath = self.ds.athletes[pid]
            if ath.hs_entry_fiscal_year is None:
                people["hs_entry_year_unknown"].append(pid)
                continue
            if ath.coverage != "fetched":
                people["coverage_unknown"].append(pid)
            ctx = make_context(self.ds, ath, rule, Options())
            for ev in ALLOWED_EVENTS:
                runs, decisions = select_runs(self.ds, pid, ev, ctx.cutoff, ctx.hs)
                for d in decisions:
                    if d.decision == "used":
                        if any(r.key == d.key and r.duplicate_suspect for r in runs):
                            counts[("held", "duplicate_suspect")] += 1
                            rows.append(self._qrow(pid, ev, "held", "duplicate_suspect", d))
                        continue
                    counts[(d.decision, d.reason)] += 1
                    if d.decision == "held":
                        rows.append(self._qrow(pid, ev, d.decision, d.reason, d))
        labels = dict(REASON_LABELS, duplicate_suspect="同一本人結果の二重掲載疑い（統合根拠なし）")
        return {
            "cutoff_label": rule.label,
            "summary": [{"decision": k[0], "reason": k[1], "label": labels.get(k[1], k[1]),
                         "count": v} for k, v in sorted(counts.items(), key=lambda x: -x[1])],
            "held_rows": rows[:500], "held_total": len(rows),
            "people": people,
            "merged_duplicates": [{"canonical": l.canonical.as_str(), "duplicate": l.duplicate.as_str(),
                                   "evidence": l.evidence} for l in self.ds.duplicate_links],
            "decisions": [r for r in self.store.reviews() if r.get("kind") == "quality"][-200:],
        }

    @staticmethod
    def _qrow(pid, ev, decision, reason, d) -> dict:
        return {"person_id": pid, "event": ev, "decision": decision, "reason": reason,
                "label": REASON_LABELS.get(reason, "同一本人結果の二重掲載疑い（統合根拠なし）"),
                "key": d.key.as_str(), "detail": d.detail}

    def feature_missing_rates(self) -> dict:
        rates: dict[str, dict] = {}
        for run in self.store.list_runs():
            if run["state"] != "completed":
                continue
            vals = self.store.values(run["run_id"])
            tmp: dict[str, list] = {}
            for row in vals:
                for v in row["values"]:
                    tmp.setdefault(v["feature_ref"], []).append(v["value"] is None)
            for ref, nulls in tmp.items():
                if ref not in rates:  # 新しい実行を優先
                    rates[ref] = {"missing_rate": round(sum(nulls) / len(nulls), 3),
                                  "n": len(nulls), "run_id": run["run_id"]}
        return rates

    def overview(self) -> dict:
        defs = self.store.definitions()
        runs = self.store.list_runs()
        q = self.quality("g2_end")
        held = sum(x["count"] for x in q["summary"] if x["decision"] == "held")
        latest = next((r for r in runs if r["state"] == "completed"), None)
        changes = None
        completed = [r for r in runs if r["state"] == "completed"]
        if len(completed) >= 2:
            changes = self.compare(completed[1]["run_id"], completed[0]["run_id"], summary_only=True)
        return {
            "dataset": {"label": self.ds.label, "is_synthetic": self.ds.is_synthetic,
                        "hash": dataset_hash(self.ds), "athletes": len(self.ds.athletes),
                        "results": len(self.ds.results)},
            "code_version": code_version(),
            "cohorts": [c.to_dict() for c in builtin_cohorts()],
            "cutoffs": {k: v.label for k, v in CUTOFF_PRESETS.items()},
            "default_cutoff": "g2_end",
            "features": {"total": len(defs), "by_status": dict(Counter(d.review_status for d in defs))},
            "latest_run": latest, "runs": len(runs),
            "quality": {"held_rows": held, "entry_unknown": len(q["people"]["hs_entry_year_unknown"]),
                        "coverage_unknown": len(q["people"]["coverage_unknown"])},
            "changes": changes,
            "time_basis": "過去の競技日基準で再構成した分析（公表日が不明なため厳密な当時情報再現ではない）",
        }

    def compare(self, a: str, b: str, summary_only: bool = False) -> dict:
        ma, mb = self.store.run_meta(a), self.store.run_meta(b)
        if not ma or not mb:
            raise SpecError("実行が見つかりません")
        pa, pb = ma["params"], mb["params"]
        param_diff = {k: [pa.get(k), pb.get(k)] for k in
                      ("dataset_hash", "code_version", "cutoff_preset", "options")
                      if pa.get(k) != pb.get(k)}
        if pa["cohort"]["ref"] != pb["cohort"]["ref"]:
            param_diff["cohort"] = [pa["cohort"]["ref"], pb["cohort"]["ref"]]
        fa = {f["ref"]: f["spec_hash"] for f in pa["features"]}
        fb = {f["ref"]: f["spec_hash"] for f in pb["features"]}
        va = {r["person_id"]: {v["feature_ref"]: v for v in r["values"]} for r in self.store.values(a)}
        vb = {r["person_id"]: {v["feature_ref"]: v for v in r["values"]} for r in self.store.values(b)}
        # 同じfeature_idの版違いも比較対象にする
        def fid(ref): return ref.split("@")[0]
        pairs = []
        for ra in fa:
            for rb in fb:
                if fid(ra) == fid(rb):
                    pairs.append((ra, rb))
        per_feature = []
        changed_rows = []
        for ra, rb in pairs:
            changed = 0
            common = sorted(set(va) & set(vb))
            for pid in common:
                x, y = va[pid].get(ra), vb[pid].get(rb)
                if x is None or y is None:
                    continue
                if x["value"] != y["value"] or x["reason"] != y["reason"]:
                    changed += 1
                    if len(changed_rows) < 300:
                        changed_rows.append({"person_id": pid, "a_ref": ra, "b_ref": rb,
                                             "a": x["value"], "b": y["value"],
                                             "a_reason": x["reason"], "b_reason": y["reason"]})
            per_feature.append({"a_ref": ra, "b_ref": rb, "spec_changed": fa[ra] != fb[rb],
                                "persons_compared": len(common), "changed": changed})
        out = {"a": a, "b": b, "param_diff": param_diff, "per_feature": per_feature,
               "only_in_a": sorted(set(map(fid, fa)) - set(map(fid, fb))),
               "only_in_b": sorted(set(map(fid, fb)) - set(map(fid, fa)))}
        if not summary_only:
            out["changed_rows"] = changed_rows
        return out

    def person(self, pid: str, cutoff_preset: str) -> dict:
        ath = self.ds.athletes.get(pid)
        if ath is None:
            raise SpecError("人物が見つかりません")
        rule = CUTOFF_PRESETS[cutoff_preset]
        ctx = make_context(self.ds, ath, rule, Options())
        decisions = {}
        if ctx.cutoff:
            for ev in ALLOWED_EVENTS:
                for d in select_runs(self.ds, pid, ev, ctx.cutoff, ctx.hs)[1]:
                    decisions[d.key.as_str()] = {"decision": d.decision, "reason": d.reason,
                                                 "label": REASON_LABELS.get(d.reason, d.reason)}
        rows = []
        for r in sorted(self.ds.results_of(pid),
                        key=lambda r: (r.competition_start or r.performed_date or date.min)):
            k = r.key.as_str()
            rows.append({
                "key": k, "event": r.event_code, "group": r.event_group,
                "competition": r.competition_name, "competition_id": r.competition_id,
                "competition_start": _iso(r.competition_start), "competition_end": _iso(r.competition_end),
                "performed_date": _iso(r.performed_date), "status": r.status, "mark_raw": r.mark_raw,
                "seconds": r.seconds, "identity": r.identity, "row_checked": r.row_checked,
                "capture_validation_status": r.capture_validation_status,
                "duplicate_suspect": r.duplicate_suspect, "source_ref": r.source_ref,
                "decision": decisions.get(k, {"decision": "not_evaluated",
                                              "reason": "別種目または個人走以外",
                                              "label": "別種目または個人走以外"}),
            })
        return {"athlete": {"person_id": ath.person_id, "name": ath.name,
                            "hs_entry_fiscal_year": ath.hs_entry_fiscal_year,
                            "hs_entry_evidence": ath.hs_entry_evidence,
                            "hs_entry_confidence": ath.hs_entry_confidence,
                            "coverage": ath.coverage, "is_synthetic": ath.is_synthetic},
                "cutoff": _iso(ctx.cutoff), "results": rows}

    def preview(self, ref: str) -> dict:
        d = self.store.definition(ref)
        if d is None:
            raise SpecError("定義が見つかりません")
        if d.review_status not in PREVIEWABLE_STATUSES:
            raise SpecError(f"「{d.review_status}」の定義はプレビューできません（利用者の定義確認後に可能）")
        all_defs = {x.ref: x for x in self.store.definitions()}
        defs = [d] + [all_defs[r] for r in d.spec.get("inputs", []) if r in all_defs]
        sample = synthetic.generate(seed=7, n_athletes=8)  # 常に小さな合成データ
        out = []
        for pid in sorted(sample.athletes)[:8]:
            v = compute_person(sample, sample.athletes[pid], defs, CUTOFF_PRESETS["g2_end"])[0]
            out.append({"person_id": pid, "name": sample.athletes[pid].name, **v.to_dict()})
        return {"ref": ref, "dataset_label": sample.label, "rows": out}


def _iso(d) -> Optional[str]:
    return d.isoformat() if d else None


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FeatureLab/0.1"

        def log_message(self, fmt, *args):  # クエリ文字列・Cookieをログに出さない
            pass

        # ---- 共通 ----
        def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self'; script-src 'self'; "
                             "img-src 'self' data:; frame-ancestors 'none'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj, extra=None):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode(), "application/json", extra)

        def _sid(self) -> Optional[str]:
            c = cookies.SimpleCookie()
            try:
                c.load(self.headers.get("Cookie", ""))
            except cookies.CookieError:
                return None
            m = c.get(SESSION_COOKIE)
            return m.value if m else None

        def _authed(self) -> bool:
            sid = self._sid()
            return sid is not None and sid in app.sessions

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                raise SpecError("リクエストが大きすぎます")
            raw = self.rfile.read(n) if n else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError as e:
                raise SpecError("JSONが不正です") from e
            if not isinstance(data, dict):
                raise SpecError("JSONオブジェクトが必要です")
            return data

        # ---- GET ----
        def do_GET(self):
            u = urlparse(self.path)
            if u.path in STATIC:
                name, ctype = STATIC[u.path]
                return self._send(200, (WEB / name).read_bytes(), ctype)
            if not u.path.startswith("/api/"):
                return self._json(404, {"error": "not found"})
            if u.path == "/api/session":
                return self._json(200, {"authenticated": self._authed()})
            if not self._authed():
                return self._json(401, {"error": "ログインが必要です"})
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            cutoff = q.get("cutoff", "g2_end")
            if cutoff not in CUTOFF_PRESETS:
                return self._json(400, {"error": "観測締切の設定が不正です"})
            try:
                return self._route_get(u.path, q, cutoff)
            except SpecError as e:
                return self._json(400, {"error": str(e)})

        def _route_get(self, path: str, q: dict, cutoff: str):
            if path == "/api/overview":
                return self._json(200, app.overview())
            if path == "/api/features":
                rates = app.feature_missing_rates()
                return self._json(200, {
                    "statuses": STATUSES, "transitions": {k: sorted(v) for k, v in TRANSITIONS.items()},
                    "allowed_ops": sorted(ALLOWED_OPS), "allowed_events": ALLOWED_EVENTS,
                    "missing_labels": MISSING_LABELS,
                    "features": [d.to_dict() | {"missing": rates.get(d.ref)}
                                 for d in app.store.definitions()]})
            if path == "/api/quality":
                return self._json(200, app.quality(cutoff))
            if path == "/api/runs":
                return self._json(200, {"runs": app.store.list_runs()})
            m = re.fullmatch(r"/api/runs/([A-Za-z0-9]{1,40})", path)
            if m:
                meta = app.store.run_meta(m.group(1))
                return self._json(200, meta) if meta else self._json(404, {"error": "なし"})
            m = re.fullmatch(r"/api/runs/([A-Za-z0-9]{1,40})/values", path)
            if m:
                meta = app.store.run_meta(m.group(1))
                if not meta:
                    return self._json(404, {"error": "なし"})
                return self._json(200, {"meta": meta, "rows": app.store.values(m.group(1)),
                                        "missing_labels": MISSING_LABELS})
            m = re.fullmatch(r"/api/runs/([A-Za-z0-9]{1,40})/export\.csv", path)
            if m:
                return self._csv(m.group(1))
            if path == "/api/compare":
                return self._json(200, app.compare(q.get("a", ""), q.get("b", "")))
            m = re.fullmatch(r"/api/persons/([A-Za-z0-9_\-]{1,64})", path)
            if m:
                return self._json(200, app.person(m.group(1), cutoff))
            return self._json(404, {"error": "not found"})

        def _csv(self, run_id: str):
            meta = app.store.run_meta(run_id)
            if not meta:
                return self._json(404, {"error": "なし"})
            buf = io.StringIO()
            w = csv.writer(buf)
            if meta["params"]["is_synthetic"]:
                w.writerow(["# 合成データ（架空）。実在選手の値ではありません"])
            w.writerow(["# run_id", run_id, "dataset_hash", meta["params"]["dataset_hash"],
                        "code_version", meta["params"]["code_version"], "cutoff",
                        meta["params"]["cutoff_label"]])
            w.writerow(["person_id", "name", "cutoff", "feature_ref", "value", "unit", "reason",
                        "evidence_count", "period_start", "period_end", "evidence", "note"])
            for row in app.store.values(run_id):
                for v in row["values"]:
                    w.writerow([row["person_id"], row["name"], row["cutoff"], v["feature_ref"],
                                "" if v["value"] is None else v["value"], v["unit"], v["reason"],
                                v["evidence_count"], v["period_start"], v["period_end"],
                                " ".join(v["evidence"]), v["note"]])
            body = ("﻿" + buf.getvalue()).encode("utf-8")
            return self._send(200, body, "text/csv",
                              {"Content-Disposition": f'attachment; filename="features_{run_id}.csv"'})

        # ---- POST ----
        def do_POST(self):
            u = urlparse(self.path)
            if self.headers.get("X-Labo-Request") != "1":  # CSRF対策（SameSite=Strictと併用）
                return self._json(403, {"error": "forbidden"})
            try:
                body = self._body()
                if u.path == "/api/login":
                    tok = body.get("token", "")
                    if isinstance(tok, str) and hmac.compare_digest(tok.encode(), app.token.encode()):
                        sid = secrets.token_urlsafe(32)
                        app.sessions.add(sid)
                        return self._json(200, {"ok": True}, {
                            "Set-Cookie": f"{SESSION_COOKIE}={sid}; HttpOnly; SameSite=Strict; Path=/"})
                    return self._json(401, {"error": "トークンが違います"})
                if not self._authed():
                    return self._json(401, {"error": "ログインが必要です"})
                return self._route_post(u.path, body)
            except SpecError as e:
                return self._json(400, {"error": str(e)})

        def _route_post(self, path: str, body: dict):
            actor = "local-user"
            if path == "/api/logout":
                app.sessions.discard(self._sid())
                return self._json(200, {"ok": True}, {
                    "Set-Cookie": f"{SESSION_COOKIE}=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/"})
            if path == "/api/features":
                d = app.store.create_definition(body, actor)
                return self._json(201, d.to_dict())
            if path == "/api/features/status":
                return self._json(200, app.store.change_status(
                    str(body.get("ref", "")), str(body.get("to", "")),
                    str(body.get("comment", "")), actor))
            if path == "/api/features/preview":
                return self._json(200, app.preview(str(body.get("ref", ""))))
            if path in ("/api/runs/plan", "/api/runs"):
                refs = body.get("features")
                if not isinstance(refs, list) or not refs or len(refs) > 200 or \
                        not all(isinstance(r, str) for r in refs):
                    raise SpecError("特徴量を1つ以上選んでください")
                cutoff = str(body.get("cutoff", "g2_end"))
                options = Options(require_published_by_cutoff=bool(body.get("strict_publication")))
                plan = app.store.plan(app.ds, str(body.get("cohort", "")), cutoff, refs, options)
                if path == "/api/runs/plan":
                    return self._json(200, plan | {"excluded_labels": MISSING_LABELS | {
                        "no_national_by_cutoff": "締切までに全国大会結果が確認できない",
                        "hs_entry_fy_out_of_range": "入学年度が範囲外"}})
                meta = app.store.prepare_run(plan, actor)
                if meta["state"] != "completed":
                    app.start_job(meta["run_id"])
                return self._json(202, {"run_id": meta["run_id"], "state": meta["state"],
                                         "reused": meta["state"] == "completed"})
            m = re.fullmatch(r"/api/runs/([A-Za-z0-9]{1,40})/(cancel|resume)", path)
            if m:
                rid, action = m.groups()
                if not app.store.run_meta(rid):
                    return self._json(404, {"error": "なし"})
                if action == "cancel":
                    ev = app.cancel_flags.get(rid)
                    if ev:
                        ev.set()
                else:
                    app.start_job(rid)
                app.store.audit(actor, f"run_{action}", {"run_id": rid})
                return self._json(202, {"ok": True})
            if path == "/api/quality/decision":
                return self._json(201, app.store.record_quality_decision(body, actor))
            return self._json(404, {"error": "not found"})

    return Handler


def load_token(data_dir: Path) -> tuple[str, Optional[Path]]:
    tok = os.environ.get("LABO_TOKEN")
    if tok:
        return tok, None
    p = data_dir / ".token"
    if p.exists():
        return p.read_text().strip(), p
    tok = secrets.token_urlsafe(24)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(tok)
    return tok, p


def build_server(host: str, port: int, data_dir: Path, token: Optional[str] = None):
    store = Store(data_dir)
    if token is None:
        token, _ = load_token(data_dir)
    app = App(store, synthetic.generate(), token)
    return ThreadingHTTPServer((host, port), make_handler(app)), app


def main() -> None:
    host = os.environ.get("LABO_HOST", "127.0.0.1")
    port = int(os.environ.get("LABO_PORT", "8765"))
    data_dir = Path(os.environ.get("LABO_DATA_DIR", "./data"))
    _, token_path = load_token(data_dir)
    srv, _ = build_server(host, port, data_dir)
    print(f"特徴量ラボ（合成データ）: http://{host}:{port}/")
    if token_path:
        print(f"ログイントークンは {token_path} に保存されています（権限600）。")
    else:
        print("ログイントークンは環境変数 LABO_TOKEN の値です。")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print("警告: ローカル以外で待ち受けています。公開しないでください。")
    srv.serve_forever()


if __name__ == "__main__":
    main()
