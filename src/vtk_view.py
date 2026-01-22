# -*- coding: utf-8 -*-
"""
VTK 可视化器:
实现ABAQUS物理场数据的三维可视化与动画播放功能。
    1. 支持读取.inp文件获取节点和单元信息;
    2. 支持读取多个.csv文件获取全场节点信息;
    3. 支持基于vtk的可视化渲染;
    4. 支持动画播放控制。
"""

import sys
import os
import numpy as np
import pandas as pd
from PyQt5 import QtWidgets, QtCore
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtGui import QIcon
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
from vtkmodules.vtkRenderingCore import vtkWindowToImageFilter
from vtkmodules.vtkIOImage import vtkPNGWriter

# -------------------------
# 定义读取数据函数
# -------------------------
def read_inp_nodes(inp_path):
    """
    读取inp文件，返回节点序号和坐标数组

    :param inp_path: .inp 文件路径
    return: node_ids (np.array), coords (np.array)
    """

    node_ids = [] # 存储节点序号
    coords = [] # 存储节点坐标，二维模型包含两个参数，三维模型包含三个参数
    read_flag = False # 读取状态标志，默认关闭

    with open(inp_path, 'r', encoding='utf-8', errors='ignore') as f: 
        for line in f:
            line = line.strip() # 去除行首尾空白
            if not line: # 跳过空行
                continue
            if line.lower().startswith('*node'): # 搜索关键字'*node'
                read_flag = True
                continue
            if read_flag and line.startswith('*'): # 遇到下一个关键字停止读取
                break
            if read_flag: # 读取状态下，解析节点行
                parts = [p.strip() for p in line.split(',')] # 分割并去除空白
                # 检查 parts 是否有足够的元素
                if len(parts) > 1: 
                    try:
                        node_ids.append(int(parts[0])) 
                        coords.append([float(x) for x in parts[1:]]) 
                    except ValueError: # 忽略格式不正确的行
                        continue
    return np.array(node_ids), np.array(coords)

def _parse_element_type(line: str):
    parts = [p.strip() for p in line.split(",")]
    for p in parts:
        if p.lower().startswith("type="):
            return p.split("=", 1)[1].strip().upper()
    return None


def read_inp_elements(inp_path):
    """
    Read element connectivity from .inp and keep element type.

    :param inp_path: .inp path
    :return: list of (nodes, elem_type)
    """
    elements = []
    read_flag = False
    elem_type = None

    with open(inp_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('**'):
                continue
            if line.startswith('*'):
                if line.lower().startswith('*element'):
                    read_flag = True
                    elem_type = _parse_element_type(line)
                else:
                    read_flag = False
                    elem_type = None
                continue
            if read_flag:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) > 1:
                    try:
                        nodes = [int(pid) for pid in parts[1:]]
                    except ValueError:
                        continue
                    elements.append((nodes, elem_type))
    return elements


def read_field_csv(csv_path, node_count):
    """
    读取.csv物理场文件，返回字段名、数据数组和帧标签列表
    
    :param csv_path: CSV 文件路径
    :param node_count: INP 模型中的节点总数 (用于校验)
    return: field_name (str), data (np.array), frame_labels (list of str)
    """
    df = pd.read_csv(csv_path)

    if df.shape[1] < 2: # 确保 CSV 至少有两列（第一列是帧标签，后面是数据）
        raise ValueError(f"CSV file {csv_path} has too few columns.")
        
    frame_labels = df.iloc[:,0].astype(str).values # 第一列作为帧标签
    field_data = df.iloc[:,1:].astype(float).values # 其余列作为数据
    
    # 使用列数（node_count）检查数据维度是否与节点数一致
    if field_data.shape[1] != node_count:  
        import os
        base_name = os.path.basename(csv_path) 
        print(f"Warning: Data columns ({field_data.shape[1]}) in {base_name} do not match node count ({node_count}).")
        
        # 如果转置后匹配节点数，则进行转置
        if field_data.shape[0] == node_count: 
            field_data = field_data.T
        else:
            # 当 node_count=0 或维度不匹配时，抛出错误
            raise ValueError(f"Data columns ({field_data.shape[1]}) do not match node count ({node_count}).")

    import os
    field_name = os.path.splitext(os.path.basename(csv_path))[0] # 去除路径和扩展名的文件名作为变量字段名
    return field_name, field_data, frame_labels

def _unpack_element(elem):
    if isinstance(elem, dict):
        return elem.get("nodes", []), elem.get("type")
    if isinstance(elem, (list, tuple)):
        if len(elem) == 2 and isinstance(elem[0], (list, tuple)) and not isinstance(elem[1], (int, np.integer)):
            return list(elem[0]), elem[1]
        return list(elem), None
    return [], None


def _select_cell(elem_type, n):
    et = (elem_type or "").upper()
    if et:
        if et.startswith("C3D4"):
            return vtk.vtkTetra()
        if et.startswith("C3D8"):
            return vtk.vtkHexahedron()
        if et.startswith("C3D6"):
            return vtk.vtkWedge()
        if et.startswith(("CPS4", "CPE4", "S4", "CAX4")):
            return vtk.vtkQuad()
        if et.startswith(("CPS3", "CPE3", "S3", "CAX3")):
            return vtk.vtkTriangle()
    if n == 4:
        return vtk.vtkQuad()
    if n == 8:
        return vtk.vtkHexahedron()
    if n == 3:
        return vtk.vtkTriangle()
    if n == 6:
        return vtk.vtkWedge()
    return None

# -------------------------
# 自定义 QVTK Widget 
# -------------------------
class CustomQVTKWidget(QVTKRenderWindowInteractor):
    """
    重写鼠标中键事件，确保在某些系统或 Qt 配置下，
    鼠标中键按下和释放事件能够正确转发给 VTK 交互器，
    从而支持 vtkInteractorStyleTrackballCamera 的中键旋转/平移。
    """
    def MiddleButtonPress(self):
        """转发 Middle Button Down 事件给 VTK"""
        self._Iren.MiddleButtonPressEvent()
        
    def MiddleButtonRelease(self):
        """转发 Middle Button Up 事件给 VTK"""
        self._Iren.MiddleButtonReleaseEvent()

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            self.MiddleButtonPress()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event): # 添加 event 参数
        if event.button() == QtCore.Qt.MiddleButton:
            self.MiddleButtonRelease()
        else:
            super().mouseReleaseEvent(event)

# -------------------------
# 自定义交互样式
# -------------------------
class CustomInteractorStyle(vtk.vtkInteractorStyleTrackballCamera):
    """
    实现 Solidworks/ABAQUS 风格的交互：
    - 滚轮滚动: 缩放 (重写 OnMouseWheelForward/Backward)
    - 中键拖动: 旋转 (继承 TrackballCamera 的默认行为)
    - 右键拖动: 平移 (继承 TrackballCamera 的默认行为)
    """
    def OnMouseWheelForward(self):
        """滚轮向前滚动 (放大)"""
        # 使用 vtkInteractorStyleTrackballCamera 的 ZoomOut 动作实现放大
        self.ZoomOut() 
        self.GetInteractor().Render()

    def OnMouseWheelBackward(self):
        """滚轮向后滚动 (缩小)"""
        # 使用 vtkInteractorStyleTrackballCamera 的 ZoomIn 动作实现缩小
        self.ZoomIn() 
        self.GetInteractor().Render()

# -------------------------
# 定义主窗口
# -------------------------
class VTKWindow(QtWidgets.QMainWindow): 
    """
    VTK 可视化主窗口类
    """
    def __init__(self, parent=None): 
        super().__init__(parent) 
        
        # 初始化变量
        self.coords = None # 节点坐标
        self.elements = None # 单元信息
        self.node_ids = None # 节点序号
        self.fields = {}  # 物理场数据字典
        self.current_field = '' # 当前物理场名称
        self.current_frame = 0 # 当前帧索引

        # VTK/渲染相关变量
        self.renderer = None
        self.ugrid = None
        self.actor = None
        self.mapper = None
        self.background_style = "abaqus"
        self.colormap_style = "rainbow"
        self.lut = self._create_rainbow_lut() # 提前创建 LUT
        self.scalar_bar = None
        
        # 初始化动画控制变量
        self.timer = QtCore.QTimer(self) # 定时器
        self.timer.timeout.connect(self.play_next_frame) # 定时器超时连接播放下一帧
        self.is_playing = False # 默认播放状态关闭
        self.loop_mode = True # 默认循环
        self.base_delay = 100 # 默认延迟 100ms (10 帧/秒)
        self.play_speed = 1.0 # 默认倍速 1.0

        self._init_ui()
        
        # 确保 VTK 窗口和背景在程序启动时就初始化 (修改: 在 _init_ui 之后调用)
        self._setup_vtk_renderer_and_interaction()

    # ---------------------
    # VTK 辅助函数
    # ---------------------
    def _create_abaqus_lut(self):
        """创建 Abaqus 风格的颜色查找表"""
        lut = vtk.vtkLookupTable()
        lut.SetNumberOfTableValues(12)
        lut.Build()
        abaqus_colors = [
            (0,0,1),(0,0.3647,1),(0,0.725,1),(0,1,0.910),
            (0,1,0.545),(0,1,0.180),(0.176,1,0),(0.545,1,0),
            (0.9098,1,0),(1,0.7255,0),(1,0.3647,0),(1,0,0)
        ]
        for i, rgb in enumerate(abaqus_colors):
            lut.SetTableValue(i, *rgb, 1.0)
        return lut

    def _create_rainbow_lut(self, num_colors=256):
        """创建 Rainbow（HSV）渐变颜色查找表"""
        lut = vtk.vtkLookupTable()
        lut.SetNumberOfTableValues(num_colors)
        lut.SetHueRange(0.667, 0.0)  # blue -> red
        lut.SetSaturationRange(1.0, 1.0)
        lut.SetValueRange(1.0, 1.0)
        lut.Build()
        return lut
        
    def _create_scalar_bar(self):
        """创建颜色图例 Actor"""
        scalar_bar = vtk.vtkScalarBarActor()
        scalar_bar.SetLookupTable(self.lut)
        scalar_bar.SetNumberOfLabels(12)
        scalar_bar.SetLabelFormat("%.2e")
        scalar_bar.SetMaximumWidthInPixels(300)
        scalar_bar.SetMaximumHeightInPixels(450)
        scalar_bar.SetPosition(0.02, 0.70)
        scalar_bar.SetWidth(0.10)
        scalar_bar.SetHeight(0.25)
        
        label_text = scalar_bar.GetLabelTextProperty()
        label_text.SetFontSize(14)
        title_text = scalar_bar.GetTitleTextProperty()
        title_text.SetFontSize(10) # 保持和原代码一致
        title_text.BoldOn()
        return scalar_bar

    def set_background_style(self, style):
        """切换视窗背景风格并重新渲染。"""
        if not style:
            return
        style = style.strip().lower()
        if style not in ("abaqus", "white"):
            return
        self.background_style = style
        self._apply_background_style(style)

    def _apply_background_style(self, style):
        if self.renderer is None:
            return
        if style == "abaqus":
            self._set_abaqus_background(self.renderer)
        elif style == "white":
            self._set_white_background(self.renderer)
        self.vtk_widget.GetRenderWindow().Render()

    def _set_abaqus_background(self, renderer):
        renderer.GradientBackgroundOn()
        renderer.SetBackground2(27/255, 45/255, 70/255)
        renderer.SetBackground(158/255, 173/255, 194/255)

    def _set_white_background(self, renderer):
        renderer.GradientBackgroundOff()
        renderer.SetBackground(1.0, 1.0, 1.0)
        renderer.SetBackground2(1.0, 1.0, 1.0)

    def set_colormap_style(self, style):
        """切换颜色映射并更新 LUT。"""
        if not style:
            return
        style = style.strip().lower()
        if style not in ("abaqus", "rainbow"):
            return
        self.colormap_style = style
        self._apply_colormap_style(style)

    def _apply_colormap_style(self, style):
        if style == "abaqus":
            new_lut = self._create_abaqus_lut()
        else:
            new_lut = self._create_rainbow_lut()

        self.lut.DeepCopy(new_lut)

        if self.mapper is not None:
            self.mapper.SetLookupTable(self.lut)
        if self.scalar_bar is not None:
            self.scalar_bar.SetLookupTable(self.lut)

        if self.vtk_widget.GetRenderWindow() is not None:
            self.vtk_widget.GetRenderWindow().Render()
        
    def _setup_vtk_renderer_and_interaction(self):
        """
        初始化 VTK 渲染器、背景和交互器。
        确保程序启动时就有渐变背景。
        """
        # 如果已经初始化过，则跳过
        if self.renderer is not None:
            return

        # 渲染器
        self.renderer = vtk.vtkRenderer()
        self.vtk_widget.GetRenderWindow().AddRenderer(self.renderer)
        self._apply_background_style(self.background_style)
        
        # 交互器
        self.interactor = self.vtk_widget.GetRenderWindow().GetInteractor()

        # 应用自定义的交互样式，实现滚轮缩放，中键旋转
        custom_style = CustomInteractorStyle() 
        self.interactor.SetInteractorStyle(custom_style)
        
        # 创建并添加 ScalarBar
        self.scalar_bar = self._create_scalar_bar()
        self.renderer.AddViewProp(self.scalar_bar) 
        
        # 首次渲染和交互器初始化
        self.renderer.ResetCamera()
        self.vtk_widget.GetRenderWindow().Render()
        self.interactor.Initialize()

    # ---------------------
    # 初始化UI
    # ---------------------
    def _init_ui(self):
        # 初始化窗口
        self.setWindowTitle("VTK Visualizer")
        icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "logo.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(900, 900) 

        # 初始化中央部件和布局
        central = QtWidgets.QWidget() 
        main_layout = QtWidgets.QVBoxLayout(central) 

        # 顶部菜单 
        menubar = self.menuBar() 
        # 加载文件菜单
        file_menu_load = menubar.addMenu("加载文件") 

        # 加载INP文件按钮
        open_inp = QtWidgets.QAction("加载INP文件", self) 
        open_inp.triggered.connect(self.open_inp_file) 
        file_menu_load.addAction(open_inp)

        # 加载CSV文件按钮
        open_csv = QtWidgets.QAction("加载CSV文件", self) 
        open_csv.triggered.connect(self.open_csv_file)
        file_menu_load.addAction(open_csv)

        # 导出文件菜单
        file_menu_export = menubar.addMenu("导出文件")

        # 导出图片按钮
        export_img = QtWidgets.QAction("导出为图片", self) 
        export_img.triggered.connect(self.export_image) 
        file_menu_export.addAction(export_img)

        # 可视化菜单
        menu_vis = menubar.addMenu("可视化")
        menu_bg = menu_vis.addMenu("背景设置")
        self.bg_group = QtWidgets.QActionGroup(self)
        self.bg_group.setExclusive(True)

        act_bg_abaqus = QtWidgets.QAction("abaqus", self)
        act_bg_abaqus.setCheckable(True)
        act_bg_abaqus.setChecked(self.background_style == "abaqus")
        act_bg_abaqus.triggered.connect(lambda: self.set_background_style("abaqus"))

        act_bg_white = QtWidgets.QAction("white", self)
        act_bg_white.setCheckable(True)
        act_bg_white.setChecked(self.background_style == "white")
        act_bg_white.triggered.connect(lambda: self.set_background_style("white"))

        self.bg_group.addAction(act_bg_abaqus)
        self.bg_group.addAction(act_bg_white)
        menu_bg.addAction(act_bg_abaqus)
        menu_bg.addAction(act_bg_white)

        menu_lut = menu_vis.addMenu("颜色映射")
        self.lut_group = QtWidgets.QActionGroup(self)
        self.lut_group.setExclusive(True)

        act_lut_abaqus = QtWidgets.QAction("abaqus", self)
        act_lut_abaqus.setCheckable(True)
        act_lut_abaqus.setChecked(self.colormap_style == "abaqus")
        act_lut_abaqus.triggered.connect(lambda: self.set_colormap_style("abaqus"))

        act_lut_rainbow = QtWidgets.QAction("Rainbow", self)
        act_lut_rainbow.setCheckable(True)
        act_lut_rainbow.setChecked(self.colormap_style == "rainbow")
        act_lut_rainbow.triggered.connect(lambda: self.set_colormap_style("rainbow"))

        self.lut_group.addAction(act_lut_abaqus)
        self.lut_group.addAction(act_lut_rainbow)
        menu_lut.addAction(act_lut_abaqus)
        menu_lut.addAction(act_lut_rainbow)

        # 顶部控制条 (物理场选择)
        ctrl_layout_field_inner = QtWidgets.QHBoxLayout() 
        ctrl_layout_field_inner.addWidget(QtWidgets.QLabel("物理场:")) 
        self.field_combo = QtWidgets.QComboBox() 
        self.field_combo.currentTextChanged.connect(self.on_field_changed)
        ctrl_layout_field_inner.addWidget(self.field_combo) 
        self.field_selection_group = QtWidgets.QGroupBox("选择物理场") 
        self.field_selection_group.setLayout(ctrl_layout_field_inner) 
        self.field_selection_group.setFixedWidth(250) # 限制宽度，防止挤压播放控件

        # 创建播放控制
        ctrl_layout_play_inner = QtWidgets.QHBoxLayout() # 使用新的 inner 布局

        # 播放/暂停按钮
        self.play_btn = QtWidgets.QPushButton("▶ 播放")
        self.play_btn.clicked.connect(self.toggle_play_pause) 
        ctrl_layout_play_inner.addWidget(self.play_btn)
        
        # 循环模式复选框
        self.loop_checkbox = QtWidgets.QCheckBox("循环播放") 
        self.loop_checkbox.setChecked(self.loop_mode)
        self.loop_checkbox.stateChanged.connect(self.on_loop_changed)
        ctrl_layout_play_inner.addWidget(self.loop_checkbox)
        
        # 倍速选择
        ctrl_layout_play_inner.addWidget(QtWidgets.QLabel("倍速:"))
        self.speed_combo = QtWidgets.QComboBox()
        self.speed_combo.addItems(["0.25x", "0.5x", "1.0x", "2.0x", "4.0x"])
        self.speed_combo.setCurrentText("1.0x")
        self.speed_combo.currentTextChanged.connect(self.on_speed_changed)
        ctrl_layout_play_inner.addWidget(self.speed_combo)

        # 当前帧标签
        self.frame_label = QtWidgets.QLabel("帧: 0 / 0")
        ctrl_layout_play_inner.addWidget(self.frame_label)
        
        self.control_group = QtWidgets.QGroupBox("控制播放") 
        self.control_group.setLayout(ctrl_layout_play_inner) 

        # 将物理场选择和播放控制放在同一行
        combined_control_layout = QtWidgets.QHBoxLayout()
        combined_control_layout.addWidget(self.field_selection_group)
        spacer = QtWidgets.QSpacerItem(20, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        combined_control_layout.addItem(spacer)
        combined_control_layout.addWidget(self.control_group)
        main_layout.addLayout(combined_control_layout)

        # VTK 窗口
        self.vtk_widget = CustomQVTKWidget(central)  
        main_layout.addWidget(self.vtk_widget)

        # 滑块
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.valueChanged.connect(self.on_slider_changed)
        self.slider.sliderPressed.connect(self.on_slider_pressed) 
        self.slider.sliderReleased.connect(self.on_slider_released) 
        main_layout.addWidget(self.slider)

        self.setCentralWidget(central)
        
        # 初始禁用播放控件
        self.set_playback_enabled(False)

    # ---------------------
    # 动画控制
    # ---------------------
    def set_playback_enabled(self, enabled):
        """控制播放相关控件的启用状态"""
        self.play_btn.setEnabled(enabled)
        self.loop_checkbox.setEnabled(enabled)
        self.speed_combo.setEnabled(enabled)
        self.slider.setEnabled(enabled)
        
    def update_timer_interval(self):
        """根据倍速更新定时器间隔"""
        if self.play_speed > 0:
            interval = int(self.base_delay / self.play_speed)
            self.timer.setInterval(max(1, interval)) # 最小间隔为 1ms

    def toggle_play_pause(self):
        """切换播放/暂停状态"""
        if not self.fields or self.current_field == '':
            return

        if self.is_playing:
            self.timer.stop()
            self.is_playing = False
            self.play_btn.setText("▶ 播放")
        else:
            # 检查是否已到最后一帧 (如果非循环模式)
            max_frame = self.fields[self.current_field]["data"].shape[0] - 1
            if self.current_frame >= max_frame and not self.loop_mode:
                self.current_frame = 0 # 从头开始播放
                self.slider.setValue(0) # 同时更新滑块

            self.update_timer_interval() # 确保定时器间隔正确
            self.timer.start()
            self.is_playing = True
            self.play_btn.setText("⏸ 暂停")

    def play_next_frame(self):
        """播放下一帧"""
        if self.current_field == '':
            self.toggle_play_pause()
            return
            
        n_frames = self.fields[self.current_field]["data"].shape[0]
        
        next_frame = self.current_frame + 1
        
        if next_frame >= n_frames:
            if self.loop_mode:
                next_frame = 0 # 循环到第一帧
            else:
                self.toggle_play_pause() # 停止播放
                return # 保持在最后一帧

        self.current_frame = next_frame
        
        # 更新滑块和场数据
        self.slider.blockSignals(True)
        self.slider.setValue(self.current_frame)
        self.slider.blockSignals(False)
        self.update_field()

    # ---------------------
    # 打开 INP
    # ---------------------
    def open_inp_file(self):
        """打开.INP文件，读取节点和单元信息"""
        path, _ = QFileDialog.getOpenFileName(self, "Open INP file", "", "INP Files (*.inp)")
        if path:
            # 读取节点和单元
            self.node_ids, self.coords = read_inp_nodes(path)
            self.elements = read_inp_elements(path)

            if self.coords is None or len(self.coords) == 0:
                QtWidgets.QMessageBox.warning(self, "Warning", "INP 文件中未读取到节点坐标！")
                self.coords = None
                self.elements = None
                self.node_ids = None
                self.set_playback_enabled(False)
                return

            # 清空已有物理场
            self.fields.clear()
            self.field_combo.clear()
            self.current_field = ''
            self.current_frame = 0
            
            # 停止播放
            if self.is_playing:
                self.toggle_play_pause()

            # 重新初始化 VTK 网格
            self._init_vtk()
            self.set_playback_enabled(False) # 需加载 CSV 后再启用播放

    # ---------------------
    # 打开 CSV
    # ---------------------
    def open_csv_file(self):
        """打开.CSV文件，读取物理场数据"""
        if self.coords is None or len(self.coords) == 0:
            QtWidgets.QMessageBox.warning(self, "Warning", "请先选择 INP 文件并确保其中包含节点坐标！")
            return
        
        # 获取节点数
        node_count = len(self.node_ids) 
        
        paths, _ = QFileDialog.getOpenFileNames(self, "Open CSV file", "", "CSV Files (*.csv)")
        for path in paths:
            try:
                field_name, data, frames = read_field_csv(path, node_count)
                self.fields[field_name] = {
                    "data": data,
                    "frames": frames,
                    "vmin": float(np.nanmin(data)) if not np.all(np.isnan(data)) else 0.0,
                    "vmax": float(np.nanmax(data)) if not np.all(np.isnan(data)) else 1.0
                }
                # 检查是否已存在，如果不存在则添加
                if self.field_combo.findText(field_name) == -1:
                    self.field_combo.addItem(field_name)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"加载 CSV 文件失败: {path}\n错误信息: {e}")
                continue


        # 默认选择第一个新添加的物理场或更新当前物理场
        if self.field_combo.count() > 0:
            if self.current_field == '' or self.current_field not in self.fields:
                # 第一次加载 CSV，默认选中第一个
                self.current_field = self.field_combo.itemText(0)
                self.field_combo.setCurrentIndex(0) # 触发 on_field_changed
            else:
                # 已经有选中场，手动调用更新，确保新加载的场的最大帧数和数据得到处理
                self.on_field_changed(self.current_field) 

            # 只要有物理场数据，就启用播放控制 (由 on_field_changed 决定是否启用)
            if self.current_field:
                self.set_playback_enabled(self.fields[self.current_field]["data"].shape[0] > 1)
        else:
            self.set_playback_enabled(False)

    # ---------------------
    # 导出功能
    # ---------------------
    def export_image(self):
        """导出当前 VTK 窗口中的帧为图片 (PNG)"""
        if self.vtk_widget.GetRenderWindow() is None:
            QtWidgets.QMessageBox.warning(self, "Warning", "VTK 渲染窗口尚未初始化！")
            return
            
        # 弹出文件对话框选择保存路径
        file_name, _ = QFileDialog.getSaveFileName(
            self, 
            "Save Current Frame Image", 
            "current_frame.png", 
            "PNG Image (*.png);;JPEG Image (*.jpg);;TIFF Image (*.tif)"
        )

        if file_name:
            # 1. 创建 vtkWindowToImageFilter
            w2i = vtkWindowToImageFilter()
            w2i.SetInput(self.vtk_widget.GetRenderWindow())
            # 设置 ReadFrontBufferOff 可以在渲染完成前进行截图
            # ReadFrontBufferOn 截取屏幕上实际显示的内容
            w2i.SetInputBufferTypeToRGB() 
            w2i.ReadFrontBufferOn() # 捕获当前显示的内容
            w2i.Update()

            # 2. 选择合适的写入器 (基于文件后缀名)
            if file_name.lower().endswith(('.png')):
                writer = vtkPNGWriter()
            elif file_name.lower().endswith(('.jpg', '.jpeg')):
                from vtkmodules.vtkIOImage import vtkJPEGWriter
                writer = vtkJPEGWriter()
            elif file_name.lower().endswith(('.tif', '.tiff')):
                from vtkmodules.vtkIOImage import vtkTIFFWriter
                writer = vtkTIFFWriter()
            else:
                QtWidgets.QMessageBox.critical(self, "Error", "不支持的文件格式，请使用 .png, .jpg 或 .tif。")
                return

            # 3. 写入文件
            writer.SetFileName(file_name)
            writer.SetInputConnection(w2i.GetOutputPort())
            
            try:
                writer.Write()
                QtWidgets.QMessageBox.information(self, "Success", f"图片已成功保存到:\n{file_name}")
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"保存图片失败: {e}")

    # ---------------------
    # VTK 模型数据初始化 (修改)
    # ---------------------
    def _init_vtk(self):
        """
        初始化或重置 VTK 网格数据结构。
        此函数仅处理模型数据，不应处理渲染器或背景设置。
        """
        # 统一移除旧的 Actor (如果存在)
        if hasattr(self, 'actor') and self.actor is not None:
            self.renderer.RemoveActor(self.actor)
            self.actor = None
            
        if self.coords is None or self.elements is None:
            # 数据无效，渲染清除后的空窗口
            self.vtk_widget.GetRenderWindow().Render()
            return

        # Points
        points = vtk.vtkPoints()
        for c in self.coords:
            z_coord = 0.0 if len(c) == 2 else c[2]
            points.InsertNextPoint(c[0], c[1], z_coord)

        # Unstructured Grid
        self.ugrid = vtk.vtkUnstructuredGrid()
        self.ugrid.SetPoints(points)

        # 构建节点序号到点索引的映射
        self.node_id_map = {nid:i for i, nid in enumerate(self.node_ids)}

        # Cells
        for elem in self.elements:
            nodes, elem_type = _unpack_element(elem)
            cell = _select_cell(elem_type, len(nodes))
            if cell is None:
                continue
            try:
                for i, nid in enumerate(nodes):
                    cell.GetPointIds().SetId(i, self.node_id_map[nid])
                self.ugrid.InsertNextCell(cell.GetCellType(), cell.GetPointIds())
            except KeyError:
                # Ignore elements containing undefined node ids
                print(f"Warning: Element skipped due to missing node ID(s).")
                continue

        # Mapper / Actor
        self.mapper = vtk.vtkDataSetMapper()
        self.mapper.SetInputData(self.ugrid)
        self.mapper.SetLookupTable(self.lut)
        self.mapper.SetScalarModeToUsePointData() 
        
        self.actor = vtk.vtkActor()
        self.actor.SetMapper(self.mapper)
        self.renderer.AddActor(self.actor)
        
        # 重置摄像机以适应新模型
        self.renderer.ResetCamera()
        self.vtk_widget.GetRenderWindow().Render()

    # ---------------------
    # 更新物理场
    # ---------------------
    def update_field(self):
        """根据 current_field 和 current_frame 更新 VTK 渲染"""
        if self.current_field=='' or self.current_field not in self.fields or self.ugrid is None:
            self.frame_label.setText("帧: 0 / 0")
            return
        
        field = self.fields[self.current_field]
        n_frames = field["data"].shape[0]
        
        if self.current_frame < 0 or self.current_frame >= n_frames:
            # 确保帧数在有效范围内，如果超出则修正
            self.current_frame = np.clip(self.current_frame, 0, n_frames - 1)
            
        # 获取当前帧的值
        values = field["data"][self.current_frame]
        
        # 将值转换为 VTK 数组
        scalars = vtk.vtkFloatArray()
        scalars.SetName(self.current_field)
        for v in values:
            scalars.InsertNextValue(float(v))
            
        self.ugrid.GetPointData().SetScalars(scalars)
        
        # 更新颜色映射范围和标题
        self.mapper.SetScalarRange(field["vmin"], field["vmax"])
        self.scalar_bar.SetTitle(self.current_field)
        
        # 更新帧标签
        frame_label_text = field["frames"][self.current_frame]
        self.frame_label.setText(f"帧: {self.current_frame+1} / {n_frames} ({frame_label_text})")
        
        self.ugrid.Modified()
        self.vtk_widget.GetRenderWindow().Render()

    # ---------------------
    # 回调
    # ---------------------
    def on_slider_pressed(self):
        """滑块按下时，停止播放（如果正在播放）"""
        if self.is_playing:
            self.timer.stop()
            self.is_playing_before_drag = True
        else:
            self.is_playing_before_drag = False

    def on_slider_released(self):
        """滑块释放时，恢复播放（如果释放前正在播放）"""
        if hasattr(self, 'is_playing_before_drag') and self.is_playing_before_drag:
            self.toggle_play_pause()
            self.is_playing_before_drag = False
            
    def on_slider_changed(self, value):
        """滑块值改变时，更新当前帧"""
        if self.current_field=='' or self.current_field not in self.fields:
            return
            
        field = self.fields[self.current_field]
        n_frames = field["data"].shape[0]
        
        if value < 0 or value >= n_frames:
            return
            
        # 仅在值与当前帧不同时才更新，防止不必要的重绘
        if self.current_frame != value:
            self.current_frame = value
            self.update_field()

    def on_field_changed(self, name):
        """物理场下拉框值改变时，切换物理场并重置滑块"""
        if name=='' or name not in self.fields:
            return
            
        # 停止播放
        if self.is_playing:
            self.toggle_play_pause()
            
        self.current_field = name
        n_frames = self.fields[name]["data"].shape[0]
        
        # 更新滑块的最大值和当前值
        self.slider.blockSignals(True)
        self.current_frame = 0
        self.slider.setMaximum(n_frames - 1)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        
        self.update_field()
        self.set_playback_enabled(n_frames > 1) # 只有多帧时才启用播放控制

    def on_loop_changed(self, state):
        """循环复选框改变时"""
        self.loop_mode = (state == QtCore.Qt.Checked)
        
    def on_speed_changed(self, text):
        """倍速下拉框改变时"""
        try:
            speed_str = text.replace('x', '').strip()
            self.play_speed = float(speed_str)
            if self.is_playing:
                self.update_timer_interval() # 立即更新定时器
        except ValueError:
            print(f"Invalid speed format: {text}")
            self.play_speed = 1.0 # 恢复默认
            
# -------------------------
# 主程序
# -------------------------
if __name__=="__main__":    
    app = QtWidgets.QApplication(sys.argv) # 创建应用
    win = VTKWindow() # 创建主窗口
    win.show() # 显示窗口
    sys.exit(app.exec_()) # 运行应用程序主循环
