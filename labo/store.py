"""研究用ファイル保存（MVP）。DBへは書き込まない。

- 実行IDは「データ版・母集団・締切規則・定義版・コード版・オプション」のハッシュ。
  同じ入力なら同じIDになり、再実行は重複を生まない。
- 結果は人物単位で追記し、途中で取消・失敗しても再開時に完了済み人物を飛ばす。
- 古い実行結果は上書きしない（完了済みの実行は読み取り専用）。
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from . import cohorts as cohorts_mod
from .catalog import builtin_definitions, phase2_definitions
from .definitions import (
    RUNNABLE_STATUSES, SECOND_REVIEW_STATUSES, TRANSITIONS, FeatureDefinition, SpecError, validate_spec,
)
from .features import compute_person, make_context
from .model import Dataset
from .periods import CUTOFF_PRESETS
from .quality import Options

_ENGINE_FILES = ["model.py", "marks.py", "periods.py", "quality.py", "features.py",
                 "definitions.py", "catalog.py", "cohorts.py"]


def code_version() -> str:
    h = hashlib.sha256()
    base = Path(__file__).parent
    for f in _ENGINE_FILES:
        h.update(f.encode())
        h.update((base / f).read_bytes())
    return h.hexdigest()[:16]


def dataset_hash(ds: Dataset) -> str:
    h = hashlib.sha256()
    for pid in sorted(ds.athletes):
        h.update(json.dumps(asdict(ds.athletes[pid]), sort_keys=True, default=str).encode())
    for r in sorted(ds.results, key=lambda r: r.key.as_str()):
        h.update(json.dumps(asdict(r), sort_keys=True, default=str).encode())
    for link in ds.duplicate_links:
        h.update(json.dumps(asdict(link), sort_keys=True, default=str).encode())
    h.update(json.dumps(sorted(ds.competitions_national)).encode())
    for e in sorted(ds.ekiden_runs, key=lambda e: (e.key.as_str(), e.leg or 0)):  # 駅伝なしなら従来と同じ値
        h.update(json.dumps(asdict(e), sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, root: Path, require_second_reviewer: bool = True):
        self.root = Path(root)
        # 利用者定義を「計算可能／研究で採用」にする人は作成者と別人であること（チームでの相互確認）
        self.require_second_reviewer = require_second_reviewer
        (self.root / "definitions").mkdir(parents=True, exist_ok=True)
        (self.root / "runs").mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ---- 監査ログ（秘密情報は書かない） ----
    def audit(self, actor: str, action: str, detail: dict) -> None:
        line = json.dumps({"at": _now(), "actor": actor, "action": action, "detail": detail},
                          ensure_ascii=False)
        with self._lock, open(self.root / "audit.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ---- 定義 ----
    def _user_def_path(self, ref: str) -> Path:
        return self.root / "definitions" / (ref.replace("@", "__v") + ".json")

    def _review_path(self) -> Path:
        return self.root / "review_decisions.jsonl"

    def reviews(self) -> list[dict]:
        p = self._review_path()
        if not p.exists():
            return []
        return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]

    def definitions(self) -> list[FeatureDefinition]:
        defs = builtin_definitions() + phase2_definitions()
        for p in sorted((self.root / "definitions").glob("*.json")):
            defs.append(FeatureDefinition.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        # 状態は不変の定義本体ではなく判断履歴から導く
        by_ref = {d.ref: d for d in defs}
        for rv in self.reviews():
            if rv.get("kind") == "status" and rv["ref"] in by_ref:
                d = by_ref[rv["ref"]]
                d.review_status = rv["to"]
                d.review_history.append(rv)
                if rv["to"] == "廃止":
                    d.deprecation_reason = rv.get("comment", "")
        return defs

    def definition(self, ref: str) -> Optional[FeatureDefinition]:
        return next((d for d in self.definitions() if d.ref == ref), None)

    def create_definition(self, payload: dict, actor: str) -> FeatureDefinition:
        fid = str(payload.get("feature_id", "")).strip()
        if not fid or not all(c.isalnum() or c == "_" for c in fid) or len(fid) > 64:
            raise SpecError("feature_id は英数字と_のみ（64文字以内）")
        existing = [d for d in self.definitions() if d.feature_id == fid]
        version = max((d.version for d in existing), default=0) + 1
        known = {d.ref for d in self.definitions()}
        spec = validate_spec(payload.get("spec"), known)
        def s(k: str, limit: int = 2000) -> str:
            v = payload.get(k, "")
            if not isinstance(v, str):
                raise SpecError(f"{k} は文字列")
            return v[:limit]
        d = FeatureDefinition(
            feature_id=fid, version=version, display_name=s("display_name", 200) or fid,
            category=s("category", 100) or "利用者定義", hypothesis=s("hypothesis"),
            event=spec.get("event", "派生"), formula=s("formula"), window=s("window", 200),
            min_n=s("min_n", 100), unit=s("unit", 20), direction=s("direction", 50) or "不明",
            required_columns=[], missing_policy=s("missing_policy"), exclusion=s("exclusion"),
            time_constraint="観測締切以前の実施日のみ（エンジン共通）", source=s("source", 500),
            author=actor, created_at=_now(), review_status="提案", tests=[], spec=spec,
            model_input_allowed=bool(payload.get("model_input_allowed", True)),
            caution=s("caution"),
        )
        with self._lock:
            path = self._user_def_path(d.ref)
            if path.exists():
                raise SpecError("同じ版が既に存在します")
            path.write_text(json.dumps(d.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        self.audit(actor, "create_definition", {"ref": d.ref})
        return d

    def change_status(self, ref: str, to: str, comment: str, actor: str) -> dict:
        d = self.definition(ref)
        if d is None:
            raise SpecError("定義が見つかりません")
        if to not in TRANSITIONS.get(d.review_status, set()):
            raise SpecError(f"{d.review_status} から {to} へは変更できません")
        if (self.require_second_reviewer and to in SECOND_REVIEW_STATUSES and not d.builtin
                and d.author.split(":")[0] == actor.split(":")[0]):
            raise SpecError(f"「{to}」への変更は作成者以外のメンバーが行ってください（相互確認）")
        rv = {"kind": "status", "ref": ref, "from": d.review_status, "to": to,
              "comment": comment[:2000], "actor": actor, "at": _now()}
        with self._lock, open(self._review_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rv, ensure_ascii=False) + "\n")
        self.audit(actor, "change_status", {"ref": ref, "to": to})
        return rv

    def record_quality_decision(self, payload: dict, actor: str) -> dict:
        """品質判断の履歴（原本は修正しない）。"""
        rv = {"kind": "quality", "target": str(payload.get("target", ""))[:300],
              "decision": str(payload.get("decision", ""))[:100],
              "comment": str(payload.get("comment", ""))[:2000], "actor": actor, "at": _now()}
        with self._lock, open(self._review_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(rv, ensure_ascii=False) + "\n")
        return rv

    # ---- 実行 ----
    def plan(self, ds: Dataset, cohort_ref: str, cutoff_preset: str, refs: list[str],
             options: Options) -> dict:
        cohort = next((c for c in cohorts_mod.builtin_cohorts() if c.ref == cohort_ref), None)
        if cohort is None:
            raise SpecError("母集団が見つかりません")
        if cutoff_preset not in CUTOFF_PRESETS:
            raise SpecError("観測締切の設定が不正です")
        rule = CUTOFF_PRESETS[cutoff_preset]
        all_defs = {d.ref: d for d in self.definitions()}
        defs = []
        for ref in refs:
            d = all_defs.get(ref)
            if d is None:
                raise SpecError(f"定義が見つかりません: {ref}")
            if d.review_status not in RUNNABLE_STATUSES:
                raise SpecError(f"{ref} は「{d.review_status}」のため計算できません（未承認の定義は実行しない）")
            defs.append(d)
        for d in list(defs):  # 派生特徴量の参照先を自動で含める
            for ref in d.spec.get("inputs", []):
                if ref not in {x.ref for x in defs}:
                    if ref not in all_defs or all_defs[ref].review_status not in RUNNABLE_STATUSES:
                        raise SpecError(f"参照先 {ref} が計算可能ではありません")
                    defs.append(all_defs[ref])
        included, excluded = [], {}
        for pid in sorted(ds.athletes):
            ok, why = cohorts_mod.evaluate(cohort, ds, ds.athletes[pid], rule)
            if ok:
                included.append(pid)
            else:
                excluded.setdefault(why, []).append(pid)
        params = {
            "dataset_hash": dataset_hash(ds), "dataset_label": ds.label,
            "is_synthetic": ds.is_synthetic, "cohort": cohort.to_dict(),
            "cutoff_preset": cutoff_preset, "cutoff_label": rule.label,
            "cutoff_rule": asdict(rule),
            "features": [{"ref": d.ref, "spec_hash": d.spec_hash()} for d in defs],
            "code_version": code_version(), "options": asdict(options),
        }
        run_id = hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False)
                                .encode()).hexdigest()[:20]
        return {"run_id": run_id, "params": params, "included": included,
                "excluded": {k: v for k, v in sorted(excluded.items())},
                "feature_refs": [d.ref for d in defs]}

    def run_dir(self, run_id: str) -> Path:
        if not run_id.isalnum() or len(run_id) > 40:
            raise SpecError("不正な実行ID")
        return self.root / "runs" / run_id

    def run_meta(self, run_id: str) -> Optional[dict]:
        p = self.run_dir(run_id) / "meta.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _write_meta(self, run_id: str, meta: dict) -> None:
        p = self.run_dir(run_id) / "meta.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, p)

    def list_runs(self) -> list[dict]:
        out = []
        for p in (self.root / "runs").glob("*/meta.json"):
            m = json.loads(p.read_text(encoding="utf-8"))
            out.append({k: m[k] for k in ("run_id", "state", "created_at", "finished_at",
                                          "done", "total", "error") if k in m}
                       | {"cohort": m["params"]["cohort"]["ref"],
                          "cutoff": m["params"]["cutoff_label"],
                          "features": len(m["params"]["features"]),
                          "is_synthetic": m["params"]["is_synthetic"]})
        return sorted(out, key=lambda m: m["created_at"], reverse=True)

    def prepare_run(self, plan: dict, actor: str) -> dict:
        """実行を登録。既に同一IDがあればそれを返す（重複を作らない）。"""
        run_id = plan["run_id"]
        with self._lock:
            meta = self.run_meta(run_id)
            if meta is not None:
                return meta
            self.run_dir(run_id).mkdir(parents=True)
            meta = {"run_id": run_id, "state": "queued", "created_at": _now(),
                    "finished_at": None, "actor": actor, "params": plan["params"],
                    "feature_refs": plan["feature_refs"], "persons": plan["included"],
                    "excluded": plan["excluded"], "done": 0,
                    "total": len(plan["included"]), "error": None}
            self._write_meta(run_id, meta)
        self.audit(actor, "create_run", {"run_id": run_id})
        return meta

    def done_persons(self, run_id: str) -> set[str]:
        p = self.run_dir(run_id) / "values.jsonl"
        if not p.exists():
            return set()
        done = set()
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["person_id"])
        return done

    def execute(self, ds: Dataset, run_id: str,
                should_cancel: Callable[[], bool] = lambda: False) -> dict:
        meta = self.run_meta(run_id)
        if meta is None:
            raise SpecError("実行が見つかりません")
        if meta["state"] == "completed":
            return meta
        if meta["params"]["dataset_hash"] != dataset_hash(ds):
            meta["state"], meta["error"] = "failed", "データ版が登録時と異なるため再開できません"
            self._write_meta(run_id, meta)
            return meta
        if meta["params"]["code_version"] != code_version():
            meta["state"], meta["error"] = "failed", "コード版が登録時と異なるため再開できません"
            self._write_meta(run_id, meta)
            return meta
        all_defs = {d.ref: d for d in self.definitions()}
        defs = [all_defs[r] for r in meta["feature_refs"]]
        rule = CUTOFF_PRESETS[meta["params"]["cutoff_preset"]]
        options = Options(**meta["params"]["options"])
        done = self.done_persons(run_id)
        meta["state"], meta["error"] = "running", None
        self._write_meta(run_id, meta)
        try:
            with open(self.run_dir(run_id) / "values.jsonl", "a", encoding="utf-8") as f:
                for pid in meta["persons"]:
                    if pid in done:
                        continue
                    if should_cancel():
                        meta["state"] = "cancelled"
                        break
                    ath = ds.athletes[pid]
                    vals = compute_person(ds, ath, defs, rule, options)
                    ctx = make_context(ds, ath, rule, options)
                    f.write(json.dumps({
                        "person_id": pid, "name": ath.name,
                        "cutoff": ctx.cutoff.isoformat() if ctx.cutoff else None,
                        "values": [v.to_dict() for v in vals]}, ensure_ascii=False) + "\n")
                    f.flush()
                    done.add(pid)
                    meta["done"] = len(done)
                    self._write_meta(run_id, meta)
            if meta["state"] == "running":
                meta["state"], meta["finished_at"] = "completed", _now()
        except Exception as e:  # noqa: BLE001 - 失敗を記録して再開可能にする
            meta["state"], meta["error"] = "failed", f"{type(e).__name__}: {e}"
        self._write_meta(run_id, meta)
        return meta

    def values(self, run_id: str) -> list[dict]:
        p = self.run_dir(run_id) / "values.jsonl"
        if not p.exists():
            return []
        seen: dict[str, dict] = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                seen.setdefault(row["person_id"], row)  # 再開時の重複は最初の行を採用
        return [seen[k] for k in sorted(seen)]
