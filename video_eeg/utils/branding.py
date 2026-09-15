"""Shared company logo; GUI decoration only, outside the EEG recording timeline."""
from pathlib import Path
LOGO=Path(__file__).resolve().parents[2]/'assets/brand/company_logo.png'

def add_dialog_logo(dialog):
    if not LOGO.is_file():return
    try:
        from psychopy.gui.qtgui import QtGui,Qt,QtWidgets
        if QtWidgets.QApplication.instance() is None or not isinstance(dialog,QtWidgets.QDialog):return
        label=dialog.addText('')
        pixmap=QtGui.QPixmap(str(LOGO))
        if pixmap.isNull():return
        # PyQt5/6 enum spelling differs. QLabel owns the image for the dialog lifetime.
        align=Qt.AlignmentFlag.AlignCenter if hasattr(Qt,'AlignmentFlag') else Qt.AlignCenter
        keep=Qt.AspectRatioMode.KeepAspectRatio if hasattr(Qt,'AspectRatioMode') else Qt.KeepAspectRatio
        smooth=Qt.TransformationMode.SmoothTransformation if hasattr(Qt,'TransformationMode') else Qt.SmoothTransformation
        label.setPixmap(pixmap.scaled(76,76,keep,smooth));label.setAlignment(align)
        label.setAccessibleName('公司标志')
    except (ImportError,AttributeError):
        # Non-Qt fallback dialogs and test doubles remain functional.
        return
