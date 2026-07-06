import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "streamlit_app.py"
)


class StreamlitUIRegressionTests(unittest.TestCase):
    def make_app(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=15)
        app.run()
        self.assertEqual([], list(app.exception))
        return app

    def test_source_section_and_safe_action_labels_are_rendered(self):
        app = self.make_app()
        self.assertIn("뉴스 기사 URL", [widget.label for widget in app.text_input])
        self.assertIn("기사 원문 불러오기", [widget.label for widget in app.button])
        self.assertIn("기사 근거 검증하기", [widget.label for widget in app.button])
        architecture_text = " ".join(element.value for element in app.markdown)
        self.assertIn("GraphRAG · 도입 예정", architecture_text)
        self.assertIn("LangGraph · 적용됨", architecture_text)
        self.assertIn("LangChain · 적용됨", architecture_text)

    def test_empty_source_request_keeps_manual_form_available(self):
        app = self.make_app()
        source_button = next(
            widget for widget in app.button if widget.label == "기사 원문 불러오기"
        )
        source_button.click().run()
        self.assertTrue(
            any("뉴스 기사 URL을 입력하거나" in warning.value for warning in app.warning)
        )
        self.assertIn("기사 제목", [widget.label for widget in app.text_input])

    def test_prefilled_session_values_remain_editable(self):
        app = self.make_app()
        app.session_state["form_news_title"] = "자동 추출 기사 제목"
        app.session_state["form_news_body"] = "자동 추출 본문"
        app.run()
        title_widget = next(widget for widget in app.text_input if widget.label == "기사 제목")
        self.assertEqual("자동 추출 기사 제목", title_widget.value)
        title_widget.input("사용자가 수정한 기사 제목").run()
        updated_widget = next(
            widget for widget in app.text_input if widget.label == "기사 제목"
        )
        self.assertEqual("사용자가 수정한 기사 제목", updated_widget.value)

    def test_article_image_candidates_are_presented_for_user_selection(self):
        app = self.make_app()
        app.session_state["latest_prefill_source"] = "뉴스 기사 URL의 HTML"
        app.session_state["latest_extraction_summary"] = {
            "body_paragraph_count": 2,
            "visual_text_count": 0,
            "image_candidate_count": 1,
            "source_candidate_count": 0,
            "extraction_confidence": "높음",
            "missing_fields": ["시각자료 관련 텍스트", "출처·단위 후보"],
        }
        app.session_state["latest_article_image_candidates"] = [
            {
                "url": "https://images.example.com/article-chart.jpg",
                "alt": "고용률 추이 그래프",
                "caption": "",
                "label": "고용률 추이 그래프",
                "likely_chart": True,
            }
        ]
        app.run()
        self.assertIn(
            "시각자료 후보 1 선택",
            [widget.label for widget in app.checkbox],
        )

    def test_ingestion_status_messages_keep_manual_form_available(self):
        cases = (
            ("success", "자동 입력 성공", "success"),
            ("uncertain", "자동 입력 결과를 확인해주세요", "warning"),
            ("access_restricted", "해당 사이트가 자동 요청을 제한했습니다", "error"),
            ("fetch_failed", "기사 페이지를 불러오지 못했습니다", "error"),
        )
        for status, message, element_name in cases:
            with self.subTest(status=status):
                app = self.make_app()
                app.session_state["latest_ingestion_outcome"] = {
                    "status": status,
                    "message": message,
                    "prefill": {},
                    "summary": {},
                }
                app.run()
                elements = getattr(app, element_name)
                self.assertTrue(any(message in element.value for element in elements))
                self.assertIn("기사 제목", [widget.label for widget in app.text_input])


if __name__ == "__main__":
    unittest.main()
