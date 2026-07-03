# -*- coding: utf-8 -*-
import sys
import os
import re
from pathlib import Path
import numpy as np
import pandas as pd
from matplotlib import cm
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWidgets import QFileDialog
from PyQt5.QtGui import QIcon
import vtk
from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

VTK_OUTPUT_WINDOW = vtk.vtkOutputWindow()
vtk.vtkOutputWindow.SetInstance(VTK_OUTPUT_WINDOW)


ROTATION_AXIS_ORIGIN = np.array([0.0, 0.0, 0.0], dtype=float)
ROTATION_STEP_DEGREES = 5.0
PLANAR_TOLERANCE_FACTOR = 1.0e-8
FONT_REGULAR_NAME = "NotoSansCJKsc-Regular.otf"
FONT_MEDIUM_NAME = "NotoSansCJKsc-Medium.otf"
FONT_BOLD_NAME = "NotoSansCJKsc-Bold.otf"
_APPLICATION_FONT_IDS = []


def _project_root():
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data").is_dir():
            return parent
    if len(here.parents) > 2:
        return here.parents[2]
    return here.parents[1]


def _font_path(filename):
    return _project_root() / "assets" / "fonts" / filename


def install_application_fonts(app):
    """Load bundled fonts into Qt and apply the medium face application-wide."""
    families = []
    medium_family = None
    for filename in (FONT_REGULAR_NAME, FONT_MEDIUM_NAME, FONT_BOLD_NAME):
        path = _font_path(filename)
        if not path.is_file():
            continue
        font_id = QtGui.QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        _APPLICATION_FONT_IDS.append(font_id)
        loaded_families = QtGui.QFontDatabase.applicationFontFamilies(font_id)
        if loaded_families:
            families.extend(loaded_families)
            if filename == FONT_MEDIUM_NAME:
                medium_family = loaded_families[0]

    if families:
        font = app.font()
        font.setFamily(medium_family or families[0])
        if medium_family:
            font.setWeight(QtGui.QFont.Medium)
        app.setFont(font)


def apply_vtk_font_file(text_property, filename):
    """Apply a bundled font to VTK text, falling back to VTK defaults if absent."""
    path = _font_path(filename)
    if text_property is None or not path.is_file():
        return
    text_property.SetFontFamily(vtk.VTK_FONT_FILE)
    text_property.SetFontFile(str(path))

def read_inp_nodes(inp_path):
    node_ids, coords = [], []
    read_flag = False
    with open(inp_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip() 
            if not line:
                continue
            if line.lower().startswith("*node"): 
                read_flag = True
                continue
            if read_flag and line.startswith("*"):
                break
            if read_flag:
                parts = [p.strip() for p in line.split(",")] 
                if len(parts) < 3: 
                    continue
                try:
                    node_ids.append(int(parts[0])) 
                    coords.append([float(x) for x in parts[1:]]) 
                except ValueError:
                    continue
    return np.array(node_ids), np.array(coords)

def _parse_element_type(line):
    parts = [p.strip() for p in line.split(",")]
    for p in parts:
        if p.lower().startswith("type="):
            return p.split("=", 1)[1].strip().upper()
    return None


def read_inp_elements(inp_path):
    elements = []
    read_flag = False
    elem_type = None
    with open(inp_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("**"):
                continue
            if line.startswith("*"):
                if line.lower().startswith("*element"):
                    read_flag = True
                    elem_type = _parse_element_type(line)
                else:
                    read_flag = False
                    elem_type = None
                continue
            if read_flag:
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 2:
                    continue
                try:
                    nodes = [int(x) for x in parts[1:]]
                except ValueError:
                    continue
                elements.append((nodes, elem_type))
    return elements


def read_field_csv(csv_path, node_count):
    df = pd.read_csv(csv_path) 
    if df.shape[1] < 2: 
        raise ValueError(f"CSV 列数太少：{csv_path}")

    frames = df.iloc[:, 0].astype(str).values 
    data = df.iloc[:, 1:].astype(float).values 

    if data.shape[1] != node_count:
        if data.shape[0] == node_count:
            data = data.T
        else:
            raise ValueError(
                f"CSV 与 INP 节点数不匹配：CSV列={data.shape[1]}，INP节点={node_count}"
            )

    field_name = os.path.splitext(os.path.basename(csv_path))[0] 
    return field_name, data, frames

def create_abaqus_lut():
    lut = vtk.vtkLookupTable()
    lut.SetNumberOfTableValues(12)
    lut.Build()

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
    for i, rgb in enumerate(abaqus_colors):
        lut.SetTableValue(i, rgb[0], rgb[1], rgb[2], 1.0)
    return lut

def create_rainbow_lut(num_colors=256):
    lut = vtk.vtkLookupTable()
    lut.SetNumberOfTableValues(num_colors)

    lut.SetHueRange(0.667, 0.0)  
    lut.SetSaturationRange(1.0, 1.0)
    lut.SetValueRange(1.0, 1.0)
    lut.Build()
    return lut


def create_rainbow_2_lut():
    lut = vtk.vtkLookupTable()
    lut.SetNumberOfTableValues(12)
    lut.Build()
    colors = [
        (0.0000, 0.3451, 0.9961),  # 0058fe
        (0.0157, 0.5373, 0.8824),  # 0489e1
        (0.0157, 0.6706, 0.7255),  # 04abb9
        (0.0196, 0.8118, 0.5294),  # 05cf87
        (0.0706, 0.9333, 0.2627),  # 12ee43
        (0.7725, 0.9804, 0.0314),  # c5fa08
        (0.9961, 0.9176, 0.1333),  # feea22
        (1.0000, 0.7373, 0.2157),  # ffbc37
        (0.9961, 0.5608, 0.2118),  # fe8f36
        (0.9922, 0.3216, 0.2078),  # fd5235
        (0.8980, 0.0745, 0.2941),  # e5134b
        (0.6902, 0.0471, 0.4078),  # b00c68
    ]
    for index, (red, green, blue) in enumerate(colors):
        lut.SetTableValue(index, red, green, blue, 1.0)
    return lut


def create_colormap_lut(style):
    if style == "abaqus":
        return create_abaqus_lut()
    if style == "rainbow_2":
        return create_rainbow_2_lut()
    matplotlib_names = {
        "viridis": "viridis",
        "plasma": "plasma",
        "inferno": "inferno",
        "magma": "magma",
        "cividis": "cividis",
        "turbo": "turbo",
        "piyg": "PiYG",
        "coolwarm": "coolwarm",
    }
    if style in matplotlib_names:
        color_map = cm.get_cmap(matplotlib_names[style], 256)
        lut = vtk.vtkLookupTable()
        lut.SetNumberOfTableValues(256)
        lut.Build()
        for index in range(256):
            red, green, blue, alpha = color_map(index)
            lut.SetTableValue(index, red, green, blue, alpha)
        return lut
    return create_rainbow_lut()


def _paired_finite_values(reference, prediction):
    reference = np.asarray(reference, dtype=float).ravel()
    prediction = np.asarray(prediction, dtype=float).ravel()
    if reference.shape != prediction.shape:
        raise ValueError("FOM 与 ROM 数据形状不一致。")
    valid = np.isfinite(reference) & np.isfinite(prediction)
    return reference[valid], prediction[valid], int(valid.size - np.count_nonzero(valid))


def calculate_error_metrics(reference, prediction, metric_keys):
    reference, prediction, invalid_count = _paired_finite_values(reference, prediction)
    if reference.size == 0:
        raise ValueError("FOM 与 ROM 之间没有可用于分析的有效数据。")

    error = prediction - reference
    absolute_error = np.abs(error)
    mse = float(np.mean(error ** 2))
    scale = max(float(np.max(np.abs(reference))), 1.0)
    zero_tolerance = scale * 1.0e-12
    relative_mask = np.abs(reference) > zero_tolerance
    relative_error = absolute_error[relative_mask] / np.abs(reference[relative_mask])
    reference_range = float(np.max(reference) - np.min(reference))
    reference_norm = float(np.linalg.norm(reference))

    results = {}
    for key in metric_keys:
        if key == "r2":
            denominator = float(np.sum((reference - np.mean(reference)) ** 2))
            results[key] = None if denominator <= zero_tolerance ** 2 else 1.0 - float(np.sum(error ** 2)) / denominator
        elif key == "mre":
            results[key] = None if relative_error.size == 0 else float(np.mean(relative_error))
        elif key == "rmse":
            results[key] = float(np.sqrt(mse))
        elif key == "mae":
            results[key] = float(np.mean(absolute_error))
        elif key == "mape":
            results[key] = None if relative_error.size == 0 else float(np.mean(relative_error) * 100.0)
        elif key == "max_ae":
            results[key] = float(np.max(absolute_error))
        elif key == "max_re":
            results[key] = None if relative_error.size == 0 else float(np.max(relative_error))
        elif key == "nrmse":
            results[key] = None if reference_range <= zero_tolerance else float(np.sqrt(mse) / reference_range)
        elif key == "relative_l2":
            results[key] = None if reference_norm <= zero_tolerance else float(np.linalg.norm(error) / reference_norm)
        elif key == "pearson":
            ref_std = float(np.std(reference))
            pred_std = float(np.std(prediction))
            results[key] = None if ref_std <= zero_tolerance or pred_std <= zero_tolerance else float(np.corrcoef(reference, prediction)[0, 1])
    return results, reference.size, invalid_count, int(reference.size - np.count_nonzero(relative_mask))


class CsvLoadWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, str)
    finished = QtCore.pyqtSignal(object, object, bool)

    def __init__(self, paths, node_count):
        super().__init__()
        self.paths = list(paths)
        self.node_count = int(node_count)
        self.cancel_requested = False

    def cancel(self):
        self.cancel_requested = True

    @QtCore.pyqtSlot()
    def run(self):
        results, errors = [], []
        total = max(len(self.paths), 1)
        for index, path in enumerate(self.paths):
            if self.cancel_requested:
                break
            filename = os.path.basename(path)
            start = int(index * 100 / total)
            self.progress.emit(start, f"正在读取 {filename}（{index + 1}/{total}）")
            try:
                name, data, frames = read_field_csv(path, self.node_count)
                if self.cancel_requested:
                    break
                self.progress.emit(
                    int((index + 0.8) * 100 / total),
                    f"正在统计 {filename} 的数值范围",
                )
                results.append(
                    (
                        name,
                        {
                            "data": data,
                            "frames": frames,
                            "vmin": float(np.nanmin(data)),
                            "vmax": float(np.nanmax(data)),
                        },
                    )
                )
            except Exception as exc:
                errors.append((path, str(exc)))
            self.progress.emit(int((index + 1) * 100 / total), f"已处理 {filename}")
        self.finished.emit(results, errors, self.cancel_requested)


class ErrorFieldWorker(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, str)
    finished = QtCore.pyqtSignal(object, object, bool)

    def __init__(self, fom_name, rom_name, fom_field, rom_field, error_types):
        super().__init__()
        self.fom_name = fom_name
        self.rom_name = rom_name
        self.fom_field = fom_field
        self.rom_field = rom_field
        self.error_types = list(error_types)
        self.cancel_requested = False

    def cancel(self):
        self.cancel_requested = True

    @QtCore.pyqtSlot()
    def run(self):
        generated, errors = [], []
        type_labels = {
            "absolute": "绝对误差",
            "relative": "相对误差",
            "normalized": "归一化绝对误差",
        }
        try:
            self.progress.emit(5, "正在匹配 FOM 与 ROM 帧")
            fom_data = np.asarray(self.fom_field["data"], dtype=float)
            rom_data = np.asarray(self.rom_field["data"], dtype=float)
            if fom_data.shape[1] != rom_data.shape[1]:
                raise ValueError("FOM 与 ROM 的节点数量不一致。")
            pairs, matching_note = GlobalConsistencyDialog._matched_frames(
                self.fom_field, self.rom_field
            )
            if not pairs:
                raise ValueError("FOM 与 ROM 没有可比较的帧。")
            fom_indices = np.asarray([pair[0] for pair in pairs], dtype=int)
            rom_indices = np.asarray([pair[1] for pair in pairs], dtype=int)
            reference = fom_data[fom_indices]
            prediction = rom_data[rom_indices]
            pair_finite = np.isfinite(reference) & np.isfinite(prediction)
            self.progress.emit(15, "正在计算基础绝对误差")
            absolute_error = np.abs(prediction - reference)
            finite_reference = reference[np.isfinite(reference)]
            scale = max(float(np.max(np.abs(finite_reference))) if finite_reference.size else 0.0, 1.0)
            denominator_valid = np.abs(reference) > scale * 1.0e-12
            reference_range = float(np.ptp(finite_reference)) if finite_reference.size else 0.0
            tolerance = scale * 1.0e-12

            total = max(len(self.error_types), 1)
            for index, error_type in enumerate(self.error_types):
                if self.cancel_requested:
                    break
                self.progress.emit(
                    20 + int(index * 70 / total),
                    f"正在生成{type_labels[error_type]}（{index + 1}/{total}）",
                )
                excluded_count = 0
                if error_type == "absolute":
                    values = absolute_error.copy()
                elif error_type == "normalized":
                    if reference_range > tolerance:
                        values = absolute_error / reference_range
                    else:
                        values = np.full_like(absolute_error, np.nan)
                        excluded_count = int(values.size)
                else:
                    values = np.full_like(absolute_error, np.nan)
                    np.divide(
                        absolute_error,
                        np.abs(reference),
                        out=values,
                        where=denominator_valid,
                    )
                    excluded_count = int(values.size - np.count_nonzero(denominator_valid))
                values[~pair_finite] = np.nan
                data = np.full(fom_data.shape, np.nan, dtype=float)
                data[fom_indices] = values
                finite = data[np.isfinite(data)]
                if finite.size == 0:
                    errors.append(f"{type_labels[error_type]}没有有效数据。")
                    continue
                field_pair = (
                    self.fom_name if self.fom_name == self.rom_name
                    else f"{self.fom_name} vs {self.rom_name}"
                )
                display_name = f"[误差] {field_pair} | {type_labels[error_type]}"
                generated.append(
                    (
                        display_name,
                        {
                            "data": data,
                            "frames": np.asarray(self.fom_field["frames"]),
                            "vmin": 0.0,
                            "vmax": float(np.max(finite)),
                            "error_type": error_type,
                            "fom_field": self.fom_name,
                            "rom_field": self.rom_name,
                            "unit": "",
                            "vtk_title": {
                                "absolute": "Absolute Error",
                                "relative": "Relative Error",
                                "normalized": "Normalized Error",
                            }[error_type],
                        },
                        len(pairs),
                        excluded_count,
                        matching_note,
                        type_labels[error_type],
                    )
                )
            self.progress.emit(95, "正在准备更新主窗口")
        except Exception as exc:
            errors.append(str(exc))
        self.finished.emit(generated, errors, self.cancel_requested)


class BackgroundTaskUiBridge(QtCore.QObject):

    def __init__(self, owner, thread, worker, progress, finished_callback, task):
        super().__init__(owner)
        self.owner = owner
        self.thread = thread
        self.worker = worker
        self.progress = progress
        self.finished_callback = finished_callback
        self.task = task

    @QtCore.pyqtSlot(int, str)
    def update_progress(self, value, message):
        if self.owner._closing or self.task.get("discarded", False):
            return
        self.progress.setLabelText(message)
        self.progress.setValue(int(value))
        self.owner.statusBar().showMessage(message)

    @QtCore.pyqtSlot(object, object, bool)
    def finish_task(self, results, errors, cancelled):
        self.progress.setValue(100)
        self.progress.close()
        if not self.owner._closing:
            self.finished_callback(results, errors, cancelled)
        self.thread.quit()

    @QtCore.pyqtSlot()
    def cleanup_task(self):
        if self.task in self.owner._background_tasks:
            self.owner._background_tasks.remove(self.task)
        self.deleteLater()

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
        if et.startswith(("CPS8", "CPE8", "CAX8", "S8")):
            return vtk.vtkQuadraticQuad()
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


def build_unstructured_grid(node_ids, coords, elements):
    points = vtk.vtkPoints() 
    for c in coords:
        if len(c) == 2: 
            points.InsertNextPoint(c[0], c[1], 0.0)
        else:
            points.InsertNextPoint(c[0], c[1], c[2]) 

    grid = vtk.vtkUnstructuredGrid() 
    grid.SetPoints(points) 

    id_map = {nid: i for i, nid in enumerate(node_ids)}

    for elem in elements:
        nodes, elem_type = _unpack_element(elem)
        n = len(nodes)
        cell = _select_cell(elem_type, n)
        if cell is None:
            continue

        try:
            for i, nid in enumerate(nodes):
                cell.GetPointIds().SetId(i, id_map[nid])
            grid.InsertNextCell(cell.GetCellType(), cell.GetPointIds())
        except KeyError:
            continue

    return grid


def _coords_3d(coords):
    arr = np.asarray(coords, dtype=float)
    if arr.ndim != 2 or arr.shape[1] not in (2, 3):
        raise ValueError("Node coordinates must have shape (n, 2) or (n, 3).")
    if arr.shape[1] == 2:
        arr = np.column_stack([arr, np.zeros(len(arr), dtype=float)])
    return arr


def detect_planar_axis(coords):
    xyz = _coords_3d(coords)
    spans = np.ptp(xyz, axis=0)
    scale = max(float(np.max(spans)), 1.0)
    tolerance = scale * PLANAR_TOLERANCE_FACTOR
    candidates = np.flatnonzero(spans <= tolerance)
    if candidates.size != 1:
        raise ValueError(
            "The mesh must lie on one axis-aligned plane (XY, XZ, or YZ). "
            f"Coordinate spans are {spans.tolist()}."
        )
    return int(candidates[0])


def extract_boundary_edges(node_ids, elements):
    id_to_index = {int(node_id): index for index, node_id in enumerate(node_ids)}
    edge_counts = {}
    edge_orientation = {}
    surface_cells = []

    for elem in elements:
        nodes, elem_type = _unpack_element(elem)
        elem_type = (elem_type or "").upper()
        is_2d_type = elem_type.startswith(("CPS", "CPE", "CAX", "S3", "S4"))
        if elem_type and not is_2d_type:
            continue
        if len(nodes) not in (3, 4, 8):
            continue
        try:
            indices = [id_to_index[int(node_id)] for node_id in nodes]
        except KeyError:
            continue
        if len(indices) == 8:
            perimeter = [
                indices[0],
                indices[4],
                indices[1],
                indices[5],
                indices[2],
                indices[6],
                indices[3],
                indices[7],
            ]
        else:
            perimeter = indices
        surface_cells.append(perimeter)
        for index in range(len(perimeter)):
            edge = (perimeter[index], perimeter[(index + 1) % len(perimeter)])
            key = tuple(sorted(edge))
            edge_counts[key] = edge_counts.get(key, 0) + 1
            edge_orientation.setdefault(key, edge)

    boundary_edges = [edge_orientation[key] for key, count in edge_counts.items() if count == 1]
    if not surface_cells:
        raise ValueError("No supported triangular or quadrilateral 2D elements were found.")
    if not boundary_edges:
        raise ValueError("No outer boundary edges were found in the 2D mesh.")
    return surface_cells, boundary_edges


def _rotate_points(points, axis, origin, angle_radians):
    axis = np.asarray(axis, dtype=float)
    axis /= np.linalg.norm(axis)
    relative = points - origin
    cosine = np.cos(angle_radians)
    sine = np.sin(angle_radians)
    return (
        origin
        + relative * cosine
        + np.cross(axis, relative) * sine
        + np.outer(relative @ axis, axis) * (1.0 - cosine)
    )


def build_rotational_surface(node_ids, coords, elements, axis_index, angle_degrees, offset_distance):
    xyz = _coords_3d(coords)
    planar_axis = detect_planar_axis(xyz)
    if axis_index == planar_axis:
        plane_names = {0: "YZ", 1: "XZ", 2: "XY"}
        axis_names = {0: "X", 1: "Y", 2: "Z"}
        raise ValueError(
            f"The {axis_names[axis_index]} axis is normal to the detected "
            f"{plane_names[planar_axis]} plane and cannot create a solid of revolution."
        )

    surface_cells, boundary_edges = extract_boundary_edges(node_ids, elements)
    offset_axis = next(index for index in range(3) if index not in (axis_index, planar_axis))
    shifted = xyz.copy()
    shifted[:, offset_axis] += float(offset_distance)

    axis = np.zeros(3, dtype=float)
    axis[axis_index] = 1.0
    relative = shifted - ROTATION_AXIS_ORIGIN
    radial = relative - np.outer(relative @ axis, axis)
    radial_distance = np.linalg.norm(radial, axis=1)
    radial_tolerance = max(float(np.ptp(shifted, axis=0).max()), 1.0) * PLANAR_TOLERANCE_FACTOR
    boundary_edges = [
        edge
        for edge in boundary_edges
        if not (
            radial_distance[edge[0]] <= radial_tolerance
            and radial_distance[edge[1]] <= radial_tolerance
        )
    ]
    if not boundary_edges:
        raise ValueError("All boundary edges lie on the selected rotation axis.")

    angle_degrees = float(angle_degrees)
    closed = np.isclose(angle_degrees, 360.0)
    segment_count = max(1, int(np.ceil(angle_degrees / ROTATION_STEP_DEGREES)))
    if closed:
        angles = np.linspace(0.0, 2.0 * np.pi, segment_count, endpoint=False)
    else:
        angles = np.linspace(0.0, np.deg2rad(angle_degrees), segment_count + 1)

    vtk_points = vtk.vtkPoints()
    source_indices = []
    boundary_node_indices = sorted({index for edge in boundary_edges for index in edge})
    layer_point_ids = []
    for layer_index, angle in enumerate(angles):
        layer = _rotate_points(shifted, axis, ROTATION_AXIS_ORIGIN, angle)
        is_end_section = not closed and layer_index in (0, len(angles) - 1)
        layer_sources = range(len(node_ids)) if is_end_section else boundary_node_indices
        point_ids = {}
        for source_index in layer_sources:
            point_ids[source_index] = vtk_points.InsertNextPoint(*layer[source_index])
            source_indices.append(source_index)
        layer_point_ids.append(point_ids)

    polygons = vtk.vtkCellArray()
    cap_polygons = vtk.vtkCellArray()
    layer_count = len(angles)
    side_steps = layer_count if closed else layer_count - 1
    for layer_index in range(side_steps):
        next_layer = (layer_index + 1) % layer_count
        for start, end in boundary_edges:
            quad = vtk.vtkQuad()
            quad.GetPointIds().SetId(0, layer_point_ids[layer_index][start])
            quad.GetPointIds().SetId(1, layer_point_ids[layer_index][end])
            quad.GetPointIds().SetId(2, layer_point_ids[next_layer][end])
            quad.GetPointIds().SetId(3, layer_point_ids[next_layer][start])
            polygons.InsertNextCell(quad)

    if not closed:
        for layer_index, reverse_order in ((0, True), (layer_count - 1, False)):
            for indices in surface_cells:
                ordered = list(reversed(indices)) if reverse_order else indices
                if len(ordered) == 3:
                    polygon = vtk.vtkTriangle()
                elif len(ordered) == 4:
                    polygon = vtk.vtkQuad()
                else:
                    polygon = vtk.vtkPolygon()
                    polygon.GetPointIds().SetNumberOfIds(len(ordered))
                for local_index, source_index in enumerate(ordered):
                    polygon.GetPointIds().SetId(local_index, layer_point_ids[layer_index][source_index])
                polygons.InsertNextCell(polygon)
                cap_polygons.InsertNextCell(polygon)

    polydata = vtk.vtkPolyData()
    polydata.SetPoints(vtk_points)
    polydata.SetPolys(polygons)
    polydata.BuildCells()
    polydata.BuildLinks()

    cap_polydata = vtk.vtkPolyData()
    cap_polydata.SetPoints(vtk_points)
    cap_polydata.SetPolys(cap_polygons)
    cap_polydata.BuildCells()
    cap_polydata.BuildLinks()
    return polydata, cap_polydata, np.asarray(source_indices, dtype=np.int64)



def make_mapper_actor_scalarbar(grid, lut, title):
    mapper = vtk.vtkDataSetMapper()
    mapper.SetInputData(grid)
    mapper.SetLookupTable(lut)
    mapper.SetScalarModeToUsePointData()
    mapper.SetColorModeToMapScalars()

    actor = vtk.vtkActor()
    actor.SetMapper(mapper)

    scalar_bar = vtk.vtkScalarBarActor()
    scalar_bar.SetLookupTable(lut) 
    scalar_bar.SetTitle(title)
    scalar_bar.SetNumberOfLabels(12)
    scalar_bar.SetLabelFormat("%.2e") 
    scalar_bar.SetMaximumWidthInPixels(140)
    scalar_bar.SetMaximumHeightInPixels(560)
    scalar_bar.SetPosition(0.02, 0.60) 
    scalar_bar.SetWidth(0.12)
    scalar_bar.SetHeight(0.35)
    label_property = scalar_bar.GetLabelTextProperty()
    title_property = scalar_bar.GetTitleTextProperty()
    label_property.SetFontSize(14)
    title_property.SetFontSize(12)
    apply_vtk_font_file(label_property, FONT_MEDIUM_NAME)
    apply_vtk_font_file(title_property, FONT_BOLD_NAME)

    return mapper, actor, scalar_bar


def build_mesh_edge_polydata(dataset):
    edge_polydata = vtk.vtkPolyData()
    if dataset is None or dataset.GetPoints() is None:
        return edge_polydata
    edge_polydata.SetPoints(dataset.GetPoints())

    lines = vtk.vtkCellArray()
    seen_edges = set()

    def add_edge(point_ids):
        ordered = tuple(int(point_id) for point_id in point_ids)
        if len(ordered) < 2 or len(set(ordered)) < 2:
            return
        reversed_order = tuple(reversed(ordered))
        key = min(ordered, reversed_order)
        if key in seen_edges:
            return
        seen_edges.add(key)
        polyline = vtk.vtkPolyLine()
        polyline.GetPointIds().SetNumberOfIds(len(ordered))
        for index, point_id in enumerate(ordered):
            polyline.GetPointIds().SetId(index, point_id)
        lines.InsertNextCell(polyline)

    for cell_index in range(dataset.GetNumberOfCells()):
        cell = dataset.GetCell(cell_index)
        if cell is None:
            continue
        if cell.GetCellType() == vtk.VTK_QUADRATIC_QUAD and cell.GetNumberOfPoints() == 8:
            ids = [int(cell.GetPointId(index)) for index in range(8)]
            for edge in (
                (ids[0], ids[4], ids[1]),
                (ids[1], ids[5], ids[2]),
                (ids[2], ids[6], ids[3]),
                (ids[3], ids[7], ids[0]),
            ):
                add_edge(edge)
            continue

        for edge_index in range(cell.GetNumberOfEdges()):
            edge = cell.GetEdge(edge_index)
            if edge is None:
                continue
            ids = [int(edge.GetPointId(index)) for index in range(edge.GetNumberOfPoints())]
            if edge.GetCellType() == vtk.VTK_QUADRATIC_EDGE and len(ids) == 3:
                ids = [ids[0], ids[2], ids[1]]
            add_edge(ids)

    edge_polydata.SetLines(lines)
    edge_polydata.BuildCells()
    return edge_polydata


def make_wireframe_actor(grid):
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputData(build_mesh_edge_polydata(grid))
    mapper.ScalarVisibilityOff()
    mapper.SetResolveCoincidentTopologyToPolygonOffset()
    mapper.SetRelativeCoincidentTopologyLineOffsetParameters(0.0, -2.0)
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    prop = actor.GetProperty()
    prop.SetColor(0.32, 0.34, 0.38)
    prop.SetOpacity(0.28)
    prop.SetLineWidth(0.6)
    actor.SetVisibility(False)
    return mapper, actor


class HotspotFilterDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.owner = parent
        self.setWindowTitle("热点高亮 - 高亮设置")
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)

        layout = QtWidgets.QFormLayout(self)
        self.mode_combo = QtWidgets.QComboBox(self)
        self.mode_combo.addItem("绝对值", "absolute")
        self.mode_combo.addItem("最大值比例", "max_ratio")
        self.mode_combo.addItem("分位数", "percentile")
        self.mode_combo.setCurrentIndex(1)
        self.mode_combo.currentIndexChanged.connect(self._update_threshold_editor)
        layout.addRow("过滤逻辑：", self.mode_combo)

        self.comparison_combo = QtWidgets.QComboBox(self)
        self.comparison_combo.addItem("大于", "greater")
        self.comparison_combo.addItem("小于", "less")
        self.comparison_combo.addItem("等于", "equal")
        layout.addRow("比较方式：", self.comparison_combo)

        self.threshold_input = QtWidgets.QDoubleSpinBox(self)
        self.threshold_input.setDecimals(6)
        self.threshold_input.setValue(20.0)
        layout.addRow("过滤阈值：", self.threshold_input)

        self.transparency_input = QtWidgets.QDoubleSpinBox(self)
        self.transparency_input.setRange(0.0, 100.0)
        self.transparency_input.setDecimals(1)
        self.transparency_input.setSingleStep(5.0)
        self.transparency_input.setSuffix(" %")
        self.transparency_input.setValue(100.0)
        layout.addRow("被过滤区域透明度：", self.transparency_input)

        buttons = QtWidgets.QDialogButtonBox(self)
        self.apply_button = buttons.addButton("应用", QtWidgets.QDialogButtonBox.ApplyRole)
        self.restore_button = buttons.addButton("恢复原始云图", QtWidgets.QDialogButtonBox.ResetRole)
        close_button = buttons.addButton("关闭", QtWidgets.QDialogButtonBox.RejectRole)
        self.apply_button.clicked.connect(self.apply_settings)
        self.restore_button.clicked.connect(self.owner.restore_original_cloud)
        close_button.clicked.connect(self.hide)
        layout.addRow(buttons)
        self._update_threshold_editor()

    def _update_threshold_editor(self):
        mode = self.mode_combo.currentData()
        old_value = self.threshold_input.value()
        if mode == "absolute":
            self.threshold_input.setRange(-1.0e15, 1.0e15)
            self.threshold_input.setSuffix("")
            self.threshold_input.setSingleStep(1.0)
        else:
            self.threshold_input.setRange(0.0, 100.0)
            self.threshold_input.setSuffix(" %")
            self.threshold_input.setSingleStep(1.0)
        self.threshold_input.setValue(np.clip(old_value, self.threshold_input.minimum(), self.threshold_input.maximum()))

    def apply_settings(self):
        self.owner.set_hotspot_filter(
            mode=self.mode_combo.currentData(),
            comparison=self.comparison_combo.currentData(),
            threshold=self.threshold_input.value(),
            filtered_transparency=self.transparency_input.value(),
        )

class NodeQueryDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("节点查询")
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setMinimumWidth(300)

        layout = QtWidgets.QVBoxLayout(self)
        self.info_label = QtWidgets.QLabel(
            "\u8282\u70b9\u7f16\u53f7\uff1a--\n"
            "x：--\n"
            "y：--\n"
            "z：--"
        )
        self.info_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        font = self.info_label.font()
        font.setPointSize(11)
        self.info_label.setFont(font)
        layout.addWidget(self.info_label)

        close_button = QtWidgets.QPushButton("关闭窗口", self)
        close_button.clicked.connect(self.hide)
        layout.addWidget(close_button, alignment=QtCore.Qt.AlignRight)

    def clear_result(self):
        self.info_label.setText(
            "\u8282\u70b9\u7f16\u53f7\uff1a--\n"
            "x：--\n"
            "y：--\n"
            "z：--"
        )

    def set_node(self, node_id, coordinates):
        x, y, z = coordinates
        lines = [
            "\u8282\u70b9\u7f16\u53f7\uff1a" + str(int(node_id)),
            "x：" + format(float(x), ".6f"),
            "y：" + format(float(y), ".6f"),
            "z：" + format(float(z), ".6f"),
        ]
        self.info_label.setText("\n".join(lines))

    def set_status(self, message):
        self.info_label.setText(str(message))

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class ExtremeQueryDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.owner = parent
        self.setWindowTitle("极值查询")
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.resize(760, 360)

        root_layout = QtWidgets.QVBoxLayout(self)
        controls = QtWidgets.QHBoxLayout()

        controls.addWidget(QtWidgets.QLabel("数据来源："))
        self.source_combo = QtWidgets.QComboBox(self)
        self.source_combo.addItem("FOM和ROM", "both")
        self.source_combo.addItem("FOM", "fom")
        self.source_combo.addItem("ROM", "rom")
        controls.addWidget(self.source_combo)

        controls.addWidget(QtWidgets.QLabel("极值类型："))
        self.type_combo = QtWidgets.QComboBox(self)
        self.type_combo.addItem("最大值", "maximum")
        self.type_combo.addItem("最小值", "minimum")
        self.type_combo.addItem("绝对值最大值", "absolute_maximum")
        controls.addWidget(self.type_combo)

        controls.addWidget(QtWidgets.QLabel("查询范围："))
        self.scope_combo = QtWidgets.QComboBox(self)
        self.scope_combo.addItem("全部节点", "all")
        self.scope_combo.addItem("当前可见节点", "visible")
        controls.addWidget(self.scope_combo)

        controls.addWidget(QtWidgets.QLabel("结果数量："))
        self.count_input = QtWidgets.QSpinBox(self)
        self.count_input.setRange(1, 20)
        self.count_input.setValue(1)
        controls.addWidget(self.count_input)

        self.auto_update_check = QtWidgets.QCheckBox("自动更新", self)
        self.auto_update_check.setChecked(True)
        controls.addWidget(self.auto_update_check)
        controls.addStretch(1)
        root_layout.addLayout(controls)

        self.context_label = QtWidgets.QLabel("当前字段/帧：--", self)
        root_layout.addWidget(self.context_label)

        self.result_table = QtWidgets.QTableWidget(0, 7, self)
        self.result_table.setHorizontalHeaderLabels(
            ["模型", "极值类型", "节点编号", "数值", "x", "y", "z"]
        )
        self.result_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.result_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.result_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.result_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        self.result_table.cellDoubleClicked.connect(
            lambda row, column: self.owner.locate_extreme_result(row)
        )
        root_layout.addWidget(self.result_table, 1)

        buttons = QtWidgets.QDialogButtonBox(self)
        query_button = buttons.addButton("查询", QtWidgets.QDialogButtonBox.ApplyRole)
        locate_button = buttons.addButton("定位到节点", QtWidgets.QDialogButtonBox.ActionRole)
        copy_button = buttons.addButton("复制结果", QtWidgets.QDialogButtonBox.ActionRole)
        clear_button = buttons.addButton("清除结果", QtWidgets.QDialogButtonBox.ResetRole)
        close_button = buttons.addButton("关闭", QtWidgets.QDialogButtonBox.RejectRole)
        query_button.clicked.connect(self.owner.run_extreme_query)
        locate_button.clicked.connect(self.locate_selected_row)
        copy_button.clicked.connect(self.copy_selected_row)
        clear_button.clicked.connect(self.owner.clear_extreme_markers)
        close_button.clicked.connect(self.hide)
        root_layout.addWidget(buttons)

    def settings(self):
        return {
            "source": self.source_combo.currentData(),
            "extreme_type": self.type_combo.currentData(),
            "scope": self.scope_combo.currentData(),
            "count": self.count_input.value(),
        }

    def set_results(self, rows, context):
        type_by_label = {
            "最大值": "maximum",
            "最小值": "minimum",
            "绝对值最大值": "absolute_maximum",
        }
        normalized_rows = []
        for source_row in rows:
            row = dict(source_row)
            row.setdefault(
                "extreme_type",
                type_by_label.get(row.get("type_label"), "maximum"),
            )
            row.setdefault("side", "right" if row.get("model") == "ROM" else "left")
            normalized_rows.append(row)
        self.result_rows = normalized_rows
        self.context_label.setText(context)
        self.result_table.setRowCount(len(normalized_rows))
        for row_index, row in enumerate(normalized_rows):
            values = [
                row["model"],
                row["type_label"],
                str(row["node_id"]),
                f"{row['value']:.6e}",
                f"{row['x']:.6f}",
                f"{row['y']:.6f}",
                f"{row['z']:.6f}",
            ]
            for column_index, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if row.get("extreme_type") == "minimum":
                    item.setBackground(QtGui.QColor("#D9F5F7"))
                elif row.get("extreme_type") == "absolute_maximum":
                    item.setBackground(QtGui.QColor("#FDE7CE"))
                else:
                    item.setBackground(QtGui.QColor("#FADADD"))
                self.result_table.setItem(row_index, column_index, item)
        if normalized_rows:
            self.result_table.selectRow(0)
            self.result_table.setCurrentCell(0, 0)

    def selected_row(self):
        selection = self.result_table.selectionModel().selectedRows()
        if selection:
            return selection[0].row()
        current_row = self.result_table.currentRow()
        if current_row >= 0:
            return current_row
        selected_items = self.result_table.selectedItems()
        return selected_items[0].row() if selected_items else -1

    def locate_selected_row(self):
        row = self.selected_row()
        if row >= 0:
            self.owner.locate_extreme_result(row)
        else:
            self.owner.statusBar().showMessage("请先选择一条极值查询结果。", 5000)

    def copy_selected_row(self):
        row = self.selected_row()
        if row < 0 or row >= len(getattr(self, "result_rows", [])):
            return
        result = self.result_rows[row]
        text = (
            f"{result['model']}\t{result['type_label']}\t{result['node_id']}\t"
            f"{result['value']:.6e}\t{result['x']:.6f}\t"
            f"{result['y']:.6f}\t{result['z']:.6f}"
        )
        QtWidgets.QApplication.clipboard().setText(text)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class GlobalConsistencyDialog(QtWidgets.QDialog):
    METRICS = (
        ("r2", "R²"),
        ("mre", "平均相对误差（MRE）"),
        ("rmse", "均方根误差（RMSE）"),
        ("mae", "平均绝对误差（MAE）"),
        ("mape", "平均绝对百分比误差（MAPE）"),
        ("max_ae", "最大绝对误差（MaxAE）"),
        ("max_re", "最大相对误差（MaxRE）"),
        ("nrmse", "归一化均方根误差（NRMSE）"),
        ("relative_l2", "相对 L2 误差"),
        ("pearson", "Pearson 相关系数"),
    )

    def __init__(self, parent):
        super().__init__(parent)
        self.owner = parent
        self.setWindowTitle("误差计算")
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.resize(680, 620)

        root = QtWidgets.QVBoxLayout(self)
        fields = QtWidgets.QFormLayout()
        self.fom_combo = QtWidgets.QComboBox(self)
        self.rom_combo = QtWidgets.QComboBox(self)
        fields.addRow("全阶模型物理场：", self.fom_combo)
        fields.addRow("降阶模型物理场：", self.rom_combo)
        root.addLayout(fields)

        node_row = QtWidgets.QHBoxLayout()
        self.node_check = QtWidgets.QCheckBox("计算指定节点", self)
        self.node_input = QtWidgets.QLineEdit(self)
        self.node_input.setPlaceholderText("节点编号")
        self.node_input.setValidator(QtGui.QIntValidator(1, 2147483647, self))
        self.node_input.setEnabled(False)
        self.node_check.toggled.connect(self.node_input.setEnabled)
        node_row.addWidget(self.node_check)
        node_row.addWidget(QtWidgets.QLabel("节点编号：", self))
        node_row.addWidget(self.node_input, 1)
        root.addLayout(node_row)

        frame_row = QtWidgets.QHBoxLayout()
        self.frame_range_check = QtWidgets.QCheckBox("指定帧范围", self)
        self.frame_range_input = QtWidgets.QLineEdit(self)
        self.frame_range_input.setPlaceholderText("例如：5 或 5 20（包含端点）")
        self.frame_range_input.setEnabled(False)
        self.frame_range_check.toggled.connect(self.frame_range_input.setEnabled)
        frame_row.addWidget(self.frame_range_check)
        frame_row.addWidget(QtWidgets.QLabel("帧范围：", self))
        frame_row.addWidget(self.frame_range_input, 1)
        root.addLayout(frame_row)

        metric_group = QtWidgets.QGroupBox("误差指标", self)
        metric_layout = QtWidgets.QGridLayout(metric_group)
        self.metric_checks = {}
        default_keys = {"r2", "rmse", "mae", "mape", "relative_l2"}
        for index, (key, label) in enumerate(self.METRICS):
            checkbox = QtWidgets.QCheckBox(label, metric_group)
            checkbox.setChecked(key in default_keys)
            self.metric_checks[key] = checkbox
            metric_layout.addWidget(checkbox, index // 2, index % 2)
        root.addWidget(metric_group)

        self.summary_label = QtWidgets.QLabel("请选择物理场和误差指标后开始分析。", self)
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        root.addWidget(self.summary_label)

        self.result_table = QtWidgets.QTableWidget(0, 2, self)
        self.result_table.setHorizontalHeaderLabels(["误差指标", "计算结果"])
        self.result_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        self.result_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        root.addWidget(self.result_table, 1)

        buttons = QtWidgets.QDialogButtonBox(self)
        analyze_button = buttons.addButton("分析", QtWidgets.QDialogButtonBox.ApplyRole)
        close_button = buttons.addButton("关闭", QtWidgets.QDialogButtonBox.RejectRole)
        analyze_button.clicked.connect(self.analyze)
        close_button.clicked.connect(self.hide)
        root.addWidget(buttons)

    def refresh_fields(self):
        old_fom = self.fom_combo.currentText()
        old_rom = self.rom_combo.currentText()
        self.fom_combo.clear()
        self.rom_combo.clear()
        self.fom_combo.addItems(list(self.owner.fields.keys()))
        self.rom_combo.addItems(list(self.owner.rom_fields.keys()))
        if old_fom and self.fom_combo.findText(old_fom) >= 0:
            self.fom_combo.setCurrentText(old_fom)
        elif self.owner.current_field in self.owner.fields:
            self.fom_combo.setCurrentText(self.owner.current_field)
        if old_rom and self.rom_combo.findText(old_rom) >= 0:
            self.rom_combo.setCurrentText(old_rom)
        elif self.fom_combo.currentText() in self.owner.rom_fields:
            self.rom_combo.setCurrentText(self.fom_combo.currentText())
        elif self.owner.rom_current_field in self.owner.rom_fields:
            self.rom_combo.setCurrentText(self.owner.rom_current_field)

    @staticmethod
    def _matched_frames(fom_field, rom_field):
        fom_labels = [str(value) for value in fom_field["frames"]]
        rom_labels = [str(value) for value in rom_field["frames"]]
        rom_positions = {}
        for index, label in enumerate(rom_labels):
            rom_positions.setdefault(label, []).append(index)
        pairs = []
        used_counts = {}
        for fom_index, label in enumerate(fom_labels):
            occurrence = used_counts.get(label, 0)
            candidates = rom_positions.get(label, [])
            if occurrence < len(candidates):
                pairs.append((fom_index, candidates[occurrence]))
                used_counts[label] = occurrence + 1
        if pairs:
            return pairs, "按公共帧标签匹配"
        count = min(fom_field["data"].shape[0], rom_field["data"].shape[0])
        return [(index, index) for index in range(count)], "无公共帧标签，按帧位置匹配"

    @staticmethod
    def _parse_frame_range(text, frame_count):
        parts = str(text).split()
        if len(parts) not in (1, 2):
            raise ValueError("帧范围只能输入一个帧号，或两个用空格分隔的帧号。")
        try:
            numbers = [int(part) for part in parts]
        except ValueError as exc:
            raise ValueError("帧范围必须使用整数帧号。") from exc
        start = numbers[0]
        end = numbers[0] if len(numbers) == 1 else numbers[1]
        if start < 1 or end < 1 or start > frame_count or end > frame_count:
            raise ValueError(f"帧号必须位于 1 到 {frame_count} 之间。")
        if start > end:
            raise ValueError("帧范围的起始帧不能大于结束帧。")
        return start, end

    def analyze(self):
        fom_name = self.fom_combo.currentText()
        rom_name = self.rom_combo.currentText()
        metric_keys = [key for key, checkbox in self.metric_checks.items() if checkbox.isChecked()]
        if fom_name not in self.owner.fields or rom_name not in self.owner.rom_fields:
            QtWidgets.QMessageBox.warning(self, "无法分析", "请先分别加载并选择 FOM 与 ROM 物理场。")
            return
        if not metric_keys:
            QtWidgets.QMessageBox.warning(self, "无法分析", "请至少选择一个误差指标。")
            return

        fom_field = self.owner.fields[fom_name]
        rom_field = self.owner.rom_fields[rom_name]
        if fom_field["data"].shape[1] != rom_field["data"].shape[1]:
            QtWidgets.QMessageBox.critical(self, "无法分析", "FOM 与 ROM 的节点数量不一致。")
            return
        pairs, matching_note = self._matched_frames(fom_field, rom_field)
        if not pairs:
            QtWidgets.QMessageBox.critical(self, "无法分析", "FOM 与 ROM 没有可比较的帧。")
            return

        frame_scope_text = "全部匹配帧"
        if self.frame_range_check.isChecked():
            try:
                start_frame, end_frame = self._parse_frame_range(
                    self.frame_range_input.text(), fom_field["data"].shape[0]
                )
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(self, "帧范围无效", str(exc))
                return
            pairs = [
                pair for pair in pairs
                if start_frame - 1 <= pair[0] <= end_frame - 1
            ]
            if not pairs:
                QtWidgets.QMessageBox.warning(
                    self,
                    "帧范围无效",
                    "指定范围内没有能够与 ROM 匹配的 FOM 帧。",
                )
                return
            frame_scope_text = (
                f"第 {start_frame} 帧" if start_frame == end_frame
                else f"第 {start_frame}–{end_frame} 帧"
            )

        fom_indices = [pair[0] for pair in pairs]
        rom_indices = [pair[1] for pair in pairs]
        reference = np.asarray(fom_field["data"][fom_indices], dtype=float)
        prediction = np.asarray(rom_field["data"][rom_indices], dtype=float)
        scope_text = "全场"
        if self.node_check.isChecked():
            node_text = self.node_input.text().strip()
            if not node_text:
                QtWidgets.QMessageBox.warning(self, "无法分析", "请输入节点编号。")
                return
            node_id = int(node_text)
            positions = np.flatnonzero(np.asarray(self.owner.node_ids) == node_id)
            if positions.size == 0:
                QtWidgets.QMessageBox.warning(self, "无法分析", f"未找到节点编号 {node_id}。")
                return
            node_index = int(positions[0])
            reference = reference[:, node_index]
            prediction = prediction[:, node_index]
            scope_text = f"节点 {node_id}"

        try:
            results, valid_count, invalid_count, zero_reference_count = calculate_error_metrics(
                reference, prediction, metric_keys
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "分析失败", str(exc))
            return

        labels = dict(self.METRICS)
        percent_metrics = {"mre", "max_re", "relative_l2", "nrmse"}
        self.result_table.setRowCount(len(metric_keys))
        for row, key in enumerate(metric_keys):
            value = results.get(key)
            if value is None or not np.isfinite(value):
                text = "N/A"
            elif key == "mape":
                text = f"{value:.6g} %"
            elif key in percent_metrics:
                text = f"{value:.6e}  ({value * 100.0:.6g} %)"
            else:
                text = f"{value:.6e}"
            self.result_table.setItem(row, 0, QtWidgets.QTableWidgetItem(labels[key]))
            self.result_table.setItem(row, 1, QtWidgets.QTableWidgetItem(text))

        self.summary_label.setText(
            f"FOM：{fom_name} | ROM：{rom_name} | 空间范围：{scope_text} | 帧范围：{frame_scope_text}\n"
            f"{matching_note}，实际计算帧 {len(pairs)}，有效样本 {valid_count}，"
            f"无效样本 {invalid_count}，相对误差零基准样本 {zero_reference_count}。"
        )

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class LocalConsistencyDialog(QtWidgets.QDialog):
    METRICS = (
        ("mae", "平均绝对误差（MAE）"),
        ("rmse", "均方根误差（RMSE）"),
        ("mape", "平均绝对百分比误差（MAPE）"),
        ("max_ae", "最大绝对误差（MaxAE）"),
        ("max_re", "最大相对误差（MaxRE）"),
    )

    def __init__(self, parent):
        super().__init__(parent)
        self.owner = parent
        self.setWindowTitle("局部一致性")
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.resize(1050, 780)

        root = QtWidgets.QVBoxLayout(self)
        settings_group = QtWidgets.QGroupBox("分析设置", self)
        settings_layout = QtWidgets.QGridLayout(settings_group)

        settings_layout.addWidget(QtWidgets.QLabel("处理对象：", self), 0, 0)
        model_row = QtWidgets.QHBoxLayout()
        self.fom_check = QtWidgets.QCheckBox("FOM", self)
        self.rom_check = QtWidgets.QCheckBox("ROM", self)
        self.fom_check.setChecked(True)
        self.rom_check.setChecked(True)
        model_row.addWidget(self.fom_check)
        model_row.addWidget(self.rom_check)
        model_row.addStretch(1)
        settings_layout.addLayout(model_row, 0, 1, 1, 3)

        settings_layout.addWidget(QtWidgets.QLabel("FOM 物理场：", self), 1, 0)
        self.fom_combo = QtWidgets.QComboBox(self)
        settings_layout.addWidget(self.fom_combo, 1, 1)
        settings_layout.addWidget(QtWidgets.QLabel("ROM 物理场：", self), 1, 2)
        self.rom_combo = QtWidgets.QComboBox(self)
        settings_layout.addWidget(self.rom_combo, 1, 3)

        settings_layout.addWidget(QtWidgets.QLabel("节点编号：", self), 2, 0)
        self.node_input = QtWidgets.QLineEdit(self)
        self.node_input.setValidator(QtGui.QIntValidator(1, 2147483647, self))
        settings_layout.addWidget(self.node_input, 2, 1)

        settings_layout.addWidget(QtWidgets.QLabel("物理量：", self), 2, 2)
        quantity_row = QtWidgets.QHBoxLayout()
        self.quantity_input = QtWidgets.QLineEdit(self)
        self.quantity_input.setPlaceholderText("例如：温度")
        self.quantity_unit_input = QtWidgets.QLineEdit(self)
        self.quantity_unit_input.setPlaceholderText("单位")
        quantity_row.addWidget(self.quantity_input, 2)
        quantity_row.addWidget(QtWidgets.QLabel("单位：", self))
        quantity_row.addWidget(self.quantity_unit_input, 1)
        settings_layout.addLayout(quantity_row, 2, 3)

        settings_layout.addWidget(QtWidgets.QLabel("帧间隔：", self), 3, 0)
        interval_row = QtWidgets.QHBoxLayout()
        self.frame_interval_input = QtWidgets.QLineEdit(self)
        interval_validator = QtGui.QDoubleValidator(0.0, 1.0e15, 12, self)
        interval_validator.setNotation(QtGui.QDoubleValidator.ScientificNotation)
        self.frame_interval_input.setValidator(interval_validator)
        self.frame_interval_input.setText("1")
        self.time_unit_input = QtWidgets.QLineEdit(self)
        self.time_unit_input.setPlaceholderText("单位")
        interval_row.addWidget(self.frame_interval_input, 2)
        interval_row.addWidget(QtWidgets.QLabel("单位：", self))
        interval_row.addWidget(self.time_unit_input, 1)
        settings_layout.addLayout(interval_row, 3, 1)

        settings_layout.addWidget(QtWidgets.QLabel("处理范围：", self), 3, 2)
        range_row = QtWidgets.QHBoxLayout()
        self.frame_range_check = QtWidgets.QCheckBox("指定帧", self)
        self.start_frame_input = QtWidgets.QSpinBox(self)
        self.end_frame_input = QtWidgets.QSpinBox(self)
        for editor in (self.start_frame_input, self.end_frame_input):
            editor.setRange(1, 1)
            editor.setEnabled(False)
        range_row.addWidget(self.frame_range_check)
        range_row.addWidget(QtWidgets.QLabel("帧索引：", self))
        range_row.addWidget(self.start_frame_input)
        range_row.addWidget(QtWidgets.QLabel("到", self))
        range_row.addWidget(self.end_frame_input)
        settings_layout.addLayout(range_row, 3, 3)

        metrics_group = QtWidgets.QGroupBox("误差指标", self)
        metrics_layout = QtWidgets.QHBoxLayout(metrics_group)
        self.metric_checks = {}
        for key, label in self.METRICS:
            checkbox = QtWidgets.QCheckBox(label, metrics_group)
            checkbox.setChecked(True)
            self.metric_checks[key] = checkbox
            metrics_layout.addWidget(checkbox)
        metrics_layout.addStretch(1)
        settings_layout.addWidget(metrics_group, 4, 0, 1, 4)

        button_row = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel("请选择物理场并设置分析参数。", self)
        self.status_label.setWordWrap(True)
        analyze_button = QtWidgets.QPushButton("分析", self)
        export_button = QtWidgets.QPushButton("导出", self)
        close_button = QtWidgets.QPushButton("关闭", self)
        analyze_button.clicked.connect(self.analyze)
        export_button.clicked.connect(self.export_data)
        close_button.clicked.connect(self.hide)
        button_row.addWidget(self.status_label, 1)
        button_row.addWidget(analyze_button)
        button_row.addWidget(export_button)
        button_row.addWidget(close_button)
        settings_layout.addLayout(button_row, 5, 0, 1, 4)
        root.addWidget(settings_group)

        self.figure = Figure(figsize=(8.5, 5.2), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        self.axes = self.figure.add_subplot(111)
        root.addWidget(self.canvas, 1)

        self.fom_check.toggled.connect(self._model_selection_changed)
        self.rom_check.toggled.connect(self._model_selection_changed)
        self.fom_combo.currentIndexChanged.connect(self._update_frame_range)
        self.rom_combo.currentIndexChanged.connect(self._update_frame_range)
        self.frame_range_check.toggled.connect(self._set_frame_range_enabled)
        self._plot_font = self._make_plot_font(FONT_MEDIUM_NAME)
        self._plot_bold_font = self._make_plot_font(FONT_BOLD_NAME)
        self._draw_empty_plot()

    @staticmethod
    def _make_plot_font(filename):
        path = _font_path(filename)
        return FontProperties(fname=str(path)) if path.is_file() else FontProperties()

    def _draw_empty_plot(self):
        self.axes.clear()
        self.axes.text(
            0.5, 0.5, "设置参数后点击“分析”生成曲线",
            ha="center", va="center", transform=self.axes.transAxes,
            fontproperties=self._plot_font,
        )
        self._style_axes()
        self.canvas.draw_idle()

    def refresh_fields(self):
        old_fom = self.fom_combo.currentText()
        old_rom = self.rom_combo.currentText()
        self.fom_combo.blockSignals(True)
        self.rom_combo.blockSignals(True)
        self.fom_combo.clear()
        self.rom_combo.clear()
        self.fom_combo.addItems(list(self.owner.fields.keys()))
        self.rom_combo.addItems(list(self.owner.rom_fields.keys()))
        if old_fom in self.owner.fields:
            self.fom_combo.setCurrentText(old_fom)
        elif self.owner.current_field in self.owner.fields:
            self.fom_combo.setCurrentText(self.owner.current_field)
        if old_rom in self.owner.rom_fields:
            self.rom_combo.setCurrentText(old_rom)
        elif self.owner.rom_current_field in self.owner.rom_fields:
            self.rom_combo.setCurrentText(self.owner.rom_current_field)
        elif self.fom_combo.currentText() in self.owner.rom_fields:
            self.rom_combo.setCurrentText(self.fom_combo.currentText())
        self.fom_combo.blockSignals(False)
        self.rom_combo.blockSignals(False)
        self._model_selection_changed()

    def _model_selection_changed(self):
        self.fom_combo.setEnabled(self.fom_check.isChecked())
        self.rom_combo.setEnabled(self.rom_check.isChecked())
        metrics_enabled = self.fom_check.isChecked() and self.rom_check.isChecked()
        for checkbox in self.metric_checks.values():
            checkbox.setEnabled(metrics_enabled)
        self._update_frame_range()

    def _reference_field(self):
        if self.fom_check.isChecked() and self.fom_combo.currentText() in self.owner.fields:
            return self.owner.fields[self.fom_combo.currentText()]
        if self.rom_check.isChecked() and self.rom_combo.currentText() in self.owner.rom_fields:
            return self.owner.rom_fields[self.rom_combo.currentText()]
        return None

    def _update_frame_range(self):
        field = self._reference_field()
        frame_count = int(field["data"].shape[0]) if field is not None else 1
        frame_count = max(frame_count, 1)
        start_value = min(self.start_frame_input.value(), frame_count)
        end_value = min(max(self.end_frame_input.value(), start_value), frame_count)
        self.start_frame_input.setRange(1, frame_count)
        self.end_frame_input.setRange(1, frame_count)
        self.start_frame_input.setValue(start_value)
        self.end_frame_input.setValue(end_value if end_value > 1 else frame_count)

    def _set_frame_range_enabled(self, enabled):
        self.start_frame_input.setEnabled(bool(enabled))
        self.end_frame_input.setEnabled(bool(enabled))

    def _validate_inputs(self):
        use_fom = self.fom_check.isChecked()
        use_rom = self.rom_check.isChecked()
        if not use_fom and not use_rom:
            raise ValueError("请至少勾选 FOM 或 ROM。")
        fom_name = self.fom_combo.currentText()
        rom_name = self.rom_combo.currentText()
        if use_fom and fom_name not in self.owner.fields:
            raise ValueError("请选择有效的 FOM 物理场。")
        if use_rom and rom_name not in self.owner.rom_fields:
            raise ValueError("请选择有效的 ROM 物理场。")
        node_text = self.node_input.text().strip()
        if not node_text:
            raise ValueError("请输入节点编号。")
        node_id = int(node_text)
        positions = np.flatnonzero(np.asarray(self.owner.node_ids) == node_id)
        if positions.size == 0:
            raise ValueError(f"未找到节点编号 {node_id}。")
        interval_text = self.frame_interval_input.text().strip()
        if not interval_text:
            raise ValueError("请输入帧间隔。")
        interval = float(interval_text)
        if not np.isfinite(interval) or interval <= 0.0:
            raise ValueError("帧间隔必须是大于 0 的有限数值。")
        if self.frame_range_check.isChecked():
            start = self.start_frame_input.value() - 1
            end = self.end_frame_input.value() - 1
            if start > end:
                raise ValueError("起始帧不能大于结束帧。")
        else:
            reference = self._reference_field()
            start = 0
            end = int(reference["data"].shape[0]) - 1
        return use_fom, use_rom, fom_name, rom_name, int(positions[0]), node_id, interval, start, end

    def _series_for_plot(self, use_fom, use_rom, fom_name, rom_name, node_index, start, end):
        if use_fom and use_rom:
            fom_field = self.owner.fields[fom_name]
            rom_field = self.owner.rom_fields[rom_name]
            if fom_field["data"].shape[1] != rom_field["data"].shape[1]:
                raise ValueError("FOM 与 ROM 的节点数量不一致。")
            pairs, matching_note = GlobalConsistencyDialog._matched_frames(fom_field, rom_field)
            pairs = [pair for pair in pairs if start <= pair[0] <= end]
            if not pairs:
                raise ValueError("指定帧范围内没有可比较的 FOM 与 ROM 帧。")
            frame_indices = np.asarray([pair[0] for pair in pairs], dtype=int)
            fom_values = np.asarray(
                [fom_field["data"][pair[0], node_index] for pair in pairs], dtype=float
            )
            rom_values = np.asarray(
                [rom_field["data"][pair[1], node_index] for pair in pairs], dtype=float
            )
            return frame_indices, fom_values, rom_values, matching_note
        if use_fom:
            field = self.owner.fields[fom_name]
            indices = np.arange(start, min(end, field["data"].shape[0] - 1) + 1, dtype=int)
            return indices, np.asarray(field["data"][indices, node_index], dtype=float), None, "仅绘制 FOM"
        field = self.owner.rom_fields[rom_name]
        indices = np.arange(start, min(end, field["data"].shape[0] - 1) + 1, dtype=int)
        return indices, None, np.asarray(field["data"][indices, node_index], dtype=float), "仅绘制 ROM"

    @staticmethod
    def _annotation_location(x, series):
        finite_series = [np.asarray(values, dtype=float) for values in series if values is not None]
        if not finite_series or len(x) < 2:
            return 0.98, "right"
        all_values = np.concatenate([values[np.isfinite(values)] for values in finite_series])
        if all_values.size == 0:
            return 0.98, "right"
        midpoint_x = (float(np.min(x)) + float(np.max(x))) * 0.5
        midpoint_y = (float(np.min(all_values)) + float(np.max(all_values))) * 0.5
        left_count = right_count = 0
        for values in finite_series:
            valid = np.isfinite(values)
            left_count += int(np.count_nonzero(valid & (x <= midpoint_x) & (values >= midpoint_y)))
            right_count += int(np.count_nonzero(valid & (x > midpoint_x) & (values >= midpoint_y)))
        return (0.02, "left") if left_count <= right_count else (0.98, "right")

    def _style_axes(self):
        for spine in self.axes.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(1.0)
        self.axes.tick_params(axis="both", which="both", direction="in", top=True, right=True)
        for label in self.axes.get_xticklabels() + self.axes.get_yticklabels():
            label.set_fontproperties(self._plot_font)

    def analyze(self):
        try:
            values = self._validate_inputs()
            use_fom, use_rom, fom_name, rom_name, node_index, node_id, interval, start, end = values
            frame_indices, fom_values, rom_values, matching_note = self._series_for_plot(
                use_fom, use_rom, fom_name, rom_name, node_index, start, end
            )
            if frame_indices.size == 0:
                raise ValueError("指定范围内没有可绘制的帧。")
            selected_metrics = [
                key for key, checkbox in self.metric_checks.items()
                if checkbox.isChecked() and checkbox.isEnabled()
            ]
            metric_results = {}
            if selected_metrics:
                metric_results, _, _, _ = calculate_error_metrics(
                    fom_values, rom_values, selected_metrics
                )
        except (ValueError, TypeError) as exc:
            QtWidgets.QMessageBox.warning(self, "无法分析", str(exc))
            return

        time_values = frame_indices.astype(float) * interval
        quantity = self.quantity_input.text().strip() or "物理量"
        quantity_unit = self.quantity_unit_input.text().strip()
        time_unit = self.time_unit_input.text().strip()
        x_label = f"时间（{time_unit}）" if time_unit else "时间"
        y_label = f"{quantity}（{quantity_unit}）" if quantity_unit else quantity

        self.axes.clear()
        if fom_values is not None:
            self.axes.plot(
                time_values, fom_values, color="black", linestyle="-", linewidth=2.5,
                label="全阶模型", zorder=2,
            )
        if rom_values is not None:
            self.axes.plot(
                time_values, rom_values, color="red", linestyle=":", linewidth=2.0,
                label="降阶模型", zorder=3,
            )
        self.axes.set_xlabel(x_label, fontproperties=self._plot_font)
        self.axes.set_ylabel(y_label, fontproperties=self._plot_font)
        self.axes.margins(x=0.03, y=0.08)
        self._style_axes()
        legend = self.axes.legend(prop=self._plot_font, frameon=False)
        if legend is not None:
            legend.set_zorder(10)

        if metric_results:
            labels = dict(self.METRICS)
            lines = []
            for key in selected_metrics:
                result = metric_results.get(key)
                if result is None or not np.isfinite(result):
                    text = "N/A"
                elif key == "mape":
                    text = f"{result:.6g} %"
                elif key == "max_re":
                    text = f"{result:.6e}（{result * 100.0:.6g} %）"
                else:
                    text = f"{result:.6e}"
                lines.append(f"{labels[key]} = {text}")
            annotation_x, alignment = self._annotation_location(
                time_values, (fom_values, rom_values)
            )
            self.axes.text(
                annotation_x, 0.98, "\n".join(lines), transform=self.axes.transAxes,
                ha=alignment, va="top", fontproperties=self._plot_font,
                bbox={"facecolor": "white", "edgecolor": "0.65", "alpha": 0.88, "pad": 5},
                zorder=20,
            )
        self.canvas.draw_idle()
        self.status_label.setText(
            f"节点 {node_id}；{matching_note}；已绘制 {len(frame_indices)} 个时序点。"
        )

    @staticmethod
    def _safe_filename_component(value):
        text = re.sub(r'[<>:"/\\|?*]+', "_", str(value).strip())
        return text.strip(" ._") or "field"

    def _build_export_dataframe(self):
        values = self._validate_inputs()
        use_fom, use_rom, fom_name, rom_name, node_index, node_id, interval, start, end = values
        frame_indices, fom_values, rom_values, matching_note = self._series_for_plot(
            use_fom, use_rom, fom_name, rom_name, node_index, start, end
        )
        if frame_indices.size == 0:
            raise ValueError("指定范围内没有可导出的帧。")

        columns = {"Time": frame_indices.astype(float) * interval}
        if fom_values is not None:
            columns[f"FE {fom_name}"] = fom_values
        if rom_values is not None:
            columns[f"Predicted {rom_name}"] = rom_values

        field_name = fom_name if use_fom else rom_name
        if self.frame_range_check.isChecked():
            range_name = f"frames_{start + 1}-{end + 1}"
        else:
            range_name = "all_frames"
        default_name = (
            f"{self._safe_filename_component(field_name)}_node_{node_id}_{range_name}.csv"
        )
        return pd.DataFrame(columns), default_name, node_id, matching_note

    def export_data(self):
        try:
            dataframe, default_name, node_id, matching_note = self._build_export_dataframe()
        except (ValueError, TypeError) as exc:
            QtWidgets.QMessageBox.warning(self, "无法导出", str(exc))
            return

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "导出局部一致性数据",
            default_name,
            "CSV 文件 (*.csv);;Excel 文件 (*.xlsx)",
        )
        if not path:
            return

        suffix = Path(path).suffix.lower()
        if suffix not in (".csv", ".xlsx"):
            suffix = ".xlsx" if "Excel" in selected_filter else ".csv"
            path += suffix

        try:
            if suffix == ".xlsx":
                dataframe.to_excel(path, index=False, engine="openpyxl")
            else:
                dataframe.to_csv(path, index=False, encoding="utf-8-sig")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "导出失败", str(exc))
            return

        self.status_label.setText(
            f"节点 {node_id}；{matching_note}；已导出 {len(dataframe)} 行数据到 {path}"
        )

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class ErrorFieldDialog(QtWidgets.QDialog):
    ERROR_TYPES = (
        ("absolute", "绝对误差"),
        ("relative", "相对误差"),
        ("normalized", "归一化绝对误差"),
    )

    def __init__(self, parent):
        super().__init__(parent)
        self.owner = parent
        self.setWindowTitle("生成误差云图")
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.resize(520, 360)

        root = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.fom_combo = QtWidgets.QComboBox(self)
        self.rom_combo = QtWidgets.QComboBox(self)
        form.addRow("FOM 物理场：", self.fom_combo)
        form.addRow("ROM 物理场：", self.rom_combo)
        root.addLayout(form)

        group = QtWidgets.QGroupBox("误差云图类型（可多选）", self)
        group_layout = QtWidgets.QVBoxLayout(group)
        self.type_checks = {}
        for key, label in self.ERROR_TYPES:
            checkbox = QtWidgets.QCheckBox(label, group)
            checkbox.setChecked(key == "absolute")
            self.type_checks[key] = checkbox
            group_layout.addWidget(checkbox)
        root.addWidget(group)

        self.status_label = QtWidgets.QLabel("生成结果将加入主窗口右侧物理场下拉框。", self)
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        root.addWidget(self.status_label)

        buttons = QtWidgets.QDialogButtonBox(self)
        generate_button = buttons.addButton("生成", QtWidgets.QDialogButtonBox.ApplyRole)
        close_button = buttons.addButton("关闭", QtWidgets.QDialogButtonBox.RejectRole)
        generate_button.clicked.connect(self.generate)
        close_button.clicked.connect(self.hide)
        root.addWidget(buttons)

    def refresh_fields(self):
        old_fom = self.fom_combo.currentText()
        old_rom = self.rom_combo.currentText()
        self.fom_combo.clear()
        self.rom_combo.clear()
        self.fom_combo.addItems(list(self.owner.fields.keys()))
        self.rom_combo.addItems(list(self.owner.rom_fields.keys()))
        if old_fom in self.owner.fields:
            self.fom_combo.setCurrentText(old_fom)
        elif self.owner.current_field in self.owner.fields:
            self.fom_combo.setCurrentText(self.owner.current_field)
        if old_rom in self.owner.rom_fields:
            self.rom_combo.setCurrentText(old_rom)
        elif self.fom_combo.currentText() in self.owner.rom_fields:
            self.rom_combo.setCurrentText(self.fom_combo.currentText())
        elif self.owner.rom_current_field in self.owner.rom_fields:
            self.rom_combo.setCurrentText(self.owner.rom_current_field)

    @staticmethod
    def _build_error_data(fom_field, rom_field, error_type):
        fom_data = np.asarray(fom_field["data"], dtype=float)
        rom_data = np.asarray(rom_field["data"], dtype=float)
        if fom_data.shape[1] != rom_data.shape[1]:
            raise ValueError("FOM 与 ROM 的节点数量不一致。")
        pairs, matching_note = GlobalConsistencyDialog._matched_frames(fom_field, rom_field)
        if not pairs:
            raise ValueError("FOM 与 ROM 没有可比较的帧。")

        output = np.full(fom_data.shape, np.nan, dtype=float)
        fom_indices = np.asarray([pair[0] for pair in pairs], dtype=int)
        rom_indices = np.asarray([pair[1] for pair in pairs], dtype=int)
        reference = fom_data[fom_indices]
        prediction = rom_data[rom_indices]
        pair_finite = np.isfinite(reference) & np.isfinite(prediction)
        absolute_error = np.abs(prediction - reference)
        excluded_count = 0
        if error_type == "absolute":
            values = absolute_error
        elif error_type == "normalized":
            finite_reference = reference[np.isfinite(reference)]
            reference_range = float(np.ptp(finite_reference)) if finite_reference.size else 0.0
            tolerance = max(float(np.max(np.abs(finite_reference))) if finite_reference.size else 0.0, 1.0) * 1.0e-12
            values = absolute_error / reference_range if reference_range > tolerance else np.full_like(absolute_error, np.nan)
            if reference_range <= tolerance:
                excluded_count = int(values.size)
        else:
            finite_reference = reference[np.isfinite(reference)]
            scale = max(float(np.max(np.abs(finite_reference))) if finite_reference.size else 0.0, 1.0)
            valid_denominator = np.abs(reference) > scale * 1.0e-12
            values = np.full_like(absolute_error, np.nan)
            np.divide(absolute_error, np.abs(reference), out=values, where=valid_denominator)
            excluded_count = int(values.size - np.count_nonzero(valid_denominator))
        values[~pair_finite] = np.nan
        output[fom_indices] = values
        return output, pairs, matching_note, excluded_count

    def generate(self):
        fom_name = self.fom_combo.currentText()
        rom_name = self.rom_combo.currentText()
        selected_types = [key for key, checkbox in self.type_checks.items() if checkbox.isChecked()]
        if fom_name not in self.owner.fields or rom_name not in self.owner.rom_fields:
            QtWidgets.QMessageBox.warning(self, "无法生成", "请先选择 FOM 与 ROM 物理场。")
            return
        if not selected_types:
            QtWidgets.QMessageBox.warning(self, "无法生成", "请至少选择一种误差云图类型。")
            return
        self.status_label.setText("误差云图正在后台计算，可在进度窗口中查看状态。")
        self.owner.generate_error_fields_async(
            fom_name, rom_name, selected_types, self
        )

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class RotationalTransparencyDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.owner = parent
        self.setWindowTitle("实体显示设置")
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setMinimumWidth(420)

        root = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("透明度：", self))
        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(self.owner.rotational_surface_transparency)))
        self.spinbox = QtWidgets.QDoubleSpinBox(self)
        self.spinbox.setRange(0.0, 100.0)
        self.spinbox.setDecimals(1)
        self.spinbox.setSingleStep(5.0)
        self.spinbox.setSuffix(" %")
        self.spinbox.setValue(self.owner.rotational_surface_transparency)
        row.addWidget(self.slider, 1)
        row.addWidget(self.spinbox)
        root.addLayout(row)

        note = QtWidgets.QLabel(
            "仅影响旋转实体的外表面；起始和结束端面保持不透明。", self
        )
        note.setWordWrap(True)
        root.addWidget(note)

        close_button = QtWidgets.QPushButton("关闭", self)
        close_button.clicked.connect(self.hide)
        root.addWidget(close_button, alignment=QtCore.Qt.AlignRight)

        self.slider.valueChanged.connect(self._slider_changed)
        self.spinbox.valueChanged.connect(self._spinbox_changed)

    def _slider_changed(self, value):
        self.spinbox.blockSignals(True)
        self.spinbox.setValue(float(value))
        self.spinbox.blockSignals(False)
        self.owner.set_rotational_surface_transparency(float(value))

    def _spinbox_changed(self, value):
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(value)))
        self.slider.blockSignals(False)
        self.owner.set_rotational_surface_transparency(float(value))

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class NodeFilterDialog(QtWidgets.QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.owner = parent
        self.setWindowTitle("节点筛选")
        self.setModal(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.setMinimumWidth(500)

        root = QtWidgets.QVBoxLayout(self)
        source_group = QtWidgets.QGroupBox("处理对象", self)
        source_layout = QtWidgets.QVBoxLayout(source_group)
        checks = QtWidgets.QHBoxLayout()
        self.fom_check = QtWidgets.QCheckBox("FOM", source_group)
        self.rom_check = QtWidgets.QCheckBox("ROM", source_group)
        self.fom_check.setChecked(True)
        self.rom_check.setChecked(True)
        checks.addWidget(self.fom_check)
        checks.addWidget(self.rom_check)
        checks.addStretch(1)
        source_layout.addLayout(checks)
        self.field_context_label = QtWidgets.QLabel(source_group)
        self.field_context_label.setWordWrap(True)
        self.field_context_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        source_layout.addWidget(self.field_context_label)
        root.addWidget(source_group)

        form = QtWidgets.QFormLayout()
        self.mode_combo = QtWidgets.QComboBox(self)
        self.mode_combo.addItem("排除节点", "exclude")
        self.mode_combo.addItem("保留节点（其余置值）", "retain")
        form.addRow("筛选模式：", self.mode_combo)

        self.node_input = QtWidgets.QLineEdit(self)
        self.node_input.setPlaceholderText("多个 Abaqus 节点编号用空格分隔")
        form.addRow("节点编号：", self.node_input)

        frame_widget = QtWidgets.QWidget(self)
        frame_layout = QtWidgets.QHBoxLayout(frame_widget)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        self.frame_check = QtWidgets.QCheckBox("指定帧", frame_widget)
        self.frame_input = QtWidgets.QLineEdit(frame_widget)
        self.frame_input.setValidator(QtGui.QIntValidator(1, 2147483647, self))
        self.frame_input.setPlaceholderText("从 1 开始的帧序号")
        self.frame_input.setEnabled(False)
        self.frame_check.toggled.connect(self.frame_input.setEnabled)
        frame_layout.addWidget(self.frame_check)
        frame_layout.addWidget(QtWidgets.QLabel("帧索引：", frame_widget))
        frame_layout.addWidget(self.frame_input, 1)
        form.addRow("处理范围：", frame_widget)

        self.value_input = QtWidgets.QLineEdit(self)
        value_validator = QtGui.QDoubleValidator(self)
        value_validator.setNotation(QtGui.QDoubleValidator.ScientificNotation)
        self.value_input.setValidator(value_validator)
        self.value_input.setText("0")
        form.addRow("数值设置为：", self.value_input)
        root.addLayout(form)

        self.status_label = QtWidgets.QLabel(
            "未指定帧时，将修改该节点在整个时间历程中的数据。", self
        )
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        root.addWidget(self.status_label)

        buttons = QtWidgets.QDialogButtonBox(self)
        filter_button = buttons.addButton("筛选", QtWidgets.QDialogButtonBox.ApplyRole)
        restore_button = buttons.addButton(
            "恢复原始物理场", QtWidgets.QDialogButtonBox.ResetRole
        )
        close_button = buttons.addButton("关闭", QtWidgets.QDialogButtonBox.RejectRole)
        filter_button.clicked.connect(self.filter_nodes)
        restore_button.clicked.connect(self.restore_original_fields)
        close_button.clicked.connect(self.hide)
        root.addWidget(buttons)
        self.refresh_context()

    def refresh_context(self):
        fom_name, rom_name = self.owner.current_edit_field_names()
        fom_was_enabled = self.fom_check.isEnabled()
        rom_was_enabled = self.rom_check.isEnabled()
        self.fom_check.setEnabled(fom_name is not None)
        self.rom_check.setEnabled(rom_name is not None)
        if fom_name is None:
            self.fom_check.setChecked(False)
        elif not fom_was_enabled:
            self.fom_check.setChecked(True)
        if rom_name is None:
            self.rom_check.setChecked(False)
        elif not rom_was_enabled:
            self.rom_check.setChecked(True)
        self.field_context_label.setText(
            f"FOM 当前字段：{fom_name or '--'}\nROM 当前字段：{rom_name or '--'}"
        )

    def filter_nodes(self):
        self.refresh_context()
        if not self.fom_check.isChecked() and not self.rom_check.isChecked():
            QtWidgets.QMessageBox.warning(self, "无法筛选", "请至少勾选 FOM 或 ROM。")
            return
        node_text = self.node_input.text().strip()
        if not node_text:
            QtWidgets.QMessageBox.warning(self, "无法筛选", "请输入节点编号。")
            return
        value_text = self.value_input.text().strip()
        if not value_text:
            QtWidgets.QMessageBox.warning(self, "无法筛选", "请输入要设置的数值。")
            return
        try:
            node_ids = list(dict.fromkeys(int(part) for part in node_text.split()))
            new_value = float(value_text)
        except ValueError:
            QtWidgets.QMessageBox.warning(
                self, "无法筛选", "节点编号必须是用空格分隔的正整数。"
            )
            return
        if not node_ids or any(node_id <= 0 for node_id in node_ids):
            QtWidgets.QMessageBox.warning(
                self, "无法筛选", "节点编号必须是用空格分隔的正整数。"
            )
            return
        if not np.isfinite(new_value):
            QtWidgets.QMessageBox.warning(self, "无法筛选", "设置数值必须是有限数值。")
            return

        frame_number = None
        if self.frame_check.isChecked():
            frame_text = self.frame_input.text().strip()
            if not frame_text:
                QtWidgets.QMessageBox.warning(self, "无法筛选", "请输入帧索引。")
                return
            frame_number = int(frame_text)
        try:
            summary = self.owner.apply_node_filter(
                node_ids=node_ids,
                new_value=new_value,
                process_fom=self.fom_check.isChecked(),
                process_rom=self.rom_check.isChecked(),
                frame_number=frame_number,
                mode=self.mode_combo.currentData(),
            )
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "无法筛选", str(exc))
            return
        self.status_label.setText(summary)
        self.refresh_context()

    def restore_original_fields(self):
        self.refresh_context()
        if not self.fom_check.isChecked() and not self.rom_check.isChecked():
            QtWidgets.QMessageBox.warning(self, "无法恢复", "请至少勾选 FOM 或 ROM。")
            return
        try:
            summary = self.owner.restore_original_filtered_fields(
                process_fom=self.fom_check.isChecked(),
                process_rom=self.rom_check.isChecked(),
            )
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "无法恢复", str(exc))
            return
        self.status_label.setText(summary)

    def closeEvent(self, event):
        event.ignore()
        self.hide()


class CustomInteractorStyle(vtk.vtkInteractorStyleTrackballCamera):
    def __init__(self, node_query_callback=None):
        super().__init__()
        self.node_query_callback = node_query_callback
        self.left_press_position = None

    def OnMiddleButtonDown(self):
        self.StartRotate()

    def OnMiddleButtonUp(self):
        self.EndRotate()

    def OnLeftButtonDown(self):
        interactor = self.GetInteractor()
        self.left_press_position = interactor.GetEventPosition() if interactor is not None else None
        self.StartPan()

    def OnLeftButtonUp(self):
        self.EndPan()
        interactor = self.GetInteractor()
        if interactor is None or self.left_press_position is None:
            return
        release_position = interactor.GetEventPosition()
        dx = release_position[0] - self.left_press_position[0]
        dy = release_position[1] - self.left_press_position[1]
        self.left_press_position = None
        if dx * dx + dy * dy <= 16 and self.node_query_callback is not None:
            self.node_query_callback(release_position[0], release_position[1])

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

class VTKCompareWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        self.node_ids = None
        self.coords = None
        self.elements = None
        self.display_source_indices_l = None
        self.display_source_indices_r = None
        self.is_rotational_surface = False
        self.rotational_surface_transparency = 0.0
        self.rotational_transparency_dialog = None
        self.node_filter_dialog = None
        self.original_field_data = {}
        self.cap_grid_l = None
        self.cap_grid_r = None
        self.cap_mapper_l = None
        self.cap_mapper_r = None
        self.cap_actor_l = None
        self.cap_actor_r = None

        self.fields = {}
        self.current_field = ""
        self.current_frame = 0 

        self.rom_fields = {}
        self.rom_current_field = ""
        self.error_fields = {}
        self.error_current_field = ""
        self._switching_error_field = False

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.play_next) 
        self.is_playing = False
        self.loop_mode = True
        self.base_delay_ms = 100 
        self.play_speed = 1.0
        self._closing = False 
        self._background_tasks = []
        self._field_data_epoch = 0

        self.lut_left = create_rainbow_lut() 
        self.lut_right = create_rainbow_lut()  

        self.background_style = "abaqus"
        self.colormap_style = "rainbow_1"
        self.grid_visible = True
        self.hotspot_filter_enabled = False
        self.hotspot_filter_mode = "max_ratio"
        self.hotspot_comparison = "greater"
        self.hotspot_threshold = 20.0
        self.filtered_transparency = 100.0
        self.hotspot_dialog = None
        self.node_query_enabled = False
        self.node_query_dialog = None
        self.node_query_press_positions = {"left": None, "right": None}
        self.extreme_query_dialog = None
        self.global_consistency_dialog = None
        self.local_consistency_dialog = None
        self.error_field_dialog = None
        self.extreme_actor_l = None
        self.extreme_actor_r = None

        self._init_ui() 
        self._init_vtk() 

    def showEvent(self, event):
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._post_show_init) 

    def _post_show_init(self):
        if getattr(self, "_post_inited", False):
            return
        self._post_inited = True

        if hasattr(self, "iren_l"):
            self.iren_l.Initialize()
        if hasattr(self, "iren_r"):
            self.iren_r.Initialize()

        self.safe_render_both()

    def _init_ui(self):
        self.setWindowTitle("Vtk Visualizer")
        icon_path = os.path.join(str(_project_root()), "assets", "logo.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1650, 950)

        central = QtWidgets.QWidget()
        main_layout = QtWidgets.QVBoxLayout(central)

        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        menubar = self.menuBar()
        menu_load = menubar.addMenu("文件加载")

        act_inp = QtWidgets.QAction("加载INP文件", self)
        act_inp.triggered.connect(self.open_inp)
        menu_load.addAction(act_inp)

        act_csv = QtWidgets.QAction("加载CSV文件（FOM）", self)
        act_csv.triggered.connect(self.open_csv_left)
        menu_load.addAction(act_csv)

        act_rom = QtWidgets.QAction("加载CSV文件（ROM）", self)
        act_rom.triggered.connect(self.open_csv_right)
        menu_load.addAction(act_rom)

        menu_load.addSeparator()
        clear_fields_action = QtWidgets.QAction("清除物理场", self)
        clear_fields_action.triggered.connect(self.clear_physical_fields)
        menu_load.addAction(clear_fields_action)

        menu_vis = menubar.addMenu("可视化")

        menu_bg = menu_vis.addMenu("背景设置")
        self.bg_group = QtWidgets.QActionGroup(self)
        self.bg_group.setExclusive(True)

        for label, style in (
            ("abaqus", "abaqus"),
            ("黑色", "black"),
            ("深灰色", "dark_gray"),
            ("灰色", "gray"),
            ("浅灰色", "light_gray"),
            ("白色", "white"),
            ("藏青色", "navy"),
            ("米色", "beige"),
        ):
            action = QtWidgets.QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self.background_style == style)
            action.triggered.connect(
                lambda checked=False, name=style: self.set_background_style(name)
            )
            self.bg_group.addAction(action)
            menu_bg.addAction(action)

        menu_lut = menu_vis.addMenu("色阶设置")
        self.lut_group = QtWidgets.QActionGroup(self)
        self.lut_group.setExclusive(True)

        act_lut_abaqus = QtWidgets.QAction("abaqus", self)
        act_lut_abaqus.setCheckable(True)
        act_lut_abaqus.setChecked(self.colormap_style == "abaqus")
        act_lut_abaqus.triggered.connect(lambda: self.set_colormap_style("abaqus"))

        act_lut_grad = QtWidgets.QAction("rainbow 1", self)
        act_lut_grad.setCheckable(True)
        act_lut_grad.setChecked(self.colormap_style == "rainbow_1")
        act_lut_grad.triggered.connect(lambda: self.set_colormap_style("rainbow_1"))

        act_lut_rainbow_2 = QtWidgets.QAction("rainbow 2", self)
        act_lut_rainbow_2.setCheckable(True)
        act_lut_rainbow_2.setChecked(self.colormap_style == "rainbow_2")
        act_lut_rainbow_2.triggered.connect(lambda: self.set_colormap_style("rainbow_2"))

        self.lut_group.addAction(act_lut_abaqus)
        self.lut_group.addAction(act_lut_grad)
        self.lut_group.addAction(act_lut_rainbow_2)
        menu_lut.addAction(act_lut_abaqus)
        menu_lut.addAction(act_lut_grad)
        menu_lut.addAction(act_lut_rainbow_2)
        menu_lut.addSeparator()
        for label, style in (
            ("viridis", "viridis"),
            ("plasma", "plasma"),
            ("inferno", "inferno"),
            ("magma", "magma"),
            ("cividis", "cividis"),
            ("turbo", "turbo"),
            ("PiYG", "piyg"),
            ("coolwarm", "coolwarm"),
        ):
            action = QtWidgets.QAction(label, self)
            action.setCheckable(True)
            action.setChecked(self.colormap_style == style)
            action.triggered.connect(
                lambda checked=False, name=style: self.set_colormap_style(name)
            )
            self.lut_group.addAction(action)
            menu_lut.addAction(action)

        self.grid_menu = menu_vis.addMenu("网格设置")
        self.grid_action_group = QtWidgets.QActionGroup(self)
        self.grid_action_group.setExclusive(True)
        self.grid_on_action = QtWidgets.QAction("开启", self, checkable=True)
        self.grid_off_action = QtWidgets.QAction("关闭", self, checkable=True)
        self.grid_on_action.setChecked(True)
        self.grid_on_action.triggered.connect(lambda: self.set_grid_visibility(True))
        self.grid_off_action.triggered.connect(lambda: self.set_grid_visibility(False))
        self.grid_action_group.addAction(self.grid_on_action)
        self.grid_action_group.addAction(self.grid_off_action)
        self.grid_menu.addAction(self.grid_on_action)
        self.grid_menu.addAction(self.grid_off_action)

        view_menu = menu_vis.addMenu("视角设置")
        for label, view_name in (
            ("主视图", "main"),
            ("俯视图", "top"),
            ("左视图", "left"),
            ("斜二测图", "dimetric"),
        ):
            action = QtWidgets.QAction(label, self)
            action.triggered.connect(
                lambda checked=False, name=view_name: self.set_standard_view(name)
            )
            view_menu.addAction(action)

        menu_vis.addSeparator()

        hotspot_menu = menu_vis.addMenu("热点高亮")
        hotspot_filter_action = QtWidgets.QAction("高亮设置", self)
        hotspot_filter_action.triggered.connect(self.show_hotspot_filter_dialog)
        hotspot_restore_action = QtWidgets.QAction("恢复原始云图", self)
        hotspot_restore_action.triggered.connect(self.restore_original_cloud)
        hotspot_menu.addAction(hotspot_filter_action)
        hotspot_menu.addAction(hotspot_restore_action)

        node_filter_action = QtWidgets.QAction("节点筛选", self)
        node_filter_action.triggered.connect(self.show_node_filter_dialog)
        menu_vis.addAction(node_filter_action)

        menu_rotate = menu_vis.addMenu("旋转实体")
        self.rotation_actions = []
        for axis_index, axis_name in enumerate(("X", "Y", "Z")):
            action = QtWidgets.QAction(f"以{axis_name}轴为中心", self)
            action.triggered.connect(
                lambda checked=False, index=axis_index: self.open_rotation_dialog(index)
            )
            action.setEnabled(False)
            menu_rotate.addAction(action)
            self.rotation_actions.append(action)
        menu_rotate.addSeparator()
        transparency_action = QtWidgets.QAction("实体显示设置", self)
        transparency_action.triggered.connect(self.show_rotational_transparency_dialog)
        menu_rotate.addAction(transparency_action)
        menu_rotate.addSeparator()
        self.restore_2d_action = QtWidgets.QAction("恢复二维网格", self)
        self.restore_2d_action.triggered.connect(self.restore_2d_mesh)
        self.restore_2d_action.setEnabled(False)
        menu_rotate.addAction(self.restore_2d_action)

        menu_analysis = menubar.addMenu("数值分析")
        query_menu = menu_analysis.addMenu("查询")
        self.node_query_menu = query_menu.addMenu("节点查询")
        self.node_query_action_group = QtWidgets.QActionGroup(self)
        self.node_query_action_group.setExclusive(True)
        self.node_query_on_action = QtWidgets.QAction("开启", self, checkable=True)
        self.node_query_off_action = QtWidgets.QAction("关闭", self, checkable=True)
        self.node_query_off_action.setChecked(True)
        self.node_query_on_action.triggered.connect(
            lambda: self.set_node_query_enabled(True)
        )
        self.node_query_off_action.triggered.connect(
            lambda: self.set_node_query_enabled(False)
        )
        self.node_query_action_group.addAction(self.node_query_on_action)
        self.node_query_action_group.addAction(self.node_query_off_action)
        self.node_query_menu.addAction(self.node_query_on_action)
        self.node_query_menu.addAction(self.node_query_off_action)

        extreme_menu = query_menu.addMenu("极值查询")
        open_extreme_action = QtWidgets.QAction("打开查询面板", self)
        open_extreme_action.triggered.connect(self.show_extreme_query_dialog)
        clear_extreme_action = QtWidgets.QAction("清除查询结果", self)
        clear_extreme_action.triggered.connect(self.clear_extreme_markers)
        extreme_menu.addAction(open_extreme_action)
        extreme_menu.addAction(clear_extreme_action)

        global_consistency_menu = menu_analysis.addMenu("全局一致性")
        global_consistency_action = QtWidgets.QAction("误差计算", self)
        global_consistency_action.triggered.connect(self.show_global_consistency_dialog)
        global_consistency_menu.addAction(global_consistency_action)

        error_field_action = QtWidgets.QAction("误差云图", self)
        error_field_action.triggered.connect(self.show_error_field_dialog)
        global_consistency_menu.addAction(error_field_action)

        local_consistency_action = QtWidgets.QAction("局部一致性", self)
        local_consistency_action.triggered.connect(self.show_local_consistency_dialog)
        menu_analysis.addAction(local_consistency_action)

        ctrl_widget = QtWidgets.QWidget()
        ctrl_layout = QtWidgets.QHBoxLayout(ctrl_widget)
        ctrl_layout.setContentsMargins(0, 0, 0, 0)
        ctrl_layout.setSpacing(10)

        ctrl_layout.addWidget(QtWidgets.QLabel("全阶模型（FOM）："))
        self.combo_left = QtWidgets.QComboBox()
        self.combo_left.setMinimumWidth(180)
        self.combo_left.currentTextChanged.connect(self.on_left_field_changed)
        ctrl_layout.addWidget(self.combo_left)

        ctrl_layout.addWidget(QtWidgets.QLabel("降阶模型（ROM）："))
        self.combo_right = QtWidgets.QComboBox()
        self.combo_right.setMinimumWidth(180)
        self.combo_right.currentTextChanged.connect(self.on_right_field_changed)
        ctrl_layout.addWidget(self.combo_right)

        self.play_btn = QtWidgets.QPushButton("▶ 播放")
        self.play_btn.clicked.connect(self.toggle_play)
        ctrl_layout.addWidget(self.play_btn)

        self.loop_chk = QtWidgets.QCheckBox("循环")
        self.loop_chk.setChecked(True)
        self.loop_chk.stateChanged.connect(lambda s: setattr(self, "loop_mode", s == QtCore.Qt.Checked))
        ctrl_layout.addWidget(self.loop_chk)

        ctrl_layout.addWidget(QtWidgets.QLabel("倍速："))
        self.speed_combo = QtWidgets.QComboBox()
        self.speed_combo.addItems(["0.25x", "0.5x", "1.0x", "2.0x", "4.0x"])
        self.speed_combo.setCurrentText("1.0x")
        self.speed_combo.currentTextChanged.connect(self.on_speed_changed)
        ctrl_layout.addWidget(self.speed_combo)

        self.frame_label = QtWidgets.QLabel("帧: 0/0")
        ctrl_layout.addWidget(self.frame_label)

        ctrl_layout.addStretch(1)
        ctrl_widget.setFixedHeight(42) 
        main_layout.addWidget(ctrl_widget)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.left_view_container = QtWidgets.QWidget(central)
        self.right_view_container = QtWidgets.QWidget(central)
        left_view_layout = QtWidgets.QVBoxLayout(self.left_view_container)
        right_view_layout = QtWidgets.QVBoxLayout(self.right_view_container)
        left_view_layout.setContentsMargins(0, 0, 0, 0)
        right_view_layout.setContentsMargins(0, 0, 0, 0)
        left_view_layout.setSpacing(2)
        right_view_layout.setSpacing(2)

        self.vtk_left = QVTKRenderWindowInteractor(self.left_view_container)
        self.vtk_right = QVTKRenderWindowInteractor(self.right_view_container)
        left_view_layout.addWidget(self.vtk_left, 1)
        right_view_layout.addWidget(self.vtk_right, 1)
        self.vtk_left.installEventFilter(self)
        self.vtk_right.installEventFilter(self)
        self.splitter.addWidget(self.left_view_container)
        self.splitter.addWidget(self.right_view_container)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        main_layout.addWidget(self.splitter, 1) 

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.valueChanged.connect(self.on_slider_changed)
        main_layout.addWidget(self.slider)

        self.setCentralWidget(central)

        self.set_controls_enabled(False)

        self._post_inited = False
        self._render_pending = False

    @staticmethod
    def _qt_to_vtk_display_position(vtk_widget, qt_position):
        render_window = vtk_widget.GetRenderWindow()
        render_width, render_height = render_window.GetSize()
        widget_width = max(1, vtk_widget.width())
        widget_height = max(1, vtk_widget.height())
        display_x = int(round(float(qt_position.x()) * render_width / widget_width))
        display_y = int(
            round(float(widget_height - 1 - qt_position.y()) * render_height / widget_height)
        )
        display_x = int(np.clip(display_x, 0, max(0, render_width - 1)))
        display_y = int(np.clip(display_y, 0, max(0, render_height - 1)))
        return display_x, display_y

    def eventFilter(self, watched, event):
        if watched in (getattr(self, "vtk_left", None), getattr(self, "vtk_right", None)):
            side = "left" if watched is self.vtk_left else "right"
            if event.type() == QtCore.QEvent.MouseButtonPress and event.button() == QtCore.Qt.LeftButton:
                if self.node_query_enabled:
                    self.node_query_press_positions[side] = (event.pos().x(), event.pos().y())
            elif event.type() == QtCore.QEvent.MouseButtonRelease and event.button() == QtCore.Qt.LeftButton:
                press_position = self.node_query_press_positions.get(side)
                self.node_query_press_positions[side] = None
                if self.node_query_enabled and press_position is not None:
                    dx = event.pos().x() - press_position[0]
                    dy = event.pos().y() - press_position[1]
                    if dx * dx + dy * dy <= 16:
                        display_x, display_y = self._qt_to_vtk_display_position(
                            watched, event.pos()
                        )
                        QtCore.QTimer.singleShot(
                            0,
                            lambda s=side, x=display_x, y=display_y: self.query_node(s, x, y),
                        )
            return False
        return super().eventFilter(watched, event)

    def set_controls_enabled(self, enabled):
        """集中控制 UI 控件启用状态。"""
        self.combo_left.setEnabled(enabled)
        self.combo_right.setEnabled(enabled)
        self.play_btn.setEnabled(enabled)
        self.loop_chk.setEnabled(enabled)
        self.speed_combo.setEnabled(enabled)
        self.slider.setEnabled(enabled)

    def set_grid_visibility(self, visible):
        self.grid_visible = bool(visible)
        self.grid_on_action.setChecked(self.grid_visible)
        self.grid_off_action.setChecked(not self.grid_visible)
        for actor in (getattr(self, "wire_actor_l", None), getattr(self, "wire_actor_r", None)):
            if actor is not None:
                actor.SetVisibility(self.grid_visible)
        self.safe_render_both()

    def set_node_query_enabled(self, enabled):
        self.node_query_enabled = bool(enabled)
        self.node_query_on_action.setChecked(self.node_query_enabled)
        self.node_query_off_action.setChecked(not self.node_query_enabled)
        if self.node_query_enabled:
            if self.node_query_dialog is None:
                self.node_query_dialog = NodeQueryDialog(self)
            self.node_query_dialog.show()
            self.node_query_dialog.raise_()
            self.node_query_dialog.activateWindow()
        elif self.node_query_dialog is not None:
            self.node_query_dialog.hide()

    @staticmethod
    def _nearest_cell_point_id(grid, cell_id, pick_position):
        if cell_id < 0 or cell_id >= grid.GetNumberOfCells():
            return -1
        cell = grid.GetCell(cell_id)
        if cell is None or cell.GetNumberOfPoints() == 0:
            return -1
        target = np.asarray(pick_position, dtype=float)
        best_point_id = -1
        best_distance = float("inf")
        point_ids = cell.GetPointIds()
        for local_index in range(point_ids.GetNumberOfIds()):
            point_id = int(point_ids.GetId(local_index))
            point = np.asarray(grid.GetPoint(point_id), dtype=float)
            distance = float(np.dot(point - target, point - target))
            if distance < best_distance:
                best_distance = distance
                best_point_id = point_id
        return best_point_id

    def query_node(self, side, display_x, display_y):
        if not self.node_query_enabled or self.node_ids is None:
            return
        if side == "right":
            renderer = self.ren_r
            actor = getattr(self, "actor_r", None)
            grid = getattr(self, "grid_r", None)
            source_indices = self.display_source_indices_r
        else:
            renderer = self.ren_l
            actor = getattr(self, "actor_l", None)
            grid = getattr(self, "grid_l", None)
            source_indices = self.display_source_indices_l
        if actor is None or grid is None:
            if self.node_query_dialog is not None:
                self.node_query_dialog.set_status("当前视窗尚未加载可查询网格。")
            return

        point_picker = vtk.vtkPointPicker()
        point_picker.SetTolerance(0.025)
        point_picker.PickFromListOn()
        point_picker.AddPickList(actor)
        point_id = -1
        if point_picker.Pick(float(display_x), float(display_y), 0.0, renderer):
            point_id = int(point_picker.GetPointId())

        if point_id < 0:
            cell_picker = vtk.vtkCellPicker()
            cell_picker.SetTolerance(0.0005)
            cell_picker.PickFromListOn()
            cell_picker.AddPickList(actor)
            if cell_picker.Pick(float(display_x), float(display_y), 0.0, renderer):
                point_id = self._nearest_cell_point_id(
                    grid,
                    int(cell_picker.GetCellId()),
                    cell_picker.GetPickPosition(),
                )

        if point_id < 0 or point_id >= grid.GetNumberOfPoints():
            if self.node_query_dialog is not None:
                self.node_query_dialog.set_status("未拾取到节点，请在模型表面附近单击。")
            return

        if source_indices is None:
            source_index = point_id
        else:
            if point_id >= len(source_indices):
                if self.node_query_dialog is not None:
                    self.node_query_dialog.set_status("节点映射失败：显示节点索引超出范围。")
                return
            source_index = int(source_indices[point_id])
        if source_index < 0 or source_index >= len(self.node_ids):
            if self.node_query_dialog is not None:
                self.node_query_dialog.set_status("节点映射失败：源节点索引无效。")
            return

        if self.node_query_dialog is None:
            self.node_query_dialog = NodeQueryDialog(self)
        coordinates = grid.GetPoint(point_id)
        self.node_query_dialog.set_node(self.node_ids[source_index], coordinates)
        if not self.node_query_dialog.isVisible():
            self.node_query_dialog.show()

    def show_extreme_query_dialog(self):
        if self.extreme_query_dialog is None:
            self.extreme_query_dialog = ExtremeQueryDialog(self)
        self.extreme_query_dialog.show()
        self.extreme_query_dialog.raise_()
        self.extreme_query_dialog.activateWindow()
        self.run_extreme_query()

    def _remove_extreme_actors(self):
        if self.extreme_actor_l is not None:
            renderer = getattr(self, "marker_ren_l", self.ren_l)
            renderer.RemoveActor(self.extreme_actor_l)
            self.extreme_actor_l = None
        if self.extreme_actor_r is not None:
            renderer = getattr(self, "marker_ren_r", self.ren_r)
            renderer.RemoveActor(self.extreme_actor_r)
            self.extreme_actor_r = None

    def clear_extreme_markers(self):
        self._remove_extreme_actors()
        if self.extreme_query_dialog is not None:
            self.extreme_query_dialog.set_results([], "当前字段/帧：--")
        if self.local_consistency_dialog is not None:
            self.local_consistency_dialog.refresh_fields()
            self.local_consistency_dialog.status_label.setText("请先加载 FOM 或 ROM 物理场。")
            self.local_consistency_dialog._draw_empty_plot()
        self.statusBar().clearMessage()
        self.safe_render_both()

    def set_standard_view(self, view_name):
        if not hasattr(self, "ren_l"):
            return
        camera = self.ren_l.GetActiveCamera()
        if camera is None:
            return

        if view_name == "top":
            direction, view_up = np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0])
        elif view_name == "left":
            direction, view_up = np.array([-1.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0])
        elif view_name == "dimetric":
            direction, view_up = np.array([1.0, -1.0, 0.75]), np.array([0.0, 0.0, 1.0])
        else:
            direction, view_up = self._main_view_orientation()

        direction = direction / np.linalg.norm(direction)
        bounds = self.grid_l.GetBounds() if getattr(self, "grid_l", None) is not None else None
        if bounds is None:
            center = np.zeros(3, dtype=float)
            distance = 1.0
        else:
            center = np.array(
                [(bounds[0] + bounds[1]) / 2.0, (bounds[2] + bounds[3]) / 2.0, (bounds[4] + bounds[5]) / 2.0]
            )
            diagonal = np.linalg.norm([bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]])
            distance = max(float(diagonal), 1.0)
        camera.SetFocalPoint(*center)
        camera.SetPosition(*(center + direction * distance))
        camera.SetViewUp(*view_up)
        camera.ParallelProjectionOn()
        camera.OrthogonalizeViewUp()
        self.ren_l.ResetCamera()
        self.ren_l.ResetCameraClippingRange()
        self.safe_render_both()

    def _main_view_orientation(self):
        if self.coords is not None:
            try:
                planar_axis = detect_planar_axis(self.coords)
                direction = np.zeros(3, dtype=float)
                direction[planar_axis] = 1.0
                if planar_axis == 2:
                    view_up = np.array([0.0, 1.0, 0.0])
                else:
                    view_up = np.array([0.0, 0.0, 1.0])
                return direction, view_up
            except ValueError:
                pass
        return np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, 1.0])

    def show_global_consistency_dialog(self):
        if self.global_consistency_dialog is None:
            self.global_consistency_dialog = GlobalConsistencyDialog(self)
        self.global_consistency_dialog.refresh_fields()
        self.global_consistency_dialog.show()
        self.global_consistency_dialog.raise_()
        self.global_consistency_dialog.activateWindow()

    def show_local_consistency_dialog(self):
        if self.local_consistency_dialog is None:
            self.local_consistency_dialog = LocalConsistencyDialog(self)
        self.local_consistency_dialog.refresh_fields()
        self.local_consistency_dialog.show()
        self.local_consistency_dialog.raise_()
        self.local_consistency_dialog.activateWindow()

    def show_error_field_dialog(self):
        if self.error_field_dialog is None:
            self.error_field_dialog = ErrorFieldDialog(self)
        self.error_field_dialog.refresh_fields()
        self.error_field_dialog.show()
        self.error_field_dialog.raise_()
        self.error_field_dialog.activateWindow()

    def show_node_filter_dialog(self):
        if self.node_filter_dialog is None:
            self.node_filter_dialog = NodeFilterDialog(self)
        self.node_filter_dialog.refresh_context()
        self.node_filter_dialog.show()
        self.node_filter_dialog.raise_()
        self.node_filter_dialog.activateWindow()

    def current_edit_field_names(self):
        fom_name = self.current_field if self.current_field in self.fields else None
        selected_right = self.combo_right.currentText()
        if selected_right in self.error_fields:
            candidate = self.error_fields[selected_right].get("rom_field")
            rom_name = candidate if candidate in self.rom_fields else None
        elif self.current_field in self.rom_fields:
            rom_name = self.current_field
        elif self.rom_current_field in self.rom_fields:
            rom_name = self.rom_current_field
        else:
            rom_name = None
        return fom_name, rom_name

    def _invalidate_dependent_error_fields(self, fom_names, rom_names):
        invalid_names = [
            name
            for name, field in self.error_fields.items()
            if field.get("fom_field") in fom_names or field.get("rom_field") in rom_names
        ]
        if not invalid_names:
            return []
        selected_right = self.combo_right.currentText()
        selected_error_rom = (
            self.error_fields[selected_right].get("rom_field")
            if selected_right in self.error_fields
            else None
        )
        self.combo_right.blockSignals(True)
        for name in invalid_names:
            self.error_fields.pop(name, None)
            index = self.combo_right.findText(name)
            if index >= 0:
                self.combo_right.removeItem(index)
        if selected_right in invalid_names:
            fallback_rom = selected_error_rom
            if fallback_rom in self.rom_fields:
                self.combo_right.setCurrentText(fallback_rom)
                self.rom_current_field = fallback_rom
            elif self.rom_fields:
                fallback_rom = next(iter(self.rom_fields))
                self.combo_right.setCurrentText(fallback_rom)
                self.rom_current_field = fallback_rom
        self.combo_right.blockSignals(False)
        self.error_current_field = ""
        if self.error_field_dialog is not None:
            self.error_field_dialog.refresh_fields()
        return invalid_names

    def _node_filter_targets(self, process_fom, process_rom):
        fom_name, rom_name = self.current_edit_field_names()
        targets = []
        if process_fom:
            if fom_name is None:
                raise ValueError("当前没有可处理的 FOM 物理场。")
            targets.append(("FOM", fom_name, self.fields[fom_name]))
        if process_rom:
            if rom_name is None:
                raise ValueError("当前没有可处理的 ROM 物理场。")
            targets.append(("ROM", rom_name, self.rom_fields[rom_name]))
        if not targets:
            raise ValueError("请至少选择一个可处理的物理场。")
        return targets

    def apply_node_filter(
        self, node_ids, new_value, process_fom, process_rom,
        frame_number=None, mode="exclude"
    ):
        if self.node_ids is None:
            raise ValueError("请先加载 INP 网格。")
        if mode not in ("exclude", "retain"):
            raise ValueError("未知的节点筛选模式。")
        id_to_index = {
            int(node_id): index for index, node_id in enumerate(self.node_ids)
        }
        missing_ids = [int(node_id) for node_id in node_ids if int(node_id) not in id_to_index]
        if missing_ids:
            missing_text = " ".join(str(node_id) for node_id in missing_ids)
            raise ValueError(f"未找到以下节点编号：{missing_text}")
        selected_indices = np.asarray(
            [id_to_index[int(node_id)] for node_id in node_ids], dtype=int
        )
        if mode == "retain":
            modify_mask = np.ones(len(self.node_ids), dtype=bool)
            modify_mask[selected_indices] = False
            modify_indices = np.flatnonzero(modify_mask)
        else:
            modify_indices = selected_indices

        targets = self._node_filter_targets(process_fom, process_rom)

        if frame_number is not None:
            for model_name, field_name, field in targets:
                frame_count = field["data"].shape[0]
                if frame_number < 1 or frame_number > frame_count:
                    raise ValueError(
                        f"{model_name} 字段 {field_name} 的帧索引必须位于 1 到 {frame_count} 之间。"
                    )

        modified_fom, modified_rom = set(), set()
        for model_name, field_name, field in targets:
            data = field["data"]
            backup_key = (model_name, field_name)
            if backup_key not in self.original_field_data:
                self.original_field_data[backup_key] = np.asarray(data).copy()
            if frame_number is None:
                data[:, modify_indices] = float(new_value)
            else:
                data[frame_number - 1, modify_indices] = float(new_value)
            finite = data[np.isfinite(data)]
            if finite.size == 0:
                raise ValueError(f"{model_name} 字段 {field_name} 修改后没有有效数值。")
            field["vmin"] = float(np.min(finite))
            field["vmax"] = float(np.max(finite))
            if model_name == "FOM":
                modified_fom.add(field_name)
            else:
                modified_rom.add(field_name)

        removed_errors = self._invalidate_dependent_error_fields(
            modified_fom, modified_rom
        )
        self.update_both_views()
        frame_text = "全部帧" if frame_number is None else f"第 {frame_number} 帧"
        models = "、".join(model_name for model_name, _name, _field in targets)
        node_text = " ".join(str(node_id) for node_id in node_ids)
        if mode == "retain":
            message = (
                f"已在 {models} 的{frame_text}保留节点 {node_text}，"
                f"其余节点设置为 {new_value:.6g}。"
            )
        else:
            message = (
                f"已将 {models} 的{frame_text}中节点 {node_text} 设置为 {new_value:.6g}。"
            )
        if removed_errors:
            message += f" 已移除 {len(removed_errors)} 个失效误差场，请重新生成。"
        self.statusBar().showMessage(message, 8000)
        return message

    def restore_original_filtered_fields(self, process_fom, process_rom):
        targets = self._node_filter_targets(process_fom, process_rom)
        restored_fom, restored_rom = set(), set()
        restored_labels = []
        for model_name, field_name, field in targets:
            backup_key = (model_name, field_name)
            original = self.original_field_data.get(backup_key)
            if original is None:
                continue
            field["data"] = original.copy()
            finite = field["data"][np.isfinite(field["data"])]
            field["vmin"] = float(np.min(finite))
            field["vmax"] = float(np.max(finite))
            self.original_field_data.pop(backup_key, None)
            restored_labels.append(f"{model_name}:{field_name}")
            if model_name == "FOM":
                restored_fom.add(field_name)
            else:
                restored_rom.add(field_name)
        if not restored_labels:
            raise ValueError("当前勾选的物理场没有可恢复的筛选记录。")
        removed_errors = self._invalidate_dependent_error_fields(
            restored_fom, restored_rom
        )
        self.update_both_views()
        message = "已恢复原始物理场：" + "、".join(restored_labels) + "。"
        if removed_errors:
            message += f" 已移除 {len(removed_errors)} 个失效误差场，请重新生成。"
        self.statusBar().showMessage(message, 8000)
        return message

    def _start_background_task(self, worker, title, finished_callback):
        thread = QtCore.QThread(self)
        progress = QtWidgets.QProgressDialog("正在准备…", "取消", 0, 100, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(QtCore.Qt.WindowModal)
        progress.setMinimumDuration(300)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        worker.moveToThread(thread)
        task = {"thread": thread, "worker": worker, "progress": progress}
        bridge = BackgroundTaskUiBridge(
            self, thread, worker, progress, finished_callback, task
        )
        task["bridge"] = bridge
        self._background_tasks.append(task)

        worker.progress.connect(bridge.update_progress)
        worker.finished.connect(bridge.finish_task)
        worker.finished.connect(worker.deleteLater)
        progress.canceled.connect(lambda: worker.cancel())
        thread.started.connect(worker.run)
        thread.finished.connect(bridge.cleanup_task)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        return task

    def generate_error_fields_async(self, fom_name, rom_name, error_types, dialog):
        task_epoch = self._field_data_epoch
        worker = ErrorFieldWorker(
            fom_name,
            rom_name,
            self.fields[fom_name],
            self.rom_fields[rom_name],
            error_types,
        )

        def apply_results(generated, errors, cancelled):
            if task_epoch != self._field_data_epoch:
                return
            generated_names, notes = [], []
            matching_note = ""
            for display_name, field_data, frame_count, excluded_count, note, type_label in generated:
                self.error_fields[display_name] = field_data
                if self.combo_right.findText(display_name) < 0:
                    self.combo_right.addItem(display_name)
                generated_names.append(display_name)
                matching_note = note
                notes.append(f"{type_label}：{frame_count} 帧，排除 {excluded_count} 个零基准值")
            if generated_names:
                self.combo_left.setCurrentText(fom_name)
                self.combo_right.setCurrentText(generated_names[-1])
            if cancelled:
                message = f"任务已取消；已完成 {len(generated_names)} 个误差场。"
            elif generated_names:
                message = f"已生成 {len(generated_names)} 个误差场（{matching_note}）。"
            else:
                message = "未生成误差场。"
            if errors:
                message += "\n" + "\n".join(errors)
            dialog.status_label.setText(message + ("\n" + "\n".join(notes) if notes else ""))
            self.statusBar().showMessage(message.split("\n", 1)[0], 6000)
            if errors and not generated_names and not cancelled:
                QtWidgets.QMessageBox.critical(self, "生成失败", "\n".join(errors))

        self._start_background_task(worker, "正在生成误差云图", apply_results)

    def locate_extreme_result(self, row_index):
        dialog = self.extreme_query_dialog
        if dialog is None or row_index < 0 or row_index >= len(getattr(dialog, "result_rows", [])):
            self.statusBar().showMessage("定位失败：查询结果行无效。", 5000)
            return
        result = dialog.result_rows[row_index]
        if "source_index" not in result:
            self.statusBar().showMessage("定位失败：结果中缺少源节点索引，请重新查询。", 5000)
            return
        side = result["side"]
        grid = self.grid_l if side == "left" else self.grid_r
        source_indices = (
            self.display_source_indices_l if side == "left" else self.display_source_indices_r
        )
        if grid is None or source_indices is None:
            self.statusBar().showMessage("定位失败：当前显示网格或节点映射不可用。", 5000)
            return
        candidates = np.flatnonzero(np.asarray(source_indices) == int(result["source_index"]))
        if candidates.size == 0:
            self.statusBar().showMessage("未找到该节点在当前显示网格中的位置。", 5000)
            return

        camera = self.ren_l.GetActiveCamera()
        camera_position = np.asarray(camera.GetPosition(), dtype=float)
        candidate_points = np.asarray(
            [grid.GetPoint(int(index)) for index in candidates], dtype=float
        )
        nearest = int(np.argmin(np.sum((candidate_points - camera_position) ** 2, axis=1)))
        target = candidate_points[nearest]

        focal_point = np.asarray(camera.GetFocalPoint(), dtype=float)
        view_vector = camera_position - focal_point
        view_norm = float(np.linalg.norm(view_vector))
        if view_norm < 1.0e-12:
            view_vector = np.array([0.0, 0.0, 1.0])
            view_norm = 1.0
        view_direction = view_vector / view_norm
        bounds = grid.GetBounds()
        diagonal = float(
            np.linalg.norm(
                [bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]]
            )
        )
        focus_distance = max(diagonal * 0.04, 1.0e-6)
        camera.SetFocalPoint(*target)
        camera.SetPosition(*(target + view_direction * focus_distance))
        if camera.GetParallelProjection():
            camera.SetParallelScale(max(diagonal * 0.025, 1.0e-6))
        camera.Modified()
        self.ren_l.ResetCameraClippingRange()
        self.ren_r.ResetCameraClippingRange()
        self.statusBar().showMessage(
            f"已定位：{result['model']} {result['type_label']}，"
            f"节点 {result['node_id']}，数值 {result['value']:.6e}",
            8000,
        )
        self.safe_render_both()

    @staticmethod
    def _extreme_source_indices(values, valid_mask, extreme_type, count):
        candidates = np.flatnonzero(valid_mask)
        if candidates.size == 0:
            return np.array([], dtype=np.int64)
        candidate_values = values[candidates]
        if extreme_type == "minimum":
            order = np.argsort(candidate_values, kind="stable")
        elif extreme_type == "absolute_maximum":
            order = np.argsort(-np.abs(candidate_values), kind="stable")
        else:
            order = np.argsort(-candidate_values, kind="stable")
        return candidates[order[: min(int(count), len(order))]].astype(np.int64)

    @staticmethod
    def _make_extreme_actor(grid, display_source_indices, selected_source_indices, color):
        if grid is None or display_source_indices is None or len(selected_source_indices) == 0:
            return None
        selected = set(int(index) for index in selected_source_indices)
        marker_coordinates = []
        for display_index, source_index in enumerate(display_source_indices):
            if int(source_index) not in selected:
                continue
            marker_coordinates.append(grid.GetPoint(display_index))
        if not marker_coordinates:
            return None

        bounds = grid.GetBounds()
        diagonal = np.linalg.norm(
            [bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4]]
        )
        marker_radius = max(float(diagonal) * 0.008, 1.0e-9)
        append = vtk.vtkAppendPolyData()
        for coordinate in marker_coordinates:
            sphere = vtk.vtkSphereSource()
            sphere.SetCenter(*coordinate)
            sphere.SetRadius(marker_radius)
            sphere.SetThetaResolution(16)
            sphere.SetPhiResolution(12)
            sphere.Update()
            append.AddInputData(sphere.GetOutput())
        append.Update()
        marker_geometry = vtk.vtkPolyData()
        marker_geometry.DeepCopy(append.GetOutput())

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(marker_geometry)
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*color)
        actor.GetProperty().SetOpacity(1.0)
        actor.GetProperty().SetAmbient(1.0)
        actor.GetProperty().SetDiffuse(0.0)
        actor.GetProperty().LightingOff()
        actor.SetPickable(False)
        return actor

    def run_extreme_query(self):
        dialog = self.extreme_query_dialog
        if dialog is None or self.node_ids is None or self.current_field not in self.fields:
            return
        settings = dialog.settings()
        requested_source = settings["source"]
        extreme_type = settings["extreme_type"]
        count = settings["count"]
        type_labels = {
            "maximum": "最大值",
            "minimum": "最小值",
            "absolute_maximum": "绝对值最大值",
        }
        left_field = self.fields[self.current_field]
        left_frame = int(np.clip(self.current_frame, 0, left_field["data"].shape[0] - 1))
        left_values = np.asarray(left_field["data"][left_frame], dtype=float)

        selected_right = self.combo_right.currentText()
        error_key = selected_right if selected_right in self.error_fields else None
        rom_key = self.current_field if self.current_field in self.rom_fields else self.rom_current_field
        right_values = None
        right_frame = None
        right_model_label = "ROM"
        right_field_name = rom_key
        if error_key is not None:
            right_field = self.error_fields[error_key]
            right_frame = self.current_frame
            right_values = np.asarray(right_field["data"][right_frame], dtype=float)
            right_model_label = "误差"
            right_field_name = error_key
        elif rom_key in self.rom_fields:
            right_field = self.rom_fields[rom_key]
            right_frame = int(np.clip(self.current_frame, 0, right_field["data"].shape[0] - 1))
            right_values = np.asarray(right_field["data"][right_frame], dtype=float)

        visible_threshold = None
        if settings["scope"] == "visible" and self.hotspot_filter_enabled:
            visible_threshold = self._current_filter_threshold(left_values, right_values)

        sources = []
        if requested_source in ("both", "fom"):
            sources.append(("FOM", "left", self.current_field, left_values))
        if requested_source in ("both", "rom") and right_values is not None:
            sources.append((right_model_label, "right", right_field_name, right_values))

        rows = []
        coordinates = _coords_3d(self.coords)
        for model_name, side, field_name, values in sources:
            valid_mask = np.isfinite(values)
            if visible_threshold is not None:
                valid_mask &= self._filter_keep_mask(values, visible_threshold)
            selected_indices = self._extreme_source_indices(
                values, valid_mask, extreme_type, count
            )
            for source_index in selected_indices:
                x, y, z = coordinates[int(source_index)]
                rows.append(
                    {
                        "model": model_name,
                        "type_label": type_labels[extreme_type],
                        "node_id": int(self.node_ids[int(source_index)]),
                        "value": float(values[int(source_index)]),
                        "x": float(x),
                        "y": float(y),
                        "z": float(z),
                        "side": side,
                        "source_index": int(source_index),
                        "field_name": field_name,
                        "extreme_type": extreme_type,
                    }
                )

        self._remove_extreme_actors()
        context_parts = [f"全阶模型：{self.current_field}", f"帧：{left_frame + 1}"]
        if right_values is not None:
            right_status_label = "降阶模型" if right_model_label == "ROM" else right_model_label
            context_parts.insert(1, f"{right_status_label}：{right_field_name}")
        dialog.set_results(rows, "当前字段/帧：" + " | ".join(context_parts))
        self.safe_render_both()

    def show_hotspot_filter_dialog(self):
        if self.hotspot_dialog is None:
            self.hotspot_dialog = HotspotFilterDialog(self)
        self.hotspot_dialog.show()
        self.hotspot_dialog.raise_()
        self.hotspot_dialog.activateWindow()

    def set_hotspot_filter(self, mode, comparison, threshold, filtered_transparency):
        self.hotspot_filter_enabled = True
        self.hotspot_filter_mode = str(mode)
        self.hotspot_comparison = str(comparison)
        self.hotspot_threshold = float(threshold)
        self.filtered_transparency = float(np.clip(filtered_transparency, 0.0, 100.0))
        self.update_both_views()

    def restore_original_cloud(self):
        self.hotspot_filter_enabled = False
        if self.current_field and self.current_field in self.fields:
            self.update_both_views()
        else:
            self._apply_colormap_style(self.colormap_style)

    def _current_filter_threshold(self, left_values, right_values=None):
        arrays = [np.asarray(left_values, dtype=float).ravel()]
        if right_values is not None:
            arrays.append(np.asarray(right_values, dtype=float).ravel())
        finite = np.concatenate(arrays)
        finite = finite[np.isfinite(finite)]
        if finite.size == 0:
            return float("nan")
        if self.hotspot_filter_mode == "max_ratio":
            return float(np.max(finite) * self.hotspot_threshold / 100.0)
        if self.hotspot_filter_mode == "percentile":
            return float(np.percentile(finite, self.hotspot_threshold))
        return float(self.hotspot_threshold)

    def _filter_keep_mask(self, values, threshold):
        values = np.asarray(values, dtype=float)
        if self.hotspot_comparison == "less":
            return values < threshold
        if self.hotspot_comparison == "equal":
            tolerance = max(abs(float(threshold)) * 1.0e-6, 1.0e-12)
            return np.isclose(values, threshold, rtol=0.0, atol=tolerance)
        return values > threshold

    def _apply_hotspot_lookup_tables(self, scalar_min, scalar_max, threshold):
        base_lut = create_colormap_lut(self.colormap_style)
        base_lut.SetRange(scalar_min, scalar_max)
        base_lut.Build()
        table_size = base_lut.GetNumberOfTableValues()
        filtered_opacity = 1.0 - self.filtered_transparency / 100.0
        sample_values = np.linspace(scalar_min, scalar_max, table_size)
        keep_mask = self._filter_keep_mask(sample_values, threshold)
        for index in range(table_size):
            red, green, blue, _alpha = base_lut.GetTableValue(index)
            alpha = 1.0 if keep_mask[index] else filtered_opacity
            base_lut.SetTableValue(index, red, green, blue, alpha)
        base_lut.Build()
        self._install_lookup_table_pair(base_lut, scalar_min, scalar_max)

    def _apply_opaque_lookup_tables(self, scalar_min, scalar_max):
        base_lut = create_colormap_lut(self.colormap_style)
        base_lut.SetRange(scalar_min, scalar_max)
        base_lut.Build()
        self._install_lookup_table_pair(base_lut, scalar_min, scalar_max)

    def _install_lookup_table_pair(self, source_lut, scalar_min, scalar_max):
        lut_left = vtk.vtkLookupTable()
        lut_right = vtk.vtkLookupTable()
        lut_left.DeepCopy(source_lut)
        lut_right.DeepCopy(source_lut)
        lut_left.SetRange(scalar_min, scalar_max)
        lut_right.SetRange(scalar_min, scalar_max)
        lut_left.Modified()
        lut_right.Modified()
        self.lut_left = lut_left
        self.lut_right = lut_right

        for mapper, lut in (
            (getattr(self, "mapper_l", None), self.lut_left),
            (getattr(self, "mapper_r", None), self.lut_right),
            (self.cap_mapper_l, self.lut_left),
            (self.cap_mapper_r, self.lut_right),
        ):
            if mapper is None:
                continue
            mapper.SetLookupTable(lut)
            mapper.SetScalarRange(scalar_min, scalar_max)
            mapper.SetColorModeToMapScalars()
            mapper.ScalarVisibilityOn()
            mapper.Modified()

        for scalarbar, lut in (
            (getattr(self, "scalarbar_l", None), self.lut_left),
            (getattr(self, "scalarbar_r", None), self.lut_right),
        ):
            if scalarbar is not None:
                scalarbar.SetLookupTable(lut)
                scalarbar.Modified()

        for actor in (getattr(self, "actor_l", None), getattr(self, "actor_r", None)):
            if actor is not None:
                actor.SetVisibility(True)
                actor.GetProperty().Modified()
                actor.Modified()
        self._apply_rotational_surface_opacity()

    @staticmethod
    def _safe_scalar_range(scalar_min, scalar_max, nonnegative=False):
        scalar_min, scalar_max = float(scalar_min), float(scalar_max)
        if scalar_max - scalar_min < 1.0e-12:
            eps = 1.0e-6 if abs(scalar_max) < 1.0e-6 else abs(scalar_max) * 1.0e-6
            if nonnegative:
                return 0.0, max(scalar_max + eps, eps)
            return scalar_min - eps, scalar_max + eps
        return scalar_min, scalar_max

    def _make_view_lut(self, scalar_min, scalar_max, values=None):
        lut = create_colormap_lut(self.colormap_style)
        lut.SetRange(scalar_min, scalar_max)
        lut.SetNanColor(0.6, 0.6, 0.6, 0.0)
        if self.hotspot_filter_enabled and values is not None:
            threshold = self._current_filter_threshold(values)
            opacity = 1.0 - self.filtered_transparency / 100.0
            samples = np.linspace(scalar_min, scalar_max, lut.GetNumberOfTableValues())
            keep_mask = self._filter_keep_mask(samples, threshold)
            for index, keep in enumerate(keep_mask):
                red, green, blue, _alpha = lut.GetTableValue(index)
                lut.SetTableValue(index, red, green, blue, 1.0 if keep else opacity)
        lut.Build()
        return lut

    def _install_independent_lookup_tables(
        self, left_range, right_range, left_values=None, right_values=None
    ):
        left_min, left_max = left_range
        right_min, right_max = right_range
        self.lut_left = self._make_view_lut(left_min, left_max, left_values)
        self.lut_right = self._make_view_lut(right_min, right_max, right_values)
        for mapper, lut, scalar_range in (
            (self.mapper_l, self.lut_left, left_range),
            (self.mapper_r, self.lut_right, right_range),
        ):
            mapper.SetLookupTable(lut)
            mapper.SetScalarRange(*scalar_range)
            mapper.SetColorModeToMapScalars()
            mapper.ScalarVisibilityOn()
            mapper.Modified()
        self.scalarbar_l.SetLookupTable(self.lut_left)
        self.scalarbar_r.SetLookupTable(self.lut_right)

        for mapper, lut, scalar_range in (
            (self.cap_mapper_l, self.lut_left, left_range),
            (self.cap_mapper_r, self.lut_right, right_range),
        ):
            if mapper is not None:
                mapper.SetLookupTable(lut)
                mapper.SetScalarRange(*scalar_range)
                mapper.SetColorModeToMapScalars()
                mapper.ScalarVisibilityOn()
                mapper.Modified()
        self._apply_rotational_surface_opacity()

    def show_rotational_transparency_dialog(self):
        if self.rotational_transparency_dialog is None:
            self.rotational_transparency_dialog = RotationalTransparencyDialog(self)
        self.rotational_transparency_dialog.show()
        self.rotational_transparency_dialog.raise_()
        self.rotational_transparency_dialog.activateWindow()

    def set_rotational_surface_transparency(self, transparency):
        self.rotational_surface_transparency = float(np.clip(transparency, 0.0, 100.0))
        self._apply_rotational_surface_opacity()
        self.safe_render_both()

    def _apply_rotational_surface_opacity(self):
        opacity = (
            1.0 - self.rotational_surface_transparency / 100.0
            if self.is_rotational_surface
            else 1.0
        )
        for actor in (getattr(self, "actor_l", None), getattr(self, "actor_r", None)):
            if actor is not None:
                actor.GetProperty().SetOpacity(opacity)
                actor.GetProperty().Modified()
        for actor in (self.cap_actor_l, self.cap_actor_r):
            if actor is not None:
                actor.GetProperty().SetOpacity(1.0)
                actor.SetVisibility(self.is_rotational_surface)

    def _remove_cap_actors(self):
        for renderer, actor in (
            (getattr(self, "ren_l", None), self.cap_actor_l),
            (getattr(self, "ren_r", None), self.cap_actor_r),
        ):
            if renderer is not None and actor is not None:
                renderer.RemoveActor(actor)
        self.cap_grid_l = None
        self.cap_grid_r = None
        self.cap_mapper_l = None
        self.cap_mapper_r = None
        self.cap_actor_l = None
        self.cap_actor_r = None

    def _install_cap_actors(self, cap_grid_l, cap_grid_r):
        self._remove_cap_actors()
        if cap_grid_l.GetNumberOfCells() == 0:
            return
        self.cap_grid_l = cap_grid_l
        self.cap_grid_r = cap_grid_r
        self.cap_mapper_l = vtk.vtkDataSetMapper()
        self.cap_mapper_r = vtk.vtkDataSetMapper()
        self.cap_actor_l = vtk.vtkActor()
        self.cap_actor_r = vtk.vtkActor()
        for mapper, actor, grid, lut, renderer in (
            (self.cap_mapper_l, self.cap_actor_l, cap_grid_l, self.lut_left, self.ren_l),
            (self.cap_mapper_r, self.cap_actor_r, cap_grid_r, self.lut_right, self.ren_r),
        ):
            mapper.SetInputData(grid)
            mapper.SetLookupTable(lut)
            mapper.SetScalarModeToUsePointData()
            mapper.SetColorModeToMapScalars()
            actor.SetMapper(mapper)
            actor.SetPickable(False)
            actor.GetProperty().SetOpacity(1.0)
            renderer.AddActor(actor)

    def open_rotation_dialog(self, axis_index):
        if self.node_ids is None or self.coords is None or self.elements is None:
            QtWidgets.QMessageBox.warning(self, "警告", "请先加载二维 INP 网格。")
            return

        dialog = QtWidgets.QDialog(self)
        axis_name = ("X", "Y", "Z")[axis_index]
        dialog.setWindowTitle(f"以{axis_name}轴为中心旋转")
        layout = QtWidgets.QFormLayout(dialog)

        angle_input = QtWidgets.QDoubleSpinBox(dialog)
        angle_input.setRange(0.0, 360.0)
        angle_input.setDecimals(2)
        angle_input.setSingleStep(5.0)
        angle_input.setSuffix("°")
        angle_input.setValue(90.0)
        layout.addRow("旋转角度：", angle_input)

        offset_input = QtWidgets.QDoubleSpinBox(dialog)
        offset_input.setRange(-1.0e12, 1.0e12)
        offset_input.setDecimals(6)
        offset_input.setSingleStep(1.0)
        offset_input.setValue(0.0)
        layout.addRow("偏移距离：", offset_input)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("确定")
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        self.apply_rotational_surface(
            axis_index=axis_index,
            angle_degrees=angle_input.value(),
            offset_distance=offset_input.value(),
        )

    def apply_rotational_surface(self, axis_index, angle_degrees, offset_distance):
        if np.isclose(angle_degrees, 0.0):
            self.restore_2d_mesh()
            return
        try:
            surface_l, cap_surface_l, source_indices = build_rotational_surface(
                self.node_ids,
                self.coords,
                self.elements,
                axis_index,
                angle_degrees,
                offset_distance,
            )
            surface_r = vtk.vtkPolyData()
            surface_r.DeepCopy(surface_l)
            cap_surface_r = vtk.vtkPolyData()
            cap_surface_r.DeepCopy(cap_surface_l)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "旋转失败", str(exc))
            return

        self.grid_l = surface_l
        self.grid_r = surface_r
        self.display_source_indices_l = source_indices
        self.display_source_indices_r = source_indices.copy()
        self.mapper_l.SetInputData(self.grid_l)
        self.mapper_r.SetInputData(self.grid_r)
        self._install_cap_actors(cap_surface_l, cap_surface_r)
        if hasattr(self, "wire_mapper_l"):
            self.wire_mapper_l.SetInputData(build_mesh_edge_polydata(self.grid_l))
        if hasattr(self, "wire_mapper_r"):
            self.wire_mapper_r.SetInputData(build_mesh_edge_polydata(self.grid_r))
        self.is_rotational_surface = True
        self._apply_rotational_surface_opacity()
        self.restore_2d_action.setEnabled(True)
        self.ren_l.ResetCamera()
        self.update_both_views()

    def restore_2d_mesh(self):
        if self.node_ids is None or self.coords is None or self.elements is None:
            return
        self.grid_l = build_unstructured_grid(self.node_ids, self.coords, self.elements)
        self.grid_r = build_unstructured_grid(self.node_ids, self.coords, self.elements)
        identity = np.arange(len(self.node_ids), dtype=np.int64)
        self.display_source_indices_l = identity
        self.display_source_indices_r = identity.copy()
        self.is_rotational_surface = False
        self._remove_cap_actors()
        self.mapper_l.SetInputData(self.grid_l)
        self.mapper_r.SetInputData(self.grid_r)
        if hasattr(self, "wire_mapper_l"):
            self.wire_mapper_l.SetInputData(build_mesh_edge_polydata(self.grid_l))
        if hasattr(self, "wire_mapper_r"):
            self.wire_mapper_r.SetInputData(build_mesh_edge_polydata(self.grid_r))
        self.is_rotational_surface = False
        self._apply_rotational_surface_opacity()
        self.restore_2d_action.setEnabled(False)
        self.ren_l.ResetCamera()
        self.update_both_views()

    def set_background_style(self, style):
        if not style:
            return
        style = style.strip().lower()
        if style not in (
            "abaqus", "black", "dark_gray", "gray", "light_gray",
            "white", "navy", "beige",
        ):
            return
        self.background_style = style
        self._apply_background_style(style)

    def _apply_background_style(self, style):
        if not hasattr(self, "ren_l") or not hasattr(self, "ren_r"):
            return
        if style == "abaqus":
            self._set_abaqus_background(self.ren_l)
            self._set_abaqus_background(self.ren_r)
        else:
            color = self._solid_background_color(style)
            self._set_solid_background(self.ren_l, color)
            self._set_solid_background(self.ren_r, color)
        self._apply_scalarbar_text_style()
        text_color, _use_shadow = self._get_scalarbar_text_style(style)
        wire_color = (0.75, 0.77, 0.80) if text_color[0] > 0.5 else (0.25, 0.27, 0.30)
        for actor in (getattr(self, "wire_actor_l", None), getattr(self, "wire_actor_r", None)):
            if actor is not None:
                actor.GetProperty().SetColor(*wire_color)
        self.safe_render_both()

    def _set_abaqus_background(self, renderer):
        renderer.GradientBackgroundOn()
        renderer.SetBackground2(27/255.0, 45/255.0, 70/255.0)
        renderer.SetBackground(158/255.0, 173/255.0, 194/255.0)

    @staticmethod
    def _solid_background_color(style):
        return {
            "black": (0.0, 0.0, 0.0),
            "dark_gray": (0.15, 0.15, 0.15),
            "gray": (0.5, 0.5, 0.5),
            "light_gray": (0.8, 0.8, 0.8),
            "white": (1.0, 1.0, 1.0),
            "navy": (0.04, 0.08, 0.18),
            "beige": (0.94, 0.91, 0.82),
        }.get(style, (1.0, 1.0, 1.0))

    def _set_solid_background(self, renderer, color):
        renderer.GradientBackgroundOff()
        renderer.SetBackground(*color)
        renderer.SetBackground2(*color)

    def _apply_scalarbar_text_style(self):
        text_color, use_shadow = self._get_scalarbar_text_style(self.background_style)
        for scalarbar in (getattr(self, "scalarbar_l", None), getattr(self, "scalarbar_r", None)):
            if scalarbar is None:
                continue
            self._style_text_property(scalarbar.GetLabelTextProperty(), text_color, use_shadow)
            self._style_text_property(scalarbar.GetTitleTextProperty(), text_color, use_shadow)

    def _get_scalarbar_text_style(self, style):
        if style == "abaqus":
            return (0.98, 0.98, 0.98), True
        red, green, blue = self._solid_background_color(style)
        luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
        if luminance >= 0.48:
            return (0.08, 0.08, 0.08), False
        return (0.98, 0.98, 0.98), True

    def _style_text_property(self, prop, text_color, use_shadow: bool):
        if prop is None:
            return
        prop.SetColor(*text_color)
        if use_shadow:
            prop.ShadowOn()
        else:
            prop.ShadowOff()

    def set_colormap_style(self, style):
        if not style:
            return
        style = style.strip().lower()
        if style not in (
            "abaqus", "rainbow_1", "rainbow_2", "viridis", "plasma",
            "inferno", "magma", "cividis", "turbo", "piyg", "coolwarm",
        ):
            return
        self.colormap_style = style
        self._apply_colormap_style(style)

    def _apply_colormap_style(self, style):
        new_lut = create_colormap_lut(style)

        self.lut_left.DeepCopy(new_lut)
        self.lut_right.DeepCopy(new_lut)

        if hasattr(self, "mapper_l"):
            self.mapper_l.SetLookupTable(self.lut_left)
        if hasattr(self, "mapper_r"):
            self.mapper_r.SetLookupTable(self.lut_right)
        if self.cap_mapper_l is not None:
            self.cap_mapper_l.SetLookupTable(self.lut_left)
        if self.cap_mapper_r is not None:
            self.cap_mapper_r.SetLookupTable(self.lut_right)
        if hasattr(self, "scalarbar_l"):
            self.scalarbar_l.SetLookupTable(self.lut_left)
        if hasattr(self, "scalarbar_r"):
            self.scalarbar_r.SetLookupTable(self.lut_right)

        if self.hotspot_filter_enabled and self.current_field in self.fields:
            self.update_both_views()
        else:
            self.safe_render_both()

    def _init_vtk(self):
        self.ren_l = vtk.vtkRenderer()
        self.vtk_left.GetRenderWindow().AddRenderer(self.ren_l)

        self.ren_r = vtk.vtkRenderer()
        self.vtk_right.GetRenderWindow().AddRenderer(self.ren_r)
        self._apply_background_style(self.background_style)

        for vtk_widget, renderer in (
            (self.vtk_left, self.ren_l),
            (self.vtk_right, self.ren_r),
        ):
            render_window = vtk_widget.GetRenderWindow()
            render_window.SetNumberOfLayers(2)
            render_window.SetAlphaBitPlanes(1)
            render_window.SetMultiSamples(0)
            renderer.SetUseDepthPeeling(True)
            renderer.SetMaximumNumberOfPeels(100)
            renderer.SetOcclusionRatio(0.1)

        shared_cam = self.ren_l.GetActiveCamera()
        self.ren_r.SetActiveCamera(shared_cam)

        self.marker_ren_l = vtk.vtkRenderer()
        self.marker_ren_r = vtk.vtkRenderer()
        for vtk_widget, marker_renderer in (
            (self.vtk_left, self.marker_ren_l),
            (self.vtk_right, self.marker_ren_r),
        ):
            marker_renderer.SetLayer(1)
            marker_renderer.SetActiveCamera(shared_cam)
            marker_renderer.SetPreserveDepthBuffer(False)
            marker_renderer.SetBackgroundAlpha(0.0)
            marker_renderer.InteractiveOff()
            vtk_widget.GetRenderWindow().AddRenderer(marker_renderer)

        self.iren_l = self.vtk_left.GetRenderWindow().GetInteractor()
        self.iren_r = self.vtk_right.GetRenderWindow().GetInteractor()
        self.interactor_style_l = CustomInteractorStyle()
        self.interactor_style_r = CustomInteractorStyle()
        self.iren_l.SetInteractorStyle(self.interactor_style_l)
        self.iren_r.SetInteractorStyle(self.interactor_style_r)
        self.iren_l.Initialize()
        self.iren_r.Initialize()

        self.iren_l.AddObserver("InteractionEvent", lambda o, e: self._request_render())
        self.iren_r.AddObserver("InteractionEvent", lambda o, e: self._request_render())

        self.safe_render_both()

    def open_inp(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载 INP 文件", "", "INP Files (*.inp)")
        if not path:
            return
        
        self.stop_play() 
        self._field_data_epoch += 1
        for task in list(self._background_tasks):
            try:
                task["discarded"] = True
                task["worker"].cancel()
                task["progress"].cancel()
            except Exception:
                pass

        self.node_ids, self.coords = read_inp_nodes(path)
        self.elements = read_inp_elements(path)
        if self.coords is None or len(self.coords) == 0:
            QtWidgets.QMessageBox.warning(self, "警告", "INP 未读取到节点！")
            return

        self.fields.clear()
        self.rom_fields.clear()
        self.error_fields.clear()
        self.original_field_data.clear()
        self.combo_left.clear()
        self.combo_right.clear()
        self.current_field = ""
        self.rom_current_field = ""
        self.error_current_field = ""
        self.current_frame = 0
        if self.node_query_dialog is not None:
            self.node_query_dialog.clear_result()
        self.extreme_actor_l = None
        self.extreme_actor_r = None
        if self.extreme_query_dialog is not None:
            self.extreme_query_dialog.set_results([], "当前字段/帧：--")

        self.slider.setMinimum(0)
        self.slider.setMaximum(0)
        self.slider.setValue(0)
        self.frame_label.setText("帧: 0/0")

        self._remove_cap_actors()
        self.ren_l.RemoveAllViewProps()
        self.ren_r.RemoveAllViewProps()
        self.marker_ren_l.RemoveAllViewProps()
        self.marker_ren_r.RemoveAllViewProps()

        self.grid_l = build_unstructured_grid(self.node_ids, self.coords, self.elements)
        self.grid_r = build_unstructured_grid(self.node_ids, self.coords, self.elements)
        identity = np.arange(len(self.node_ids), dtype=np.int64)
        self.display_source_indices_l = identity
        self.display_source_indices_r = identity.copy()
        self.is_rotational_surface = False
        self._apply_rotational_surface_opacity()

        self.mapper_l, self.actor_l, self.scalarbar_l = make_mapper_actor_scalarbar(
            self.grid_l, self.lut_left, "FOM"
        )
        self.ren_l.AddActor(self.actor_l)
        self.wire_mapper_l, self.wire_actor_l = make_wireframe_actor(self.grid_l)
        self.ren_l.AddActor(self.wire_actor_l)
        self.ren_l.AddViewProp(self.scalarbar_l)   

        # 右侧 mapper/actor/scalarbar
        self.mapper_r, self.actor_r, self.scalarbar_r = make_mapper_actor_scalarbar(
            self.grid_r, self.lut_right, "ROM"
        )
        self.ren_r.AddActor(self.actor_r)
        self.wire_mapper_r, self.wire_actor_r = make_wireframe_actor(self.grid_r)
        self.ren_r.AddActor(self.wire_actor_r)
        self.ren_r.AddViewProp(self.scalarbar_r)  
        self.set_grid_visibility(self.grid_visible)

        self._apply_background_style(self.background_style)

        # 重置相机并渲染
        self.ren_l.ResetCamera()
        self.safe_render_both()

        # 还没加载 CSV，控件先禁用
        self.set_controls_enabled(False)
        for action in self.rotation_actions:
            action.setEnabled(True)
        self.restore_2d_action.setEnabled(False)

    def clear_physical_fields(self):
        self._field_data_epoch += 1
        self.stop_play()

        for task in list(self._background_tasks):
            try:
                task["discarded"] = True
                task["worker"].cancel()
                task["progress"].cancel()
            except Exception:
                pass

        self.fields.clear()
        self.rom_fields.clear()
        self.error_fields.clear()
        self.original_field_data.clear()
        self.current_field = ""
        self.rom_current_field = ""
        self.error_current_field = ""
        self.current_frame = 0

        for combo in (self.combo_left, self.combo_right):
            combo.blockSignals(True)
            combo.clear()
            combo.blockSignals(False)

        self.slider.blockSignals(True)
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.slider.blockSignals(False)
        self.frame_label.setText("帧: 0/0")
        self.set_controls_enabled(False)

        for dataset in (
            getattr(self, "grid_l", None),
            getattr(self, "grid_r", None),
            self.cap_grid_l,
            self.cap_grid_r,
        ):
            if dataset is not None:
                dataset.GetPointData().SetScalars(None)
                dataset.Modified()
        for mapper in (
            getattr(self, "mapper_l", None),
            getattr(self, "mapper_r", None),
            self.cap_mapper_l,
            self.cap_mapper_r,
        ):
            if mapper is not None:
                mapper.ScalarVisibilityOff()
                mapper.Modified()
        if hasattr(self, "scalarbar_l"):
            self.scalarbar_l.SetTitle("FOM")
        if hasattr(self, "scalarbar_r"):
            self.scalarbar_r.SetTitle("ROM")

        self.clear_extreme_markers()
        if self.node_query_dialog is not None:
            self.node_query_dialog.clear_result()
        if self.global_consistency_dialog is not None:
            self.global_consistency_dialog.refresh_fields()
            self.global_consistency_dialog.result_table.setRowCount(0)
            self.global_consistency_dialog.summary_label.setText(
                "请选择物理场和误差指标后开始分析。"
            )
        if self.local_consistency_dialog is not None:
            self.local_consistency_dialog.refresh_fields()
            self.local_consistency_dialog.status_label.setText("请选择物理场并设置分析参数。")
            self.local_consistency_dialog._draw_empty_plot()
        if self.error_field_dialog is not None:
            self.error_field_dialog.refresh_fields()
            self.error_field_dialog.status_label.setText(
                "生成结果将加入主窗口右侧物理场下拉框。"
            )
        if self.node_filter_dialog is not None:
            self.node_filter_dialog.refresh_context()
            self.node_filter_dialog.status_label.setText(
                "未指定帧时，将修改该节点在整个时间历程中的数据。"
            )

        self.statusBar().showMessage("已清除全部 FOM、ROM 和误差物理场。", 5000)
        self.safe_render_both()

    def open_csv_left(self):
        if self.node_ids is None: 
            QtWidgets.QMessageBox.warning(self, "警告", "请先加载 INP")
            return

        paths, _ = QFileDialog.getOpenFileNames(self, "加载高保真 CSV", "", "CSV Files (*.csv)") 
        if not paths:
            return
        self._load_csv_async("left", paths)

    def open_csv_right(self):
        if self.node_ids is None: 
            QtWidgets.QMessageBox.warning(self, "警告", "请先加载 INP") 
            return

        paths, _ = QFileDialog.getOpenFileNames(self, "加载降阶 CSV", "", "CSV Files (*.csv)") 
        if not paths:
            return
        self._load_csv_async("right", paths)

    def _load_csv_async(self, side, paths):
        task_epoch = self._field_data_epoch
        worker = CsvLoadWorker(paths, len(self.node_ids))
        side_label = "FOM" if side == "left" else "ROM"

        def apply_results(results, errors, cancelled):
            if task_epoch != self._field_data_epoch:
                return
            target = self.fields if side == "left" else self.rom_fields
            combo = self.combo_left if side == "left" else self.combo_right
            loaded_names = []
            overwritten_names = set()
            for name, field_data in results:
                model_name = "FOM" if side == "left" else "ROM"
                if name in target:
                    overwritten_names.add(name)
                self.original_field_data.pop((model_name, name), None)
                target[name] = field_data
                if combo.findText(name) < 0:
                    combo.addItem(name)
                loaded_names.append(name)
            if overwritten_names:
                self._invalidate_dependent_error_fields(
                    overwritten_names if side == "left" else set(),
                    overwritten_names if side == "right" else set(),
                )
            if side == "left" and self.current_field == "" and loaded_names:
                combo.setCurrentText(loaded_names[0])
            elif side == "right" and self.rom_current_field == "" and loaded_names:
                combo.setCurrentText(loaded_names[0])
            if self.local_consistency_dialog is not None:
                self.local_consistency_dialog.refresh_fields()

            if cancelled:
                self.statusBar().showMessage(
                    f"{side_label} 加载已取消；已加载 {len(loaded_names)} 个物理场。", 6000
                )
            elif loaded_names:
                self.statusBar().showMessage(
                    f"已加载 {len(loaded_names)} 个 {side_label} 物理场。", 5000
                )
            if errors:
                details = "\n\n".join(f"{path}\n{message}" for path, message in errors)
                QtWidgets.QMessageBox.warning(self, "部分 CSV 加载失败", details)

        self._start_background_task(
            worker, f"正在加载 {side_label} 物理场", apply_results
        )

    def on_left_field_changed(self, name):
        if not name or name not in self.fields:
            return
        self.current_field = name

        n_frames = self.fields[name]["data"].shape[0]
        self.current_frame = 0

        self.slider.blockSignals(True)
        self.slider.setMinimum(0)
        self.slider.setMaximum(max(0, n_frames - 1))
        self.slider.setValue(0)
        self.slider.blockSignals(False)

        self.set_controls_enabled(True)

        if self._switching_error_field:
            return

        selected_right = self.combo_right.currentText()
        if (
            selected_right in self.error_fields
            and self.error_fields[selected_right]["fom_field"] != name
        ):
            fallback = name if name in self.rom_fields else self.rom_current_field
            if fallback in self.rom_fields:
                self.combo_right.setCurrentText(fallback)
                return

        if self.node_filter_dialog is not None:
            self.node_filter_dialog.refresh_context()

        self.update_both_views()

    def on_right_field_changed(self, name):
        if not name:
            return
        if name in self.error_fields:
            self.error_current_field = name
            error_field = self.error_fields[name]
            fom_field = error_field["fom_field"]
            if fom_field in self.fields and self.combo_left.currentText() != fom_field:
                self._switching_error_field = True
                try:
                    self.combo_left.setCurrentText(fom_field)
                finally:
                    self._switching_error_field = False
            current_values = np.asarray(error_field["data"][self.current_frame], dtype=float)
            if not np.any(np.isfinite(current_values)):
                valid_frames = np.flatnonzero(
                    np.any(np.isfinite(error_field["data"]), axis=1)
                )
                if valid_frames.size:
                    self.current_frame = int(valid_frames[0])
                    self.slider.blockSignals(True)
                    self.slider.setValue(self.current_frame)
                    self.slider.blockSignals(False)
        elif name in self.rom_fields:
            self.rom_current_field = name
            self.error_current_field = ""
        else:
            return

        if self.node_filter_dialog is not None:
            self.node_filter_dialog.refresh_context()

        self.update_both_views()


    def on_slider_changed(self, value):
        if self.current_field == "" or self.current_field not in self.fields: 
            return
        n_frames = self.fields[self.current_field]["data"].shape[0] 
        if value < 0 or value >= n_frames: 
            return
        
        self.current_frame = value

        self.update_both_views()

    def on_speed_changed(self, text):
        try:
            self.play_speed = float(text.replace("x", "").strip()) 
        except ValueError:
            self.play_speed = 1.0
        if self.is_playing: 
            self._apply_timer_interval()

    def _apply_timer_interval(self):
        interval = int(self.base_delay_ms / max(1e-6, self.play_speed))
        self.timer.setInterval(max(1, interval))

    def toggle_play(self):
        if self.current_field == "" or self.current_field not in self.fields: 
            return

        if self.is_playing: 
            self.stop_play()
        else: 
            self._apply_timer_interval()
            self.timer.start()
            self.is_playing = True
            self.play_btn.setText("⏸ 暂停")

            self.slider.setEnabled(False)

    def stop_play(self):
        self.timer.stop()
        self.is_playing = False
        self.play_btn.setText("▶ 播放")
        self.slider.setEnabled(True)

    def play_next(self):
        if self.current_field == "" or self.current_field not in self.fields: 
            self.stop_play()
            return

        n_frames = self.fields[self.current_field]["data"].shape[0]
        nxt = self.current_frame + 1
        if nxt >= n_frames: 
            if self.loop_mode:
                nxt = 0
            else:
                self.stop_play()
                return

        self.current_frame = nxt
        self.slider.blockSignals(True)
        self.slider.setValue(nxt)
        self.slider.blockSignals(False)

        self.update_both_views()

    def update_both_views(self):
        if self.current_field == "" or self.current_field not in self.fields:
            self.frame_label.setText("帧: 0/0")
            return

        field = self.fields[self.current_field]
        n_frames = field["data"].shape[0]
        self.current_frame = int(np.clip(self.current_frame, 0, n_frames - 1))
        selected_right = self.combo_right.currentText()
        error_key = selected_right if selected_right in self.error_fields else None
        if error_key is not None:
            error_data = np.asarray(self.error_fields[error_key]["data"], dtype=float)
            current_has_data = np.any(np.isfinite(error_data[self.current_frame]))
            if not current_has_data:
                valid_frames = np.flatnonzero(np.any(np.isfinite(error_data), axis=1))
                if valid_frames.size:
                    self.current_frame = int(valid_frames[0])
                    self.slider.blockSignals(True)
                    self.slider.setValue(self.current_frame)
                    self.slider.blockSignals(False)
        v_left_source = field["data"][self.current_frame]
        left_indices = self.display_source_indices_l
        v_left = v_left_source if left_indices is None else v_left_source[left_indices]
        scalars_l = vtk.vtkFloatArray()
        scalars_l.SetName(self.current_field)
        for x in v_left:
            scalars_l.InsertNextValue(float(x))
        self.grid_l.GetPointData().SetScalars(scalars_l)
        if self.cap_grid_l is not None:
            self.cap_grid_l.GetPointData().SetScalars(scalars_l)
            self.cap_grid_l.Modified()
        self.scalarbar_l.SetTitle(self.current_field)

        rom_key = None
        if error_key is None and self.current_field in self.rom_fields:
            rom_key = self.current_field
        elif error_key is None and self.rom_current_field in self.rom_fields:
            rom_key = self.rom_current_field

        have_right = False
        v_right_source = None
        if error_key is not None:
            rfield = self.error_fields[error_key]
            vtk_title = rfield.get("vtk_title", "Error Field")
            v_right_source = rfield["data"][self.current_frame]
            right_indices = self.display_source_indices_r
            v_right = v_right_source if right_indices is None else v_right_source[right_indices]
            scalars_r = vtk.vtkFloatArray()
            scalars_r.SetName(vtk_title)
            for x in v_right:
                scalars_r.InsertNextValue(float(x))
            self.grid_r.GetPointData().SetScalars(scalars_r)
            if self.cap_grid_r is not None:
                self.cap_grid_r.GetPointData().SetScalars(scalars_r)
                self.cap_grid_r.Modified()
            self.scalarbar_r.SetTitle(vtk_title)
            have_right = True
        elif rom_key is not None:
            rfield = self.rom_fields[rom_key]
            rn = rfield["data"].shape[0]
            rf = int(np.clip(self.current_frame, 0, rn - 1))
            v_right_source = rfield["data"][rf]
            right_indices = self.display_source_indices_r
            v_right = v_right_source if right_indices is None else v_right_source[right_indices]

            scalars_r = vtk.vtkFloatArray()
            scalars_r.SetName(rom_key)
            for x in v_right:
                scalars_r.InsertNextValue(float(x))
            self.grid_r.GetPointData().SetScalars(scalars_r)
            if self.cap_grid_r is not None:
                self.cap_grid_r.GetPointData().SetScalars(scalars_r)
                self.cap_grid_r.Modified()
            have_right = True
            self.scalarbar_r.SetTitle(rom_key)
        else:
            self.scalarbar_r.SetTitle("ROM")

        left_min, left_max = field["vmin"], field["vmax"]
        if error_key is not None:
            left_range = self._safe_scalar_range(left_min, left_max)
            right_range = self._safe_scalar_range(rfield["vmin"], rfield["vmax"], nonnegative=True)
            self._install_independent_lookup_tables(
                left_range,
                right_range,
                v_left_source,
                v_right_source,
            )
        elif have_right:
            right_min, right_max = rfield["vmin"], rfield["vmax"]
            shared_min = min(left_min, right_min)
            shared_max = max(left_max, right_max)
        else:
            shared_min, shared_max = left_min, left_max
            self.grid_r.GetPointData().SetScalars(None)
            if self.cap_grid_r is not None:
                self.cap_grid_r.GetPointData().SetScalars(None)

        if error_key is None:
            shared_min, shared_max = self._safe_scalar_range(shared_min, shared_max)
            self.mapper_l.SetScalarRange(shared_min, shared_max)
            self.mapper_r.SetScalarRange(shared_min, shared_max)
            if self.hotspot_filter_enabled:
                filter_threshold = self._current_filter_threshold(
                    v_left_source, v_right_source if have_right else None
                )
                self._apply_hotspot_lookup_tables(shared_min, shared_max, filter_threshold)
            else:
                self._apply_opaque_lookup_tables(shared_min, shared_max)

        self.scalarbar_l.SetTitle(self.current_field)
        frame_text = field["frames"][self.current_frame] if "frames" in field else str(self.current_frame)
        unavailable = error_key is not None and not np.any(np.isfinite(v_right_source))
        suffix = "，误差场无匹配数据" if unavailable else ""
        self.frame_label.setText(
            f"帧: {self.current_frame + 1}/{n_frames} ({frame_text}{suffix})"
        )

        self.grid_l.Modified()
        self.grid_r.Modified()

        if (
            self.extreme_query_dialog is not None
            and self.extreme_query_dialog.isVisible()
            and self.extreme_query_dialog.auto_update_check.isChecked()
        ):
            self.run_extreme_query()

        self.safe_render_both()

    def safe_render(self, vtk_widget):
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
            return

    def safe_render_both(self):
        if getattr(self, "_closing", False):
            return
        self.safe_render(self.vtk_left)
        self.safe_render(self.vtk_right)

    def _request_render(self):
        if getattr(self, "_closing", False): 
            return

        if self._render_pending:
            return
        self._render_pending = True
        QtCore.QTimer.singleShot(0, self._do_render)

    def _do_render(self):
        if getattr(self, "_closing", False):
            return

        self._render_pending = False
        self.safe_render_both()

    def closeEvent(self, event):
        self._closing = True

        for task in list(getattr(self, "_background_tasks", [])):
            try:
                task["worker"].cancel()
                task["progress"].close()
            except Exception:
                pass
        for task in list(getattr(self, "_background_tasks", [])):
            try:
                thread = task["thread"]
                thread.quit()
                thread.wait()
            except Exception:
                pass

        try:
            if hasattr(self, "timer") and self.timer.isActive():
                self.timer.stop()
        except Exception:
            pass

        try:
            self._render_pending = True
        except Exception:
            pass

        try:
            if hasattr(self, "iren_l") and self.iren_l is not None:
                self.iren_l.RemoveAllObservers()
            if hasattr(self, "iren_r") and self.iren_r is not None:
                self.iren_r.RemoveAllObservers()
        except Exception:
            pass

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


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    install_application_fonts(app)
    win = VTKCompareWindow()
    win.show()
    sys.exit(app.exec_()) 
