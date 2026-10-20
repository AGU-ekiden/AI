import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from labo import synthetic
from labo.definitions import SpecError
from labo.quality import Options
from labo.server import WEB, build_server
from labo.store import Store
from labo.users import UserStore

ALL = None


def _refs(store):
    return [d.ref for d in store.definitions() if d.builtin and d.review_status in ("計算可能", "研究で採用")]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name))
        self.ds = synthetic.generate()

    def tearDown(self):
        self.tmp.cleanup()

    def _plan(self, refs=None, cohort="all_with_entry_year@1"):
        return self.store.plan(self.ds, cohort, "g2_end", refs or _refs(self.store), Options())

    def test_synthetic_is_deterministic_and_labelled(self):
        self.assertEqual(synthetic.generate().results, self.ds.results)
        self.assertTrue(self.ds.is_synthetic)
        self.assertTrue(all(a.is_synthetic for a in self.ds.athletes.values()))

    def test_rerun_and_resume_do_not_duplicate(self):
        plan = self._plan()
        self.store.prepare_run(plan, "t")
        calls = [0]

        def cancel_after_5():
            calls[0] += 1
            return calls[0] > 5
        meta = self.store.execute(self.ds, plan["run_id"], cancel_after_5)
        self.assertEqual(meta["state"], "cancelled")
        self.assertEqual(meta["done"], 5)
        meta = self.store.execute(self.ds, plan["run_id"])
        self.assertEqual(meta["state"], "completed")
        lines = (self.store.run_dir(plan["run_id"]) / "values.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), len(plan["included"]))
        again = self._plan()
        self.assertEqual(again["run_id"], plan["run_id"])
        self.assertEqual(self.store.prepare_run(again, "t")["state"], "completed")
        self.assertEqual(len(self.store.list_runs()), 1)

    def test_unapproved_definition_is_not_executed(self):
        d = self.store.create_definition({"feature_id": "best_1500_s", "spec": {
            "op": "min", "event": "1500m", "window": {"kind": "hs"}}}, "t")
        self.assertEqual(d.review_status, "提案")
        with self.assertRaises(SpecError):
            self._plan([d.ref])
        with self.assertRaises(SpecError):
            self.store.change_status(d.ref, "計算可能", "飛び級", "t")
        for to in ("定義確認", "テスト済み"):
            self.store.change_status(d.ref, to, "確認", "t")
        self.store.change_status(d.ref, "計算可能", "別メンバー確認", "u2:other")
        self.assertEqual(self._plan([d.ref])["feature_refs"], [d.ref])

    def test_new_version_does_not_change_past_run(self):
        spec = {"op": "min", "event": "5000m", "window": {"kind": "recent_days", "days": 365}}
        d1 = self.store.create_definition({"feature_id": "my_best", "spec": spec}, "t")
        for to in ("定義確認", "テスト済み"):
            self.store.change_status(d1.ref, to, "ok", "t")
        self.store.change_status(d1.ref, "計算可能", "ok", "u2:other")
        p1 = self._plan([d1.ref])
        self.store.prepare_run(p1, "t")
        self.store.execute(self.ds, p1["run_id"])
        before = self.store.values(p1["run_id"])
        d2 = self.store.create_definition({"feature_id": "my_best", "spec": dict(
            spec, window={"kind": "recent_days", "days": 180})}, "t")
        self.assertEqual(d2.version, 2)
        self.store.change_status(d1.ref, "廃止", "v2へ移行", "t")
        self.assertEqual(self.store.values(p1["run_id"]), before)
        self.assertEqual(self.store.definition(d1.ref).spec, spec)

    def test_cohort_plan_excludes_future_information(self):
        plan = self.store.plan(self.ds, "national_by_cutoff@1", "g2_end", _refs(self.store), Options())
        self.assertNotIn("SYN9005", plan["included"])
        self.assertIn("SYN9005", plan["excluded"]["no_national_by_cutoff"])
        self.assertIn("SYN9001", plan["excluded"]["hs_entry_year_unknown"])

    def test_outputs_have_no_prediction_or_ranking(self):
        plan = self._plan()
        self.store.prepare_run(plan, "t")
        self.store.execute(self.ds, plan["run_id"])
        text = (self.store.run_dir(plan["run_id"]) / "values.jsonl").read_text()
        text += json.dumps(self.store.run_meta(plan["run_id"]), ensure_ascii=False)
        for word in ("probability", "rank", "score", "成功確率", "順位", "実証済"):
            self.assertNotIn(word, text)
        self.assertTrue(self.store.run_meta(plan["run_id"])["params"]["is_synthetic"])


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        users = UserStore(Path(cls.tmp.name))
        cls.admin, cls.token = users.add("管理者", "admin")
        cls.editor2, cls.token2 = users.add("研究担当B", "editor")
        cls.viewer, cls.vtoken = users.add("閲覧者", "viewer")
        cls.srv, cls.app = build_server("127.0.0.1", 0, Path(cls.tmp.name))
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.tmp.cleanup()

    def req(self, path, body=None, cookie=None, csrf=True):
        headers = {"Content-Type": "application/json"}
        if csrf:
            headers["X-Labo-Request"] = "1"
        if cookie:
            headers["Cookie"] = cookie
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.headers, e.read()

    def login(self, token=None):
        code, headers, _ = self.req("/api/login", {"token": token or self.token})
        self.assertEqual(code, 200)
        return headers["Set-Cookie"].split(";")[0]

    def test_unauthenticated_and_forged_sessions_rejected(self):
        self.assertEqual(self.req("/api/overview")[0], 401)
        self.assertEqual(self.req("/api/overview", cookie="labo_session=forged")[0], 401)
        self.assertEqual(self.req("/api/login", {"token": "wrong"})[0], 401)
        self.assertEqual(self.req("/api/runs", {"features": ["x"]})[0], 401)
        self.assertEqual(self.req("/api/login", {"token": self.token + "x"})[0], 401)

    def test_roles_and_disabled_users(self):
        vc = self.login(self.vtoken)
        self.assertEqual(self.req("/api/overview", cookie=vc)[0], 200)
        code, _, _ = self.req("/api/features", {"feature_id": "v", "spec": {
            "op": "min", "event": "5000m", "window": {"kind": "hs"}}}, vc)
        self.assertEqual(code, 403)
        me = json.loads(self.req("/api/session", cookie=vc)[2])["user"]
        self.assertEqual((me["role"], me["can_write"]), ("viewer", False))
        self.app.users.set_disabled(self.viewer["user_id"], True)
        try:
            self.assertEqual(self.req("/api/overview", cookie=vc)[0], 401)
            self.assertEqual(self.req("/api/login", {"token": self.vtoken})[0], 401)
        finally:
            self.app.users.set_disabled(self.viewer["user_id"], False)

    def test_second_member_must_approve_user_definitions(self):
        a, b = self.login(), self.login(self.token2)
        code, _, body = self.req("/api/features", {"feature_id": "peer_check", "spec": {
            "op": "min", "event": "1500m", "window": {"kind": "hs"}}}, a)
        self.assertEqual(code, 201)
        ref = json.loads(body)["ref"]
        self.assertIn(self.admin["user_id"], json.loads(body)["author"])
        for to in ("定義確認", "テスト済み"):
            self.assertEqual(self.req("/api/features/status", {"ref": ref, "to": to, "comment": "c"}, a)[0], 200)
        self.assertEqual(self.req("/api/features/status", {"ref": ref, "to": "計算可能", "comment": "c"}, a)[0], 400)
        self.assertEqual(self.req("/api/features/status", {"ref": ref, "to": "計算可能", "comment": "c"}, b)[0], 200)
        audit = (Path(self.tmp.name) / "audit.jsonl").read_text()
        self.assertIn("研究担当B", audit)
        for t in (self.token, self.token2, self.vtoken):
            self.assertNotIn(t, audit)

    def test_csrf_header_required(self):
        cookie = self.login()
        self.assertEqual(self.req("/api/features", {"feature_id": "x"}, cookie, csrf=False)[0], 403)

    def test_static_assets_do_not_contain_secrets(self):
        for path in ("/", "/app.js", "/style.css"):
            code, _, body = self.req(path)
            self.assertEqual(code, 200)
            self.assertNotIn(self.token.encode(), body)
        self.assertNotIn(self.token, (Path(self.tmp.name) / "users.json").read_text())
        for f in WEB.iterdir():
            self.assertNotIn(b"service_role", f.read_bytes())
        self.assertEqual(self.req("/../data/.token")[0], 404)

    def test_update_requires_supervised_launcher(self):
        cookie = self.login()
        code, _, body = self.req("/api/admin/update", {}, cookie)
        self.assertEqual(code, 400)  # start_lab から起動していなければ画面から更新できない
        self.assertIn("start_lab", json.loads(body)["error"])

    def test_sessions_survive_restart(self):
        from labo.server import SessionStore
        with tempfile.TemporaryDirectory() as tmp:
            s1 = SessionStore(Path(tmp) / "sessions.json")
            s1["sid-abc"] = ("u001", time.time() + 60)
            s2 = SessionStore(Path(tmp) / "sessions.json")
            self.assertEqual(s2.get("sid-abc")[0], "u001")
            self.assertNotIn("sid-abc", (Path(tmp) / "sessions.json").read_text())  # ハッシュだけ保存
            s2.pop("sid-abc")
            self.assertIsNone(SessionStore(Path(tmp) / "sessions.json").get("sid-abc"))

    def test_research_view(self):
        cookie = self.login()
        code, _, body = self.req("/api/research", cookie=cookie)
        self.assertEqual(code, 200)
        d = json.loads(body)
        self.assertFalse(d["can_run"])          # 合成データでは再計算・再評価できない
        self.assertIsNone(d["tables"])           # 集計ファイルがまだない
        self.assertTrue(any(f["status"] == "テスト済み" for f in d["features"]))
        code, _, body = self.req("/api/research/run", {}, cookie)
        self.assertEqual(code, 400)
        code, _, body = self.req("/api/candidates?scope=pending", cookie=cookie)
        self.assertEqual(code, 200)
        self.assertFalse(json.loads(body)["available"])   # 点数はまだ作られていない

    def test_end_to_end_run_and_export(self):
        cookie = self.login()
        code, _, body = self.req("/api/overview", cookie=cookie)
        self.assertEqual(code, 200)
        self.assertTrue(json.loads(body)["dataset"]["is_synthetic"])
        refs = [f["ref"] for f in json.loads(self.req("/api/features", cookie=cookie)[2])["features"]
                if f["review_status"] == "計算可能"]
        payload = {"cohort": "all_with_entry_year@1", "cutoff": "g2_end", "features": refs}
        code, _, body = self.req("/api/runs", payload, cookie)
        self.assertEqual(code, 202)
        run_id = json.loads(body)["run_id"]
        self.app.threads[run_id].join(30)
        meta = json.loads(self.req(f"/api/runs/{run_id}", cookie=cookie)[2])
        self.assertEqual(meta["state"], "completed")
        code, headers, csv_body = self.req(f"/api/runs/{run_id}/export.csv", cookie=cookie)
        self.assertEqual(code, 200)
        self.assertIn("合成データ", csv_body.decode("utf-8-sig").splitlines()[0])
        code, _, body = self.req("/api/persons/SYN9004?cutoff=g2_end", cookie=cookie)
        reasons = {r["decision"]["reason"] for r in json.loads(body)["results"]}
        self.assertIn("date_spans_cutoff", reasons)
        self.assertEqual(self.req("/api/quality", cookie=cookie)[0], 200)
        self.assertEqual(self.req(f"/api/compare?a={run_id}&b={run_id}", cookie=cookie)[0], 200)

    def test_malicious_definition_input_rejected(self):
        cookie = self.login()
        code, _, body = self.req("/api/features", {
            "feature_id": "x'); DROP TABLE rkm.records;--",
            "spec": {"op": "min", "event": "5000m", "window": {"kind": "hs"}}}, cookie)
        self.assertEqual(code, 400)
        code, _, _ = self.req("/api/features", {
            "feature_id": "evil", "spec": {"op": "eval", "code": "__import__('os')"}}, cookie)
        self.assertEqual(code, 400)


if __name__ == "__main__":
    unittest.main()
