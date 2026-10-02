"""screenshot.py — capture the full (virtual) desktop and drop it on the Windows
clipboard as CF_DIB so the user can paste it into any app.

Used by the "screenshot" voice command. Relies on Pillow (already a pyautogui
dependency) for capture + pywin32 (already in the venv) for the clipboard write.
"""

from __future__ import annotations

import io
import logging
import sys

logger = logging.getLogger("screenshot")


def screenshot_to_clipboard(all_screens: bool = True) -> bool:
    """Grab the screen and put it on the clipboard. Returns True on success.

    all_screens=True captures the full virtual desktop (every monitor), which
    is what "whole screen" means on a multi-monitor setup. Set False to capture
    only the primary monitor.
    """
    try:
        from PIL import Image, ImageGrab
    except Exception as e:  # pragma: no cover
        logger.error(f"Pillow not available for screenshot: {e}")
        return False

    try:
        import win32clipboard
    except Exception as e:  # pragma: no cover
        logger.error(f"pywin32 not available for clipboard: {e}")
        return False

    try:
        img = ImageGrab.grab(all_screens=all_screens)
        ok = _copy_pil_image_to_clipboard(img, win32clipboard)
    except Exception as e:
        logger.error(f"Screenshot failed: {e}")
        return False
    if ok:
        _toast("Screenshot copied to clipboard")
    return ok


def _toast(text: str = "Screenshot copied", ms: int = 1300) -> None:
    """Flash a small borderless confirmation that self-dismisses.

    Runs on its own thread with its own Tk root so it never blocks the caller
    or steals focus from the window the operator is working in. Any failure is
    swallowed — feedback must never break the capture.
    """
    import threading

    def _show() -> None:
        try:
            import tkinter as tk

            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            try:
                root.attributes("-alpha", 0.92)
            except Exception:
                pass
            tk.Label(
                root,
                text=text,
                bg="#111111",
                fg="#ffffff",
                font=("Segoe UI", 12),
                padx=16,
                pady=10,
            ).pack()
            root.update_idletasks()
            width = root.winfo_width()
            screen_w = root.winfo_screenwidth()
            root.geometry(f"+{screen_w - width - 24}+24")
            root.after(ms, root.destroy)
            root.mainloop()
        except Exception:
            pass

    threading.Thread(target=_show, daemon=True).start()


def _copy_pil_image_to_clipboard(img, win32clipboard) -> bool:
    """Write a PIL image to the Windows clipboard as CF_DIB."""
    out = io.BytesIO()
    img.convert("RGB").save(out, "BMP")
    dib_data = out.getvalue()[14:]  # strip the 14-byte BMP file header

    try:
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        logger.error(f"Clipboard write failed: {e}")
        return False
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ok = screenshot_to_clipboard()
    print(f"screenshot_to_clipboard -> {ok}")
    sys.exit(0 if ok else 1)