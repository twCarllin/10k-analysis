import json
import re
import time
from pathlib import Path
from datetime import datetime

import anthropic

BASE_DIR = Path(__file__).resolve().parent.parent

_config = json.loads((BASE_DIR / "config.json").read_text())
client = anthropic.Anthropic(api_key=_config["anthropic_api_key"])

_dry_run = False


def set_dry_run(enabled: bool):
    global _dry_run
    _dry_run = enabled


_MOCK_OUTPUTS = json.loads((BASE_DIR / "runtime" / "mock_outputs.json").read_text())


def truncate_with_notice(text: str, max_chars: int) -> str:
    """Truncate text with explicit notice to the agent."""
    if len(text) <= max_chars:
        return text
    return (
        text[:max_chars]
        + f"\n\n[截斷提示：以上為前 {max_chars} 字，"
        + f"原始文件共 {len(text)} 字，仍有後續內容未包含。"
        + "請勿將此視為文件結尾，結論應反映資料可能不完整。]"
    )


def _get_skill_version(skill_name: str) -> str:
    skill_path = BASE_DIR / f"skills/{skill_name}.md"
    if not skill_path.exists():
        return "unknown"
    header = skill_path.read_text(encoding="utf-8")[:200]
    m = re.search(r"skill_version:\s*([\d.]+)", header)
    return m.group(1) if m else "unknown"


def run_agent(agent_name, skill_name, inputs,
              model=None, max_tokens=None, task_label=None) -> dict:
    label = task_label or skill_name

    if _dry_run:
        time.sleep(0.05)
        mock = _MOCK_OUTPUTS.get(skill_name, {"insufficient_data": False})
        print(f"      [dry-run] {label}")
        return json.loads(json.dumps(mock))  # deep copy

    model = model or _config.get("model", "claude-sonnet-4-5")
    skill_limits = _config.get("max_tokens_by_skill", {})
    max_tokens = max_tokens or skill_limits.get(skill_name) or _config.get("max_tokens", 4096)
    agent_md = (BASE_DIR / f"agents/{agent_name}.md").read_text()
    skill_md = (BASE_DIR / f"skills/{skill_name}.md").read_text()
    system = f"{agent_md}\n\n---\n\n[SKILL]\n{skill_md}"

    parts = ["[INPUT]"]
    for k, v in inputs.items():
        if v is not None:
            parts.append(f"\n## {k}\n{v}")

    user_content = "\n".join(parts)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_content}],
    )

    raw = response.content[0].text.strip()
    skill_ver = _get_skill_version(skill_name)
    _save_context(label, system, user_content, raw, response.usage, skill_ver)

    raw_clean = re.sub(r"^```(?:json)?\s*", "", raw)
    raw_clean = re.sub(r"\s*```$", "", raw_clean)
    # Try parsing; on Extra data error, extract first complete JSON object
    try:
        return json.loads(raw_clean)
    except json.JSONDecodeError:
        m = re.search(r"\{", raw_clean)
        if m:
            depth = 0
            for i, ch in enumerate(raw_clean[m.start():], start=m.start()):
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(raw_clean[m.start():i + 1])
                        except json.JSONDecodeError:
                            break
        return {"error": "JSON parse failed", "raw": raw_clean[:500], "skill": skill_name}


def _save_context(label, system, user_content, response_text, usage, skill_version="unknown"):
    """Save request/response context and append to usage log."""
    log_dir = BASE_DIR / "data" / "output" / "contexts"
    log_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_label = re.sub(r"[^\w\-.]", "_", label)

    # Request context
    req_path = log_dir / f"{ts}_{safe_label}_request.md"
    req_path.write_text(
        f"# Request: {label}\n"
        f"Time: {datetime.now().isoformat()}\n"
        f"Tokens: in={usage.input_tokens}, out={usage.output_tokens}\n\n"
        f"## System\n\n{system}\n\n"
        f"## User\n\n{user_content}\n",
        encoding="utf-8",
    )

    # Response context
    resp_path = log_dir / f"{ts}_{safe_label}_response.md"
    resp_path.write_text(
        f"# Response: {label}\n"
        f"Time: {datetime.now().isoformat()}\n"
        f"Tokens: in={usage.input_tokens}, out={usage.output_tokens}\n\n"
        f"## Raw Output\n\n{response_text}\n",
        encoding="utf-8",
    )

    # Usage log (append)
    out_dir = BASE_DIR / "data" / "output"
    cost = usage.input_tokens * 3e-6 + usage.output_tokens * 15e-6
    entry = {
        "ts": datetime.now().isoformat(),
        "label": label,
        "version": skill_version,
        "in": usage.input_tokens,
        "out": usage.output_tokens,
        "cost": cost,
        "request_file": req_path.name,
        "response_file": resp_path.name,
    }
    with open(out_dir / "usage.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
