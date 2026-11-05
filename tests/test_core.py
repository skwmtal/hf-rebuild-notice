import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import (CONVERT, CONVERT_PREP, URGENT_CHECK, actions_for, address_keys, derive_stage, load_zones,
                  match_member, priority)


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
        keys = address_keys("인천광역시 미추홀구 주안동 1344-1 우진아파트 2동 305호")
        self.assertEqual(keys.jibuns, {("주안동", "1344", "1")})

    def test_road_with_bungil(self):
        keys = address_keys("비룡길 23번길 일원(용현근린공원우측)")
        self.assertIn(("비룡길23번길", None), keys.roads)
        self.assertTrue(keys.is_area)


class MatchTest(unittest.TestCase):
    zones = load_zones()

    def test_exact_road_address(self):
        m = match_member("인천 미추홀구 인주대로366번길 23, 3동 402호", self.zones)
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


class RuleTest(unittest.TestCase):
    def test_trust_member_converts_before_demolition(self):
        self.assertEqual(actions_for("사업시행인가", "신탁")[0], CONVERT)
        self.assertEqual(actions_for("예정", "신탁")[0], CONVERT_PREP)
        self.assertEqual(actions_for("이주·철거", "신탁")[0], URGENT_CHECK)
        self.assertNotIn(CONVERT, actions_for("사업시행인가", "저당"))

    def test_trust_in_progress_is_urgent(self):
        self.assertEqual(priority("사업시행인가", "신탁")[1], "긴급")
        self.assertEqual(priority("사업시행인가", "저당")[1], "보통")
        self.assertEqual(priority("예정", "신탁")[1], "낮음")


if __name__ == "__main__":
    unittest.main()
