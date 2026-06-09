from __future__ import annotations

import tempfile
import time
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .extractor import find_date_mentions
from .models import AuditConfig, ExtractedPage
from .utils import make_summary, normalize_text


IMAGE_URL_ATTRIBUTES = ("data-src", "data-original", "data-lazy-src", "src")
SMALL_IMAGE_EDGE_LIMIT = 80


class ImageOcrRunner:
    def __init__(self, config: AuditConfig):
        self.config = config
        self.engine = _load_ocr_engine(config)
        self.fetcher = PoliteImageFetcher(config)

    def enrich_page(self, page: ExtractedPage, html: str, base_url: str) -> ExtractedPage:
        if not html:
            return page

        chunks: list[str] = []
        for index, image_url in enumerate(extract_image_urls(html, base_url)[: self.config.image_ocr_max_images_per_page], 1):
            image_bytes = self.fetcher.fetch_image(image_url)
            if not image_bytes:
                continue
            text = self._ocr_image_bytes(image_bytes)
            if len(text) < self.config.image_ocr_min_text_chars:
                continue
            chunks.append(f"图片{index} {image_url}\n{text}")

        if not chunks:
            return page

        ocr_text = normalize_text("\n\n".join(chunks))
        body_text = normalize_text("\n\n".join([page.body_text, "[图片OCR]", ocr_text]))
        return replace(
            page,
            body_text=body_text,
            summary=make_summary(body_text),
            date_mentions=find_date_mentions(" ".join([page.title, body_text])),
        )

    def _ocr_image_bytes(self, image_bytes: bytes) -> str:
        try:
            from PIL import Image
        except ImportError as exc:
            raise RuntimeError("图片 OCR 需要 Pillow，请运行 pip install -r requirements-ocr.txt") from exc

        try:
            with Image.open(BytesIO(image_bytes)) as image:
                if image.width < SMALL_IMAGE_EDGE_LIMIT and image.height < SMALL_IMAGE_EDGE_LIMIT:
                    return ""
                image = image.convert("RGB")
                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                    temp_path = Path(handle.name)
                try:
                    image.save(temp_path, format="PNG")
                    raw_result = self.engine(str(temp_path))
                finally:
                    temp_path.unlink(missing_ok=True)
        except Exception:
            return ""

        return normalize_text("\n".join(_extract_text_lines(raw_result)))


class PoliteImageFetcher:
    def __init__(self, config: AuditConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": config.user_agent})
        self.last_hit_by_host: dict[str, float] = {}
        self.robots_by_site: dict[str, robotparser.RobotFileParser | None] = {}

    def fetch_image(self, url: str) -> bytes:
        if self.config.respect_robots_txt and not self._allowed_by_robots(url):
            return b""
        self._wait(url)
        try:
            response = self.session.get(url, timeout=self.config.timeout_seconds, allow_redirects=True)
        except requests.RequestException:
            return b""

        content_type = response.headers.get("content-type", "").lower()
        if response.status_code >= 400 or not content_type.startswith("image/"):
            return b""
        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.config.image_ocr_max_image_bytes:
                    return b""
            except ValueError:
                pass
        if len(response.content) > self.config.image_ocr_max_image_bytes:
            return b""
        return response.content

    def _wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        last_hit = self.last_hit_by_host.get(host)
        now = time.monotonic()
        if last_hit is not None:
            wait_seconds = self.config.polite_delay_seconds - (now - last_hit)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
        self.last_hit_by_host[host] = time.monotonic()

    def _allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        site = f"{parts.scheme}://{parts.netloc}"
        if site not in self.robots_by_site:
            parser = robotparser.RobotFileParser()
            parser.set_url(urljoin(site, "/robots.txt"))
            try:
                parser.read()
            except Exception:
                self.robots_by_site[site] = None
            else:
                self.robots_by_site[site] = parser
        parser = self.robots_by_site[site]
        if parser is None:
            return True
        return parser.can_fetch(self.config.user_agent, url)


def extract_image_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    urls: list[str] = []
    seen: set[str] = set()
    for image in soup.find_all("img"):
        url = ""
        for attribute in IMAGE_URL_ATTRIBUTES:
            value = str(image.get(attribute) or "").strip()
            if value and not value.startswith("data:"):
                url = value
                break
        if not url:
            continue
        absolute_url = urljoin(base_url, url)
        if not urlsplit(absolute_url).scheme.startswith("http"):
            continue
        if absolute_url in seen:
            continue
        urls.append(absolute_url)
        seen.add(absolute_url)
    return urls


def _load_ocr_engine(config: AuditConfig | None = None):
    # 优先尝试 Mistral OCR（云端 API）
    api_key = ""
    model = "mistral-ocr-latest"
    if config is not None:
        api_key = config.mistral_ocr_api_key
        model = config.mistral_ocr_model
    if not api_key:
        import os as _os
        api_key = _os.environ.get("MISTRAL_API_KEY", "")
    if api_key:
        return _load_mistral_engine(api_key, model)

    # 本地 OCR 降级
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        try:
            from rapidocr import RapidOCR
        except ImportError:
            return _load_tesseract_engine()
    return RapidOCR()


def _load_mistral_engine(api_key: str, model: str):
    try:
        from mistralai.client import Mistral
    except ImportError as exc:
        raise RuntimeError("Mistral OCR 需要 mistralai 包，请运行 pip install mistralai") from exc

    class MistralOcrEngine:
        def __init__(self, client: Mistral, model_name: str):
            self.client = client
            self.model_name = model_name

        def __call__(self, image_path: str):
            import base64
            from pathlib import Path as _Path

            image_data = _Path(image_path).read_bytes()
            b64 = base64.b64encode(image_data).decode()
            # 推断 MIME 类型
            suffix = _Path(image_path).suffix.lower()
            mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
            mime = mime_map.get(suffix, "image/png")
            data_url = f"data:{mime};base64,{b64}"

            result = self.client.ocr.process(
                model=self.model_name,
                document={"type": "image_url", "image_url": data_url},
            )
            # 提取文本
            lines: list[str] = []
            for page in (result.pages or []):
                md = getattr(page, "markdown", None) or ""
                if md.strip():
                    lines.append(md.strip())
            return [{"text": "\n".join(lines)}]

    client = Mistral(api_key=api_key)
    return MistralOcrEngine(client, model)


def _load_tesseract_engine():
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("图片 OCR 需要 RapidOCR 或 Tesseract，请运行 pip install -r requirements-ocr.txt") from exc

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        raise RuntimeError("已安装 pytesseract，但未找到 Tesseract OCR 可执行程序或语言包。") from exc

    class TesseractEngine:
        def __call__(self, image_path: str):
            text = pytesseract.image_to_string(image_path, lang="chi_sim+eng")
            return [{"text": text}]

    return TesseractEngine()


def _extract_text_lines(raw_result) -> list[str]:
    if raw_result is None:
        return []
    if isinstance(raw_result, tuple):
        raw_result = raw_result[0]
    if hasattr(raw_result, "txts"):
        return [str(text).strip() for text in raw_result.txts if str(text).strip()]
    if hasattr(raw_result, "texts"):
        return [str(text).strip() for text in raw_result.texts if str(text).strip()]
    if isinstance(raw_result, dict):
        for key in ("txts", "texts", "rec_texts"):
            if key in raw_result:
                return [str(text).strip() for text in raw_result[key] if str(text).strip()]
        return []
    if not isinstance(raw_result, list):
        return []

    lines: list[str] = []
    for item in raw_result:
        text = ""
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("txt") or "")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            text = str(item[1] or "")
        if text.strip():
            lines.append(text.strip())
    return lines
