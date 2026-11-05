"""재건축 알림이 시제품의 핵심 로직: 정비사업 단계 판단, 주소 매칭, 안내 규칙, 우선순위."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"
ZONES_CSV = DATA / "michuhol_redevelopment.csv"
MEMBERS_CSV = DATA / "members_synthetic.csv"

STAGES = ["예정", "조합설립", "사업시행인가", "관리처분인가", "이주·철거", "공사 중", "준공"]

SRC_HF = "공사 홈페이지 「주택연금 자세히 알아보기」"
SRC_TRUST = "공사 「자주하는 질문(신탁)」"
SRC_100 = "공사 「주택연금 백문백답」(2026.6월 기준)"
SRC_GUIDE = "공사 「주택연금 설명서(신탁방식)」(2026.6.1)"
SRC_GUIDE_M = "공사 「주택연금 설명서(저당권방식)」(2026.6.1)"
SRC_LAW = "한국주택금융공사법 시행령 제3조의2"
SRC_LAW_28 = "한국주택금융공사법 시행령 제28조의2"
SRC_JEONSE = "공사 「주택연금 가입자 특례전세자금보증」 안내"


# ---------- 정비사업 현황 ----------

def project_type(raw: str) -> str:
    for key, label in [("재개발", "재개발"), ("재건축", "재건축"), ("소규모", "소규모주택정비"), ("주거환경", "주거환경개선")]:
        if key in raw:
            return label
    return "기타"


def derive_stage(row: pd.Series) -> str:
    """공개 데이터의 인가 일자와 '현 추진사항'으로 현재 단계를 정한다."""
    status = str(row.get("현 추진사항") or "")
    has = lambda col: pd.notna(row.get(col)) and str(row.get(col)).strip() != ""
    if "준공" in status:
        return "준공"
    if has("착공") or "착공" in status:
        return "공사 중"
    if "이주" in status or "철거" in status:
        return "이주·철거"
    if has("관리처분계획인가"):
        return "관리처분인가"
    if has("사업시행인가") or "사업시행" in status:
        return "사업시행인가"
    if has("조합설립인가") or "조합설립" in status or "건축심의" in status:
        return "조합설립"
    return "예정"


REGULATED_TYPES = ("재개발", "재건축", "소규모주택정비")  # 공사 규정의 '재건축등'


def load_zones(path: Path = ZONES_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="cp949")
    df["유형"] = df["사업유형"].map(project_type)
    df["단계"] = df.apply(derive_stage, axis=1)
    df["규정 적용"] = df["유형"].map(
        lambda t: "적용" if t in REGULATED_TYPES else "적용 여부 공사 확인 필요")
    df["투기과열지구"] = False  # 미추홀구는 2025.10.15 대책의 지정 지역이 아니다.
    df["구역ID"] = [f"Z{int(n):03d}" for n in df["연번"]]
    return df


# ---------- 주소 정규화와 매칭 ----------

ROAD_RE = re.compile(r"([가-힣0-9]*?[가-힣](?:대로|로|길))(\d+번길)?(\d+(?:-\d+)?)?")
JIBUN_RE = re.compile(r"([가-힣]+\d*동)(\d+)(?:-(\d+))?")


@dataclass
class AddressKeys:
    roads: set[tuple[str, str | None]] = field(default_factory=set)  # (도로명+번길, 건물번호)
    jibuns: set[tuple[str, str, str | None]] = field(default_factory=set)  # (동, 본번, 부번)
    is_area: bool = False  # '일원' 표기: 구역이 해당 도로·지번 주변 일대
    text: str = ""


def address_keys(addr: str) -> AddressKeys:
    a = re.sub(r"인천광역시|인천|미추홀구", "", str(addr))
    a = re.sub(r"\d+동\s*\d+호|\d+호", "", a)  # 아파트 동·호수는 지번이 아님
    a = a.replace("번지", "")
    compact = re.sub(r"\s+", "", a)
    keys = AddressKeys(is_area="일원" in compact or bool(re.search(r"외\d+필지", compact)), text=compact)
    for m in JIBUN_RE.finditer(compact):
        keys.jibuns.add((m.group(1), m.group(2), m.group(3)))
    road_part = JIBUN_RE.sub(" ", compact)
    for m in ROAD_RE.finditer(road_part):
        road = m.group(1) + (m.group(2) or "")
        keys.roads.add((road, m.group(3)))
    return keys


SIMILARITY_MIN = 0.8


@dataclass
class Match:
    zone_id: str | None
    confidence: str  # 높음 / 중간 / 직원 확인 / 없음
    reason: str


def match_one(member: AddressKeys, zone: AddressKeys) -> tuple[int, str] | None:
    """(점수, 근거) 또는 None. 점수 3=확실, 2=유력, 1=유사(직원 확인)."""
    for dong, main, sub in member.jibuns:
        for zdong, zmain, zsub in zone.jibuns:
            if dong == zdong and main == zmain:
                if sub == zsub:
                    return 3, f"지번 일치({dong} {main}{'-' + sub if sub else ''})"
                if zone.is_area:
                    return 2, f"같은 본번, 구역 일대({dong} {zmain})"
    for road, num in member.roads:
        for zroad, znum in zone.roads:
            if road != zroad:
                continue
            if num and znum and num == znum:
                return 3, f"도로명 주소 일치({road} {num})"
            if zone.is_area and (znum is None or "번길" in road):
                return 2, f"같은 도로, '일원' 구역({road})"
    ratio = SequenceMatcher(None, member.text, zone.text).ratio()
    if ratio >= SIMILARITY_MIN:
        return 1, f"주소 표기 유사도 {ratio:.2f}"
    return None


def match_member(addr: str, zones: pd.DataFrame) -> Match:
    mk = address_keys(addr)
    best: tuple[int, str, str] | None = None
    for _, z in zones.iterrows():
        res = match_one(mk, address_keys(z["위치"]))
        if res and (best is None or res[0] > best[0]):
            best = (res[0], res[1], z["구역ID"])
    if best is None:
        return Match(None, "없음", "정비구역과 일치하는 주소 없음")
    label = {3: "높음", 2: "중간", 1: "직원 확인"}[best[0]]
    return Match(best[2], label, best[1])


# ---------- 안내 규칙 ----------

@dataclass(frozen=True)
class Action:
    title: str
    detail: str
    source: str


DEADLINE_LABEL = {"조합설립": "조합설립인가 전", "사업시행인가": "사업시행계획인가 전", "관리처분인가": "관리처분계획인가 전"}
DEADLINE_RULES = [
    ("투기과열지구 재건축(소규모재건축 포함)", "조합설립인가 전"),
    ("그 외 재건축·재개발", "관리처분계획인가 전"),
    ("소규모주택정비", "사업시행계획인가 전"),
    ("같은 구역에 신탁 가입자가 더 있는 경우(리모델링 제외)", "조합설립인가 전"),
]


def conversion_deadline(zone_type: str, overheated: bool = False, other_trust_in_zone: bool = False) -> str | None:
    """이 단계에 들어서기 전까지 전환해야 한다. 규정의 '재건축등'이 아니면 None.

    공개 현황은 소규모재건축을 따로 구분하지 않아, 투기과열지구에서는 소규모주택정비 전체에 앞선 기한을 쓴다.
    """
    if zone_type not in REGULATED_TYPES:
        return None
    if other_trust_in_zone or (overheated and zone_type in ("재건축", "소규모주택정비")):
        return "조합설립"
    return "사업시행인가" if zone_type == "소규모주택정비" else "관리처분인가"


def deadline_status(stage: str, deadline: str | None) -> str | None:
    if deadline is None:
        return None
    gap = STAGES.index(deadline) - STAGES.index(stage)
    if gap <= 0:
        return "경과"
    return "임박" if gap == 1 else "여유"


def convert_action(deadline: str) -> Action:
    return Action(
        "저당권 방식으로 전환",
        f"신탁 방식은 신탁등기를 둔 채 사업이 진행되면 연금을 계속 받을 수 없습니다. {DEADLINE_LABEL[deadline]}까지 저당권 방식으로 바꿔야 합니다. "
        "바꿔도 월지급금과 보증료는 그대로입니다. 신규 설정비는 현재 한시적으로 1회 공사가 전부 또는 일부 지원합니다. "
        "기존 말소비와 등록면허세·지방교육세는 가입자 부담입니다(세금은 일부 감면).",
        f"{SRC_GUIDE}, {SRC_100}, {SRC_TRUST}")


def convert_prep_action(deadline: str) -> Action:
    return Action(
        "저당권 방식 전환을 미리 알아 두세요",
        f"아직 사업 초기입니다. 신탁 방식은 {DEADLINE_LABEL[deadline]}까지 저당권 방식으로 바꿔야 하니, 절차와 비용을 미리 상담해 두세요.",
        f"{SRC_GUIDE}, {SRC_TRUST}")


def deadline_passed_action(deadline: str) -> Action:
    return Action(
        "전환 기한 경과, 바로 확인",
        f"공개 자료상 이 구역은 전환 기한({DEADLINE_LABEL[deadline]})을 넘긴 단계입니다. "
        "신탁 방식이 그대로라면 연금 지급에 문제가 생길 수 있어 지사가 바로 확인합니다.",
        f"{SRC_GUIDE}, {SRC_100}")


def move_away_action(deadline: str, collateral: str) -> Action:
    return Action(
        "참여하지 않고 이사하려면 기한이 있습니다",
        f"재건축 등에 참여하지 않고 이사해 연금을 이어 받으려면 {DEADLINE_LABEL[deadline]}까지 담보주택을 변경해야 합니다.",
        SRC_GUIDE if collateral == "신탁" else SRC_GUIDE_M)


TRUST_CHECK = Action("규정 적용 여부 확인",
                     "이 사업은 규정의 재건축등에 명시되어 있지 않아 지사가 적용 여부를 먼저 확인합니다.", SRC_LAW_28)
KEEP = Action("주택연금은 계속 받을 수 있습니다",
              "재건축·재개발이 진행돼도 주택연금 계약은 유지할 수 있습니다.", SRC_HF)
PROOF = Action("조합원이 되면 참여 서류를 내야 합니다",
               "조합원으로 참여하면 증빙 서류를 공사에 내야 하고, 공사가 참여 여부를 3개월마다 확인합니다. "
               "요청에 응하지 않으면 지급정지 예외가 적용되지 않습니다.", f"{SRC_100}, {SRC_GUIDE_M}")
CASH_OUT = Action("분양 신청 여부를 미리 생각해 두세요",
                  "분양을 신청하지 않거나 철회하면, 또는 입주권을 팔면 조합원 지위를 잃어 연금 지급이 멈춥니다. "
                  "참여 결과 청산금을 받아도 지급정지 사유이며, 받은 금액과 대출 잔액 중 적은 금액을 갚아야 합니다.", SRC_100)
SHARE = Action("분담금은 연금에서 미리 찾아 쓸 수 있습니다",
               "재건축 등 분담금 납부에는 대출한도의 70% 이내에서 개별인출을 쓸 수 있습니다. "
               "이미 낸 분담금은 해당되지 않고, 인출한도를 설정하면 월지급금이 줄어듭니다.", f"{SRC_LAW}, {SRC_100}")
MOVE = Action("이주 자금을 준비하세요",
              "계약을 유지하면 조합 이주비대출을 받지 못할 수 있고, 신탁에서 전환한 경우 조합원 분담금 대출도 제한될 수 있습니다. "
              "재개발·재건축·리모델링 참여로 다른 집에 살아야 하면 가입자 특례 전세자금보증(최대 3억 원)을 신청할 수 있습니다.",
              f"{SRC_HF}, {SRC_GUIDE}, {SRC_JEONSE}")
DEMOLISH = Action("집이 철거돼도 연금은 이어집니다",
                  "재건축 등에 참여 중인 저당권 방식이면 철거로 담보주택이 없어져도 지급정지 예외에 해당해 연금이 계속 나옵니다.", SRC_100)
COMPLETE = Action("준공 후 등기 절차가 있습니다",
                  "새 집 소유권을 취득하면 공사가 1순위 근저당권을 다시 설정합니다. 지사에서 절차를 안내해 드립니다.", SRC_HF)

RULES: dict[str, list[Action]] = {
    "예정": [KEEP],
    "조합설립": [KEEP, PROOF, CASH_OUT],
    "사업시행인가": [PROOF, CASH_OUT, SHARE],
    "관리처분인가": [CASH_OUT, SHARE, MOVE],
    "이주·철거": [MOVE, DEMOLISH],
    "공사 중": [DEMOLISH, COMPLETE],
    "준공": [COMPLETE],
}


def actions_for(stage: str, collateral: str, deadline: str | None) -> list[Action]:
    status = deadline_status(stage, deadline)
    acts = [a for a in RULES[stage] if not (collateral == "신탁" and a == KEEP)]
    if status in ("임박", "여유"):
        acts.append(move_away_action(deadline, collateral))
    if collateral != "신탁":
        return acts
    if status is None:
        first = TRUST_CHECK
    elif status == "경과":
        first = deadline_passed_action(deadline)
    elif stage == "예정" and status == "여유":
        first = convert_prep_action(deadline)
    else:
        first = convert_action(deadline)
    return [first] + acts


STAGE_WEIGHT = {"예정": 1, "조합설립": 3, "사업시행인가": 4, "관리처분인가": 5, "이주·철거": 4, "공사 중": 2, "준공": 3}
TRUST_SCORE = {"경과": 10, "임박": 9, "여유": 7, None: 4}


def priority(stage: str, collateral: str, deadline: str | None) -> tuple[int, str]:
    score = STAGE_WEIGHT[stage]
    if collateral == "신탁":
        status = deadline_status(stage, deadline)
        score = 2 if stage == "예정" and status == "여유" else TRUST_SCORE[status]
    label = "긴급" if score >= 8 else "높음" if score >= 5 else "보통" if score >= 3 else "낮음"
    return score, label


# ---------- 안내문 ----------

def notice_text(member: pd.Series, zone: pd.Series, actions: list[Action]) -> str:
    lines = [
        f"[주택연금 안내] {member['호칭']}님, 한국주택금융공사입니다.",
        "",
        f"살고 계신 집이 '{zone['구역명']}' {zone['유형']} 구역에 들어 있고, 지금은 '{zone['단계']}' 단계입니다.",
        "지금 확인해 두실 일을 알려 드립니다.",
        "",
    ]
    for i, a in enumerate(actions, 1):
        lines += [f"{i}. {a.title}", f"   {a.detail}", f"   (근거: {a.source})", ""]
    lines.append("궁금하신 점은 담당 지사로 전화 주시면 자세히 안내해 드립니다.")
    lines.append("※ 이 안내는 공개된 정비사업 현황 자료를 바탕으로 보내 드립니다.")
    return "\n".join(lines)


def build_dashboard(zones: pd.DataFrame, members: pd.DataFrame) -> pd.DataFrame:
    rows = []
    zone_by_id = zones.set_index("구역ID")
    matches = {m["가입자ID"]: match_member(m["주소"], zones) for _, m in members.iterrows()}
    trust_in_zone = Counter(matches[m["가입자ID"]].zone_id for _, m in members.iterrows()
                            if m["담보방식"] == "신탁" and matches[m["가입자ID"]].confidence in ("높음", "중간"))
    for _, m in members.iterrows():
        mt = matches[m["가입자ID"]]
        row = {"가입자": m["가입자ID"], "주소": m["주소"], "담보 방식": m["담보방식"],
               "매칭 신뢰도": mt.confidence, "매칭 근거": mt.reason}
        if mt.zone_id is None:
            rows.append({**row, "구역": "-", "단계": "-", "규정 적용": "-", "전환 기한": "-", "우선순위": "대상 아님", "점수": 0, "다음 조치": "-"})
            continue
        z = zone_by_id.loc[mt.zone_id]
        trust = m["담보방식"] == "신탁"
        deadline = conversion_deadline(z["유형"], bool(z["투기과열지구"]), trust and trust_in_zone[mt.zone_id] > 1)
        score, label = priority(z["단계"], m["담보방식"], deadline)
        if mt.confidence == "직원 확인":
            label = "직원 확인"
        status = deadline_status(z["단계"], deadline)
        limit = f"{DEADLINE_LABEL[deadline]} ({status})" if trust and deadline else ("공사 확인" if trust else "-")
        acts = actions_for(z["단계"], m["담보방식"], deadline)
        rows.append({**row, "구역": z["구역명"], "구역ID": mt.zone_id, "단계": z["단계"], "규정 적용": z["규정 적용"],
                     "전환 기한": limit, "기한": deadline, "우선순위": label, "점수": score, "다음 조치": acts[0].title})
    df = pd.DataFrame(rows)
    order = {"긴급": 0, "높음": 1, "직원 확인": 2, "보통": 3, "낮음": 4, "대상 아님": 5}
    return df.sort_values(["우선순위", "점수"], key=lambda s: s.map(order) if s.name == "우선순위" else -s).reset_index(drop=True)
