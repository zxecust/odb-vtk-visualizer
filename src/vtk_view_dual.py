# -*- coding: utf-8 -*-
"""
VTK可视化器：
实现ABAQUS物理场数据的三维可视化、动画播放和多模型并行显示功能。

主要功能包括：
    1. 支持读取.inp文件获取节点和单元信息;
    2. 支持读取多个.csv文件获取全场节点信息;
    3. 支持基于vtk的可视化渲染;
    4. 支持动画播放控制；
    5. 支持多模型并行对比显示；
    6. 支持多模型视窗同步相机视角。
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


# =====================================================
# 数据读取模块
# =====================================================
def read_inp_nodes(inp_path: str):
    """读取 INP 文件中的节点信息，返回节点序号和坐标数组。"""
    node_ids, coords = [], []
    read_flag = False
    with open(inp_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip() # 去除首尾空白
            if not line:
                continue
            if line.lower().startswith("*node"): # 识别*Node关键字
                read_flag = True
                continue
            if read_flag and line.startswith("*"): # 遇到下一个*关键字则停止读取节点
                break
            if read_flag:
                parts = [p.strip() for p in line.split(",")] # 以逗号分割
                if len(parts) < 3: # 节点至少应有编号和两个坐标
                    continue
                try:
                    node_ids.append(int(parts[0])) # 节点编号
                    coords.append([float(x) for x in parts[1:]]) # 节点坐标
                except ValueError:
                    continue
    return np.array(node_ids), np.array(coords)

def read_inp_elements(inp_path: str):
    """读取 INP 文件中的单元信息，返回单元节点编号列表。"""
    elements = []
    read_flag = False
    with open(inp_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip() # 去除首尾空白
            if not line:
                continue
            if line.lower().startswith("*element"): # 识别*Element关键字
                read_flag = True
                continue
            if read_flag and line.startswith("*"): # 遇到下一个*关键字则停止读取单元
                break
            if read_flag:
                parts = [p.strip() for p in line.split(",")] # 以逗号分割
                if len(parts) < 2: # 单元至少应有编号和一个节点
                    continue
                try:
                    elements.append([int(x) for x in parts[1:]]) # 单元节点编号
                except ValueError:
                    continue
    return elements

def read_field_csv(csv_path: str, node_count: int):
    """读取物理场 CSV 文件，返回字段名、数据数组和帧标签。"""
    df = pd.read_csv(csv_path) #这一步操作中默认将CSV文件的第一行作为列名
    if df.shape[1] < 2: # 至少应有帧标签和一个节点数据
        raise ValueError(f"CSV 列数太少：{csv_path}")

    frames = df.iloc[:, 0].astype(str).values # 第一列为帧标签
    data = df.iloc[:, 1:].astype(float).values # 其余列为节点数据

    # 校验维度：希望 data shape = (n_frames, n_nodes)
    if data.shape[1] != node_count:
        # 若转置后匹配则转置
        if data.shape[0] == node_count:
            data = data.T
        else:
            raise ValueError(
                f"CSV 与 INP 节点数不匹配：CSV列={data.shape[1]}，INP节点={node_count}"
            )

    field_name = os.path.splitext(os.path.basename(csv_path))[0] # 用文件名作为字段名
    return field_name, data, frames

# =====================================================
# VTK 辅助：Abaqus 12 色 LUT
# =====================================================
def create_abaqus_lut():
    """创建 Abaqus 风格的 12 色 LUT。"""
    lut = vtk.vtkLookupTable()
    lut.SetNumberOfTableValues(12)
    lut.Build()

    # 你的顺序：小值蓝 -> 大值红（与 Abaqus 常见显示一致）
    abaqus_colors = [
        (0, 0, 1),        # 0000ff
        (0, 0.3647, 1),   # 005dff
        (0, 0.725, 1),    # 00b9ff
        (0, 1, 0.910),    # 00ffe8
        (0, 1, 0.545),    # 00ff8b
        (0, 1, 0.180),    # 00ff2e
        (0.176, 1, 0),    # 2eff00
        (0.545, 1, 0),    # 8bff00
        (0.9098, 1, 0),   # e8ff00
        (1, 0.7255, 0),   # ffb900
        (1, 0.3647, 0),   # ff5d00
        (1, 0, 0)         # ff0000
    ]
    for i, rgb in enumerate(abaqus_colors): # 设置 LUT 颜色
        lut.SetTableValue(i, rgb[0], rgb[1], rgb[2], 1.0)
    return lut

def create_rainbow_lut(num_colors: int = 256):
    """创建 rainbow（HSV）渐变 LUT（深蓝->红色）。"""
    lut = vtk.vtkLookupTable()
    lut.SetNumberOfTableValues(num_colors)
    # 通过 HSV HueRange 生成类似 JET 的彩虹渐变
    lut.SetHueRange(0.667, 0.0)  # blue -> red
    lut.SetSaturationRange(1.0, 1.0)
    lut.SetValueRange(1.0, 1.0)
    lut.Build()
    return lut

def build_unstructured_grid(node_ids: np.ndarray, coords: np.ndarray, elements: list):
    """根据节点和单元信息构建 VTK 非结构化网格。"""
    points = vtk.vtkPoints() # 创建 vtkPoints 对象
    for c in coords:
        if len(c) == 2: 
            points.InsertNextPoint(c[0], c[1], 0.0) # 2D 情况，Z 设为 0
        else:
            points.InsertNextPoint(c[0], c[1], c[2]) # 3D 情况

    grid = vtk.vtkUnstructuredGrid() # 创建 vtkUnstructuredGrid 对象
    grid.SetPoints(points) # 设置点坐标

    id_map = {nid: i for i, nid in enumerate(node_ids)}

    for elem in elements:
        n = len(elem)
        cell = None
        # 根据节点数选择单元类型
        if n == 4: 
            cell = vtk.vtkQuad()
        elif n == 8:
            cell = vtk.vtkHexahedron()
        elif n == 3:
            cell = vtk.vtkTriangle()
        elif n == 6:
            cell = vtk.vtkWedge()
        else:
            continue

        # 将ABAQUS的一个单元转化为VTK网格里的一个cell
        try:
            for i, nid in enumerate(elem):
                cell.GetPointIds().SetId(i, id_map[nid])
            grid.InsertNextCell(cell.GetCellType(), cell.GetPointIds()) 
        except KeyError:
            continue

    return grid


def make_mapper_actor_scalarbar(grid: vtk.vtkUnstructuredGrid, lut: vtk.vtkLookupTable, title: str):
    """为给定网格创建 mapper、actor 和 scalar bar。"""
    # mapper
    # 绑定网格和 LUT
    mapper = vtk.vtkDataSetMapper()
    mapper.SetInputData(grid)
    mapper.SetLookupTable(lut)
    mapper.SetScalarModeToUsePointData()
    mapper.SetColorModeToMapScalars()

    # actor
    # 绑定 mapper 到 actor
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)

    # scalar bar 
    # 放在视窗角落，设置标签数量/格式/字体等
    scalar_bar = vtk.vtkScalarBarActor()
    scalar_bar.SetLookupTable(lut) # 绑定 LUT
    scalar_bar.SetTitle(title)
    scalar_bar.SetNumberOfLabels(12)
    scalar_bar.SetLabelFormat("%.2e") # 科学计数法
    scalar_bar.SetMaximumWidthInPixels(140)
    scalar_bar.SetMaximumHeightInPixels(450)
    scalar_bar.SetPosition(0.02, 0.70) # 设置位置（左上角）
    scalar_bar.SetWidth(0.12)
    scalar_bar.SetHeight(0.25)
    scalar_bar.GetLabelTextProperty().SetFontSize(14) # 设置标签字体大小
    scalar_bar.GetTitleTextProperty().SetFontSize(12)
    scalar_bar.GetTitleTextProperty().BoldOn()

    return mapper, actor, scalar_bar

# =====================================================
# 自定义交互样式
# =====================================================
class CustomInteractorStyle(vtk.vtkInteractorStyleTrackballCamera):
    """
    自定义交互样式：
    - 滚轮：缩放（Dolly）
    - 左键拖动：旋转（Rotate）
    - 中键拖动：平移（Pan）
    """

    def __init__(self):
        super().__init__()

    # 左键拖动：旋转
    def OnMiddleButtonDown(self):
        self.StartRotate()

    def OnMiddleButtonUp(self):
        self.EndRotate()

    # 中键拖动：平移
    def OnLeftButtonDown(self):
        self.StartPan()

    def OnLeftButtonUp(self):
        self.EndPan()

    # 滚轮：缩放（VTK默认也支持，但这里显式控制倍率）
    def OnMouseWheelForward(self):
        self._dolly(1.1)

    def OnMouseWheelBackward(self):
        self._dolly(1.0 / 1.1)

    def _dolly(self, factor: float):
        ren = self.GetCurrentRenderer()
        if ren is None:
            return
        cam = ren.GetActiveCamera()
        if cam is None:
            return

        self.Dolly(factor)
        ren.ResetCameraClippingRange()
        self.GetInteractor().Render()

# =====================================================
# 主窗口
# =====================================================
class VTKCompareWindow(QtWidgets.QMainWindow):
    """
    主界面窗口：左侧显示 FOM（全阶），右侧显示 ROM（降阶）。

    1) 管理数据状态（INP、fom_fields、rom_fields、当前帧/字段）
    2) 管理 Qt UI（菜单、下拉框、slider、播放控制）
    3) 管理 VTK 渲染对象（renderer、grid、mapper、actor、scalarbar）
    4) 动画播放（QTimer 驱动 current_frame 前进）
    5) 视角同步（左右 renderer 共享 vtkCamera）
    6) 安全渲染与关闭保护（避免销毁阶段 OpenGL 错误）
    """
    def __init__(self):
        super().__init__()

        # 模型
        self.node_ids = None
        self.coords = None
        self.elements = None

        # 左侧全阶模型物理场
        # { field_name: { "data": np.ndarray, "frames": list, "vmin": float, "vmax": float } }
        self.fields = {}
        self.current_field = ""
        self.current_frame = 0 # 当前帧索引

        # 右侧降阶模型物理场
        self.rom_fields = {}
        self.rom_current_field = ""

        # 播放控制
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.play_next) # 定时推进帧
        self.is_playing = False
        self.loop_mode = True
        self.base_delay_ms = 100 # 1x 速度下的帧间隔（毫秒）
        self.play_speed = 1.0
        self._closing = False # 关闭阶段标记：用于阻止渲染/回调

        # VTK objects
        self.lut_left = create_rainbow_lut() # 左侧独立 LUT
        self.lut_right = create_rainbow_lut()  # 右侧独立 LUT

        self.background_style = "abaqus"
        self.colormap_style = "rainbow"

        self._init_ui() # 初始化 UI
        self._init_vtk() # 初始化 VTK 渲染

    def showEvent(self, event):
        """窗口显示后初始化交互器和首次渲染。"""
        super().showEvent(event)
        # 这里用 singleShot 延迟执行 _post_show_init，目的是
        # 等窗口句柄真正可用后再 Initialize interactor / Render。
        QtCore.QTimer.singleShot(0, self._post_show_init) 

    def _post_show_init(self):
        """延迟初始化交互器和首次渲染。"""
        # 避免在窗口还未真正创建/可见时初始化 interactor 导致问题
        # 只执行一次（_post_inited 标志）
        if getattr(self, "_post_inited", False):
            return
        self._post_inited = True

        if hasattr(self, "iren_l"):
            self.iren_l.Initialize()
        if hasattr(self, "iren_r"):
            self.iren_r.Initialize()

        self.safe_render_both()

    # -------------------------
    # UI 构建
    # -------------------------
    def _init_ui(self):
        """构建主界面 UI。"""
        self.setWindowTitle("Vtk Visualizer")
        icon_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "logo.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1650, 950)

        central = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(central)

        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # 菜单栏
        menubar = self.menuBar()
        menu_load = menubar.addMenu("加载文件")

        act_inp = QtWidgets.QAction("加载INP文件", self)
        act_inp.triggered.connect(self.open_inp)
        menu_load.addAction(act_inp)

        act_csv = QtWidgets.QAction("加载CSV文件（FOM）", self)
        act_csv.triggered.connect(self.open_csv_left)
        menu_load.addAction(act_csv)

        act_rom = QtWidgets.QAction("加载CSV文件（ROM）", self)
        act_rom.triggered.connect(self.open_csv_right)
        menu_load.addAction(act_rom)

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

        act_lut_grad = QtWidgets.QAction("rainbow", self)
        act_lut_grad.setCheckable(True)
        act_lut_grad.setChecked(self.colormap_style == "rainbow")
        act_lut_grad.triggered.connect(lambda: self.set_colormap_style("rainbow"))

        self.lut_group.addAction(act_lut_abaqus)
        self.lut_group.addAction(act_lut_grad)
        menu_lut.addAction(act_lut_abaqus)
        menu_lut.addAction(act_lut_grad)

        # 控制条
        ctrl_widget = QtWidgets.QWidget()
        ctrl_layout = QtWidgets.QHBoxLayout(ctrl_widget)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(10)

        # 左物理场选择
        ctrl_layout.addWidget(QtWidgets.QLabel("全阶模型（FOM）："))
        self.combo_left = QtWidgets.QComboBox()
        self.combo_left.setMinimumWidth(180)
        self.combo_left.currentTextChanged.connect(self.on_left_field_changed)
        ctrl_layout.addWidget(self.combo_left)

        # 右物理场选择
        ctrl_layout.addWidget(QtWidgets.QLabel("降阶模型（ROM）："))
        self.combo_right = QtWidgets.QComboBox()
        self.combo_right.setMinimumWidth(180)
        self.combo_right.currentTextChanged.connect(self.on_right_field_changed)
        ctrl_layout.addWidget(self.combo_right)

        # 播放按钮
        self.play_btn = QtWidgets.QPushButton("▶ 播放")
        self.play_btn.clicked.connect(self.toggle_play)
        ctrl_layout.addWidget(self.play_btn)

        # 循环复选框
        self.loop_chk = QtWidgets.QCheckBox("循环")
        self.loop_chk.setChecked(True)
        self.loop_chk.stateChanged.connect(lambda s: setattr(self, "loop_mode", s == QtCore.Qt.Checked))
        ctrl_layout.addWidget(self.loop_chk)

        # 倍速选择
        ctrl_layout.addWidget(QtWidgets.QLabel("倍速："))
        self.speed_combo = QtWidgets.QComboBox()
        self.speed_combo.addItems(["0.25x", "0.5x", "1.0x", "2.0x", "4.0x"])
        self.speed_combo.setCurrentText("1.0x")
        self.speed_combo.currentTextChanged.connect(self.on_speed_changed)
        ctrl_layout.addWidget(self.speed_combo)

        # 帧标签
        self.frame_label = QtWidgets.QLabel("帧: 0/0")
        ctrl_layout.addWidget(self.frame_label)

        ctrl_layout.addStretch(1)
        ctrl_widget.setFixedHeight(42)  # 控制条固定高度，解决顶部空白
        main_layout.addWidget(ctrl_widget)

        # 双 VTK 窗口
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.vtk_left = QVTKRenderWindowInteractor(central)
        self.vtk_right = QVTKRenderWindowInteractor(central)
        self.splitter.addWidget(self.vtk_left)
        self.splitter.addWidget(self.vtk_right)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        main_layout.addWidget(self.splitter, 1)  # VTK 区域占满剩余空间

        # 帧滑块
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.valueChanged.connect(self.on_slider_changed)
        main_layout.addWidget(self.slider)

        self.setCentralWidget(central)

        # 初始禁用（必须加载INP和CSV后才可操作）
        self.set_controls_enabled(False)

        # 一些渲染状态标志
        self._post_inited = False
        self._render_pending = False

    def set_controls_enabled(self, enabled: bool):
        """集中控制 UI 控件启用状态。"""
        self.combo_left.setEnabled(enabled)
        self.combo_right.setEnabled(enabled)
        self.play_btn.setEnabled(enabled)
        self.loop_chk.setEnabled(enabled)
        self.speed_combo.setEnabled(enabled)
        self.slider.setEnabled(enabled)

    def set_background_style(self, style: str):
        """切换视窗背景风格并重新渲染。"""
        if not style:
            return
        style = style.strip().lower()
        if style not in ("abaqus", "white"):
            return
        self.background_style = style
        self._apply_background_style(style)

    def _apply_background_style(self, style: str):
        if not hasattr(self, "ren_l") or not hasattr(self, "ren_r"):
            return
        if style == "abaqus":
            self._set_abaqus_background(self.ren_l)
            self._set_abaqus_background(self.ren_r)
        elif style == "white":
            self._set_white_background(self.ren_l)
            self._set_white_background(self.ren_r)
        self.safe_render_both()

    def _set_abaqus_background(self, renderer):
        renderer.GradientBackgroundOn()
        renderer.SetBackground2(27/255.0, 45/255.0, 70/255.0)
        renderer.SetBackground(158/255.0, 173/255.0, 194/255.0)

    def _set_white_background(self, renderer):
        renderer.GradientBackgroundOff()
        renderer.SetBackground(1.0, 1.0, 1.0)
        renderer.SetBackground2(1.0, 1.0, 1.0)

    def set_colormap_style(self, style: str):
        """切换颜色映射并同步左右 LUT。"""
        if not style:
            return
        style = style.strip().lower()
        if style not in ("abaqus", "rainbow"):
            return
        self.colormap_style = style
        self._apply_colormap_style(style)

    def _apply_colormap_style(self, style: str):
        if style == "abaqus":
            new_lut = create_abaqus_lut()
        else:
            new_lut = create_rainbow_lut()

        self.lut_left.DeepCopy(new_lut)
        self.lut_right.DeepCopy(new_lut)

        if hasattr(self, "mapper_l"):
            self.mapper_l.SetLookupTable(self.lut_left)
        if hasattr(self, "mapper_r"):
            self.mapper_r.SetLookupTable(self.lut_right)
        if hasattr(self, "scalarbar_l"):
            self.scalarbar_l.SetLookupTable(self.lut_left)
        if hasattr(self, "scalarbar_r"):
            self.scalarbar_r.SetLookupTable(self.lut_right)

        self.safe_render_both()

    # -------------------------
    # VTK 初始化
    # -------------------------
    def _init_vtk(self):
        """初始化 VTK 渲染器和交互器，并设置视角同步。"""
        # 左 renderer
        self.ren_l = vtk.vtkRenderer()
        self.vtk_left.GetRenderWindow().AddRenderer(self.ren_l)

        # 右 renderer
        self.ren_r = vtk.vtkRenderer()
        self.vtk_right.GetRenderWindow().AddRenderer(self.ren_r)
        self._apply_background_style(self.background_style)

        # 视角同步：共享同一个 vtkCamera
        shared_cam = self.ren_l.GetActiveCamera()
        self.ren_r.SetActiveCamera(shared_cam)

        # 交互器
        self.iren_l = self.vtk_left.GetRenderWindow().GetInteractor()
        self.iren_r = self.vtk_right.GetRenderWindow().GetInteractor()
        self.iren_l.SetInteractorStyle(CustomInteractorStyle()) # 每个 interactor 需要独立的 style 实例（不要复用同一个对象）
        self.iren_r.SetInteractorStyle(CustomInteractorStyle())
        self.iren_l.Initialize() # 初始化交互器
        self.iren_r.Initialize()

        # 交互事件触发合并渲染请求
        self.iren_l.AddObserver("InteractionEvent", lambda o, e: self._request_render())
        self.iren_r.AddObserver("InteractionEvent", lambda o, e: self._request_render())

        # 初次渲染（显示背景）
        self.safe_render_both()

    # -------------------------
    # 加载 INP
    # -------------------------
    def open_inp(self):
        """加载 INP 文件，构建网格并初始化视图。"""
        path, _ = QFileDialog.getOpenFileName(self, "加载 INP 文件", "", "INP Files (*.inp)")
        if not path:
            return
        
        self.stop_play() # 停止播放

        # 读取节点和单元
        self.node_ids, self.coords = read_inp_nodes(path)
        self.elements = read_inp_elements(path)
        if self.coords is None or len(self.coords) == 0:
            QtWidgets.QMessageBox.warning(self, "Warning", "INP 未读取到节点！")
            return

        # 切换 INP 时：清空两侧物理场（避免累加）
        self.fields.clear()
        self.rom_fields.clear()
        self.combo_left.clear()
        self.combo_right.clear()
        self.current_field = ""
        self.rom_current_field = ""
        self.current_frame = 0

        # slider / label 重置
        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.setValue(0)
        self.frame_label.setText("帧: 0/0")

        # 清掉旧 actor / scalarbar
        self.ren_l.RemoveAllViewProps()
        self.ren_r.RemoveAllViewProps()

        # 重建左右几何
        self.grid_l = build_unstructured_grid(self.node_ids, self.coords, self.elements)
        self.grid_r = build_unstructured_grid(self.node_ids, self.coords, self.elements)

        # 左侧 mapper/actor/scalarbar
        self.mapper_l, self.actor_l, self.scalarbar_l = make_mapper_actor_scalarbar(
            self.grid_l, self.lut_left, "FOM"
        )
        self.ren_l.AddActor(self.actor_l)
        self.ren_l.AddViewProp(self.scalarbar_l)   # 加入图例

        # 右侧 mapper/actor/scalarbar
        self.mapper_r, self.actor_r, self.scalarbar_r = make_mapper_actor_scalarbar(
            self.grid_r, self.lut_right, "ROM"
        )
        self.ren_r.AddActor(self.actor_r)
        self.ren_r.AddViewProp(self.scalarbar_r)  # 加入图例

        # 重置相机并渲染
        self.ren_l.ResetCamera()
        self.safe_render_both()

        # 还没加载 CSV，控件先禁用
        self.set_controls_enabled(False)

    # -------------------------
    # 加载 左侧 CSV（FOM）
    # -------------------------
    def open_csv_left(self):
        """加载左侧（FOM）物理场 CSV（支持多选）。"""
        if self.node_ids is None: # 必须先加载 INP
            QtWidgets.QMessageBox.warning(self, "Warning", "请先加载 INP")
            return

        paths, _ = QFileDialog.getOpenFileNames(self, "加载高保真 CSV", "", "CSV Files (*.csv)") # 多选
        if not paths:
            return

        node_count = len(self.node_ids)
        for p in paths:
            try:
                name, data, frames = read_field_csv(p, node_count)
                self.fields[name] = {
                    "data": data,
                    "frames": frames,
                    "vmin": float(np.nanmin(data)),
                    "vmax": float(np.nanmax(data)),
                }
                if self.combo_left.findText(name) == -1:
                    self.combo_left.addItem(name)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"加载失败：{p}\n{e}")

        # 默认选择一个
        if self.combo_left.count() > 0 and self.current_field == "":
            self.combo_left.setCurrentIndex(0)  # 会触发 on_left_field_changed

    # -------------------------
    # 加载 右侧 CSV（ROM）
    # -------------------------
    def open_csv_right(self):
        """加载右侧（ROM）物理场 CSV（支持多选）。"""
        if self.node_ids is None: # 必须先加载 INP
            QtWidgets.QMessageBox.warning(self, "Warning", "请先加载 INP") 
            return

        paths, _ = QFileDialog.getOpenFileNames(self, "加载降阶 CSV", "", "CSV Files (*.csv)") # 多选
        if not paths:
            return

        node_count = len(self.node_ids)
        for p in paths:
            try:
                name, data, frames = read_field_csv(p, node_count)
                self.rom_fields[name] = {
                    "data": data,
                    "frames": frames,
                    "vmin": float(np.nanmin(data)),
                    "vmax": float(np.nanmax(data)),
                }
                if self.combo_right.findText(name) == -1:
                    self.combo_right.addItem(name)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"加载失败：{p}\n{e}")

        if self.combo_right.count() > 0 and self.rom_current_field == "":
            self.combo_right.setCurrentIndex(0)  # 会触发 on_right_field_changed

    # -------------------------
    # 选择字段（左右）
    # -------------------------
    def on_left_field_changed(self, name: str):
        """左侧物理场选择变化回调。"""
        if not name or name not in self.fields:
            return
        self.current_field = name

        n_frames = self.fields[name]["data"].shape[0]
        self.current_frame = 0

        # slider 更新
        self.slider.blockSignals(True)
        self.slider.setMinimum(0)
        self.slider.setMaximum(max(0, n_frames - 1))
        self.slider.setValue(0)
        self.slider.blockSignals(False)

        # 启用控件（至少左侧有数据）
        self.set_controls_enabled(True)

        # 更新视图
        self.update_both_views()

    def on_right_field_changed(self, name: str):
        """右侧物理场选择变化回调。"""
        if not name or name not in self.rom_fields:
            return
        self.rom_current_field = name

        # 更新视图
        self.update_both_views()

    # -------------------------
    # slider
    # -------------------------
    def on_slider_changed(self, value: int):
        """"slider 值变化回调，仅在手动拖动时触发。"""
        if self.current_field == "" or self.current_field not in self.fields: # 检验物理场存在
            return
        n_frames = self.fields[self.current_field]["data"].shape[0] 
        if value < 0 or value >= n_frames: #检验帧范围
            return
        
        # 更新当前帧
        self.current_frame = value

        # 更新视图
        self.update_both_views()

    # -------------------------
    # 播放 / 倍速
    # -------------------------
    def on_speed_changed(self, text: str):
        """倍速选择变化回调。"""
        try:
            self.play_speed = float(text.replace("x", "").strip()) # 解析倍速
        except ValueError:
            self.play_speed = 1.0
        if self.is_playing: # 如果在播放中，更新计时器间隔
            self._apply_timer_interval()

    def _apply_timer_interval(self):
        """根据当前 play_speed 应用计时器间隔。"""
        interval = int(self.base_delay_ms / max(1e-6, self.play_speed))
        self.timer.setInterval(max(1, interval))

    def toggle_play(self):
        """播放/暂停按钮回调。"""
        if self.current_field == "" or self.current_field not in self.fields: #若未选择物理场则不播放
            return

        if self.is_playing: # 正在播放则暂停
            self.stop_play()
        else: # 未播放则开始播放
            self._apply_timer_interval()
            self.timer.start()
            self.is_playing = True
            self.play_btn.setText("⏸ 暂停")

            # 播放时禁用 slider 手动拖动（你的之前需求）
            self.slider.setEnabled(False)

    def stop_play(self):
        """停止播放动画。"""
        self.timer.stop()
        self.is_playing = False
        self.play_btn.setText("▶ 播放")
        self.slider.setEnabled(True)

    def play_next(self):
        """推进到下一帧并回调"""
        # 每 tick 推进帧并更新渲染
        if self.current_field == "" or self.current_field not in self.fields: # 如果未选择物理场则停止
            self.stop_play()
            return

        n_frames = self.fields[self.current_field]["data"].shape[0]
        nxt = self.current_frame + 1
        if nxt >= n_frames: # 如果播放完毕则回到初始帧
            if self.loop_mode:
                nxt = 0
            else:
                self.stop_play()
                return

        self.current_frame = nxt
        # slider 驱动（但播放时 slider 禁用，所以这里用 blockSignals 更新值）
        self.slider.blockSignals(True)
        self.slider.setValue(nxt)
        self.slider.blockSignals(False)

        # 更新视图
        self.update_both_views()

    # -------------------------
    # 更新两侧视图（核心）
    # -------------------------
    def update_both_views(self):
        """核心刷新函数：把“当前帧”的 scalars 写入左右 grid，并触发渲染。"""
        # 左侧：固定使用 self.current_field
        # 右侧：优先显示与左侧同名字段（便于对比：例如 U、S_Mises 等同字段）
        # 如果右侧没有同名字段，则使用 self.rom_current_field
        # 如果右侧无任何数据，则仅更新 scalarbar title 为 "ROM"
        if self.current_field == "" or self.current_field not in self.fields:
            self.frame_label.setText("帧: 0/0")
            return

        # 左侧（FOM）
        field = self.fields[self.current_field]
        n_frames = field["data"].shape[0]
        self.current_frame = int(np.clip(self.current_frame, 0, n_frames - 1))

        v_left = field["data"][self.current_frame]
        scalars_l = vtk.vtkFloatArray()
        scalars_l.SetName(self.current_field)
        for x in v_left:
            scalars_l.InsertNextValue(float(x))
        self.grid_l.GetPointData().SetScalars(scalars_l)

        self.scalarbar_l.SetTitle(self.current_field)

        # 右侧（ROM）
        # 优先：若 ROM 里有同名字段，用同名；否则用 rom_current_field；否则不更新 scalars
        rom_key = None
        if self.current_field in self.rom_fields:
            rom_key = self.current_field
        elif self.rom_current_field in self.rom_fields:
            rom_key = self.rom_current_field
        have_right = False
        if rom_key is not None:
            rfield = self.rom_fields[rom_key]
            rn = rfield["data"].shape[0]
            rf = int(np.clip(self.current_frame, 0, rn - 1))
            v_right = rfield["data"][rf]

            scalars_r = vtk.vtkFloatArray()
            scalars_r.SetName(rom_key)
            for x in v_right:
                scalars_r.InsertNextValue(float(x))
            self.grid_r.GetPointData().SetScalars(scalars_r)
            have_right = True

            self.scalarbar_r.SetTitle(rom_key)
        else:
            # 没有 ROM 数据时，右侧仍显示模型与图例（可选：你也可以隐藏右侧）
            self.scalarbar_r.SetTitle("ROM")

        # 统一左右颜色图例的数值范围
        left_min, left_max = field["vmin"], field["vmax"]
        if have_right:
            right_min, right_max = rfield["vmin"], rfield["vmax"]
            shared_min = min(left_min, right_min)
            shared_max = max(left_max, right_max)
        else:
            shared_min, shared_max = left_min, left_max
            self.grid_r.GetPointData().SetScalars(None) # 没有数据时清空右侧颜色场

        # 防止极端情况：范围为 0（全常数场），VTK 会映射异常/标尺难看
        if shared_max - shared_min < 1e-12:
            eps = 1e-6 if abs(shared_max) < 1e-6 else abs(shared_max) * 1e-6
            shared_min -= eps
            shared_max += eps

        # mapper 与 LUT 同步同一 range，保证颜色和标尺一致
        self.mapper_l.SetScalarRange(shared_min, shared_max)
        self.mapper_r.SetScalarRange(shared_min, shared_max)

        self.lut_left.SetRange(shared_min, shared_max)
        self.lut_right.SetRange(shared_min, shared_max)

        self.scalarbar_l.SetTitle(self.current_field)

        # 帧标签
        frame_text = field["frames"][self.current_frame] if "frames" in field else str(self.current_frame)
        self.frame_label.setText(f"帧: {self.current_frame + 1}/{n_frames} ({frame_text})")

        # render
        self.grid_l.Modified()
        self.grid_r.Modified()

        # 更新视图
        self.safe_render_both()

    # -------------------------
    # 安全渲染与渲染合并
    # -------------------------
    def safe_render(self, vtk_widget):
        """安全渲染单个 VTK widget。"""
        # 在窗口关闭/隐藏/句柄无效时，避免调用 Render() 导致 OpenGL 错误
        try:
            if vtk_widget is None:
                return
            if not vtk_widget.isVisible():
                return
            if vtk_widget.winId() == 0:
                return
            rw = vtk_widget.GetRenderWindow()
            if rw is None:
                return
            rw.Render()
        except Exception:
            # 防止窗口销毁过程中触发 OpenGL 错误
            return

    def safe_render_both(self):
        """安全渲染左右两个VTK widget。若处于 closing 阶段，直接返回。"""
        if getattr(self, "_closing", False):
            return
        self.safe_render(self.vtk_left)
        self.safe_render(self.vtk_right)

    def _request_render(self):
        """请求一次“合并渲染”。"""

        # 交互器在 InteractionEvent 中可能触发很多次回调
        # 用 _render_pending + singleShot(0) 合并多次渲染请求，降低 Render 调用频率
        if getattr(self, "_closing", False): 
            return

        if self._render_pending:
            return
        self._render_pending = True
        QtCore.QTimer.singleShot(0, self._do_render)

    def _do_render(self):
        """执行合并渲染（由 singleShot 调度到事件队列尾部）。"""
        if getattr(self, "_closing", False):
            return

        self._render_pending = False
        self.safe_render_both()

    def closeEvent(self, event):
        """
        重写窗口关闭事件：显式关闭流程，避免 Qt 销毁窗口句柄后，
        VTK 仍尝试使用 OpenGL 上下文而报错（Windows 常见 wglMakeCurrent 崩溃）。

        防护策略：
        1) _closing=True 阻止后续渲染与回调
        2) 停止动画 timer
        3) 阻止合并渲染逻辑继续排队
        4) RemoveAllObservers() 移除交互回调
        5) RenderWindow.Finalize() 提前释放 OpenGL 资源（关键）
        """
        self._closing = True

        # 停止动画计时器
        try:
            if hasattr(self, "timer") and self.timer.isActive():
                self.timer.stop()
        except Exception:
            pass

        # 阻止后续的合并渲染
        # 如果有 _render_pending 标志，这里直接置 True
        try:
            self._render_pending = True
        except Exception:
            pass

        # 移除 VTK 交互器的所有观察者
        try:
            if hasattr(self, "iren_l") and self.iren_l is not None:
                self.iren_l.RemoveAllObservers()
            if hasattr(self, "iren_r") and self.iren_r is not None:
                self.iren_r.RemoveAllObservers()
        except Exception:
            pass

        # 显式 Finalize RenderWindow
        try:
            if hasattr(self, "vtk_left") and self.vtk_left is not None:
                rw = self.vtk_left.GetRenderWindow()
                if rw is not None:
                    rw.Finalize()
            if hasattr(self, "vtk_right") and self.vtk_right is not None:
                rw = self.vtk_right.GetRenderWindow()
                if rw is not None:
                    rw.Finalize()
        except Exception:
            pass

        event.accept()


# =====================================================
# main
# =====================================================
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv) # 创建 QApplication
    win = VTKCompareWindow() # 创建主窗口
    win.show()
    sys.exit(app.exec_()) # 进入 Qt 事件循环
