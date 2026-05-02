import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def convert_to_markdown(doc_path: str | Path) -> str:
    doc_path = Path(doc_path)
    cache_path = BASE_DIR / "data/cache/md" / doc_path.with_suffix(".md").name
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    md_text = _html_to_text_fallback(doc_path) or _markitdown_fallback(doc_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(md_text, encoding="utf-8")
    return md_text


def _strip_ixbrl(html: str) -> str:
    """Strip inline XBRL metadata from SEC filing HTML, keeping only visible text.
    
    SEC 10-K filings use inline XBRL (iXBRL) format where:
    - <ix:header>, <ix:references>, <ix:resources> contain XBRL metadata
    - <ix:nonNumeric>, <ix:nonFraction> wrap actual text with XBRL attributes
    - The actual content is in the text nodes of these elements
    
    This function extracts just the human-readable text.
    """
    # Remove hidden XBRL sections entirely
    html = re.sub(r'<ix:header>.*?</ix:header>', '', html, flags=re.DOTALL)
    html = re.sub(r'<ix:references>.*?</ix:references>', '', html, flags=re.DOTALL)
    html = re.sub(r'<ix:resources>.*?</ix:resources>', '', html, flags=re.DOTALL)
    
    # Remove style and script tags
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    
    # Replace ix:nonNumeric/ix:nonFraction with just their text content
    # These wrap actual text like: <ix:nonNumeric ...>some text</ix:nonNumeric>
    html = re.sub(r'<ix:nonNumeric[^>]*>(.*?)</ix:nonNumeric>', r'\1', html, flags=re.DOTALL)
    html = re.sub(r'<ix:nonFraction[^>]*>(.*?)</ix:nonFraction>', r'\1', html, flags=re.DOTALL)
    
    # Remove any remaining ix:* tags but keep text
    html = re.sub(r'<ix:[^>]+>', '', html)
    html = re.sub(r'</ix:[^>]+>', '', html)
    
    # Remove xbrli:* tags (context/unit definitions)
    html = re.sub(r'<xbrli:[^>]+>.*?</xbrli:[^>]+>', '', html, flags=re.DOTALL)
    html = re.sub(r'</?xbrli:[^>]*>', '', html)
    
    # Remove link:* tags
    html = re.sub(r'<link:[^>]+/>', '', html)
    html = re.sub(r'</?link:[^>]*>', '', html)
    
    return html


def _html_to_text_fallback(doc_path: Path) -> str | None:
    """Convert SEC iXBRL HTML to readable text using BeautifulSoup.
    
    This is the primary fallback for HTM/HTML files since markitdown
    doesn't handle iXBRL properly.
    """
    suffix = doc_path.suffix.lower()
    if suffix not in (".htm", ".html"):
        return None
    
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    
    html = doc_path.read_text(encoding="utf-8", errors="replace")
    
    # Strip XBRL metadata first
    html = _strip_ixbrl(html)
    
    # Parse with BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    
    # Remove remaining hidden elements
    for tag in soup.find_all(["style", "script", "head"]):
        tag.decompose()
    
    # Convert to text with some structure preservation
    text = soup.get_text(separator="\n")
    
    # Clean up excessive whitespace
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            lines.append(line)
    
    result = "\n\n".join(lines)
    
    # Validate: should have at least some Item headers
    item_count = len(re.findall(r'(?i)item\s+\d', result))
    if item_count < 2:
        return None  # Let markitdown try instead
    
    return result


def _inject_anchor_markers(html: str) -> str:
    """Convert empty anchor divs/spans to visible markers so markdown retains them."""
    return re.sub(
        r'<(div|span|a)\s+id="([^"]+)">\s*</\1>',
        r'<\1 id="\2">[anchor:\2]</\1>',
        html,
    )


def _markitdown_fallback(doc_path: Path) -> str:
    from markitdown import MarkItDown

    suffix = doc_path.suffix.lower()
    if suffix in (".htm", ".html"):
        import tempfile
        html = doc_path.read_text(encoding="utf-8", errors="replace")
        html = _inject_anchor_markers(html)
        with tempfile.NamedTemporaryFile(suffix=".htm", mode="w",
                                         encoding="utf-8", delete=False) as f:
            f.write(html)
            tmp_path = f.name
        result = MarkItDown().convert(tmp_path).text_content
        Path(tmp_path).unlink(missing_ok=True)
        return result

    return MarkItDown().convert(str(doc_path)).text_content
