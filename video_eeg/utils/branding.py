"""Shared company logo; GUI decoration only, outside the EEG recording timeline."""
from pathlib import Path
LOGO=Path(__file__).resolve().parents[2]/'assets/brand/company_logo.png'
STARTUP_SIZE=(570,380)
LOGO_SIZE=96


def configure_startup_dialog(dialog):
    """Use the same Qt size/DPI rules and center both startup windows."""
    from psychopy.gui import qtgui
    from importlib import import_module
    widgets=qtgui.QtWidgets
    if not isinstance(dialog,widgets.QDialog):return
    core=import_module(qtgui.haveQt+'.QtCore')
    # Wrap descriptive text instead of letting a long line expand the window.
    for label in dialog.findChildren(widgets.QLabel):
        label.setWordWrap(True)
    if hasattr(dialog,'inputFields'):
        # Keep the header compact; give the form rows comfortable, deliberate
        # heights instead of letting Qt spread blank space above the fields.
        dialog.layout.setContentsMargins(16,12,16,12)
        dialog.layout.setSpacing(10)
        dialog.layout.setRowMinimumHeight(1,64)
        dialog.layout.setRowMinimumHeight(2,42)
        for row in range(3,dialog.irow):
            dialog.layout.setRowMinimumHeight(row,54)
        dialog.layout.setRowMinimumHeight(dialog.irow,32)
        for field in dialog.inputFields:
            if isinstance(field,widgets.QLineEdit):field.setMinimumHeight(28)
        dialog.okBtn.setMinimumHeight(30)
        dialog.cancelBtn.setMinimumHeight(30)
    dialog.setFixedSize(*STARTUP_SIZE)
    def center():
        screen=qtgui.QtGui.QGuiApplication.primaryScreen()
        if screen is None:return
        frame=dialog.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        dialog.move(frame.topLeft())
    class CenterOnShow(core.QObject):
        def eventFilter(self,watched,event):
            show_type=core.QEvent.Type.Show if hasattr(core.QEvent,'Type') else core.QEvent.Show
            if event.type()==show_type:
                # Native title-bar dimensions are available after show.
                core.QTimer.singleShot(0,center)
            return False
    dialog._startup_center_filter=CenterOnShow(dialog)
    dialog.installEventFilter(dialog._startup_center_filter)
    center()

def add_dialog_logo(dialog):
    try:
        from psychopy.gui.qtgui import QtGui,Qt,QtWidgets
        if QtWidgets.QApplication.instance() is None or not isinstance(dialog,QtWidgets.QDialog):return
        # This form has defaults and no asterisk-marked required fields.
        dialog.requiredMsg.hide()
        if not LOGO.is_file():return
        label=dialog.addText('')
        pixmap=QtGui.QPixmap(str(LOGO))
        if pixmap.isNull():return
        # PyQt5/6 enum spelling differs. QLabel owns the image for the dialog lifetime.
        align=(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignTop) if hasattr(Qt,'AlignmentFlag') else (Qt.AlignLeft|Qt.AlignTop)
        keep=Qt.AspectRatioMode.KeepAspectRatio if hasattr(Qt,'AspectRatioMode') else Qt.KeepAspectRatio
        smooth=Qt.TransformationMode.SmoothTransformation if hasattr(Qt,'TransformationMode') else Qt.SmoothTransformation
        label.setPixmap(pixmap.scaled(64,64,keep,smooth));label.setAlignment(align)
        label.setFixedSize(64,64)
        dialog.layout.setAlignment(label,align)
        label.setAccessibleName('公司标志')
    except (ImportError,AttributeError):
        # Non-Qt fallback dialogs and test doubles remain functional.
        return
