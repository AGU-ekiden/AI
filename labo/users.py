"""チーム利用者の管理（ローカルファイル）。

- トークンは発行時に一度だけ表示し、保存はソルト付きPBKDF2ハッシュのみ。
- 役割：admin（管理）/ editor（定義作成・判断記録・計算実行）/ viewer（閲覧のみ）。
- 利用者の追加・無効化はサーバー端末上のCLIのみ（Web画面からは不可）。
  例：python3 -m labo.users add --name 山田 --role editor
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROLES = ("admin", "editor", "viewer")
ROLE_LABELS = {"admin": "管理者", "editor": "研究担当", "viewer": "閲覧のみ"}
_ITER = 200_000


def _hash(token: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", token.encode(), salt, _ITER).hex()


class UserStore:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "users.json"
        self._lock = threading.Lock()

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, users: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(users, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        return [{k: u[k] for k in ("user_id", "name", "role", "disabled", "created_at")}
                for u in self._load()]

    def add(self, name: str, role: str) -> tuple[dict, str]:
        """利用者を追加し、(公開情報, トークン) を返す。トークンはこの時だけ得られる。"""
        if role not in ROLES:
            raise ValueError(f"role は {ROLES} のいずれか")
        name = name.strip()
        if not name or len(name) > 50:
            raise ValueError("name は1〜50文字")
        with self._lock:
            users = self._load()
            uid = f"u{len(users) + 1:03d}"
            token = f"{uid}.{secrets.token_urlsafe(24)}"
            salt = secrets.token_bytes(16)
            user = {"user_id": uid, "name": name, "role": role, "disabled": False,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "salt": salt.hex(), "token_hash": _hash(token, salt)}
            users.append(user)
            self._save(users)
        return {k: user[k] for k in ("user_id", "name", "role")}, token

    def set_disabled(self, user_id: str, disabled: bool) -> None:
        with self._lock:
            users = self._load()
            for u in users:
                if u["user_id"] == user_id:
                    u["disabled"] = disabled
                    self._save(users)
                    return
        raise ValueError("利用者が見つかりません")

    def authenticate(self, token: str) -> Optional[dict]:
        if not isinstance(token, str) or "." not in token or len(token) > 200:
            return None
        uid = token.split(".", 1)[0]
        for u in self._load():
            if u["user_id"] == uid and not u["disabled"]:
                if hmac.compare_digest(_hash(token, bytes.fromhex(u["salt"])), u["token_hash"]):
                    return {k: u[k] for k in ("user_id", "name", "role")}
        return None

    def get(self, user_id: str) -> Optional[dict]:
        """有効な利用者の現在の情報（役割変更・無効化を即時反映するため毎回読む）。"""
        for u in self._load():
            if u["user_id"] == user_id and not u["disabled"]:
                return {k: u[k] for k in ("user_id", "name", "role")}
        return None


def main() -> None:  # pragma: no cover - CLI
    ap = argparse.ArgumentParser(description="特徴量ラボの利用者管理")
    ap.add_argument("--data-dir", default=os.environ.get("LABO_DATA_DIR", "./data"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("--name", required=True)
    a.add_argument("--role", choices=ROLES, default="viewer")
    sub.add_parser("list")
    d = sub.add_parser("disable")
    d.add_argument("user_id")
    e = sub.add_parser("enable")
    e.add_argument("user_id")
    args = ap.parse_args()
    us = UserStore(Path(args.data_dir))
    if args.cmd == "add":
        info, token = us.add(args.name, args.role)
        print(f"追加しました: {info['user_id']} {info['name']}（{ROLE_LABELS[info['role']]}）")
        print("ログイントークン（この一度だけ表示。本人へ安全な方法で渡してください）:")
        print(token)
    elif args.cmd == "list":
        for u in us.list():
            print(u["user_id"], u["name"], ROLE_LABELS[u["role"]], "無効" if u["disabled"] else "有効")
    else:
        us.set_disabled(args.user_id, args.cmd == "disable")
        print("更新しました")


if __name__ == "__main__":
    main()
