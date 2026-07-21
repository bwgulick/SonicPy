# -*- coding: utf8 -*-
#
__version__ = "0.6.2"

import os
from pathlib import Path
import platform
from PyQt5 import QtWidgets
from PyQt5 import QtCore
#import pyqtgraph
import cv2 # pip install opencv-python
#import setuptools


theme = 1

resources_path = os.path.join(os.path.dirname(__file__), 'resources')
calibrants_path = os.path.join(resources_path, 'calibrants')
icons_path = os.path.join(resources_path, 'icons')
data_path = os.path.join(resources_path, 'data')
style_path = os.path.join(resources_path, 'style')
title = "SonicPy: Travel-distance analysis. ver." + __version__ + "  © R. Hrubiak, 2022."
home_path = str(Path.home())



def _install_excepthook():
    """Log uncaught exceptions to a file next to the app and show a dialog.

    In a windowed PyInstaller build there is no console, so without this any
    uncaught error disappears with no feedback to the user.
    """
    import sys
    import traceback

    log_path = os.path.join(home_path, 'sonicpy_ia_error.log')

    def handle(exc_type, exc_value, exc_tb):
        text = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(log_path, 'a') as f:
                f.write(text + '\n')
        except Exception:
            pass
        try:
            box = QtWidgets.QMessageBox(
                QtWidgets.QMessageBox.Critical, "Unexpected error",
                "%s\n\nDetails were written to:\n%s" % (exc_value, log_path),
                QtWidgets.QMessageBox.Ok)
            box.setDetailedText(text)
            box.setTextInteractionFlags(
                QtCore.Qt.TextSelectableByMouse | QtCore.Qt.TextSelectableByKeyboard)
            box.exec_()
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle


def main():
    from ia.controllers.ImageAnalysisController import ImageAnalysisController
    _install_excepthook()
    if hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    if hasattr(QtCore.Qt, 'AA_UseHighDpiPixmaps'):
        QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    _platform = platform.system()

    app = QtWidgets.QApplication([])
    #app.aboutToQuit.connect(app.deleteLater)
    
    controller = ImageAnalysisController(app = app, offline= True)
    controller.show_window()

    if _platform == "Darwin":    #macOs has a 'special' way of handling preferences menu
        window = controller.display_window
        pact = QtWidgets.QAction('Preferences', app)
        pact.triggered.connect(controller.preferences_module)
        pact.setMenuRole(QtWidgets.QAction.PreferencesRole)
        pmenu = QtWidgets.QMenu('Preferences')
        pmenu.addAction(pact)
        menu = window.menuBar
        menu.addMenu(pmenu)
    
    app.exec_()

