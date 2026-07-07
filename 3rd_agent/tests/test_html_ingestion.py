import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from frontend.html_ingestion import (
    MAX_HTML_BYTES,
    AccessRestrictedError,
    ArticleFetchError,
    ArticleFetchTimeoutError,
    ArticleNotFoundError,
    InvalidArticleURLError,
    InvalidHTMLContentError,
    extract_text_blocks_from_html,
    fetch_html_from_url,
    get_ingestion_error_message,
    download_image_from_url,
    prefill_form_from_html_content,
    read_html_from_upload,
    select_chart_image_candidates,
    summarize_extraction,
    _SafeRedirectHandler,
    _normalize_html_before_parse,
)


SAMPLE_HTML = """
<html><head><title>브라우저 제목</title></head><body>
<h1>기사 제목</h1><article><p>첫 번째 기사 문단입니다.</p><p>두 번째 문단입니다.</p>
<figure><img alt="고용률 추이 차트"><figcaption>출처: 통계청, 단위: %</figcaption></figure>
<table><caption>연도별 고용률</caption><tr><th>2025</th><td>70.1</td></tr></table></article>
</body></html>
"""

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "test_samples" / "html"


class FakeHeaders:
    def __init__(self, content_type="text/html", charset="utf-8"):
        self.content_type = content_type
        self.charset = charset

    def get_content_type(self):
        return self.content_type

    def get_content_charset(self):
        return self.charset


class FakeResponse:
    def __init__(self, body, content_type="text/html"):
        self.body = body
        self.headers = FakeHeaders(content_type)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return "https://news.example.com/final-article"

    def read(self, _size):
        return self.body


class HTMLIngestionTests(unittest.TestCase):
    def test_chart_filter_excludes_news_photo_reporter_and_advertisement(self):
        html = """
        <html><body><h1>경제 전망 기사</h1><article>
        <p>산업 전망과 주요 지표 변화를 설명하는 첫 번째 기사 문단입니다.</p>
        <p>수출 증감률과 성장률 전망을 비교하는 두 번째 기사 문단입니다.</p>
        <figure><img src="https://img.test/chart.jpg" width="800" height="500"
          alt="2025년 산업별 수출 증감률 전망 그래프"><figcaption>단위: %, 출처: 산업연구원</figcaption></figure>
        <figure><img src="https://img.test/port.jpg" width="800" height="500"
          alt="부산항 컨테이너 자료사진"><figcaption>연합뉴스 자료사진</figcaption></figure>
        <div class="reporter profile"><img src="https://img.test/reporter.jpg" width="160" height="160" alt="김기자 기자 프로필"></div>
        <div class="advert banner"><img src="https://img.test/banner.jpg" width="800" height="200" alt="광고 배너"></div>
        </article></body></html>
        """

        blocks = extract_text_blocks_from_html(html, "https://news.test/article/1")
        selected = select_chart_image_candidates(blocks["image_candidates"])

        self.assertEqual(1, len(selected))
        self.assertEqual("https://img.test/chart.jpg", selected[0]["url"])
        self.assertTrue(selected[0]["selection_reasons"])

    def test_photo_word_does_not_override_explicit_chart_without_photo_context(self):
        candidates = [
            {
                "url": "https://img.test/chart.jpg",
                "alt": "고용률 추이 그래프",
                "caption": "단위: %",
                "label": "고용률 추이 그래프",
                "likely_chart": True,
                "chart_score": 8,
                "selection_reasons": ["그래프 표현"],
                "exclusion_reasons": [],
            }
        ]
        self.assertEqual(candidates, select_chart_image_candidates(candidates))

    def test_article_metadata_title_wins_over_site_brand_h1(self):
        html = """
        <html><head>
        <meta property="og:site_name" content="경향신문">
        <meta property="og:title" content="대선 투표율로 본 ‘정치 참여’ - 경향신문">
        </head><body>
        <header><h1>창간 80주년 경향신문</h1></header>
        <article><p>여성 투표율과 정치 참여 변화를 분석한 기사 본문입니다.</p></article>
        </body></html>
        """

        blocks = extract_text_blocks_from_html(html)

        self.assertEqual("대선 투표율로 본 ‘정치 참여’", blocks["title"])

    def test_malformed_tracking_iframe_is_removed_before_dom_parse(self):
        """변경 회귀: 닫히지 않은 noscript iframe이 이후 기사 DOM을 삼키지 않는다."""
        html = (FIXTURE_DIR / "malformed_noscript_iframe_article.html").read_text(
            encoding="utf-8"
        )
        blocks = extract_text_blocks_from_html(html)

        self.assertEqual("[itemprop='articleBody']", blocks["body_selector"])
        self.assertEqual("높음", blocks["extraction_confidence"])
        self.assertEqual(2, len(blocks["body_paragraphs"]))
        self.assertEqual(1, len(blocks["image_candidates"]))
        self.assertIn("한국관광공사", " ".join(blocks["source_candidates"]))

    def test_normal_noscript_and_regular_iframe_are_not_broadly_removed(self):
        html = """
        <html><body>
        <noscript>JavaScript를 활성화해주세요.</noscript>
        <iframe src="https://video.example.test/embed"></iframe>
        <article><p>정상 기사 본문입니다.</p></article>
        </body></html>
        """
        normalized = _normalize_html_before_parse(html)
        blocks = extract_text_blocks_from_html(html)

        self.assertIn("JavaScript를 활성화해주세요.", normalized)
        self.assertIn("video.example.test/embed", normalized)
        self.assertEqual(["정상 기사 본문입니다."], blocks["body_paragraphs"])

    def test_disagreeing_article_candidates_lower_confidence(self):
        html = """
        <html><body><h1>후보 충돌 기사</h1>
        <article><p>첫 후보는 금융시장 전망과 은행 수익 변화를 길게 설명합니다.</p>
        <p>금리와 대출 증가율을 근거로 첫 번째 분석을 제시합니다.</p>
        <p>앞으로 추가 금융 통계를 확인할 필요가 있다고 설명합니다.</p></article>
        <article><p>두 번째 후보는 관광산업과 지역 방문객 변화를 길게 설명합니다.</p>
        <p>숙박과 교통 수요를 근거로 전혀 다른 분석을 제시합니다.</p>
        <p>앞으로 추가 관광 통계를 확인할 필요가 있다고 설명합니다.</p></article>
        </body></html>
        """
        blocks = extract_text_blocks_from_html(html)

        self.assertNotEqual("높음", blocks["extraction_confidence"])

    def test_generic_container_competes_with_misleading_article_candidate(self):
        """변경 회귀: 공통 article이 있어도 미등록 div 본문을 함께 비교한다."""
        html = (FIXTURE_DIR / "adaptive_competing_containers.html").read_text(
            encoding="utf-8"
        )
        blocks = extract_text_blocks_from_html(html)
        body = " ".join(blocks["body_paragraphs"])

        self.assertTrue(str(blocks["body_selector"]).startswith("adaptive:"))
        self.assertEqual(3, len(blocks["body_paragraphs"]))
        self.assertIn("첫 번째 실제 본문", body)
        self.assertNotIn("입력 2026", body)

    def test_mixed_paragraph_and_break_text_is_preserved_in_dom_order(self):
        """변경 회귀: p와 br 직접 텍스트가 섞여도 한쪽 문단을 잃지 않는다."""
        html = (FIXTURE_DIR / "mixed_paragraph_break_article.html").read_text(
            encoding="utf-8"
        )
        blocks = extract_text_blocks_from_html(html)
        body = " ".join(blocks["body_paragraphs"])

        self.assertEqual(3, len(blocks["body_paragraphs"]))
        self.assertLess(body.index("첫 번째 문단"), body.index("두 번째 문단"))
        self.assertLess(body.index("두 번째 문단"), body.index("세 번째 문단"))

    def test_nate_br_article_uses_direct_text_instead_of_image_caption(self):
        """변경 회귀: p 캡션이 있어도 더 풍부한 br 본문을 우선한다."""
        html = (FIXTURE_DIR / "nate_br_article_structure.html").read_text(
            encoding="utf-8"
        )
        blocks = extract_text_blocks_from_html(
            html,
            base_url="https://news.nate.com/view/20260608n00049",
        )
        body = " ".join(blocks["body_paragraphs"])

        self.assertEqual("#realArtcContents", blocks["body_selector"])
        self.assertEqual("높음", blocks["extraction_confidence"])
        self.assertEqual(3, len(blocks["body_paragraphs"]))
        self.assertIn("첫 번째 실제 기사 문단", body)
        self.assertNotIn("기사 이미지", body)
        self.assertNotIn("추천 기사", body)
        self.assertEqual(1, len(blocks["image_candidates"]))
        self.assertFalse(blocks["image_candidates"][0]["likely_chart"])

    def test_adaptive_selector_chooses_article_body_over_metadata_article(self):
        """변경 회귀: 첫 article이 날짜 카드여도 실제 기사 본문을 선택한다."""
        html = (FIXTURE_DIR / "adaptive_multi_article.html").read_text(encoding="utf-8")
        blocks = extract_text_blocks_from_html(
            html,
            base_url="https://www.example-news.test/news/articleView.html?idxno=100",
        )
        body = " ".join(blocks["body_paragraphs"])

        self.assertEqual("[itemprop='articleBody']", blocks["body_selector"])
        self.assertEqual("높음", blocks["extraction_confidence"])
        self.assertEqual(3, len(blocks["body_paragraphs"]))
        self.assertNotIn("입력 2025", body)
        self.assertNotIn("reporter@example.test", body)
        self.assertNotIn("관련기사", body)
        self.assertEqual(1, len(blocks["image_candidates"]))
        self.assertTrue(blocks["image_candidates"][0]["likely_chart"])
        self.assertIn("(표=대신증권)", blocks["source_candidates"])

    def test_short_metadata_article_is_not_reported_as_high_confidence(self):
        html = """
        <html><body><h1>기사 제목</h1><article>
        <p>입력 2025.12.03 15:51</p><p>수정 2025.12.19 07:35</p>
        </article></body></html>
        """
        blocks = extract_text_blocks_from_html(html)

        self.assertEqual("낮음", blocks["extraction_confidence"])

    def test_json_ld_news_article_is_used_as_standard_fallback(self):
        html = (FIXTURE_DIR / "json_ld_article.html").read_text(encoding="utf-8")
        blocks = extract_text_blocks_from_html(html)
        self.assertEqual("JSON-LD 표준 기사 제목", blocks["title"])
        self.assertEqual("json-ld:NewsArticle.articleBody", blocks["body_selector"])
        self.assertEqual(2, len(blocks["body_paragraphs"]))

    def test_nate_profile_excludes_page_noise_and_related_images(self):
        html = (FIXTURE_DIR / "nate_article_structure.html").read_text(encoding="utf-8")
        blocks = extract_text_blocks_from_html(
            html,
            base_url="https://news.nate.com/view/20260104n15377",
        )
        body = " ".join(blocks["body_paragraphs"])
        self.assertEqual("#articleContetns", blocks["body_selector"])
        self.assertEqual("높음", blocks["extraction_confidence"])
        self.assertNotIn("랭킹 TOP 100", body)
        self.assertNotIn("공유하기", body)
        self.assertNotIn("NATE Communications", body)
        self.assertEqual(2, len(blocks["image_candidates"]))
        candidate_urls = [candidate["url"] for candidate in blocks["image_candidates"]]
        self.assertIn(
            "https://news.nateimg.co.kr/orgImg/sample/chart.jpg",
            candidate_urls,
        )
        self.assertTrue(all("blank" not in url and "related" not in url for url in candidate_urls))

    def test_saved_html_fixtures_match_expected_extractions(self):
        expected = json.loads(
            (FIXTURE_DIR / "expected_extractions.json").read_text(encoding="utf-8")
        )
        for filename, contract in expected.items():
            with self.subTest(filename=filename):
                html = (FIXTURE_DIR / filename).read_text(encoding="utf-8")
                blocks = extract_text_blocks_from_html(html)
                summary = summarize_extraction(blocks)
                self.assertEqual(contract["title"], blocks["title"])
                self.assertEqual(
                    contract["body_paragraph_count"], summary["body_paragraph_count"]
                )
                self.assertEqual(
                    contract["source_candidate_count"], summary["source_candidate_count"]
                )
                if contract["visual_contains"]:
                    self.assertIn(contract["visual_contains"], " ".join(blocks["visual_texts"]))

    def test_extracts_article_and_visual_blocks(self):
        result = extract_text_blocks_from_html(SAMPLE_HTML)
        self.assertEqual("기사 제목", result["title"])
        self.assertIn("첫 번째 기사 문단입니다.", result["body_paragraphs"])
        self.assertIn("고용률 추이 차트", result["visual_texts"])
        self.assertIn("출처: 통계청, 단위: %", result["source_candidates"])

    def test_prefill_maps_to_existing_form_fields(self):
        result = prefill_form_from_html_content(SAMPLE_HTML)
        self.assertEqual("기사 제목", result["news_title"])
        self.assertIn("두 번째 문단입니다.", result["news_body"])
        self.assertEqual("검증 제한", result["draft_judgement"])
        self.assertEqual(
            {
                "news_title",
                "news_body",
                "chart_text",
                "source_text",
                "draft_judgement",
                "claim_chart_summary",
                "missing_info",
            },
            set(result),
        )

    def test_reads_uploaded_html_bytes(self):
        self.assertIn("기사 제목", read_html_from_upload(io.BytesIO(SAMPLE_HTML.encode())))

    def test_uploaded_login_wall_is_access_restricted(self):
        upload = io.BytesIO(
            "<html><body>유료회원 전용 콘텐츠입니다.</body></html>".encode("utf-8")
        )
        with self.assertRaises(AccessRestrictedError):
            read_html_from_upload(upload)

    def test_reads_cp949_uploaded_html(self):
        self.assertIn("기사 제목", read_html_from_upload(io.BytesIO(SAMPLE_HTML.encode("cp949"))))

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    @patch("frontend.html_ingestion._open_public_url")
    def test_url_fetch_returns_response_html_not_url_text(
        self, mocked_open_url, mocked_getaddrinfo
    ):
        mocked_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 443))
        ]
        mocked_open_url.return_value = FakeResponse(SAMPLE_HTML.encode())
        html = fetch_html_from_url("https://news.example.com/article")
        self.assertIn("<h1>기사 제목</h1>", html)
        self.assertNotEqual("https://news.example.com/article", html)

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    @patch("frontend.html_ingestion._open_public_url")
    def test_url_fetch_rejects_non_html_response(self, mocked_open_url, mocked_getaddrinfo):
        mocked_getaddrinfo.return_value = [
            (2, 1, 6, "", ("93.184.216.34", 443))
        ]
        mocked_open_url.return_value = FakeResponse(b"binary", "application/pdf")
        with self.assertRaises(InvalidHTMLContentError):
            fetch_html_from_url("https://news.example.com/article.pdf")

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    @patch("frontend.html_ingestion._open_public_url")
    def test_200_login_wall_is_access_restricted(
        self, mocked_open_url, mocked_getaddrinfo
    ):
        mocked_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        mocked_open_url.return_value = FakeResponse(
            "<html><title>회원 전용</title><body>로그인 후 이용해주세요.</body></html>".encode()
        )
        with self.assertRaises(AccessRestrictedError):
            fetch_html_from_url("https://news.example.com/members-only")

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    @patch("frontend.html_ingestion._open_public_url")
    def test_article_mentioning_login_is_not_false_positive(
        self, mocked_open_url, mocked_getaddrinfo
    ):
        mocked_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        article = (
            "<html><article><p>로그인 후 이용이라는 문구를 분석한 기사입니다.</p>"
            f"<p>{'충분히 긴 정상 기사 본문입니다. ' * 200}</p></article></html>"
        )
        mocked_open_url.return_value = FakeResponse(article.encode())
        self.assertIn("정상 기사", fetch_html_from_url("https://news.example.com/article"))

    def test_falls_back_to_all_paragraphs_without_article(self):
        result = extract_text_blocks_from_html("<h1>제목</h1><div><p>본문입니다.</p></div>")
        self.assertEqual(["본문입니다."], result["body_paragraphs"])

    def test_extraction_summary_reports_missing_visual_metadata(self):
        blocks = extract_text_blocks_from_html("<h1>제목</h1><article><p>본문</p></article>")
        summary = summarize_extraction(blocks)
        self.assertEqual(1, summary["body_paragraph_count"])
        self.assertIn("시각자료 관련 텍스트", summary["missing_fields"])
        self.assertIn("출처·단위 후보", summary["missing_fields"])

    def test_rejects_empty_upload(self):
        with self.assertRaises(InvalidHTMLContentError):
            read_html_from_upload(io.BytesIO(b""))

    def test_rejects_non_http_url_before_request(self):
        with self.assertRaises(InvalidArticleURLError):
            fetch_html_from_url("file:///private/article.html")

    def test_rejects_url_with_embedded_credentials(self):
        with self.assertRaises(InvalidArticleURLError):
            fetch_html_from_url("https://user:secret@news.example.com/article")

    def test_rejects_direct_private_and_link_local_addresses(self):
        for url in (
            "http://127.0.0.1/article",
            "http://169.254.169.254/latest/meta-data",
            "http://10.0.0.8/article",
            "http://[::1]/article",
        ):
            with self.subTest(url=url), self.assertRaises(InvalidArticleURLError):
                fetch_html_from_url(url)

    def test_rejects_private_redirect_before_following_it(self):
        handler = _SafeRedirectHandler()
        with self.assertRaises(InvalidArticleURLError):
            handler.redirect_request(
                Request("https://news.example.com/article"),
                None,
                302,
                "Found",
                {},
                "http://127.0.0.1/internal",
            )

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    def test_rejects_hostname_resolving_to_private_ipv4(self, mocked_getaddrinfo):
        mocked_getaddrinfo.return_value = [(2, 1, 6, "", ("10.0.0.8", 443))]
        with self.assertRaises(InvalidArticleURLError):
            fetch_html_from_url("https://news.example.com/article")

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    def test_rejects_hostname_resolving_to_private_ipv6(self, mocked_getaddrinfo):
        mocked_getaddrinfo.return_value = [(23, 1, 6, "", ("::1", 443, 0, 0))]
        with self.assertRaises(InvalidArticleURLError):
            fetch_html_from_url("https://news.example.com/article")

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    @patch("frontend.html_ingestion._open_public_url")
    def test_rejects_oversized_html_response(self, mocked_open_url, mocked_getaddrinfo):
        mocked_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        mocked_open_url.return_value = FakeResponse(b"x" * (MAX_HTML_BYTES + 1))
        with self.assertRaises(InvalidHTMLContentError):
            fetch_html_from_url("https://news.example.com/large")

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    @patch("frontend.html_ingestion._open_public_url")
    def test_timeout_becomes_fetch_error(self, mocked_open_url, mocked_getaddrinfo):
        mocked_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        mocked_open_url.side_effect = TimeoutError("timeout")
        with self.assertRaises(ArticleFetchTimeoutError):
            fetch_html_from_url("https://news.example.com/slow")

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    @patch("frontend.html_ingestion._open_public_url")
    def test_explicit_http_restrictions_are_classified(
        self, mocked_open_url, mocked_getaddrinfo
    ):
        mocked_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        for code in (401, 403, 429, 451):
            with self.subTest(code=code):
                mocked_open_url.side_effect = HTTPError(
                    "https://news.example.com/article", code, "restricted", {}, None
                )
                with self.assertRaises(AccessRestrictedError):
                    fetch_html_from_url("https://news.example.com/article")

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    @patch("frontend.html_ingestion._open_public_url")
    def test_missing_articles_are_fetch_failures(
        self, mocked_open_url, mocked_getaddrinfo
    ):
        mocked_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        for code in (404, 410):
            with self.subTest(code=code):
                mocked_open_url.side_effect = HTTPError(
                    "https://news.example.com/missing", code, "missing", {}, None
                )
                with self.assertRaises(ArticleNotFoundError):
                    fetch_html_from_url("https://news.example.com/missing")

    @patch("frontend.html_ingestion.socket.getaddrinfo")
    @patch("frontend.html_ingestion._open_public_url")
    def test_downloads_only_supported_image_response(self, mocked_open_url, mocked_getaddrinfo):
        mocked_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 443))]
        mocked_open_url.return_value = FakeResponse(b"jpeg-data", "image/jpeg")
        result = download_image_from_url("https://images.example.com/chart.jpg")
        self.assertEqual(b"jpeg-data", result["data"])
        self.assertEqual(".jpg", result["suffix"])

    def test_error_message_keeps_manual_input_available(self):
        message = get_ingestion_error_message(InvalidHTMLContentError("HTML이 비어 있습니다."))
        self.assertIn("직접 입력", message)

    def test_restricted_and_fetch_failure_messages_are_distinct(self):
        restricted = get_ingestion_error_message(AccessRestrictedError("blocked"))
        missing = get_ingestion_error_message(ArticleNotFoundError("missing"))
        timeout = get_ingestion_error_message(ArticleFetchTimeoutError("timeout"))

        self.assertIn("자동 요청을 제한", restricted)
        self.assertIn("찾지 못했습니다", missing)
        self.assertIn("시간 안에", timeout)


if __name__ == "__main__":
    unittest.main()
