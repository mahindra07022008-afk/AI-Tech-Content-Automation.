"""Run inside MoneyPrinterTurbo's venv (cwd = MPT home).

Reads a prompt on stdin, generates text with MoneyPrinterTurbo's configured LLM
provider (claude_code = the locally logged-in `claude` CLI, headless, tools disabled)
and prints one JSON line: {"ok": true, "text": "..."} or {"ok": false, "error": "..."}.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())


def main() -> int:
    prompt = sys.stdin.read()
    try:
        from app.services import llm  # MoneyPrinterTurbo
        text = llm._generate_response(prompt)
        if not text or str(text).startswith("Error:"):
            raise RuntimeError(str(text)[:500] or "empty response")
        print(json.dumps({"ok": True, "text": text}, ensure_ascii=False))
        return 0
    except Exception as exc:  # report, never print secrets
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:800]}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
