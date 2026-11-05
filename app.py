"""재건축 알림이 시제품 화면 (Streamlit). 실행: streamlit run app.py"""
import html
import os
import re

import pandas as pd
import streamlit as st

from core import DEADLINE_RULES, MEMBERS_CSV, STAGES, actions_for, build_dashboard, load_zones, notice_text

st.set_page_config(page_title="재건축 알림이", layout="wide")

NOTICE_STYLE = ("font-size:21px;line-height:1.75;background:#fffdf5;border:1px solid #e8dcb0;"
                "border-radius:10px;padding:22px 26px;color:#222;font-family:sans-serif;")


def notice_html(text: str) -> str:
    """안내문을 마크다운 해석 없이 그대로 보여 준다. 항목 제목은 굵게, 근거는 작게."""
    out = []
    for line in text.splitlines():
        esc = html.escape(line.strip())
        if re.match(r"\d+\. ", line):
            out.append(f"<div style='margin-top:14px;font-weight:700'>{esc}</div>")
        elif line.strip().startswith("(근거"):
            out.append(f"<div style='margin-left:28px;font-size:15px;color:#777'>{esc}</div>")
        elif line.startswith("   "):
            out.append(f"<div style='margin-left:28px'>{esc}</div>")
        elif esc:
            out.append(f"<div>{esc}</div>")
    return f"<div style='{NOTICE_STYLE}'>{''.join(out)}</div>"


@st.cache_data
def load():
    zones = load_zones()
    members = pd.read_csv(MEMBERS_CSV)
    return zones, members, build_dashboard(zones, members)


zones, members, board = load()

st.title("재건축 알림이")
st.caption("정비사업 공공데이터로 주택연금 가입자에게 먼저 알리는 사후관리 서비스 · 시연용 시제품")
st.info("정비사업 현황은 실제 공공데이터(「인천광역시 미추홀구_정비사업 추진현황」, 2026-07-28 수정)이고, "
        "**가입자 정보는 모두 가상**입니다. 안내문은 규칙표로 만들며, 실제 도입 시 공사 자체 생성형 AI로 문장을 다듬는 구조입니다. "
        "전환 기한은 공사 설명서(2026.6.1) 기준이고, 미추홀구는 투기과열지구가 아닌 것으로 계산합니다.")

tab_board, tab_notice, tab_zones, tab_rules = st.tabs(["직원 현황판", "가입자 안내문", "정비사업 현황", "안내 규칙표"])

with tab_board:
    targets = board[board["우선순위"] != "대상 아님"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("확인한 정비구역", f"{len(zones)}곳")
    c2.metric("구역 안 가입자", f"{len(targets)}명", f"전체 {len(board)}명 중")
    c3.metric("긴급 (신탁·전환 기한 경과 또는 임박)", f"{(targets['우선순위'] == '긴급').sum()}명")
    c4.metric("직원 확인 필요", f"{(targets['우선순위'] == '직원 확인').sum()}명")

    pick = st.multiselect("우선순위", ["긴급", "높음", "직원 확인", "보통", "낮음", "대상 아님"],
                          default=["긴급", "높음", "직원 확인", "보통", "낮음"])
    view = board[board["우선순위"].isin(pick)]
    colors = {"긴급": "#f8d7da", "높음": "#fde2c8", "직원 확인": "#fff3c4", "보통": "#e2efda", "낮음": "#eef2f7"}
    styled = view[["우선순위", "가입자", "구역", "단계", "담보 방식", "전환 기한", "다음 조치", "매칭 근거"]].style.map(
        lambda v: f"background-color: {colors.get(v, '')}", subset=["우선순위"])
    st.table(styled.hide(axis="index"))
    st.caption("우선순위: 신탁 방식이면서 전환 기한이 지났거나 임박한 가입자를 먼저 보여 줍니다. "
               "주소 표기가 비슷하기만 한 건은 '직원 확인'으로 분류해 사람이 최종 판단합니다.")

with tab_notice:
    matched = board[board["우선순위"] != "대상 아님"]
    labels = {f"{r['가입자']} · {r['구역']} · {r['우선순위']}": r["가입자"] for _, r in matched.iterrows()}
    choice = st.selectbox("가입자 선택", list(labels))
    mid = labels[choice]
    m = members.set_index("가입자ID").loc[mid]
    b = matched.set_index("가입자").loc[mid]
    z = zones.set_index("구역ID").loc[b["구역ID"]]

    left, right = st.columns([1, 2])
    with left:
        st.subheader("가입자 (가상)")
        st.write(f"- 담보 방식: **{m['담보방식']}**")
        st.write(f"- 나이: {m['나이']}세")
        st.write(f"- 연락 방법: {m['연락 방법']}")
        st.write(f"- 가족 알림 동의: {'예' if m['가족 알림 동의'] == 'Y' else '아니오'}")
        st.write(f"- 매칭: {b['매칭 신뢰도']} ({b['매칭 근거']})")
        st.subheader("정비사업 (공공데이터)")
        st.write(f"- {z['구역명']} ({z['유형']}), 현재 **{z['단계']}**")
        for col in ["정비구역지정", "조합설립인가", "사업시행인가", "관리처분계획인가", "착공"]:
            if pd.notna(z[col]):
                st.write(f"- {col}: {z[col]}")
        st.write(f"- 현 추진사항: {z['현 추진사항']}")
        if z["규정 적용"] != "적용":
            st.warning("이 사업은 규정의 재건축등에 명시되어 있지 않아 공사가 적용 여부를 확인한 뒤 발송합니다.")
        if b["매칭 신뢰도"] == "직원 확인":
            st.warning("주소가 비슷하기만 해 직원 확인 후 발송합니다.")

    with right:
        acts = actions_for(z["단계"], m["담보방식"], b["기한"] if pd.notna(b["기한"]) else None)
        text = notice_text(m, z, acts)
        st.subheader("안내문 미리보기")
        st.html(notice_html(text))
        channel = "지사 전화 안내 대본으로 사용" if m["연락 방법"] == "지사 전화" else "알림톡 발송"
        family = " · 동의한 가족에게도 발송" if m["가족 알림 동의"] == "Y" else ""
        st.caption(f"발송 방식: {channel}{family}")

        has_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
        if st.button("생성형 AI로 문장 다듬기", disabled=not has_ai):
            from ai_polish import polish
            with st.spinner("다듬는 중..."):
                st.html(notice_html(polish(text)))
        if not has_ai:
            st.caption("API 키가 설정되지 않아 규칙 기반 안내문만 표시합니다.")

with tab_zones:
    counts = zones["단계"].value_counts().reindex(STAGES).fillna(0).astype(int)
    st.bar_chart(counts)
    st.dataframe(zones[["구역명", "유형", "규정 적용", "단계", "위치", "조합설립인가", "사업시행인가", "관리처분계획인가", "착공", "현 추진사항"]],
                 hide_index=True, width="stretch", height=480)

with tab_rules:
    st.write("판단은 이 규칙표가 하고, 안내문은 규칙표가 고른 내용만 씁니다.")
    st.subheader("저당권 전환 기한")
    st.table(pd.DataFrame(DEADLINE_RULES, columns=["사업", "이때까지 전환"]).style.hide(axis="index"))
    st.caption("근거: 공사 「주택연금 설명서(신탁방식)」(2026.6.1). 참여 없이 이사할 때의 담보주택 변경 기한도 비슷합니다.")
    st.subheader("사업 단계별 안내 (기한이 관리처분계획인가 전인 경우)")
    rows = []
    for stage in STAGES:
        for collateral in ("신탁", "저당"):
            for a in actions_for(stage, collateral, "관리처분인가"):
                rows.append({"사업 단계": stage, "담보 방식": collateral, "안내": a.title, "근거": a.source})
    st.table(pd.DataFrame(rows).style.hide(axis="index"))
