# -*- coding: utf-8 -*-
"""普通 Python 启动的 ODB 导出界面，数据读取由 Abaqus Python 执行。"""
import ctypes
import glob
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime

from PyQt5 import QtCore, QtGui, QtWidgets

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "script" / "odb_export_backend.py"
EVENT_PREFIX = "ODB_EXPORT_EVENT "


def install_application_fonts(app):
    """Match the visualizer's font family, weight and default point size."""
    families = []
    medium_family = None
    for filename in ("NotoSansCJKsc-Regular.otf", "NotoSansCJKsc-Medium.otf",
                     "NotoSansCJKsc-Bold.otf"):
        font_id = QtGui.QFontDatabase.addApplicationFont(str(ROOT / "assets" / "fonts" / filename))
        if font_id >= 0:
            loaded = QtGui.QFontDatabase.applicationFontFamilies(font_id)
            families.extend(loaded)
            if loaded and filename == "NotoSansCJKsc-Medium.otf":
                medium_family = loaded[0]
    if families:
        font = app.font()
        font.setFamily(medium_family or families[0])
        if medium_family:
            font.setWeight(QtGui.QFont.Medium)
        app.setFont(font)


def discover_abaqus():
    candidates = []
    for name in ("abaqus", "abaqus.bat"):
        found = shutil.which(name)
        if found:
            candidates.append(found)
    command_dirs = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if any(word in entry.lower() for word in ("abaqus", "simulia")):
            command_dirs.append(entry.strip('"'))
    roots = []
    if os.name == "nt":
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        roots = [chr(65 + index) + ":/" for index in range(26) if mask & (1 << index)]
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                    try:
                        with winreg.OpenKey(
                            hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                            0, winreg.KEY_READ | view
                        ) as entries:
                            for index in range(winreg.QueryInfoKey(entries)[0]):
                                try:
                                    with winreg.OpenKey(entries, winreg.EnumKey(entries, index)) as item:
                                        name = winreg.QueryValueEx(item, "DisplayName")[0]
                                        if "abaqus" in name.lower() or "simulia" in name.lower():
                                            location = winreg.QueryValueEx(item, "InstallLocation")[0]
                                            command_dirs.extend([
                                                os.path.join(location, "Commands"),
                                                os.path.join(os.path.dirname(location), "Commands"),
                                            ])
                                except OSError:
                                    continue
                    except OSError:
                        continue
        except ImportError:
            pass
        for drive in roots:
            for pattern in (
                "ABAQUS*/Commands", "SIMULIA/Commands",
                "SIMULIA/*/Commands", "SIMULIA/EstProducts/*/Commands",
                "Program Files*/Dassault Systemes*/SIMULIA/Commands",
                "Program Files*/SIMULIA/Commands",
                "Program Files*/Dassault Systemes*/SIMULIA/*/Commands",
            ):
                command_dirs.extend(glob.glob(os.path.join(drive, pattern)))
    else:
        command_dirs.extend(glob.glob("/opt/SIMULIA/Commands"))
        command_dirs.extend(glob.glob("/opt/abaqus*/Commands"))
    for directory in command_dirs:
        for pattern in ("abaqus*", "abq[0-9]*"):
            for path in glob.glob(os.path.join(directory, pattern)):
                if Path(path).suffix.lower() in (".bat", ".cmd", ".exe", ""):
                    candidates.append(path)
    unique = {os.path.normcase(os.path.abspath(path)): os.path.abspath(path)
              for path in candidates if os.path.isfile(path)}
    def preference(path):
        years = re.findall(r"20\d{2}", path)
        year = max(map(int, years)) if years else 0
        return (-year, 0 if Path(path).stem.lower() == "abaqus" else 1, path.lower())
    return sorted(unique.values(), key=preference)


class EnvironmentScanner(QtCore.QThread):
    discovered = QtCore.pyqtSignal(list)

    def run(self):
        try:
            self.discovered.emit(discover_abaqus())
        except Exception:
            self.discovered.emit([])


class UpgradeDialog(QtWidgets.QDialog):
    def __init__(self, odb_path, launcher, batch=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("升级 ODB")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        def add_text(text):
            label = QtWidgets.QLabel(text)
            label.setTextFormat(QtCore.Qt.PlainText)
            label.setWordWrap(True)
            label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
            layout.addWidget(label)
            return label

        add_text("当前 Abaqus 已确认此 ODB 需要升级。是否升级副本并继续？")
        self.details = QtWidgets.QTextBrowser()
        self.details.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.details.setStyleSheet("QTextBrowser { background: transparent; }")
        self.details.setWordWrapMode(QtGui.QTextOption.WrapAnywhere)
        self.details.setPlainText("文件：{}\n\n使用环境：{}".format(odb_path, launcher))
        self.details.setMinimumHeight(self.fontMetrics().lineSpacing() * 6 + 12)
        layout.addWidget(self.details)
        add_text("副本保存到原文件目录下的 odb_upgraded 文件夹，原文件保留。"
                 "升级成功后自动继续；取消则终止当前流程。")
        self.remember = None
        if batch:
            self.remember = QtWidgets.QCheckBox("对本次剩余文件应用此选择")
            layout.addWidget(self.remember)
        buttons = QtWidgets.QDialogButtonBox()
        self.upgrade_button = buttons.addButton("升级并继续", QtWidgets.QDialogButtonBox.AcceptRole)
        cancel = buttons.addButton("取消", QtWidgets.QDialogButtonBox.RejectRole)
        self.upgrade_button.setAutoDefault(False)
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        width = min(640, screen.availableGeometry().width() - 40) if screen else 640
        self.resize(width, self.sizeHint().height())


class FieldRow(QtWidgets.QWidget):
    changed = QtCore.pyqtSignal()
    remove_requested = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.fields = {}
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(12)
        layout.addWidget(QtWidgets.QLabel("物理场："))
        self.variable = QtWidgets.QComboBox()
        layout.addWidget(self.variable)
        layout.addSpacing(12)
        layout.addWidget(QtWidgets.QLabel("分量："))
        self.component = QtWidgets.QComboBox()
        layout.addWidget(self.component)
        remove = QtWidgets.QPushButton("删除")
        remove.setFixedWidth(72)
        remove.setToolTip("删除这一行")
        remove.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(remove)
        layout.addStretch()
        self.variable.currentTextChanged.connect(self.update_components)
        self.component.currentIndexChanged.connect(self.changed)

    def set_fields(self, fields):
        previous_variable = self.variable.currentText()
        previous_component = self.component.currentData()
        self.fields = fields
        # Every row uses widths calculated from the same field catalogue, rather
        # than from its current selection or the time it was first shown.
        choices = ["无（标量）"] + [choice for info in fields.values()
                                   for choice in info.get("choices", [])]
        widths = []
        names = list(fields) + choices
        for combo in (self.variable, self.component):
            metrics = combo.fontMetrics()
            text_width = max([metrics.horizontalAdvance(name) for name in names] or [0])
            option = QtWidgets.QStyleOptionComboBox()
            option.initFrom(combo)
            size = combo.style().sizeFromContents(
                QtWidgets.QStyle.CT_ComboBox, option,
                QtCore.QSize(text_width + 12, metrics.height()), combo)
            widths.append(size.width())
        width = min(180, max(140, max(widths)))
        self.variable.setFixedWidth(width)
        self.component.setFixedWidth(width)
        self.variable.blockSignals(True)
        self.variable.clear()
        self.variable.addItems(sorted(fields))
        if previous_variable in fields:
            self.variable.setCurrentText(previous_variable)
        elif "S" in fields:
            self.variable.setCurrentText("S")
        self.variable.blockSignals(False)
        self.update_components()
        position = self.component.findData(previous_component)
        if position >= 0 and previous_variable == self.variable.currentText():
            self.component.setCurrentIndex(position)

    def update_components(self):
        self.component.clear()
        info = self.fields.get(self.variable.currentText(), {})
        if info.get("scalar"):
            self.component.addItem("无（标量）", None)
        for choice in info.get("choices", []):
            self.component.addItem(choice, choice)
        for preferred in ("Mises", "Magnitude"):
            position = self.component.findData(preferred)
            if position >= 0:
                self.component.setCurrentIndex(position)
                break
        self.changed.emit()

    def selection(self):
        return {"variable": self.variable.currentText(), "choice": self.component.currentData()}


class ODBExporterWindow(QtWidgets.QMainWindow):
    def __init__(self, scan_environment=True):
        super().__init__()
        self.setWindowTitle("ODB Exporter")
        self.setWindowIcon(QtGui.QIcon(str(ROOT / "assets" / "abaqus.ico")))
        self.settings = QtCore.QSettings("ODBVisualizer", "ODBExporter")
        self.fields = {}
        self.files = []
        self.rows = []
        self.ready = False
        self.action = None
        self.received_result = False
        self._backend_error = False
        self._backend_done = False
        self._summary_failures = 0
        self._cancel_requested = False
        self._upgrade_declined = False
        self._upgraded_files = {}
        self._upgrade_remaining = False
        self._buffer = b""
        self._temporary = tempfile.TemporaryDirectory(prefix="odb_exporter_")
        self.cancel_path = Path(self._temporary.name) / "cancel"
        self.upgrade_decision_path = Path(self._temporary.name) / "upgrade_decision.json"
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._process_error)
        self._build_ui()
        self.add_row()
        self._update_enabled()
        self._set_initial_size()
        if scan_environment:
            QtCore.QTimer.singleShot(0, self.scan_environment)

    def _set_initial_size(self):
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            self.resize(800, 1000)
            return
        available = screen.availableGeometry()
        self.resize(min(800, max(1, available.width() - 40)),
                    min(1000, max(1, available.height() - 60)))

    def _build_ui(self):
        central = QtWidgets.QWidget()
        # Keep all controls reachable if the screen cannot fit the full layout.
        viewport = QtWidgets.QScrollArea()
        viewport.setFrameShape(QtWidgets.QFrame.NoFrame)
        viewport.setWidgetResizable(True)
        viewport.setWidget(central)
        self.setCentralWidget(viewport)
        root = QtWidgets.QVBoxLayout(central)
        root.setSpacing(12)
        environment = QtWidgets.QGroupBox("Abaqus 环境")
        env_layout = QtWidgets.QHBoxLayout(environment)
        self.environment_combo = QtWidgets.QComboBox()
        self.environment_combo.currentIndexChanged.connect(self._environment_changed)
        env_layout.addWidget(self.environment_combo, 1)
        self.scan_button = QtWidgets.QPushButton("重新扫描")
        self.manual_button = QtWidgets.QPushButton("手动指定")
        self.scan_button.clicked.connect(self.scan_environment)
        self.manual_button.clicked.connect(self._choose_environment)
        env_layout.addWidget(self.scan_button)
        env_layout.addWidget(self.manual_button)
        root.addWidget(environment)

        self.input_group = QtWidgets.QGroupBox("导出设置")
        form = QtWidgets.QVBoxLayout(self.input_group)
        mode_row = QtWidgets.QHBoxLayout()
        mode_row.setSpacing(10)
        mode_row.addWidget(QtWidgets.QLabel("导出模式："))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("单独导出", "single")
        self.mode_combo.addItem("批量导出", "batch")
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        mode_row.addWidget(self.mode_combo)
        self.input_path = QtWidgets.QLineEdit()
        self.input_path.setPlaceholderText("选择一个 ODB 文件")
        self.input_path.textChanged.connect(self._input_changed)
        self.input_path.editingFinished.connect(self.load_metadata)
        self.browse_input = QtWidgets.QPushButton("浏览文件")
        self.browse_input.clicked.connect(self._choose_input)
        self.read_button = QtWidgets.QPushButton("读取信息")
        self.read_button.clicked.connect(self.load_metadata)
        mode_row.addWidget(self.input_path, 1)
        mode_row.addWidget(self.browse_input)
        mode_row.addWidget(self.read_button)
        form.addLayout(mode_row)
        object_row = QtWidgets.QHBoxLayout()
        object_row.setSpacing(10)
        object_row.addWidget(QtWidgets.QLabel("导出对象："))
        self.object_combo = QtWidgets.QComboBox()
        self.object_combo.addItem("整个装配体", "assembly")
        self.object_combo.addItem("指定实例", "instance")
        self.object_combo.currentIndexChanged.connect(self._object_changed)
        selector_width = max(self.mode_combo.sizeHint().width(), self.object_combo.sizeHint().width())
        self.mode_combo.setFixedWidth(selector_width)
        self.object_combo.setFixedWidth(selector_width)
        object_row.addWidget(self.object_combo)
        object_row.addWidget(QtWidgets.QLabel("实例："))
        self.instance_combo = QtWidgets.QComboBox()
        self.instance_combo.currentIndexChanged.connect(self._instance_changed)
        object_row.addWidget(self.instance_combo, 1)
        form.addLayout(object_row)
        inp_row = QtWidgets.QHBoxLayout()
        inp_row.setSpacing(10)
        self.inp_label = QtWidgets.QLabel("配套 INP：")
        inp_row.addWidget(self.inp_label)
        self.inp_path = QtWidgets.QLineEdit()
        self.inp_path.setPlaceholderText("自动匹配同名 INP")
        self.inp_button = QtWidgets.QPushButton("浏览文件")
        self.inp_button.clicked.connect(self._choose_inp)
        inp_row.addWidget(self.inp_path, 1)
        inp_row.addWidget(self.inp_button)
        form.addLayout(inp_row)
        root.addWidget(self.input_group)

        self.field_group = QtWidgets.QGroupBox("物理场选择")
        self.field_group.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        field_layout = QtWidgets.QVBoxLayout(self.field_group)
        field_layout.setContentsMargins(14, 24, 14, 14)
        field_layout.setSpacing(12)
        self.row_container = QtWidgets.QWidget()
        self.row_layout = QtWidgets.QVBoxLayout(self.row_container)
        self.row_layout.setContentsMargins(16, 12, 16, 12)
        self.row_layout.setSpacing(12)
        self.row_layout.addStretch()
        scroll = QtWidgets.QScrollArea()
        self.field_scroll = scroll
        scroll.setObjectName("fieldScroll")
        scroll.setStyleSheet("QScrollArea#fieldScroll { border: 1px solid palette(mid); border-radius: 4px; }")
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.row_container)
        field_layout.addWidget(scroll)
        self.add_button = QtWidgets.QPushButton("新增")
        self.add_button.setFixedWidth(72)
        self.add_button.setToolTip("新增一个导出物理场")
        self.add_button.clicked.connect(self.add_row)
        field_layout.addWidget(self.add_button, 0, QtCore.Qt.AlignLeft)
        root.addWidget(self.field_group)

        self.output_group = QtWidgets.QGroupBox("输出设置")
        output_layout = QtWidgets.QVBoxLayout(self.output_group)
        path_row = QtWidgets.QHBoxLayout()
        path_row.setSpacing(10)
        path_row.addWidget(QtWidgets.QLabel("导出路径："))
        self.output_path = QtWidgets.QLineEdit()
        self.output_button = QtWidgets.QPushButton("浏览文件")
        self.output_button.clicked.connect(self._choose_output)
        path_row.addWidget(self.output_path, 1)
        path_row.addWidget(self.output_button)
        output_layout.addLayout(path_row)
        options_row = QtWidgets.QHBoxLayout()
        options_row.setSpacing(10)
        options_row.addWidget(QtWidgets.QLabel("帧间隔："))
        self.stride_spin = QtWidgets.QSpinBox()
        self.stride_spin.setRange(1, 1000000)
        self.stride_spin.setFixedWidth(max(100, self.stride_spin.sizeHint().width()))
        options_row.addWidget(self.stride_spin)
        options_row.addWidget(QtWidgets.QLabel("节点合并："))
        self.reduce_combo = QtWidgets.QComboBox()
        self.reduce_combo.addItem("平均值", "avg")
        self.reduce_combo.addItem("最大值", "max")
        self.reduce_combo.setFixedWidth(max(120, self.reduce_combo.sizeHint().width()))
        options_row.addWidget(self.reduce_combo)
        self.overwrite_check = QtWidgets.QCheckBox("覆盖已有结果")
        options_row.addWidget(self.overwrite_check)
        options_row.addStretch()
        output_layout.addLayout(options_row)
        root.addWidget(self.output_group)

        buttons = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("正在准备…")
        buttons.addWidget(self.status_label, 1)
        self.export_button = QtWidgets.QPushButton("开始导出")
        self.cancel_button = QtWidgets.QPushButton("取消")
        self.export_button.clicked.connect(self.start_export)
        self.cancel_button.clicked.connect(self.cancel)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.cancel_button)
        root.addLayout(buttons)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setFixedHeight(14)
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        progress_layout = QtWidgets.QHBoxLayout()
        progress_layout.addWidget(self.progress, 1)
        self.progress_label = QtWidgets.QLabel("0%")
        self.progress_label.setMinimumWidth(40)
        self.progress_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        progress_layout.addWidget(self.progress_label)
        root.addLayout(progress_layout)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(10000)
        self.log_box.setMinimumHeight(120)
        self.log_box.setPlaceholderText("处理日志")
        root.addWidget(self.log_box, 1)

    def log(self, message):
        self.log_box.appendPlainText("[{}] {}".format(
            datetime.now().strftime("%H:%M:%S"), message))
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())

    def scan_environment(self):
        if self.action or (hasattr(self, "scanner") and self.scanner.isRunning()):
            return
        self.ready = False
        self.log("正在扫描系统路径、注册表和常见安装目录中的 Abaqus 环境…")
        self.status_label.setText("正在扫描 Abaqus 环境…")
        self.scan_button.setEnabled(False)
        self.scanner = EnvironmentScanner(self)
        self.scanner.discovered.connect(self._scanned)
        self.scanner.finished.connect(self._update_enabled)
        self.scanner.start()
        self._update_enabled()

    def _scanned(self, candidates):
        saved = self.settings.value("launcher", "", type=str)
        if saved and Path(saved).is_file() and saved not in candidates:
            candidates.insert(0, saved)
        self.environment_combo.blockSignals(True)
        self.environment_combo.clear()
        self.environment_combo.addItems(candidates)
        if saved in candidates:
            self.environment_combo.setCurrentText(saved)
        self.environment_combo.blockSignals(False)
        self.scan_button.setEnabled(True)
        if candidates:
            self.log("发现 {} 个 Abaqus 启动入口，正在验证选中的环境。".format(len(candidates)))
            self._environment_changed()
        else:
            self.status_label.setText("未发现 Abaqus，请手动指定启动程序")
            self.log("未发现 Abaqus 安装环境。请安装 Abaqus，或点击“手动指定”选择 abaqus.bat / abq版本.bat。")
            self._update_enabled()

    def _choose_environment(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选择 Abaqus 启动程序", "",
            "Abaqus 启动程序 (*.bat *.cmd *.exe);;所有文件 (*)")
        if path:
            position = self.environment_combo.findText(path)
            if position < 0:
                self.environment_combo.addItem(path)
                position = self.environment_combo.count() - 1
            self.environment_combo.setCurrentIndex(position)
            if self.ready:
                self._environment_changed()

    def _environment_changed(self):
        self.ready = False
        self._upgraded_files.clear()
        self._upgrade_remaining = False
        self.fields = {}
        for row in self.rows:
            row.set_fields({})
        if self.environment_combo.currentText() and not self.action:
            self._start_backend({"action": "probe"})

    def _mode_changed(self):
        self._upgrade_remaining = False
        self.files = []
        self.fields = {}
        self.input_path.clear()
        self.inp_path.clear()
        batch = self.mode_combo.currentData() == "batch"
        self.input_path.setPlaceholderText("选择包含 ODB 文件的目录" if batch else "选择一个 ODB 文件")
        self.inp_label.setText("模板 INP：" if batch else "配套 INP：")
        self.inp_path.setPlaceholderText("选择批量共用的模板 INP" if batch else "自动匹配同名 INP")
        for row in self.rows:
            row.set_fields({})
        self.instance_combo.clear()
        self._update_enabled()

    def _input_changed(self):
        self._upgrade_remaining = False
        self.files = []
        self.fields = {}
        self.instance_combo.blockSignals(True)
        self.instance_combo.clear()
        self.instance_combo.blockSignals(False)
        for row in self.rows:
            row.set_fields({})
        self._update_enabled()

    def _object_changed(self):
        self._update_enabled()
        if self.input_path.text().strip():
            self.load_metadata()

    def _instance_changed(self):
        if self.object_combo.currentData() == "instance" and self.instance_combo.currentText():
            self.load_metadata()

    def _choose_input(self):
        if self.mode_combo.currentData() == "batch":
            path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择 ODB 所在目录")
        else:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "选择 ODB 文件", "", "ODB 文件 (*.odb)")
        if path:
            self.input_path.setText(path)
            self.load_metadata()

    def _choose_inp(self):
        title = "选择模板 INP" if self.mode_combo.currentData() == "batch" else "选择配套 INP"
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, title, "", "INP 文件 (*.inp)")
        if path:
            self.inp_path.setText(path)

    def _choose_output(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择导出路径", self.output_path.text())
        if path:
            self.output_path.setText(path)

    def collect_files(self):
        path = Path(self.input_path.text().strip())
        if self.mode_combo.currentData() == "batch":
            if not path.is_dir():
                raise ValueError("请选择有效的 ODB 所在目录。")
            files = sorted(
                [str(child.resolve()) for child in path.iterdir()
                 if child.is_file() and child.suffix.lower() == ".odb"],
                key=lambda name: Path(name).name.lower())
        else:
            if not path.is_file() or path.suffix.lower() != ".odb":
                raise ValueError("请选择有效的 ODB 文件。")
            files = [str(path.resolve())]
        if not files:
            raise ValueError("所选目录中没有 ODB 文件（第一版只处理当前目录）。")
        return files

    def load_metadata(self):
        if not self.ready or self.action:
            return
        try:
            self.files = self.collect_files()
        except ValueError as exc:
            self.log(str(exc))
            return
        if not self.output_path.text().strip():
            self.output_path.setText(str(Path(self.files[0]).parent / "reports_csv"))
        self.fields = {}
        self.log("共 {} 个 ODB，读取选项来源：{}".format(len(self.files), self.files[0]))
        request = {"action": "inspect", "odb_path": self.files[0]}
        if self.object_combo.currentData() == "instance" and self.instance_combo.currentText():
            request["instance_name"] = self.instance_combo.currentText()
        self._start_backend(request)

    def add_row(self):
        row = FieldRow(self.row_container)
        row.set_fields(self.fields)
        row.remove_requested.connect(self.remove_row)
        self.rows.append(row)
        self.row_layout.insertWidget(self.row_layout.count() - 1, row)
        margins = self.row_layout.contentsMargins()
        # Keep three complete rows visible; further rows scroll vertically.
        height = (row.sizeHint().height() * 3 + self.row_layout.spacing() * 2
                  + margins.top() + margins.bottom() + self.field_scroll.frameWidth() * 2)
        self.field_scroll.setFixedHeight(height)

    def remove_row(self, row):
        if len(self.rows) == 1:
            self.log("至少保留一行物理场选择。")
            return
        self.rows.remove(row)
        self.row_layout.removeWidget(row)
        row.deleteLater()

    def _update_enabled(self):
        idle = self.action is None
        self.environment_combo.setEnabled(idle)
        self.manual_button.setEnabled(idle)
        self.input_group.setEnabled(idle and self.ready)
        self.field_group.setEnabled(idle and self.ready and bool(self.fields))
        self.output_group.setEnabled(idle and self.ready)
        self.export_button.setEnabled(idle and self.ready and bool(self.fields))
        self.cancel_button.setEnabled(not idle and self.action in ("inspect", "export"))
        self.instance_combo.setEnabled(self.object_combo.currentData() == "instance")
        self.inp_path.setEnabled(True)
        self.inp_button.setEnabled(True)
        scanning = hasattr(self, "scanner") and self.scanner.isRunning()
        self.scan_button.setEnabled(idle and not scanning)

    def _start_backend(self, request):
        if self.action:
            return
        missing = [str(BACKEND)] if not BACKEND.is_file() else []
        if missing:
            self.ready = False
            self.status_label.setText("导出脚本缺失，请查看下方日志")
            self.log("无法启动：缺少必需的导出脚本：{}".format("；".join(missing)))
            self._update_enabled()
            return
        launcher = self.environment_combo.currentText()
        if not Path(launcher).is_file():
            self.log("Abaqus 启动程序不存在，请重新扫描或手动指定。")
            return
        if os.name == "nt" and any(char in launcher for char in '"%\r\n'):
            self.log("Abaqus 启动路径包含不支持的字符，请选择标准安装路径。")
            return
        self.cancel_path.unlink(missing_ok=True)
        self.upgrade_decision_path.unlink(missing_ok=True)
        request["cancel_file"] = str(self.cancel_path)
        request["upgrade_decision_file"] = str(self.upgrade_decision_path)
        request["upgraded_files"] = dict(self._upgraded_files)
        request["batch"] = self.mode_combo.currentData() == "batch"
        if request["action"] == "export" and request["batch"]:
            request["_upgrade_remaining"] = self._upgrade_remaining
        request_path = Path(self._temporary.name) / "request.json"
        request_path.write_text(json.dumps(request, ensure_ascii=True), encoding="utf-8")
        self.action = request["action"]
        if self.action == "inspect":
            self._requested_instance = request.get("instance_name")
        self.received_result = False
        self._backend_error = False
        self._backend_done = False
        self._summary_failures = 0
        self._cancel_requested = False
        self._upgrade_declined = False
        self._buffer = b""
        self.progress.setRange(0, 1000 if self.action == "export" else 0)
        self.progress.setValue(0)
        self.progress_label.setText("0%" if self.action == "export" else "…")
        self.status_label.setText({
            "probe": "正在验证 Abaqus 环境…", "inspect": "正在读取模型信息…",
            "export": "正在导出…",
        }[self.action])
        self._update_enabled()
        self.process.setWorkingDirectory(self._temporary.name)
        environment = QtCore.QProcessEnvironment.systemEnvironment()
        environment.insert("PYTHONIOENCODING", "utf-8")
        environment.insert("PYTHONUNBUFFERED", "1")
        if os.name == "nt" and Path(launcher).suffix.lower() in (".bat", ".cmd"):
            runner = Path(self._temporary.name) / "run_abaqus.cmd"
            runner.write_text(
                '@echo off\n"%ODB_EXPORT_LAUNCHER%" python "%ODB_EXPORT_BACKEND%" "%ODB_EXPORT_REQUEST%"\n',
                encoding="ascii")
            environment.insert("ODB_EXPORT_LAUNCHER", launcher)
            environment.insert("ODB_EXPORT_BACKEND", str(BACKEND))
            environment.insert("ODB_EXPORT_REQUEST", str(request_path))
            self.process.setProcessEnvironment(environment)
            self.process.start(os.environ.get("COMSPEC", "cmd.exe"), ["/d", "/c", str(runner)])
        else:
            self.process.setProcessEnvironment(environment)
            self.process.start(launcher, ["python", str(BACKEND), str(request_path)])

    def _read_output(self):
        self._buffer += bytes(self.process.readAllStandardOutput())
        while b"\n" in self._buffer:
            line, self._buffer = self._buffer.split(b"\n", 1)
            self._handle_line(self._decode_line(line.rstrip(b"\r")))

    @staticmethod
    def _decode_line(line):
        try:
            return line.decode("utf-8")
        except UnicodeDecodeError:
            return line.decode("mbcs" if os.name == "nt" else "utf-8", errors="replace")

    def _handle_line(self, line):
        if not line:
            return
        if not line.startswith(EVENT_PREFIX):
            self.log("Abaqus 输出：" + line)
            return
        try:
            event = json.loads(line[len(EVENT_PREFIX):])
        except ValueError:
            self.log("无法解析后台消息：" + line)
            return
        kind = event.get("event")
        if kind == "probe":
            self.ready = True
            self.received_result = True
            self.settings.setValue("launcher", self.environment_combo.currentText())
            self.log("Abaqus 环境可用，内置 Python {}。".format(event["version"]))
        elif kind == "metadata":
            self.received_result = True
            old_name = self.instance_combo.currentText()
            self.instance_combo.blockSignals(True)
            self.instance_combo.clear()
            self.instance_combo.addItems([item["name"] for item in event["instances"]])
            if old_name:
                self.instance_combo.setCurrentText(old_name)
            self.instance_combo.blockSignals(False)
            self.fields = event["fields"]
            for row in self.rows:
                row.set_fields(self.fields)
            self.log("已读取 {} 个实例、{} 个可用物理场。".format(
                len(event["instances"]), len(self.fields)))
        elif kind == "log":
            prefix = {"warning": "提示：", "error": "错误："}.get(event.get("level"), "")
            self.log(prefix + event["message"])
        elif kind == "upgrade_required":
            self.status_label.setText("等待确认升级 ODB 副本…")
            self._confirm_upgrade(event)
        elif kind == "upgrade_started":
            self._upgrade_progress = max(0, self.progress.value())
            self.progress.setRange(0, 0)
            self.progress_label.setText("…")
            self.status_label.setText("正在升级 ODB 副本…")
        elif kind == "upgraded":
            self._upgraded_files[event["odb_path"]] = event["copy"]
            if self.action == "export":
                self.progress.setRange(0, 1000)
                self.progress.setValue(getattr(self, "_upgrade_progress", 0))
                self.progress_label.setText("{}%".format(self.progress.value() // 10))
            self.status_label.setText("升级完成，继续处理…")
        elif kind == "progress":
            self.progress.setRange(0, 1000)
            self.progress.setValue(round(event["value"] * 10))
            self.progress_label.setText("{}%".format(int(event["value"])))
            if event.get("message"):
                self.status_label.setText(event["message"])
        elif kind == "summary":
            self.received_result = True
            self._summary_failures = event["failures"]
            self.log("处理结束：成功 {} 项，跳过 {} 项，失败 {} 项。".format(
                event["success"], event["skipped"], event["failures"]))
        elif kind == "done":
            self._backend_done = True
        elif kind in ("error", "cancelled"):
            self.log(event["message"])
            if kind == "cancelled":
                self._cancel_requested = True
                self._upgrade_declined = event.get("reason") == "upgrade_declined"
            else:
                self._backend_error = True

    def _confirm_upgrade(self, event):
        dialog = UpgradeDialog(event["odb_path"], self.environment_combo.currentText(),
                               batch=bool(event.get("batch")), parent=self)
        accepted = dialog.exec_() == QtWidgets.QDialog.Accepted
        decision = {"upgrade": accepted,
                    "apply_remaining": bool(accepted and dialog.remember and dialog.remember.isChecked())}
        if self.action == "inspect":
            self._upgrade_remaining = decision["upgrade"] and decision["apply_remaining"]
        # Publish the decision atomically so the waiting backend cannot read partial JSON.
        temporary = self.upgrade_decision_path.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(decision), encoding="utf-8")
            temporary.replace(self.upgrade_decision_path)
        except OSError as exc:
            self.log("无法提交升级选择，已请求终止：{}".format(exc))
            self.cancel()

    def _finished(self, exit_code, _exit_status):
        self._read_output()
        if self._buffer.strip():
            self._handle_line(self._decode_line(self._buffer.strip()))
        action = self.action
        self.action = None
        if action == "export" or self._cancel_requested or self._backend_error:
            self._upgrade_remaining = False
        self.progress.setRange(0, 1000)
        self.progress_label.setText("{:.0f}%".format(self.progress.value() / 10))
        if self._backend_error:
            self.status_label.setText("处理失败，请查看下方日志中的具体错误")
            if action == "probe":
                self.ready = False
        elif self._cancel_requested:
            self.status_label.setText("已取消升级，请查看下方日志中的原因" if self._upgrade_declined else "已取消")
        elif self.received_result and self._backend_done and exit_code == 0:
            self.progress.setValue(1000)
            self.progress_label.setText("100%")
            self.status_label.setText(
                "环境已就绪" if action == "probe" else
                "处理结束，部分导出失败" if self._summary_failures else "处理完成")
        else:
            if action == "probe":
                self.ready = False
            self.status_label.setText("处理未完成，请查看日志")
            self.log("未收到完整的后台结果（启动程序退出代码：{}）。请检查 Abaqus 启动日志。".format(exit_code))
        self._update_enabled()
        # 第一次切换指定实例时，先读取实例列表，再读取该实例实际拥有的字段。
        if (action == "inspect" and self.received_result and self._backend_done and
                not self._backend_error and not self._cancel_requested and exit_code == 0 and
                self.object_combo.currentData() == "instance" and
                self.instance_combo.currentText() and
                self._requested_instance != self.instance_combo.currentText()):
            QtCore.QTimer.singleShot(0, self.load_metadata)

    def _process_error(self, error):
        if error == QtCore.QProcess.FailedToStart:
            self.log("无法启动 Abaqus，请检查所选启动程序是否有效。")
            self.action = None
            self.ready = False
            self._update_enabled()

    def start_export(self):
        try:
            files = self.collect_files()
            if files != self.files:
                raise ValueError("输入路径已改变，请先点击“读取信息”。")
            tasks = [row.selection() for row in self.rows]
            if any(not task["variable"] or
                   self.fields.get(task["variable"]) is None or
                   (task["choice"] is None and not self.fields[task["variable"]]["scalar"])
                   for task in tasks):
                raise ValueError("请为每一行选择有效的物理场和分量。")
            keys = [(task["variable"], task["choice"]) for task in tasks]
            if len(set(keys)) != len(keys):
                raise ValueError("存在重复的物理场和分量，请删除重复行。")
            output = self.output_path.text().strip()
            if not output:
                raise ValueError("请选择导出路径。")
            if self.object_combo.currentData() == "instance" and not self.instance_combo.currentText():
                raise ValueError("请选择要导出的实例。")
            inp = self.inp_path.text().strip()
            batch = self.mode_combo.currentData() == "batch"
            if batch:
                if not inp or not Path(inp).is_file() or Path(inp).suffix.lower() != ".inp":
                    raise ValueError("请选择有效的模板 INP，批量中的所有 ODB 将共用此模板。")
                inp = str(Path(inp).resolve())
            else:
                expected = Path(inp) if inp else Path(files[0]).with_suffix(".inp")
                if not expected.is_file():
                    raise ValueError("未找到配套 INP，请在“配套 INP”中手动选择。")
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "无法导出", str(exc))
            self.log(str(exc))
            return
        self.log("开始处理 {} 个 ODB、每个文件 {} 个导出项。".format(len(files), len(tasks)))
        self._start_backend({
            "action": "export", "files": files, "tasks": tasks,
            "batch": batch,
            "object_mode": self.object_combo.currentData(),
            "instance_name": self.instance_combo.currentText()
            if self.object_combo.currentData() == "instance" else None,
            "inp_path": inp or None, "output_dir": str(Path(output).resolve()),
            "frame_stride": self.stride_spin.value(),
            "reduce_method": self.reduce_combo.currentData(),
            "overwrite": self.overwrite_check.isChecked(),
        })

    def cancel(self):
        if self.action:
            self.cancel_path.touch()
            self._cancel_requested = True
            self.cancel_button.setEnabled(False)
            self.log("已请求取消，后台将在完成当前读取操作后停止。")

    def closeEvent(self, event):
        if self.process.state() != QtCore.QProcess.NotRunning:
            self.cancel()
            if self.process.state() == QtCore.QProcess.Starting:
                self.process.waitForStarted(3000)
            process_id = self.process.processId()
            if os.name == "nt" and process_id:
                subprocess.run(
                    ["taskkill", "/PID", str(process_id), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                self.process.kill()
            self.process.waitForFinished(3000)
        if hasattr(self, "scanner") and self.scanner.isRunning():
            self.scanner.wait()
        self._temporary.cleanup()
        event.accept()


def main():
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ODBVisualizer.ODBExporter")
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon(str(ROOT / "assets" / "abaqus.ico")))
    install_application_fonts(app)
    window = ODBExporterWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
