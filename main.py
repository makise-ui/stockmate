import sys  # noqa: F401

# Fix for PyInstaller + Pillow
try:
    import PIL._tkinter_finder  # noqa: F401
except ImportError:
    pass

from gui.app import MainApp

if __name__ == "__main__":
    app = MainApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
