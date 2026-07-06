import unittest

from frontend.ingestion_outcome import (
    build_failure_outcome,
    classify_extraction_outcome,
)


class IngestionOutcomeTests(unittest.TestCase):
    def test_high_confidence_article_succeeds_without_images(self):
        prefill = {
            "news_title": "기사 제목",
            "news_body": "충분한 길이와 문장성을 갖춘 기사 본문입니다. " * 3,
        }
        summary = {
            "body_paragraph_count": 2,
            "image_candidate_count": 0,
            "extraction_confidence": "높음",
        }

        outcome = classify_extraction_outcome(prefill, summary)

        self.assertEqual("success", outcome["status"])
        self.assertIn("이미지 후보 0개", outcome["message"])

    def test_low_confidence_article_is_uncertain_and_prefill_is_preserved(self):
        prefill = {
            "news_title": "기사 제목",
            "news_body": "추출된 본문은 사용자가 원문과 비교할 수 있도록 보존합니다.",
        }
        summary = {
            "body_paragraph_count": 1,
            "image_candidate_count": 0,
            "extraction_confidence": "낮음",
        }

        outcome = classify_extraction_outcome(prefill, summary)

        self.assertEqual("uncertain", outcome["status"])
        self.assertEqual(prefill, outcome["prefill"])

    def test_short_body_is_uncertain_even_with_high_confidence_label(self):
        outcome = classify_extraction_outcome(
            {"news_title": "제목", "news_body": "짧은 본문"},
            {
                "body_paragraph_count": 1,
                "image_candidate_count": 1,
                "extraction_confidence": "높음",
            },
        )
        self.assertEqual("uncertain", outcome["status"])

    def test_failure_outcomes_do_not_create_false_prefill(self):
        for status in ("access_restricted", "fetch_failed"):
            with self.subTest(status=status):
                outcome = build_failure_outcome(status, "안내 문구")
                self.assertEqual(status, outcome["status"])
                self.assertEqual({}, outcome["prefill"])
                self.assertEqual({}, outcome["summary"])


if __name__ == "__main__":
    unittest.main()
