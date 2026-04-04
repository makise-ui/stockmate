import sys

# Fix for PyInstaller + Pillow
try:
    import PIL._tkinter_finder
except ImportError:
    pass

from gui.app import MainApp

if __name__ == "__main__":
    app = MainApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
