"""正規化後の入力モデル。

原本（rkm）の値は変更せず、アダプターがこの形へ読み替える。
欠損・状態は「値がない」で潰さず、理由コードとして保持する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

# 結果の状態。観測値・空欄・未取得・取得失敗・DNS/DNF/DSQ・形式不明を区別する。
STATUS_OK = "ok"
STATUS_DNS = "DNS"
STATUS_DNF = "DNF"
STATUS_DSQ = "DSQ"
STATUS_BLANK = "blank"            # 記録欄が空欄
STATUS_NOT_FETCHED = "not_fetched"  # 未取得
STATUS_FETCH_FAILED = "fetch_failed"  # 取得失敗
STATUS_FORMAT_UNKNOWN = "format_unknown"  # 表記を解釈できない
STATUS_OUT_OF_SCOPE = "out_of_scope"  # 対象外
STATUS_NO_MARK = "no_mark"         # 記録なし（rkm の NM・NI・DNE。利用者決定 2026-10-19）
STATUS_UNCONFIRMED = "status_unconfirmed"  # 意味が未確認の状態（例：「競走中止」）
RESULT_STATUSES = {
    STATUS_OK, STATUS_DNS, STATUS_DNF, STATUS_DSQ, STATUS_BLANK,
    STATUS_NOT_FETCHED, STATUS_FETCH_FAILED, STATUS_FORMAT_UNKNOWN, STATUS_OUT_OF_SCOPE,
    STATUS_NO_MARK, STATUS_UNCONFIRMED,
}

# 本人照合
IDENTITY_CONFIRMED = "confirmed"
IDENTITY_UNCONFIRMED = "unconfirmed"

# 個人走以外の親レコード（チーム合計の可能性）
NON_INDIVIDUAL_GROUPS = {"ekiden", "team", "relay"}

# 人物単位の取得状態。「取得済み」は「全結果が揃った」ことを意味しない。
COVERAGE_FETCHED = "fetched"
COVERAGE_UNKNOWN = "unknown"
COVERAGE_FETCH_FAILED = "fetch_failed"


@dataclass(frozen=True)
class ResultKey:
    """結果の一意キー。record_id 単独では一意でない（同じレースが複数選手に現れる）。"""
    person_id: str
    profile_id: str
    record_id: str

    def as_str(self) -> str:
        return f"{self.person_id}/{self.profile_id}/{self.record_id}"


@dataclass(frozen=True)
class Result:
    key: ResultKey
    event_code: Optional[str]          # "5000m" "3000mSC" など。不明は None
    event_group: Optional[str]         # "individual" / "ekiden" / "team" / "relay" / None
    competition_id: Optional[str]
    competition_name: str
    competition_start: Optional[date]  # 大会初日（rkm.records.date が初日の場合がある）
    competition_end: Optional[date]    # 大会最終日（不明は None）
    performed_date: Optional[date]     # その種目を実際に走った日（確認済みのみ）
    status: str
    mark_raw: str
    seconds: Optional[float]           # 内部は秒。原表記は mark_raw に残す
    precision_digits: Optional[int]    # 小数点以下桁数（計時精度）
    timing: Optional[str]              # "electric" / "hand" / None
    identity: str = IDENTITY_UNCONFIRMED
    round_order: Optional[int] = None  # 根拠のあるラウンド順（予選=1, 決勝=2 など）
    start_time: Optional[str] = None   # 確認された競技開始時刻 "HH:MM"
    first_available_at: Optional[date] = None  # 公表日（不明が普通）
    captured_at: Optional[date] = None         # 実際の取得日
    capture_validation_status: Optional[str] = None  # raw_only 等。除外理由には使わない
    row_checked: bool = False          # 行単位の数値妥当性・日付・出典の確認済みか
    duplicate_suspect: bool = False    # 同一本人結果の二重掲載疑い（未解決）
    source_ref: str = ""               # 原本への参照（source_sha256 等）
    round_raw: str = ""                # ラウンドの原文（同一レースの二重表示の判定に使う）
    # rkm.records.date は「分からない場合は大会初日」（column_docs）。初日と同じ日付の行は初日の可能性がある
    date_maybe_first_day: bool = False


@dataclass(frozen=True)
class Athlete:
    person_id: str
    name: str
    hs_entry_fiscal_year: Optional[int]   # 高校入学年度（4月始まり）
    hs_entry_evidence: str = ""           # 根拠
    hs_entry_confidence: str = "unknown"  # "confirmed" / "inferred" / "unknown"
    coverage: str = COVERAGE_UNKNOWN
    is_synthetic: bool = False


@dataclass(frozen=True)
class DuplicateLink:
    """同一本人結果の二重掲載を証拠に基づき統合する対応表の1行。"""
    canonical: ResultKey
    duplicate: ResultKey
    evidence: str
    decided_by: str


@dataclass(frozen=True)
class EkidenLeg:
    key: ResultKey
    leg: int
    is_self: Optional[bool]
    leg_value: Optional[float]     # 区間タイム（秒）
    pass_value: Optional[float]    # 通過の累積時間（秒）。個人区間タイムではない
    leg_distance_m: Optional[float] = None  # 年度別区間距離（確認済みのみ）


@dataclass
class Dataset:
    athletes: dict[str, Athlete]
    results: list[Result]
    duplicate_links: list[DuplicateLink] = field(default_factory=list)
    competitions_national: set[str] = field(default_factory=set)  # 全国大会扱いの competition_id
    is_synthetic: bool = False
    label: str = ""

    def results_of(self, person_id: str) -> list[Result]:
        return [r for r in self.results if r.key.person_id == person_id]
