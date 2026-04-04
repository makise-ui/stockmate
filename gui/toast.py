"""Toast notification wrapper for ttkbootstrap."""

from typing import Literal

import tkinter.messagebox as messagebox

ToastKind = Literal["success", "warning", "danger", "info"]

_KIND_MAP: dict[ToastKind, str] = {
    "success": "success",
    "warning": "warning",
    "danger": "danger",
    "info": "primary",
}


def show_toast(
    title: str,
    message: str,
    kind: ToastKind = "info",
    duration: int = 3000,
) -> None:
    """Show a toast notification, falling back to messagebox on error.

    Args:
        title: Toast title text.
        message: Toast body text.
        kind: Visual style — one of ``"success"``, ``"warning"``, ``"danger"``, ``"info"``.
        duration: How long the toast stays visible, in milliseconds.
    """
    if not title or not message:
        return

    toast_type = _KIND_MAP.get(kind, "primary")

    try:
        from ttkbootstrap.toast import ToastNotification

        toast = ToastNotification(
            title=title,
            message=message,
            duration=duration,
            toasttype=toast_type,
        )
        toast.show_toast()
    except Exception:
        if kind == "danger":
            messagebox.showerror(title, message)
        elif kind == "warning":
            messagebox.showwarning(title, message)
        else:
            messagebox.showinfo(title, message)
