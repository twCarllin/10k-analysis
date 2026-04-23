import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def convert_to_markdown(doc_path: str | Path) -> str:
    doc_path = Path(doc_path)
    cache_path = BASE_DIR / "data/cache/md" / doc_path.with_suffix(".md").name
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    md_text = _llamaparse(doc_path) or _markitdown_fallback(doc_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(md_text, encoding="utf-8")
    return md_text


def _llamaparse(doc_path: Path) -> str | None:
    try:
        import os
        from llama_parse import LlamaParse

        api_key = os.environ.get("LLAMA_CLOUD_API_KEY")
        if not api_key:
            return None
        docs = LlamaParse(
            api_key=api_key, result_type="markdown", verbose=False
        ).load_data(str(doc_path))
        md_text = "\n\n".join(doc.text for doc in docs)
        # 驗證 header 數量：至少要有 3 個 Item header
        if (
            len(
                re.findall(
                    r"^#{1,3}\s*item\s+\d",
                    md_text,
                    re.MULTILINE | re.IGNORECASE,
                )
            )
            < 3
        ):
            return None
        return md_text
    except Exception:
        return None


def _markitdown_fallback(doc_path: Path) -> str:
    from markitdown import MarkItDown

    return MarkItDown().convert(str(doc_path)).text_content
