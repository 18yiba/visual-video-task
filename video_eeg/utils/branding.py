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
        dialog.layout.setRowMinimumHeight(1,80)
        first_field=getattr(dialog,'_startup_form_row',3)
        if first_field>2:dialog.layout.setRowMinimumHeight(2,28)
        for row in range(first_field,dialog.irow):
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

def add_dialog_logo(dialog,description='',resume_hint=''):
    try:
        from psychopy.gui.qtgui import QtGui,Qt,QtWidgets
        if QtWidgets.QApplication.instance() is None or not isinstance(dialog,QtWidgets.QDialog):
            dialog.addText(description+resume_hint)
            return
        # This form has defaults and no asterisk-marked required fields.
        dialog.requiredMsg.hide()
        header=QtWidgets.QWidget(dialog)
        row=QtWidgets.QHBoxLayout(header);row.setContentsMargins(0,0,0,0);row.setSpacing(12)
        align=(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter) if hasattr(Qt,'AlignmentFlag') else (Qt.AlignLeft|Qt.AlignVCenter)
        keep=Qt.AspectRatioMode.KeepAspectRatio if hasattr(Qt,'AspectRatioMode') else Qt.KeepAspectRatio
        smooth=Qt.TransformationMode.SmoothTransformation if hasattr(Qt,'TransformationMode') else Qt.SmoothTransformation
        pixmap=QtGui.QPixmap(str(LOGO)) if LOGO.is_file() else QtGui.QPixmap()
        if not pixmap.isNull():
            label=QtWidgets.QLabel(header);label.setPixmap(pixmap.scaled(64,64,keep,smooth))
            label.setFixedSize(64,64);label.setAlignment(align);label.setAccessibleName('公司标志')
            row.addWidget(label)
        title=QtWidgets.QLabel(description,header)
        font=QtGui.QFont('Microsoft YaHei',11);font.setBold(True);title.setFont(font)
        title.setAlignment(align);title.setWordWrap(True);row.addWidget(title,1)
        dialog.layout.addWidget(header,dialog.irow,0,1,2);dialog.irow+=1
        if resume_hint:dialog.addText(resume_hint.lstrip('；')+'。')
        dialog._startup_form_row=dialog.irow
    except (ImportError,AttributeError):
        # Non-Qt fallback dialogs and test doubles remain functional.
        dialog.addText(description+resume_hint)
