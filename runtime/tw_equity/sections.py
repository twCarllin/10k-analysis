"""sections.py — 依錨點組裝送入 agent 的文字段落白名單（deterministic）。"""

from __future__ import annotations

import json

from runtime.tw_equity.doc_anchor import PageRange
from runtime.tw_equity.pdf_doc import PdfDoc
from runtime.tw_equity.tables import TablesBundle

_DEFAULT_MAX_CHARS = 12000

_AR_KEYS = ("ar_letter", "ar_business", "ar_market", "ar_mdna", "ar_risk")
_GOV_KEYS = ("ar_governance", "ar_capital")
_FS_KEYS = ("fs_note_related", "fs_note_contingent", "fs_note_disclosure", "fs_audit_kam")


def build_sections(
    ar: PdfDoc,
    ar_anchors: dict[str, PageRange | None],
    fs: PdfDoc,
    fs_anchors: dict[str, PageRange | None],
    ps: PdfDoc,
    ps_anchors: dict[str, PageRange | None],
    *,
    bundle: TablesBundle,
    max_chars: dict[str, int] | None = None,
    gov_anchors: dict[str, PageRange | None] | None = None,
) -> dict[str, str]:
    from agent_runner import truncate_with_notice

    max_chars = max_chars or {}
    out: dict[str, str] = {}
    for doc, anchors, keys in (
        (ar, ar_anchors, _AR_KEYS), (ar, gov_anchors, _GOV_KEYS), (fs, fs_anchors, _FS_KEYS),
    ):
        for key in keys:
            rng = (anchors or {}).get(key)
            if rng is None:
                out[key] = ""
                continue
            text = doc.text_of(rng.start, rng.end)
            out[key] = truncate_with_notice(text, max_chars.get(key, _DEFAULT_MAX_CHARS))
    out["tables_json"] = json.dumps(bundle.to_dict(), ensure_ascii=False)
    return out
