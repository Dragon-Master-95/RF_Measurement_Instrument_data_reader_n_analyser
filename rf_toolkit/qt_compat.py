# Qt binding used by the GUI: PySide6 -> PySide2 -> PyQt5 (first one installed).
# Every GUI module imports Qt from here so the choice is made in one place.

try:
    from PySide6 import QtCore, QtGui, QtWidgets
    QAction = QtGui.QAction
    QT_BINDING = "PySide6"
except ImportError:
    try:
        from PySide2 import QtCore, QtGui, QtWidgets
        QAction = QtWidgets.QAction
        QT_BINDING = "PySide2"
    except ImportError:
        from PyQt5 import QtCore, QtGui, QtWidgets
        QAction = QtWidgets.QAction
        QT_BINDING = "PyQt5"

Qt = QtCore.Qt


def exec_dialog(dialog):
    """dialog.exec() on Qt6, exec_() on older bindings."""
    return dialog.exec() if hasattr(dialog, "exec") else dialog.exec_()

__all__ = ["QtCore", "QtGui", "QtWidgets", "QAction", "QT_BINDING", "Qt", "exec_dialog"]
