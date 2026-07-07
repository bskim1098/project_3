"""뉴스 URL/스크랩 HTML을 기존 입력 폼 값으로 바꾸는 전처리 도구.

변경 배경:
- URL 문자열 자체를 LLM에 전달하던 구조가 아니라 HTML 원문을 먼저 확보한다.
- 현재 단일 에이전트 단계에서는 규칙 기반 추출까지만 담당한다.
- 추후 주장-근거 검증 에이전트가 ``extract_text_blocks_from_html`` 결과를
  받아 고도화할 수 있도록 네트워크·추출·폼 매핑 경계를 분리했다.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup, Tag


MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024
SOURCE_HINTS = ("출처", "자료", "단위", "주석", "source", "caption", "통계")
VISUAL_HINTS = ("차트", "그래프", "도표", "표 ", "통계", "추이", "chart", "graph", "table")
ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
ACCESS_RESTRICTION_MARKERS = (
    "access denied",
    "request has been blocked",
    "automated access",
    "too many requests",
    "로그인이 필요합니다",
    "로그인 후 이용",
    "구독 후 이용",
    "유료회원 전용",
    "접근이 제한되었습니다",
    "비정상적인 접근",
)

NOSCRIPT_BLOCK_PATTERN = re.compile(
    r"<noscript\b[^>]*>.*?</noscript\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)

SITE_PROFILES: dict[str, dict[str, list[str]]] = {
    "news.nate.com": {
        # 네이트는 실제 기사 본문 id에 Contetns 오타가 포함되어 있다.
        # 일부 제휴 언론사는 실제 본문을 더 안쪽 realArtcContents에 br 기반으로 둔다.
        "body_selectors": ["#realArtcContents", "#articleContetns"],
        # 실제 태그에 id가 중복되는 경우가 있어 GoImg 호출도 함께 사용한다.
        "image_selectors": ["img[onclick*='GoImg']", "img[id^='mainimg']"],
        "exclude_selectors": [],
    },
}

COMMON_BODY_SELECTORS = [
    # 변경: 명시적인 기사 본문 표준을 넓은 article 태그보다 먼저 평가한다.
    # 실제 선택은 첫 요소가 아니라 아래 모든 selector 후보의 점수를 비교한다.
    "[itemprop='articleBody']",
    "main article",
    "main .article-body",
    ".article-body",
    ".article_body",
    ".news-body",
    ".news_body",
    ".article-content",
    ".article_content",
    "article",
]

NOISE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "nav",
    "aside",
    "form",
    "button",
    "iframe",
    ".advertisement",
    ".advert",
    ".ad",
    ".ads",
    ".ranking",
    ".rank",
    ".related",
    ".relation",
    ".recommend",
    ".share",
    ".social",
    ".comment",
    ".article-footer",
    ".article-relation",
    ".related-news",
    ".reporter-box",
]

NOISE_TEXT_PATTERNS = (
    "공유하기",
    "랭킹 TOP",
    "전체보기",
    "네이트온",
    "페이스북",
    "기사전송",
    "© NATE Communications",
)

# 본문 컨테이너 내부에 추천 기사까지 포함된 CMS에서 이 경계 이후를 기사 본문으로
# 취급하지 않는다. 짧은 독립 문단에만 적용해 기사 문장 안의 동명 표현은 보존한다.
BODY_END_PATTERNS = (
    "저작권자",
    "copyrightⓒ",
    "copyright ©",
    "무단전재 및 재배포 금지",
    "관련기사",
    "기자의 다른기사",
    "기자의 인기기사",
    "가장 많이 읽은 기사",
    "이 시각 많이 본 뉴스",
    "ⓒ중앙일보",
)

METADATA_ONLY_PATTERNS = (
    re.compile(r"^(?:입력|수정|승인)\s*\d{4}[.\-/]\d{1,2}[.\-/]\d{1,2}"),
    re.compile(r"^(?:기자명|작성자)\s*"),
    re.compile(r"^댓글\s*\d*"),
)

IGNORED_IMAGE_TEXTS = {"빈이미지", "slide", "logo", "icon", "광고"}
IGNORED_IMAGE_PATH_HINTS = ("blank", "ico_", "/icon/", "logo", "spacer", "pixel")
IGNORED_BODY_TEXTS = {"기사 이미지", "이미지", "사진"}


class ImageCandidate(TypedDict):
    """기사 본문 안에서 발견한 사용자 선택용 이미지 후보."""

    url: str
    alt: str
    caption: str
    label: str
    likely_chart: bool
    chart_score: NotRequired[int]
    selection_reasons: NotRequired[list[str]]
    exclusion_reasons: NotRequired[list[str]]


class DownloadedImage(TypedDict):
    """안전 검사를 통과한 원격 이미지 데이터."""

    data: bytes
    suffix: str
    final_url: str


class HTMLTextBlocks(TypedDict):
    """주장-근거 검증 에이전트에 넘길 수 있는 전처리 결과 계약."""

    title: str
    body_paragraphs: list[str]
    visual_texts: list[str]
    source_candidates: list[str]
    image_candidates: NotRequired[list[ImageCandidate]]
    body_selector: NotRequired[str]
    extraction_confidence: NotRequired[str]
    document_url: NotRequired[str]


class FormPrefill(TypedDict):
    """기존 Streamlit 입력 폼과의 자동 채움 계약."""

    news_title: str
    news_body: str
    chart_text: str
    source_text: str
    draft_judgement: str
    claim_chart_summary: str
    missing_info: str


@dataclass
class _TextExtraction:
    """한 DOM 후보에 적용한 문단 추출 방식과 품질 점수."""

    method: str
    blocks: list[str]
    score: int


@dataclass
class _ArticleCandidate:
    """사이트 규칙과 무관하게 경쟁하는 내부 기사 본문 후보."""

    element: Tag
    selector: str
    profile_hint: bool = False
    structured_hint: bool = False
    blocks: list[str] | None = None
    score: int = -10_000


class HTMLIngestionError(Exception):
    """사용자에게 수동 입력 대안을 안내할 수 있는 HTML 처리 오류."""


class InvalidArticleURLError(HTMLIngestionError):
    """지원하지 않거나 안전하지 않은 기사 URL."""


class ArticleFetchError(HTMLIngestionError):
    """기사 서버 요청 실패."""


class AccessRestrictedError(ArticleFetchError):
    """기사 서버가 자동 요청 또는 접근을 명시적으로 제한함."""


class ArticleNotFoundError(ArticleFetchError):
    """요청한 기사 URL이 존재하지 않거나 더 이상 제공되지 않음."""


class ArticleFetchTimeoutError(ArticleFetchError):
    """제한 시간 안에 기사 서버 응답을 받지 못함."""


class InvalidHTMLContentError(HTMLIngestionError):
    """비어 있거나 HTML이 아닌 입력."""


def _raise_if_access_restricted_html(html: str) -> None:
    """200 응답이어도 차단·로그인 안내만 있는 짧은 문서는 제한으로 분류한다."""
    soup = BeautifulSoup(html, "html.parser")
    page_text = " ".join(soup.get_text(" ", strip=True).split())
    normalized = page_text.casefold()

    # 정상 기사에서 제한 관련 단어를 인용할 수 있으므로, 페이지 전체가 짧고
    # 명시적인 안내 문구가 있을 때만 제한으로 본다.
    if len(page_text) <= 3000 and any(
        marker in normalized for marker in ACCESS_RESTRICTION_MARKERS
    ):
        raise AccessRestrictedError("기사 대신 로그인·구독 또는 접근 제한 화면이 반환되었습니다.")


def _validate_public_http_url(url: str) -> str:
    normalized = url.strip()
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise InvalidArticleURLError("http 또는 https 형식의 뉴스 기사 URL을 입력해주세요.")
    if parsed.username is not None or parsed.password is not None:
        raise InvalidArticleURLError("사용자명이나 비밀번호가 포함된 URL은 사용할 수 없습니다.")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"}:
        raise InvalidArticleURLError("로컬 주소는 기사 URL로 사용할 수 없습니다.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        address = None
    if address and not address.is_global:
        raise InvalidArticleURLError("사설 또는 로컬 네트워크 주소는 사용할 수 없습니다.")
    if address is None:
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            resolved = socket.getaddrinfo(
                parsed.hostname,
                port,
                type=socket.SOCK_STREAM,
            )
        except (socket.gaierror, ValueError) as error:
            raise ArticleFetchError("기사 URL의 주소를 확인하지 못했습니다.") from error
        if not resolved:
            raise ArticleFetchError("기사 URL의 주소를 확인하지 못했습니다.")
        for entry in resolved:
            # IPv6 link-local 주소에 붙을 수 있는 scope id(%eth0)는 IP 판정에서 제외한다.
            resolved_host = str(entry[4][0]).split("%", 1)[0]
            resolved_address = ipaddress.ip_address(resolved_host)
            if not resolved_address.is_global:
                raise InvalidArticleURLError(
                    "사설 또는 로컬 네트워크로 연결되는 URL은 사용할 수 없습니다."
                )
    return normalized


class _SafeRedirectHandler(HTTPRedirectHandler):
    """리다이렉트 대상에 연결하기 전에 URL과 DNS를 다시 검증한다."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_http_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_public_url(request: Request, timeout: float):
    """안전한 리다이렉트 핸들러를 적용해 공개 URL만 연다."""
    return build_opener(_SafeRedirectHandler()).open(request, timeout=timeout)


def _decode_html_bytes(raw: bytes, declared_charset: str | None = None) -> str:
    """HTTP 헤더·meta 선언과 실제 바이트가 다를 때 한글이 덜 깨지는 인코딩을 고른다."""
    head = raw[:8192].decode("ascii", errors="ignore")
    meta_match = re.search(
        r"charset\s*=\s*['\"]?([a-zA-Z0-9._-]+)",
        head,
        flags=re.IGNORECASE,
    )
    candidates = [
        declared_charset or "",
        meta_match.group(1) if meta_match else "",
        "utf-8-sig",
        "utf-8",
        "cp949",
        "euc-kr",
    ]
    for encoding in _ordered_unique(candidates):
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize_html_before_parse(html: str) -> str:
    """브라우저와 달리 기본 파서를 무너뜨리는 추적용 비정상 블록만 제거한다.

    변경 범위:
    - noscript 안에 iframe 시작 태그가 있지만 닫는 iframe 태그가 없는 경우만 제거한다.
    - 정상 noscript와 noscript 밖의 iframe은 원본 그대로 보존한다.
    - 특정 언론사 selector가 아니라 파싱 전에 적용되는 일반 복구 규칙이다.
    """

    def replace_malformed_block(match: re.Match[str]) -> str:
        block = match.group(0)
        lowered = block.lower()
        if re.search(r"<iframe\b", lowered) and "</iframe" not in lowered:
            return ""
        return block

    return NOSCRIPT_BLOCK_PATTERN.sub(replace_malformed_block, html)


def fetch_html_from_url(url: str, timeout: float = 12.0) -> str:
    """기사 URL에서 HTML을 가져온다. URL 문자열은 분석 입력으로 쓰지 않는다."""
    safe_url = _validate_public_http_url(url)
    request = Request(
        safe_url,
        headers={"User-Agent": "DataChecker/1.0 (+news-chart-evidence-review)"},
    )
    try:
        with _open_public_url(request, timeout=timeout) as response:
            _validate_public_http_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise InvalidHTMLContentError("URL 응답이 HTML 문서가 아닙니다.")
            raw = response.read(MAX_HTML_BYTES + 1)
            if len(raw) > MAX_HTML_BYTES:
                raise InvalidHTMLContentError("HTML 문서가 허용 크기(5MB)를 초과했습니다.")
            charset = response.headers.get_content_charset() or "utf-8"
    except InvalidArticleURLError:
        raise
    except InvalidHTMLContentError:
        raise
    except HTTPError as error:
        if error.code in {401, 403, 429, 451}:
            raise AccessRestrictedError(
                f"기사 서버가 HTTP {error.code} 접근 제한을 반환했습니다."
            ) from error
        if error.code in {404, 410}:
            raise ArticleNotFoundError(
                f"기사 서버가 HTTP {error.code} 응답을 반환했습니다."
            ) from error
        raise ArticleFetchError(f"기사 서버가 HTTP {error.code} 오류를 반환했습니다.") from error
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", None)
        if isinstance(error, TimeoutError) or isinstance(reason, TimeoutError):
            raise ArticleFetchTimeoutError(
                "제한 시간 안에 기사 HTML을 가져오지 못했습니다."
            ) from error
        raise ArticleFetchError("제한 시간 안에 기사 HTML을 가져오지 못했습니다.") from error
    html = _decode_html_bytes(raw, charset)
    _raise_if_access_restricted_html(html)
    return html


def download_image_from_url(url: str, timeout: float = 12.0) -> DownloadedImage:
    """사용자가 선택한 기사 이미지 하나를 공개 URL에서 안전하게 내려받는다."""
    safe_url = _validate_public_http_url(url)
    request = Request(
        safe_url,
        headers={
            "User-Agent": "DataChecker/1.0 (+news-chart-evidence-review)",
            "Accept": "image/jpeg,image/png,image/webp",
        },
    )
    try:
        with _open_public_url(request, timeout=timeout) as response:
            final_url = _validate_public_http_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in ALLOWED_IMAGE_TYPES:
                raise InvalidHTMLContentError("선택한 URL의 응답이 지원되는 이미지가 아닙니다.")
            data = response.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                raise InvalidHTMLContentError("이미지 파일이 허용 크기(10MB)를 초과했습니다.")
    except (InvalidArticleURLError, InvalidHTMLContentError):
        raise
    except HTTPError as error:
        raise ArticleFetchError(f"이미지 서버가 HTTP {error.code} 오류를 반환했습니다.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise ArticleFetchError("제한 시간 안에 기사 이미지를 가져오지 못했습니다.") from error
    return {
        "data": data,
        "suffix": ALLOWED_IMAGE_TYPES[content_type],
        "final_url": final_url,
    }


def read_html_from_upload(uploaded_file: Any) -> str:
    """Streamlit 업로드 객체에서 스크랩 HTML 문자열을 읽는다."""
    raw = uploaded_file.getvalue() if hasattr(uploaded_file, "getvalue") else uploaded_file.read()
    if not raw:
        raise InvalidHTMLContentError("업로드한 HTML 파일이 비어 있습니다.")
    if len(raw) > MAX_HTML_BYTES:
        raise InvalidHTMLContentError("HTML 파일이 허용 크기(5MB)를 초과했습니다.")
    html = raw if isinstance(raw, str) else _decode_html_bytes(raw)
    _raise_if_access_restricted_html(html)
    return html


def _ordered_unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _class_names(element: Tag) -> list[str]:
    """BeautifulSoup의 class 속성을 항상 문자열 목록으로 정규화한다."""
    raw_classes = element.get("class")
    if raw_classes is None:
        return []
    if isinstance(raw_classes, list):
        return [str(item) for item in raw_classes]
    return str(raw_classes).split()


def _document_url(soup: BeautifulSoup, base_url: str) -> str:
    canonical = soup.select_one("link[rel='canonical']")
    if canonical and canonical.get("href"):
        return str(canonical.get("href")).strip()
    og_url = soup.select_one("meta[property='og:url']")
    if og_url and og_url.get("content"):
        return str(og_url.get("content")).strip()
    return base_url.strip()


def _site_profile(document_url: str) -> dict[str, list[str]]:
    hostname = (urlparse(document_url).hostname or "").lower()
    return SITE_PROFILES.get(hostname, {})


def _clean_article_fragment(element: Tag | BeautifulSoup) -> BeautifulSoup:
    """본문 경계 이후와 공통 UI 잡음을 제거한 독립 DOM 조각을 만든다."""
    fragment = BeautifulSoup(str(element), "html.parser")

    # 변경: 저작권 문구가 p가 아닌 div의 직접 텍스트인 언론사도 있다. 문단을
    # 뽑기 전에 DOM 순서상 경계 이후 태그를 제거해야 추천 기사 문단·이미지가
    # 본문과 시각자료 후보에 섞이지 않는다.
    for text_node in fragment.find_all(string=True):
        text = _clean_text(text_node)
        if len(text) <= 160 and any(
            pattern.lower() in text.lower() for pattern in BODY_END_PATTERNS
        ):
            for following in list(text_node.find_all_next()):
                if isinstance(following, Tag):
                    following.decompose()
            text_node.extract()
            break

    for selector in NOISE_SELECTORS:
        for noise in fragment.select(selector):
            noise.decompose()
    return fragment


def _normalize_body_blocks(values: list[str]) -> list[str]:
    normalized = []
    ignored = {item.lower() for item in IGNORED_BODY_TEXTS}
    for value in values:
        text = _clean_text(value)
        if len(text) < 2 or text.lower() in ignored:
            continue
        normalized.append(text)
    return _ordered_unique(normalized)


def _score_text_extraction(method: str, blocks: list[str], structural_bonus: int = 0) -> int:
    if not blocks:
        return -10_000
    total_size = sum(len(block) for block in blocks)
    metadata_count = sum(
        1
        for block in blocks
        if any(pattern.search(block) for pattern in METADATA_ONLY_PATTERNS)
    )
    short_count = sum(1 for block in blocks if len(block) < 20)
    expected_block_count = max(3, total_size // 100 + 3)
    fragmentation_penalty = max(0, len(blocks) - expected_block_count) * 120
    noise_count = sum(
        1
        for block in blocks
        if any(pattern.lower() in block.lower() for pattern in NOISE_TEXT_PATTERNS)
    )
    method_bonus = 80 if method == "paragraph" else 0
    return (
        total_size
        + len(blocks) * 90
        + structural_bonus
        + method_bonus
        - metadata_count * 350
        - short_count * 35
        - noise_count * 250
        - fragmentation_penalty
    )


def _text_extraction_variants(fragment: BeautifulSoup) -> list[_TextExtraction]:
    """같은 후보에서 p와 br/혼합 DOM 결과를 독립적으로 생성한다."""
    paragraph_values: list[str] = []
    for paragraph in fragment.find_all("p"):
        text = _clean_text(paragraph.get_text(" ", strip=True))
        link_text = sum(
            len(_clean_text(link.get_text(" ", strip=True)))
            for link in paragraph.find_all("a")
        )
        if not text or text.lower() in {item.lower() for item in IGNORED_BODY_TEXTS}:
            continue
        if link_text and link_text / len(text) > 0.6:
            continue
        paragraph_values.append(text)

    paragraph_values = _normalize_body_blocks(paragraph_values)

    # 변경: p 캡션 하나 때문에 br fallback이 막히지 않도록 별도 DOM 복제본에서
    # br을 줄 경계로 바꾼다. 이 결과에는 p와 직접 텍스트가 DOM 순서대로 함께 담긴다.
    br_count = len(fragment.find_all("br"))
    line_fragment = BeautifulSoup(str(fragment), "html.parser")
    for line_break in line_fragment.find_all("br"):
        line_break.replace_with("\n")
    line_values = _normalize_body_blocks([
        _clean_text(line)
        for line in line_fragment.get_text("\n", strip=True).splitlines()
    ])

    return [
        _TextExtraction(
            method="paragraph",
            blocks=paragraph_values,
            score=_score_text_extraction("paragraph", paragraph_values),
        ),
        _TextExtraction(
            method="dom-lines",
            blocks=line_values,
            score=(
                _score_text_extraction(
                    "dom-lines",
                    line_values,
                    structural_bonus=120 if br_count >= 2 else 0,
                )
                if br_count
                else -10_000
            ),
        ),
    ]


def _best_text_extraction(fragment: BeautifulSoup) -> _TextExtraction:
    variants = _text_extraction_variants(fragment)
    return max(variants, key=lambda extraction: extraction.score)


def _body_text_candidates(fragment: BeautifulSoup) -> list[str]:
    """여러 문단 추출 방식 중 품질 점수가 가장 높은 결과를 반환한다."""
    return _best_text_extraction(fragment).blocks


def _container_features(element: Tag) -> tuple[str, list[str], int]:
    """후보를 같은 기준으로 비교할 수 있도록 본문 특징을 계산한다."""
    fragment = _clean_article_fragment(element)
    paragraphs = _body_text_candidates(fragment)
    text = _clean_text(" ".join(paragraphs))
    link_text = sum(
        len(_clean_text(link.get_text(" ", strip=True))) for link in fragment.find_all("a")
    )
    return text, paragraphs, link_text


def _container_score(element: Tag) -> int:
    """사이트명이 아니라 DOM 의미와 텍스트 밀도로 기사 본문 가능성을 평가한다."""
    text, paragraphs, link_text = _container_features(element)
    if not text or not paragraphs:
        return -10_000

    normalized_itemprop = str(element.get("itemprop") or "").lower()
    identifier = " ".join(
        [str(element.get("id") or ""), *_class_names(element)]
    ).lower()
    semantic_bonus = 0
    if "articlebody" in normalized_itemprop:
        semantic_bonus += 1200
    if re.search(r"article[-_ ]?(?:body|content)|(?:body|content)[-_ ]?article", identifier):
        semantic_bonus += 450
    if element.name == "article":
        semantic_bonus += 180
    elif element.name == "main":
        semantic_bonus += 100

    metadata_count = sum(
        1
        for paragraph in paragraphs
        if any(pattern.search(paragraph) for pattern in METADATA_ONLY_PATTERNS)
    )
    noise_penalty = sum(
        300 for pattern in NOISE_TEXT_PATTERNS if pattern.lower() in text.lower()
    )
    short_penalty = 700 if len(text) < 80 else 0
    metadata_penalty = metadata_count * 450
    link_penalty = int(link_text * 2.5)
    sentence_bonus = min(text.count(".") + text.count("다.") + text.count("”"), 20) * 20

    return (
        len(text)
        + len(paragraphs) * 140
        + sentence_bonus
        + semantic_bonus
        - link_penalty
        - noise_penalty
        - short_penalty
        - metadata_penalty
    )


def _text_similarity(left: list[str], right: list[str]) -> float:
    left_tokens = set(re.findall(r"\w+", " ".join(left).lower()))
    right_tokens = set(re.findall(r"\w+", " ".join(right).lower()))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _adaptive_confidence(
    best: _ArticleCandidate,
    second: _ArticleCandidate | None,
) -> str:
    """본문 품질, 후보 간 점수 차이와 결과 합의를 함께 평가한다."""
    paragraphs = best.blocks or []
    text = _clean_text(" ".join(paragraphs))
    non_metadata = [
        paragraph
        for paragraph in paragraphs
        if not any(pattern.search(paragraph) for pattern in METADATA_ONLY_PATTERNS)
    ]
    if not non_metadata or len(text) < 40 or best.score < 0:
        return "낮음"

    clear_winner = second is None or best.score - second.score >= max(250, best.score * 0.12)
    candidate_agreement = second is not None and _text_similarity(
        non_metadata,
        second.blocks or [],
    ) >= 0.72

    # 같은 DOM에 p와 br 표현이 함께 있을 때 의미 있는 두 추출 결과가 크게
    # 다르면 자동 확신을 낮춘다. 한쪽이 캡션뿐인 경우는 비교에서 제외한다.
    variants = _text_extraction_variants(_clean_article_fragment(best.element))
    meaningful_variants = [
        variant
        for variant in variants
        if variant.blocks and sum(len(item) for item in variant.blocks) >= len(text) * 0.45
    ]
    extraction_agreement = True
    if len(meaningful_variants) >= 2:
        extraction_agreement = _text_similarity(
            meaningful_variants[0].blocks,
            meaningful_variants[1].blocks,
        ) >= 0.45

    stable_choice = clear_winner or candidate_agreement or second is None
    if (
        len(non_metadata) >= 3
        and len(text) >= 180
        and stable_choice
        and extraction_agreement
    ):
        return "높음"
    if (
        (best.profile_hint or best.structured_hint)
        and len(non_metadata) >= 2
        and stable_choice
        and extraction_agreement
    ):
        return "높음"
    if len(non_metadata) >= 2 or len(text) >= 100:
        return "보통"
    return "낮음"


def _candidate_label(element: Tag) -> str:
    identifier = str(element.get("id") or "").strip()
    if identifier:
        return f"adaptive:#{identifier}"
    classes = [item.strip() for item in _class_names(element) if item.strip()]
    if classes:
        return "adaptive:." + ".".join(classes[:3])
    return f"adaptive:{element.name}"


def _has_body_structure(element: Tag) -> bool:
    if element.find("p") is not None or element.find("br") is not None:
        return True
    text = _clean_text(element.get_text(" ", strip=True))
    return element.name in {"article", "main", "section"} and len(text) >= 80


def _collect_body_candidates(
    soup: BeautifulSoup,
    document_url: str,
) -> list[_ArticleCandidate]:
    """프로필·표준·일반 DOM·JSON-LD 후보를 하나의 경쟁 목록으로 만든다."""
    candidates: dict[int, _ArticleCandidate] = {}

    def register(
        element: Tag,
        selector: str,
        *,
        profile_hint: bool = False,
        structured_hint: bool = False,
    ) -> None:
        if not _has_body_structure(element):
            return
        key = id(element)
        current = candidates.get(key)
        if current is None:
            candidates[key] = _ArticleCandidate(
                element=element,
                selector=selector,
                profile_hint=profile_hint,
                structured_hint=structured_hint,
            )
            return
        current.profile_hint = current.profile_hint or profile_hint
        current.structured_hint = current.structured_hint or structured_hint
        if profile_hint or structured_hint:
            current.selector = selector

    profile = _site_profile(document_url)
    for selector in profile.get("body_selectors", []):
        for element in soup.select(selector):
            if isinstance(element, Tag):
                register(element, selector, profile_hint=True)

    for selector in COMMON_BODY_SELECTORS:
        for element in soup.select(selector):
            if isinstance(element, Tag):
                register(
                    element,
                    selector,
                    structured_hint="articleBody" in selector,
                )

    # 변경: 공통 article이 하나 발견됐다는 이유로 탐색을 끝내지 않는다. 이름을
    # 모르는 div/section도 p 또는 br 구조가 있으면 동일한 후보군에 넣는다.
    for element in soup.find_all(["main", "article", "section", "div"]):
        if isinstance(element, Tag) and _has_body_structure(element):
            register(element, _candidate_label(element))

    json_ld = _json_ld_news_article(soup)
    article_body = str(json_ld.get("articleBody") or "").strip()
    if article_body:
        synthetic_soup = BeautifulSoup("<article></article>", "html.parser")
        synthetic_article = synthetic_soup.find("article")
        if isinstance(synthetic_article, Tag):
            raw_blocks = [
                _clean_text(block)
                for block in re.split(r"(?:\r?\n){2,}", article_body)
                if _clean_text(block)
            ]
            for block in raw_blocks:
                paragraph = synthetic_soup.new_tag("p")
                paragraph.string = block
                synthetic_article.append(paragraph)
            register(
                synthetic_article,
                "json-ld:NewsArticle.articleBody",
                structured_hint=True,
            )

    for candidate in candidates.values():
        fragment = _clean_article_fragment(candidate.element)
        extraction = _best_text_extraction(fragment)
        candidate.blocks = extraction.blocks
        candidate.score = _container_score(candidate.element) + extraction.score
        if candidate.profile_hint:
            candidate.score += 600
        if candidate.structured_hint:
            candidate.score += 450

    # 변경: 페이지 전체 wrapper는 실제 본문 후보를 포함한다는 이유만으로 더 많은
    # 텍스트 점수를 얻기 쉽다. 거의 같은 본문을 가진 더 좁은 자식 후보가 있으면
    # 부모의 추가 블록 수에 비례해 감점해 기사 경계를 좁게 잡는다.
    candidate_by_element_id = {
        id(candidate.element): candidate for candidate in candidates.values()
    }
    for child in candidates.values():
        child_size = sum(len(block) for block in child.blocks or [])
        if child_size <= 0:
            continue
        for ancestor in child.element.parents:
            if not isinstance(ancestor, Tag):
                continue
            parent = candidate_by_element_id.get(id(ancestor))
            if parent is None or not parent.blocks:
                continue
            parent_size = sum(len(block) for block in parent.blocks)
            coverage = child_size / max(parent_size, 1)
            similarity = _text_similarity(child.blocks or [], parent.blocks)
            if coverage < 0.55 and similarity < 0.55:
                continue
            extra_blocks = max(0, len(parent.blocks) - len(child.blocks or []))
            parent.score -= 900 + extra_blocks * 150

    return [candidate for candidate in candidates.values() if candidate.blocks]


def _json_ld_news_article(soup: BeautifulSoup) -> dict[str, Any]:
    """표준 JSON-LD에서 첫 NewsArticle/Article 객체를 찾는다."""

    def walk(value: Any):
        if isinstance(value, dict):
            article_type = value.get("@type")
            types = article_type if isinstance(article_type, list) else [article_type]
            if any(item in {"NewsArticle", "Article"} for item in types):
                yield value
            for nested in value.values():
                yield from walk(nested)
        elif isinstance(value, list):
            for nested in value:
                yield from walk(nested)

    for script in soup.select("script[type='application/ld+json']"):
        try:
            payload = json.loads(script.string or script.get_text() or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for article in walk(payload):
            if article.get("articleBody") or article.get("headline"):
                return article
    return {}


def _select_body_container(
    soup: BeautifulSoup,
    document_url: str,
) -> tuple[Tag | None, str, str]:
    candidates = _collect_body_candidates(soup, document_url)
    if not candidates:
        return None, "확인되지 않음", "낮음"
    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    return best.element, best.selector, _adaptive_confidence(best, second)


def _is_noise_text(text: str) -> bool:
    normalized = _clean_text(text)
    if not normalized:
        return True
    if (
        len(normalized) <= 160
        and re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", normalized)
        and re.search(r"(?:기자|특파원)", normalized)
    ):
        return True
    if len(normalized) <= 30 and re.fullmatch(
        r"[가-힣]{2,5}\s+(?:기자|특파원)", normalized
    ):
        return True
    return any(pattern.lower() in normalized.lower() for pattern in NOISE_TEXT_PATTERNS)


def _extract_body_paragraphs(container: Tag | None, confidence: str) -> list[str]:
    if container is None:
        return []
    fragment = _clean_article_fragment(container)

    paragraphs: list[str] = []
    for text in _body_text_candidates(fragment):
        if len(text) <= 120 and any(
            pattern.lower() in text.lower() for pattern in BODY_END_PATTERNS
        ):
            break
        if _is_noise_text(text):
            continue
        if len(text) < 100 and (
            any(text.lower().startswith(hint.lower()) for hint in SOURCE_HINTS)
            or bool(re.match(r"\((?:표|사진|그래프|자료)\s*=", text))
        ):
            continue
        paragraphs.append(text)
    return _ordered_unique(paragraphs)


def _has_visual_hint(text: str) -> bool:
    """'대표' 오탐 없이 '(표=출처)' 같은 짧은 캡션까지 인식한다."""
    normalized = _clean_text(text).lower()
    if not normalized:
        return False
    non_table_hints = [hint for hint in VISUAL_HINTS if hint.strip() != "표"]
    if any(hint in normalized for hint in non_table_hints):
        return True
    return bool(re.search(r"(?:^|[\s(\[])표(?:$|[\s=:\])])", normalized))


def _is_source_candidate(text: str) -> bool:
    normalized = _clean_text(text)
    return any(hint.lower() in normalized.lower() for hint in SOURCE_HINTS) or bool(
        re.search(r"\((?:표|사진|그래프|자료)\s*=", normalized)
    )


def _extract_image_url(image: Tag) -> str:
    onclick = str(image.get("onclick") or "")
    original_match = re.search(r"GoImg\(['\"]([^'\"]+)", onclick)
    if original_match:
        return original_match.group(1)
    for attribute in ("data-original", "data-src", "data-lazy-src", "src"):
        value = image.get(attribute)
        if value:
            return str(value).strip()
    srcset = str(image.get("srcset") or "").strip()
    return srcset.split(",")[0].strip().split(" ")[0] if srcset else ""


def _numeric_dimension(image: Tag, name: str) -> int | None:
    match = re.search(r"\d+", str(image.get(name) or ""))
    return int(match.group()) if match else None


_CHART_STRONG_HINTS = ("차트", "그래프", "도표", "인포그래픽", "chart", "graph")
_CHART_CONTEXT_HINTS = (
    "전망", "증감률", "추이", "비중", "현황", "통계", "분포", "지표", "단위", "출처",
)
_PHOTO_HINTS = (
    "자료사진", "현장사진", "기념촬영", "포토", "기자", "프로필", "인물", "photo",
)
_PROFILE_HINTS = ("reporter", "author", "profile", "avatar", "byline")
_AD_HINTS = ("advert", "banner", "promotion", "광고", "배너")


def _score_chart_image_candidate(
    image: Tag,
    url: str,
    alt: str,
    caption: str,
    width: int | None,
    height: int | None,
) -> tuple[int, list[str], list[str]]:
    """HTML 메타정보만으로 표·차트 후보 점수와 설명을 만든다."""
    parent_tokens: list[str] = []
    for parent in list(image.parents)[:4]:
        if not isinstance(parent, Tag):
            continue
        parent_tokens.append(str(parent.get("id") or ""))
        classes = parent.get("class") or []
        parent_tokens.extend(str(value) for value in classes)
    text_evidence = " ".join((alt, caption, *parent_tokens)).lower()
    evidence = f"{text_evidence} {url.lower()}"
    score = 0
    reasons: list[str] = []
    exclusions: list[str] = []

    if any(hint in evidence for hint in _CHART_STRONG_HINTS) or bool(
        re.search(r"(?:^|[\s(\[])표(?:$|[\s=:\])])", f"{alt} {caption}")
    ):
        score += 5
        reasons.append("캡션·대체텍스트에서 표·차트 표현을 확인했습니다.")
    if any(hint in evidence for hint in _CHART_CONTEXT_HINTS):
        score += 3
        reasons.append("전망·증감률·통계 등 시각자료 문맥을 확인했습니다.")
    if re.search(r"(?:19|20)\d{2}|\d+(?:\.\d+)?\s*(?:%|명|건|원|달러|배)", f"{alt} {caption}"):
        score += 2
        reasons.append("연도·수치·단위 표현을 확인했습니다.")
    if image.find_parent(("figure", "table")) is not None:
        score += 1
        reasons.append("기사의 figure/table 영역에 있습니다.")
    if width and height and width >= 500 and width / max(height, 1) >= 1.2:
        score += 1
        reasons.append("가로형 시각자료 크기입니다.")

    # 많은 언론사가 모든 기사 이미지를 /photo/ 경로에 저장하므로 사진 제외
    # 표현은 URL이 아니라 캡션·alt·주변 DOM에서만 판정한다.
    if any(hint in text_evidence for hint in _PHOTO_HINTS):
        score -= 5
        exclusions.append("사진·기자·인물 관련 표현이 있습니다.")
    if any(hint in evidence for hint in _PROFILE_HINTS):
        score -= 7
        exclusions.append("작성자 또는 프로필 영역에 있습니다.")
    if any(hint in evidence for hint in _AD_HINTS):
        score -= 10
        exclusions.append("광고·배너 관련 표현이 있습니다.")
    if width and height and width <= 180 and height <= 180 and abs(width - height) <= 40:
        score -= 4
        exclusions.append("작은 정사각형 프로필 이미지 형태입니다.")
    return score, reasons, exclusions


def select_chart_image_candidates(
    candidates: list[ImageCandidate], minimum_score: int = 4
) -> list[ImageCandidate]:
    """표·차트 근거가 충분하고 명확한 제외 사유가 없는 후보만 반환한다."""
    return [
        candidate
        for candidate in candidates
        if candidate.get("chart_score", 0) >= minimum_score
        and not candidate.get("exclusion_reasons")
    ]


def _extract_image_candidates(
    container: Tag | BeautifulSoup | None,
    document_url: str,
) -> list[ImageCandidate]:
    if container is None:
        return []
    fragment = _clean_article_fragment(container)
    profile = _site_profile(document_url)
    selectors = profile.get("image_selectors") or ["figure img", "table img", "img"]
    images: list[Tag] = []
    for selector in selectors:
        images.extend(image for image in fragment.select(selector) if isinstance(image, Tag))

    candidates: list[ImageCandidate] = []
    seen: set[str] = set()
    for image in images:
        alt = _clean_text(image.get("alt"))
        raw_url = _extract_image_url(image)
        if not raw_url:
            continue
        normalized_url = urljoin(document_url or "https://", raw_url)
        parsed = urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        width = _numeric_dimension(image, "width")
        height = _numeric_dimension(image, "height")
        lowered_path = parsed.path.lower()
        if alt and alt.lower() in {text.lower() for text in IGNORED_IMAGE_TEXTS}:
            continue
        if any(hint in lowered_path for hint in IGNORED_IMAGE_PATH_HINTS):
            continue
        if width and height and width <= 120 and height <= 90:
            continue
        if normalized_url in seen:
            continue
        figure = image.find_parent("figure")
        caption_element = figure.find("figcaption") if figure else None
        caption = _clean_text(caption_element.get_text(" ", strip=True)) if caption_element else ""
        chart_score, reasons, exclusions = _score_chart_image_candidate(
            image, normalized_url, alt, caption, width, height
        )
        candidates.append(
            {
                "url": normalized_url,
                "alt": alt,
                "caption": caption,
                "label": alt or caption or f"기사 이미지 후보 {len(candidates) + 1}",
                "likely_chart": chart_score >= 4 and not exclusions,
                "chart_score": chart_score,
                "selection_reasons": reasons,
                "exclusion_reasons": exclusions,
            }
        )
        seen.add(normalized_url)
    return candidates


def _extract_visual_texts(container: Tag | None, images: list[ImageCandidate]) -> list[str]:
    if container is None:
        return []
    fragment = _clean_article_fragment(container)
    values = [
        _clean_text(element.get_text(" ", strip=True))
        for element in fragment.select("table, figcaption")
    ]
    # 스크랩 HTML은 img src가 제거되기도 한다. 이때도 차트임이 명시된 alt는
    # 시각자료 설명 후보로 보존하되 일반 기사 사진의 alt는 포함하지 않는다.
    for image in fragment.find_all("img"):
        alt = _clean_text(image.get("alt"))
        if alt and _has_visual_hint(alt):
            values.append(alt)
    for image in images:
        if image["likely_chart"]:
            values.extend([image["alt"], image["caption"]])
    return _ordered_unique(values)


def _strip_site_name(title: str, soup: BeautifulSoup) -> str:
    """메타 제목 끝에 반복된 사이트 이름만 제거한다."""
    normalized = _clean_text(title)
    site_meta = soup.select_one("meta[property='og:site_name']")
    site_name = _clean_text(site_meta.get("content")) if site_meta else ""
    if not normalized or not site_name:
        return normalized
    for separator in (" - ", " | ", " · ", " : "):
        suffix = separator + site_name
        if normalized.casefold().endswith(suffix.casefold()):
            return normalized[: -len(suffix)].strip()
    return normalized


def _extract_title(soup: BeautifulSoup, container: Tag | None = None) -> str:
    """사이트 로고용 h1보다 기사 구조화 메타데이터를 우선해 제목을 찾는다."""
    json_ld = _json_ld_news_article(soup)
    if json_ld.get("headline"):
        return _strip_site_name(_clean_text(json_ld["headline"]), soup)

    for selector in (
        "meta[property='og:title']",
        "meta[name='twitter:title']",
        "meta[property='twitter:title']",
    ):
        title_meta = soup.select_one(selector)
        if title_meta and title_meta.get("content"):
            return _strip_site_name(_clean_text(title_meta.get("content")), soup)

    # 구조화 메타데이터가 없는 단순 HTML에서는 선택된 기사 컨테이너와 가까운
    # 제목을 먼저 보고, 마지막 수단으로 문서의 첫 h1을 사용한다.
    if container is not None:
        local_h1 = container.find("h1")
        if local_h1:
            title = _clean_text(local_h1.get_text(" ", strip=True))
            if title:
                return title
    h1 = soup.find("h1")
    if h1:
        title = _clean_text(h1.get_text(" ", strip=True))
        if title:
            return title
    return _strip_site_name(
        _clean_text(soup.title.get_text(" ", strip=True)) if soup.title else "",
        soup,
    )


def extract_text_blocks_from_html(html: str, base_url: str = "") -> HTMLTextBlocks:
    """DOM 범위를 좁혀 기사 본문·시각자료 텍스트·이미지 후보를 분류한다."""
    if not html.strip():
        raise InvalidHTMLContentError("분석할 HTML 내용이 비어 있습니다.")
    # 변경: 브라우저는 복구하지만 html.parser는 이후 문서 전체를 iframe 텍스트로
    # 삼키는 비정상 noscript 구조가 있다. 원본 state를 만들지 않고 파싱 복사본만
    # 제한적으로 정규화한 뒤 기존 적응형 후보 추출을 그대로 적용한다.
    parse_html = _normalize_html_before_parse(html)
    soup = BeautifulSoup(parse_html, "html.parser")
    document_url = _document_url(soup, base_url)
    container, body_selector, confidence = _select_body_container(soup, document_url)
    profile = _site_profile(document_url)
    if container is not None:
        for selector in profile.get("exclude_selectors", []):
            for element in container.select(selector):
                element.decompose()
    paragraphs = _extract_body_paragraphs(container, confidence)
    # 사이트 프로필의 이미지 선택자는 본문 태그 바깥에 원본 이미지가 배치되는
    # 레거시 구조까지 좁은 selector로 처리한다. 공통 추출은 여전히 본문 내부만 본다.
    image_root: Tag | BeautifulSoup | None = soup if profile.get("image_selectors") else container
    images = _extract_image_candidates(image_root, document_url)
    visual_parts = _extract_visual_texts(container, images)
    return {
        "title": _extract_title(soup, container),
        "body_paragraphs": paragraphs,
        "visual_texts": visual_parts,
        "source_candidates": [
            text for text in visual_parts if _is_source_candidate(text)
        ],
        "image_candidates": images,
        "body_selector": body_selector,
        "extraction_confidence": confidence,
        "document_url": document_url,
    }


def summarize_extraction(blocks: HTMLTextBlocks) -> dict[str, Any]:
    """새 state를 만들지 않고 UI에 보여줄 추출 건수와 누락 항목을 반환한다."""
    missing = []
    if not blocks["title"]:
        missing.append("기사 제목")
    if not blocks["body_paragraphs"]:
        missing.append("기사 본문")
    if not blocks["visual_texts"]:
        missing.append("시각자료 관련 텍스트")
    if not blocks["source_candidates"]:
        missing.append("출처·단위 후보")
    image_candidates = blocks.get("image_candidates", [])
    return {
        "body_paragraph_count": len(blocks["body_paragraphs"]),
        "visual_text_count": len(blocks["visual_texts"]),
        "source_candidate_count": len(blocks["source_candidates"]),
        "image_candidate_count": len(image_candidates),
        "chart_candidate_count": len(select_chart_image_candidates(image_candidates)),
        "body_selector": blocks.get("body_selector", "확인되지 않음"),
        "extraction_confidence": blocks.get("extraction_confidence", "낮음"),
        "missing_fields": missing,
    }


def prefill_form_from_text_blocks(blocks: HTMLTextBlocks) -> FormPrefill:
    """정리된 HTML 텍스트 블록을 기존 폼 계약으로 변환한다."""
    body = "\n\n".join(blocks["body_paragraphs"])
    chart_texts = blocks["visual_texts"]
    sources = set(blocks["source_candidates"])
    chart_only = [text for text in chart_texts if text not in sources]
    return {
        "news_title": blocks["title"],
        "news_body": body,
        "chart_text": "\n".join(chart_only or chart_texts),
        "source_text": "\n".join(blocks["source_candidates"]),
        "draft_judgement": "검증 제한",
        "claim_chart_summary": "",
        "missing_info": "",
    }


def prefill_form_from_html_content(html: str, base_url: str = "") -> FormPrefill:
    """추출 결과를 사용자가 수정 가능한 기존 폼의 일곱 필드로 매핑한다.

    변경/확장 지점:
    - 현재는 확인 가능한 HTML 텍스트만 폼에 옮기며 새로운 판정이나 관계 요약을
      생성하지 않는다. 따라서 임시 판정은 가장 보수적인 ``검증 제한``이다.
    - 추후 주장-근거 검증 에이전트는 이 함수가 받은 URL 문자열이 아니라
      ``extract_text_blocks_from_html``의 정리된 결과를 입력으로 연결해야 한다.
    - 에이전트 연결 후에도 반환 key 계약은 유지해야 Streamlit 폼 매핑이 깨지지 않는다.
    """
    blocks = extract_text_blocks_from_html(html, base_url=base_url)
    return prefill_form_from_text_blocks(blocks)


def get_ingestion_error_message(error: Exception) -> str:
    """오류 유형별로 안전한 사용자 안내를 반환한다."""
    if isinstance(error, InvalidArticleURLError):
        return str(error)
    if isinstance(error, AccessRestrictedError):
        return (
            "해당 사이트가 자동 요청을 제한했습니다. 브라우저에서 저장한 HTML을 "
            "업로드하거나 직접 입력해주세요."
        )
    if isinstance(error, ArticleNotFoundError):
        return (
            "기사 페이지를 찾지 못했습니다. URL을 확인하거나 저장한 HTML 파일을 "
            "업로드해주세요."
        )
    if isinstance(error, ArticleFetchTimeoutError):
        return (
            "제한 시간 안에 기사 페이지를 불러오지 못했습니다. 잠시 후 다시 "
            "시도하거나 HTML 파일을 업로드해주세요."
        )
    if isinstance(error, ArticleFetchError):
        return (
            "URL에서 기사 HTML을 가져오지 못했습니다. 스크랩한 HTML 파일을 "
            "업로드하거나 직접 입력해주세요."
        )
    if isinstance(error, InvalidHTMLContentError):
        return f"{error} 다른 HTML 파일을 업로드하거나 직접 입력해주세요."
    return "자동 분류에 실패했습니다. 기존 입력 폼에 직접 입력한 뒤 검증할 수 있습니다."
