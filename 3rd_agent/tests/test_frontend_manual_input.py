import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from frontend.streamlit_app import (
    make_input_state,
    make_temp_ce_state,
    make_temp_ig_state,
    save_remote_chart_images,
)


class FrontendManualInputRegressionTests(unittest.TestCase):
    @patch("frontend.streamlit_app.download_image_from_url")
    def test_selected_remote_image_is_saved_to_existing_image_path_flow(self, mocked_download):
        mocked_download.return_value = {
            "data": b"image-bytes",
            "suffix": ".jpg",
            "final_url": "https://images.example.com/chart.jpg",
        }
        with tempfile.TemporaryDirectory() as directory:
            with patch("frontend.streamlit_app.PROJECT_ROOT", Path(directory)):
                paths, errors = save_remote_chart_images(
                    ["https://images.example.com/chart.jpg"]
                )
            self.assertEqual([], errors)
            self.assertEqual(1, len(paths))
            self.assertEqual(b"image-bytes", Path(paths[0]).read_bytes())

    def test_manual_input_still_maps_to_existing_state_contract(self):
        input_state = make_input_state(
            news_title="기사 제목",
            news_body="기사 본문 주장",
            chart_text="2025년 70.1%",
            source_text="출처: 통계청, 단위: %",
            chart_image_paths=["chart.png"],
        )
        self.assertEqual("기사 제목", input_state["input_news_title"])
        self.assertEqual(["chart.png"], input_state["input_chart_image_paths"])
        self.assertTrue(all(key.startswith("input_") for key in input_state))

    def test_temporary_agent_states_preserve_existing_keys(self):
        ce_state = make_temp_ce_state(
            "기사 제목", "기사 본문", "차트 설명", ["chart.png"], "주의 필요", "관계 요약"
        )
        ig_state = make_temp_ig_state("출처: 통계청", ["chart.png"], ["기간"])
        self.assertEqual("주의 필요", ce_state["ce_draft_judgement"])
        self.assertEqual(["기간"], ig_state["ig_missing_info"])
        self.assertTrue(all(key.startswith("ce_") for key in ce_state))
        self.assertTrue(all(key.startswith("ig_") for key in ig_state))


if __name__ == "__main__":
    unittest.main()
