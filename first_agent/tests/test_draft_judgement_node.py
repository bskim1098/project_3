import unittest

from ce_agent.nodes.draft_judgement_node import decide_draft_judgement


class DraftJudgementNodeTests(unittest.TestCase):
    def test_information_gap_overrides_contradiction(self):
        result = decide_draft_judgement(
            ["수치"], [], ["출처가 부족합니다."], "contradicted"
        )
        self.assertEqual("검증 제한", result)

    def test_clear_direction_conflict_allows_high_distortion_risk(self):
        self.assertEqual(
            "왜곡 가능성 높음",
            decide_draft_judgement(["수치"], [], [], "contradicted"),
        )

    def test_supported_but_strong_word_needs_caution(self):
        self.assertEqual(
            "주의 필요",
            decide_draft_judgement(["수치"], ["폭증"], [], "supported"),
        )


if __name__ == "__main__":
    unittest.main()
