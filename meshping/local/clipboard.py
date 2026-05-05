from __future__ import annotations

import shutil
import subprocess


def copy_text(text: str) -> bool:
    commands = [
        ["pbcopy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ]
    for command in commands:
        if shutil.which(command[0]) is None:
            continue
        try:
            subprocess.run(command, input=text, text=True, check=True, timeout=2)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False
