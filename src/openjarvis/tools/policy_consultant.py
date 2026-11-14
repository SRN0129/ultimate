"""Policy & Governance Consultant Suite + Voice Speaker for ULTIMATE.

Provides specialized tools for a Policy and Governance Consultant:
1. save_policy_note: Saves structured policy notes, governance memos, and
   meeting minutes to C:\\Users\\soumy\\Desktop\\Ultimate_Policy_Workspace\\Notes
   and optionally opens them on the laptop.
2. draft_email: Creates a structured professional email draft, copies it to the
   laptop clipboard, saves an archive copy, and optionally opens the email
   composer (mailto: / Gmail) on the laptop.
3. clipboard_read / clipboard_write: Reads or updates the laptop clipboard for
   instant grammatical correction and policy tone refinement.
4. speak_laptop: Speaks text out loud through the laptop's speakers in a clear,
   composed assistant voice (ULTIMATE).
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_WORKSPACE_DIR = Path.home() / "Desktop" / "Ultimate_Policy_Workspace"
_NOTES_DIR = _WORKSPACE_DIR / "Notes"
_EMAILS_DIR = _WORKSPACE_DIR / "Emails"


def speak_on_laptop_async(text: str) -> None:
    """Speak text out loud on the laptop speakers asynchronously via PowerShell SAPI."""
    clean = (
        text.replace("*", "")
        .replace("#", "")
        .replace("`", "")
        .replace("\r", " ")
        .replace("\n", ". ")
        .strip()
    )
    if not clean:
        return
    # Limit spoken length to keep voice interaction brisk and conversational
    if len(clean) > 650:
        clean = clean[:650] + "... Full text is ready on your screen."

    ps_script = f"""
    Add-Type -AssemblyName System.Speech
    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    $synth.Volume = 100
    $synth.Rate = 1
    try {{
        $voices = $synth.GetInstalledVoices() | Where-Object {{ $_.Enabled }}
        foreach ($v in $voices) {{
            if ($v.VoiceInfo.Name -match "David|George|Mark|Ryan|Hazel|Zira") {{
                $synth.SelectVoice($v.VoiceInfo.Name)
                break
            }}
        }}
    }} catch {{}}
    $synth.Speak({json.dumps(clean)})
    """
    try:
        subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                ps_script,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


@ToolRegistry.register("policy_consultant")
class PolicyConsultantTool(BaseTool):
    """Policy & Governance Consultant workflow and voice tool."""

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="policy_consultant",
            description=(
                "Specialized tool for Policy & Governance Consulting workflows, "
                "email drafting, note-taking, grammar/clipboard editing, and speaking out loud on the laptop:\n"
                "- save_note: Save a structured policy note, governance memo, or meeting brief to Desktop/Ultimate_Policy_Workspace/Notes (title='...', content='...', open_on_laptop=True/False).\n"
                "- list_notes: List saved policy notes and email drafts.\n"
                "- draft_email: Save a formal email draft, copy it to the laptop clipboard, and optionally open the laptop email composer (recipient='...', subject='...', content='...', open_on_laptop=True/False).\n"
                "- get_clipboard: Read current text from the laptop clipboard so you can proofread, grammar-correct, or rewrite it.\n"
                "- set_clipboard_and_paste: Copy corrected/polished text to the laptop clipboard and optionally type/paste it into the active window (content='...', auto_paste=True/False).\n"
                "- speak: Speak a message out loud through the laptop speakers (content='...')."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": (
                            "Action: save_note, list_notes, draft_email, "
                            "get_clipboard, set_clipboard_and_paste, speak"
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": "Title of the policy note or document.",
                    },
                    "recipient": {
                        "type": "string",
                        "description": "Email recipient address (optional).",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Email subject line.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full text body of the note, email, corrected grammar text, or spoken message.",
                    },
                    "open_on_laptop": {
                        "type": "boolean",
                        "description": "Whether to immediately open the note or email composer on the laptop screen.",
                    },
                    "auto_paste": {
                        "type": "boolean",
                        "description": "Whether to press Ctrl+V to paste the corrected text into the active laptop window.",
                    },
                },
                "required": ["action"],
            },
            category="productivity",
            requires_confirmation=False,
            timeout_seconds=30.0,
        )

    def execute(self, **kwargs: Any) -> ToolResult:
        action = str(kwargs.get("action", "")).strip().lower()
        title = str(kwargs.get("title", "Policy_Note")).strip()
        recipient = str(kwargs.get("recipient", "")).strip()
        subject = str(kwargs.get("subject", "Policy & Governance Update")).strip()
        content = str(kwargs.get("content", "")).strip()
        open_on_laptop = bool(kwargs.get("open_on_laptop", True))
        auto_paste = bool(kwargs.get("auto_paste", False))

        try:
            if action == "save_note":
                return self._save_note(title, content, open_on_laptop)
            if action == "list_notes":
                return self._list_notes()
            if action == "draft_email":
                return self._draft_email(recipient, subject, content, open_on_laptop)
            if action == "get_clipboard":
                return self._get_clipboard()
            if action == "set_clipboard_and_paste":
                return self._set_clipboard_and_paste(content, auto_paste)
            if action == "speak":
                speak_on_laptop_async(content)
                return ToolResult(
                    tool_name="policy_consultant",
                    content=f"Spoke on laptop: {content}",
                    success=True,
                )
            return ToolResult(
                tool_name="policy_consultant",
                content=f"Unknown policy_consultant action: '{action}'",
                success=False,
            )
        except Exception as exc:
            return ToolResult(
                tool_name="policy_consultant",
                content=f"PolicyConsultantTool error ({action}): {exc}",
                success=False,
            )

    def _save_note(self, title: str, content: str, open_on_laptop: bool) -> ToolResult:
        _NOTES_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        safe_title = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in title)[:50]
        file_path = _NOTES_DIR / f"{ts}_{safe_title}.md"
        formatted = (
            f"# {title}\n"
            f"**Date:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"**Prepared by:** ULTIMATE Policy & Governance Assistant\n\n"
            f"---\n\n{content}\n"
        )
        file_path.write_text(formatted, encoding="utf-8")
        if open_on_laptop:
            try:
                subprocess.Popen(["notepad.exe", str(file_path)])
            except Exception:
                pass
        return ToolResult(
            tool_name="policy_consultant",
            content=f"Saved policy note to {file_path}"
            + (" and opened it in Notepad on your laptop." if open_on_laptop else "."),
            success=True,
            metadata={"path": str(file_path), "title": title},
        )

    def _list_notes(self) -> ToolResult:
        _NOTES_DIR.mkdir(parents=True, exist_ok=True)
        _EMAILS_DIR.mkdir(parents=True, exist_ok=True)
        files: List[Dict[str, str]] = []
        for folder, kind in ((_NOTES_DIR, "Note"), (_EMAILS_DIR, "Email")):
            for f in sorted(folder.glob("*.*"), key=lambda p: p.stat().st_mtime, reverse=True)[:15]:
                files.append({"type": kind, "name": f.name, "path": str(f)})
        return ToolResult(
            tool_name="policy_consultant",
            content=json.dumps({"workspace": str(_WORKSPACE_DIR), "files": files}, indent=2),
            success=True,
            metadata={"files": files},
        )

    def _draft_email(
        self, recipient: str, subject: str, body: str, open_on_laptop: bool
    ) -> ToolResult:
        import pyperclip

        _EMAILS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        safe_subj = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in subject)[:40]
        file_path = _EMAILS_DIR / f"{ts}_{safe_subj}.txt"
        full_draft = f"To: {recipient}\nSubject: {subject}\n\n{body}\n"
        file_path.write_text(full_draft, encoding="utf-8")
        pyperclip.copy(body)

        if open_on_laptop:
            try:
                mailto_url = (
                    f"mailto:{urllib.parse.quote(recipient)}"
                    f"?subject={urllib.parse.quote(subject)}"
                    f"&body={urllib.parse.quote(body[:1500])}"
                )
                os.startfile(mailto_url)
            except Exception:
                try:
                    subprocess.Popen(["notepad.exe", str(file_path)])
                except Exception:
                    pass

        return ToolResult(
            tool_name="policy_consultant",
            content=(
                f"Email draft '{subject}' saved to {file_path}, copied to laptop clipboard"
                + (", and opened in your laptop mail composer." if open_on_laptop else ".")
            ),
            success=True,
            metadata={"path": str(file_path), "subject": subject, "body": body},
        )

    def _get_clipboard(self) -> ToolResult:
        import pyperclip

        txt = pyperclip.paste()
        return ToolResult(
            tool_name="policy_consultant",
            content=txt or "(Clipboard is empty)",
            success=True,
        )

    def _set_clipboard_and_paste(self, content: str, auto_paste: bool) -> ToolResult:
        import pyperclip

        pyperclip.copy(content)
        if auto_paste:
            import pyautogui

            pyautogui.FAILSAFE = False
            pyautogui.hotkey("ctrl", "v")
        return ToolResult(
            tool_name="policy_consultant",
            content=f"Copied {len(content)} characters to laptop clipboard"
            + (" and pasted into active window." if auto_paste else "."),
            success=True,
        )


__all__ = ["PolicyConsultantTool", "speak_on_laptop_async"]
