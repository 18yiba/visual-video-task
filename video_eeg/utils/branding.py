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
        label.setPixmap(pixmap.scaled(LOGO_SIZE,LOGO_SIZE,keep,smooth));label.setAlignment(align)
        label.setAccessibleName('公司标志')
    except (ImportError,AttributeError):
        # Non-Qt fallback dialogs and test doubles remain functional.
        return
