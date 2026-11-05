import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import (MEMBERS_CSV, actions_for, address_keys, build_dashboard, conversion_deadline, deadline_status,
                  derive_stage, load_zones, match_member, priority)


def row(**kw):
    return pd.Series(kw)


class StageTest(unittest.TestCase):
    def test_status_text_wins_over_dates(self):
        self.assertEqual(derive_stage(row(관리처분계획인가="2022-03-28", **{"현 추진사항": "이주완료"})), "이주·철거")
        self.assertEqual(derive_stage(row(착공="2023-10-25", **{"현 추진사항": "준공인가"})), "준공")

    def test_dates_when_no_status_keyword(self):
        self.assertEqual(derive_stage(row(사업시행인가="2026-01-19", **{"현 추진사항": "사업시행계획인가"})), "사업시행인가")
        self.assertEqual(derive_stage(row(정비구역지정="2026-01-19", **{"현 추진사항": "추진위원회구성"})), "예정")


class AddressTest(unittest.TestCase):
    def test_unit_numbers_are_not_jibun(self):
        keys = address_keys("인천광역시 미추홀구 주안동 1344-1 우진아파트 999동 999호")
        self.assertEqual(keys.jibuns, {("주안동", "1344", "1")})

    def test_road_with_bungil(self):
        keys = address_keys("비룡길 23번길 일원(용현근린공원우측)")
        self.assertIn(("비룡길23번길", None), keys.roads)
        self.assertTrue(keys.is_area)


class MatchTest(unittest.TestCase):
    zones = load_zones()

    def test_exact_road_address(self):
        m = match_member("인천 미추홀구 인주대로366번길 23, 999동 999호", self.zones)
        self.assertEqual((m.zone_id, m.confidence), ("Z014", "높음"))

    def test_jibun_in_parentheses(self):
        m = match_member("인천광역시 미추홀구 주안동 1344-1", self.zones)
        self.assertEqual((m.zone_id, m.confidence), ("Z013", "높음"))

    def test_area_zone_same_road(self):
        m = match_member("인천광역시 미추홀구 석바위로5번길 17", self.zones)
        self.assertEqual((m.zone_id, m.confidence), ("Z001", "중간"))

    def test_near_miss_goes_to_staff(self):
        m = match_member("인천광역시 미추홀구 숙골로 8번길 14-1", self.zones)
        self.assertEqual(m.confidence, "직원 확인")

    def test_outside(self):
        self.assertIsNone(match_member("인천광역시 미추홀구 토금중로 30", self.zones).zone_id)


    def test_parcels_count_as_area(self):
        m = match_member("인천광역시 미추홀구 용현동 557-48", self.zones)
        self.assertEqual((m.zone_id, m.confidence), ("Z048", "중간"))

    def test_same_road_other_number_is_not_flagged(self):
        self.assertIsNone(match_member("인천광역시 미추홀구 인주대로 155", self.zones).zone_id)


class DeadlineTest(unittest.TestCase):
    def test_deadline_by_project(self):
        self.assertEqual(conversion_deadline("재개발"), "관리처분인가")
        self.assertEqual(conversion_deadline("재건축"), "관리처분인가")
        self.assertEqual(conversion_deadline("소규모주택정비"), "사업시행인가")
        self.assertEqual(conversion_deadline("재건축", overheated=True), "조합설립")
        self.assertEqual(conversion_deadline("재개발", overheated=True), "관리처분인가")
        self.assertEqual(conversion_deadline("재개발", other_trust_in_zone=True), "조합설립")
        self.assertIsNone(conversion_deadline("주거환경개선"))

    def test_status(self):
        self.assertEqual(deadline_status("조합설립", "관리처분인가"), "여유")
        self.assertEqual(deadline_status("사업시행인가", "관리처분인가"), "임박")
        self.assertEqual(deadline_status("관리처분인가", "관리처분인가"), "경과")
        self.assertIsNone(deadline_status("준공", None))

    def test_small_scale_projects_follow_the_rules(self):
        zones = load_zones().set_index("유형")
        self.assertTrue((zones.loc["소규모주택정비", "규정 적용"] == "적용").all())
        self.assertEqual(zones.loc["주거환경개선", "규정 적용"], "적용 여부 공사 확인 필요")


class RuleTest(unittest.TestCase):
    def test_trust_member_first_action(self):
        convert = actions_for("사업시행인가", "신탁", "관리처분인가")[0]
        self.assertEqual(convert.title, "저당권 방식으로 전환")
        self.assertIn("관리처분계획인가 전", convert.detail)
        self.assertEqual(actions_for("예정", "신탁", "관리처분인가")[0].title, "저당권 방식 전환을 미리 알아 두세요")
        self.assertEqual(actions_for("사업시행인가", "신탁", "사업시행인가")[0].title, "전환 기한 경과, 바로 확인")
        self.assertEqual(actions_for("준공", "신탁", None)[0].title, "규정 적용 여부 확인")

    def test_mortgage_member_never_converts(self):
        titles = [a.title for a in actions_for("사업시행인가", "저당", "관리처분인가")]
        self.assertNotIn("저당권 방식으로 전환", titles)
        self.assertIn("참여하지 않고 이사하려면 기한이 있습니다", titles)

    def test_priority_follows_deadline(self):
        self.assertEqual(priority("사업시행인가", "신탁", "사업시행인가")[1], "긴급")
        self.assertEqual(priority("사업시행인가", "신탁", "관리처분인가")[1], "긴급")
        self.assertEqual(priority("조합설립", "신탁", "관리처분인가")[1], "높음")
        self.assertEqual(priority("예정", "신탁", "관리처분인가")[1], "낮음")
        self.assertEqual(priority("예정", "신탁", "조합설립")[1], "긴급")
        self.assertEqual(priority("사업시행인가", "저당", "관리처분인가")[1], "보통")


class BoardTest(unittest.TestCase):
    def test_demo_results(self):
        board = build_dashboard(load_zones(), pd.read_csv(MEMBERS_CSV))
        targets = board[board["우선순위"] != "대상 아님"].set_index("가입자")
        self.assertEqual(len(targets), 16)
        self.assertEqual((targets["우선순위"] == "긴급").sum(), 6)
        self.assertEqual((targets["우선순위"] == "직원 확인").sum(), 1)
        self.assertEqual(targets.loc["M004", "다음 조치"], "전환 기한 경과, 바로 확인")
        self.assertEqual(targets.loc["M001", "다음 조치"], "저당권 방식으로 전환")


if __name__ == "__main__":
    unittest.main()
