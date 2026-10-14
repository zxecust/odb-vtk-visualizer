# -*- coding: utf-8 -*-
"""Self-contained Abaqus backend for ODB Exporter; compatible with Python 2 and 3."""
from __future__ import print_function

import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import traceback

import csv
import math
from collections import OrderedDict

EVENT_PREFIX = "ODB_EXPORT_EVENT "
INVARIANTS = {
    "MISES": "Mises", "TRESCA": "Tresca", "PRESS": "Pressure",
    "MAX_PRINCIPAL": "MaxPrincipal", "MID_PRINCIPAL": "MidPrincipal",
    "MIN_PRINCIPAL": "MinPrincipal", "MAGNITUDE": "Magnitude",
}


# INP mesh ordering, node extraction and CSV output.
def abaqus_native_string(value):
    """Convert Unicode only at the Abaqus Python 2 API boundary."""
    if sys.version_info[0] < 3 and isinstance(value, type(u"")):
        try:
            return value.encode(sys.getfilesystemencoding() or "utf-8")
        except UnicodeEncodeError:
            raise ValueError(u"当前 Abaqus 环境无法编码此路径或名称，请使用系统支持的字符。")
    return value


def _option(keyword, name):
    for item in keyword.split(",")[1:]:
        if "=" in item:
            key, value = item.split("=", 1)
            if key.strip().lower() == name.lower():
                return value.strip().strip("\"'")
    return None


def _inp_lines(path, stack=None):
    path = os.path.abspath(path)
    stack = [] if stack is None else stack
    if path in stack:
        raise ValueError("Circular INP Include: " + " -> ".join(stack + [path]))
    with io.open(path, "r", encoding="utf-8-sig", errors="ignore") as stream:
        for raw in stream:
            line = raw.strip()
            if not line or line.startswith("**"):
                continue
            if line.split(",", 1)[0].lower() == "*include":
                name = _option(line, "input") or _option(line, "file")
                if not name:
                    raise ValueError("Include has no input file: " + path)
                child = name if os.path.isabs(name) else os.path.join(os.path.dirname(path), name)
                for included in _inp_lines(child, stack + [path]):
                    yield included
            else:
                yield line


def _new_mesh():
    return {"nodes": OrderedDict(), "used": set(), "elements": 0}


def _element_size(kind):
    kind = (kind or "").upper().replace(" ", "")
    if kind.startswith(("MASS", "ROTARYI")):
        return 1
    match = re.match(r"^(?:B|PIPE|FRAME)[23]([123])", kind)
    if match:
        return {"1": 2, "2": 3, "3": 4}[match.group(1)]
    for pattern in (r"^T[23]D([23])", r"^CONN[23]D(2)",
                    r"^(?:C|DC|AC|COH|CIN)?3D(\d+)",
                    r"^(?:CPE|CPS|CAX|CGAX|DC2D|SAX|M3D|R3D|STRI|S|SC)(\d+)"):
        match = re.match(pattern, kind)
        if match:
            return int(match.group(1))
    return None


def read_inp_node_order(inp_path):
    """Return instance/node pairs in the visualizer's INP mesh order."""
    parts = OrderedDict()
    instances = []
    global_mesh, assembly_mesh = _new_mesh(), _new_mesh()
    part = instance = mesh = None
    assembly = assembly_seen = False
    mode, kind = None, None
    pending, pending_mesh = [], None

    def finish_element():
        if pending_mesh is not None and pending:
            expected = _element_size(kind)
            if expected is None or len(pending) >= expected:
                pending_mesh["elements"] += 1
                pending_mesh["used"].update(pending if expected is None else pending[:expected])

    for line in _inp_lines(inp_path):
        if line.startswith("*"):
            finish_element()
            pending, pending_mesh = [], None
            mode, kind, mesh = None, None, None
            keyword = line.split(",", 1)[0].lower()
            if keyword == "*part":
                name = _option(line, "name")
                if not name:
                    raise ValueError("Part has no name.")
                part = parts.setdefault(name.lower(), _new_mesh())
            elif keyword == "*end part":
                part = None
            elif keyword == "*assembly":
                assembly = assembly_seen = True
            elif keyword == "*end assembly":
                assembly = False
            elif keyword == "*instance":
                name = _option(line, "name")
                if not name:
                    raise ValueError("Instance has no name.")
                instance = {"name": name, "part": _option(line, "part"), "mesh": _new_mesh()}
                instances.append(instance)
            elif keyword == "*end instance":
                instance = None
            elif keyword in ("*node", "*element"):
                mesh = (part if part is not None else instance["mesh"]
                        if instance is not None else assembly_mesh if assembly else global_mesh)
                mode, kind = keyword, _option(line, "type")
            continue
        if mesh is None:
            continue
        tokens = [item.strip() for item in line.split(",") if item.strip()]
        if mode == "*node":
            if len(tokens) >= 3:
                try:
                    label = int(tokens[0])
                    for coordinate in tokens[1:4]:
                        float(coordinate)
                except ValueError:
                    continue
                mesh["nodes"][label] = None
        elif mode == "*element":
            try:
                values = [int(item) for item in tokens]
            except ValueError:
                finish_element()
                pending, pending_mesh = [], None
                continue
            if pending_mesh is None:
                pending_mesh, pending = mesh, values[1:]
            else:
                pending.extend(values)
            expected = _element_size(kind)
            if ((expected is not None and len(pending) >= expected)
                    or (expected is None and not line.endswith(","))):
                finish_element()
                pending, pending_mesh = [], None
    finish_element()
    order = []

    def append(definition, name, preserve_all):
        if definition["elements"]:
            order.extend((name, label) for label in definition["nodes"]
                         if preserve_all or label in definition["used"])

    if assembly_seen:
        for item in instances:
            definition = item["mesh"]
            if not definition["elements"]:
                part_name = (item["part"] or "").lower()
                if part_name not in parts:
                    raise ValueError("Instance references missing Part: " + item["name"])
                definition = parts[part_name]
            append(definition, item["name"], True)
        append(assembly_mesh, "", False)
        if not instances and not assembly_mesh["elements"]:
            for definition in parts.values():
                append(definition, "", True)
    else:
        append(global_mesh, "", False)
        for definition in parts.values():
            append(definition, "", True)
    if not order:
        raise ValueError("No mesh nodes found in INP.")
    return order


def _instance_key(name, instances):
    matches = [key for key in instances.keys() if key.lower() == name.lower()]
    if len(matches) != 1:
        raise ValueError("ODB instance not found or ambiguous: " + name)
    return matches[0]


def _export_order(odb, export_mode, instance_name, inp_path):
    instances = odb.rootAssembly.instances
    if export_mode == "assembly":
        if not inp_path:
            raise ValueError("Assembly export requires the INP used by the visualizer.")
        order = [(_instance_key(name, instances) if name else "", label)
                 for name, label in read_inp_node_order(inp_path)]
    elif export_mode == "instance":
        names = list(instances.keys())
        if not names:
            raise ValueError("ODB has no instances.")
        name = _instance_key(instance_name, instances) if instance_name else names[0]
        if inp_path:
            order = read_inp_node_order(inp_path)
            named = [(scope, label) for scope, label in order if scope]
            order = [(name, label) for scope, label in order
                     if scope.lower() == name.lower() or (not named and not scope)]
        else:
            order = [(name, node.label) for node in sorted(instances[name].nodes, key=lambda node: node.label)]
            print("No INP: nodes sorted by ODB labels; INP order is not verified.")
    else:
        raise ValueError("export_mode must be 'assembly' or 'instance'.")
    if not order:
        raise ValueError("No nodes selected; check the INP and instance_name.")
    if len(set(order)) != len(order):
        raise ValueError("Duplicate instance/node keys; check the INP mesh scopes.")
    grouped = OrderedDict()
    for name, label in order:
        grouped.setdefault(name, set()).add(label)
    for name, labels in grouped.items():
        if name:
            missing = labels - set(node.label for node in instances[name].nodes)
            if missing:
                raise ValueError("INP nodes missing in ODB instance {}: {}".format(name, sorted(missing)[:10]))
    return order, grouped


def _scalar_field(field, choice):
    if not choice:
        return field
    import abaqusConstants as constants
    aliases = {"mises": "MISES", "maxprincipal": "MAX_PRINCIPAL", "minprincipal": "MIN_PRINCIPAL",
               "midprincipal": "MID_PRINCIPAL", "tresca": "TRESCA", "pressure": "PRESS",
               "press": "PRESS", "magnitude": "MAGNITUDE"}
    key = re.sub(r"[\s._-]+", "", choice).lower()
    if key in aliases:
        return field.getScalarField(invariant=getattr(constants, aliases[key]))
    matches = [label for label in getattr(field, "componentLabels", ()) if label.lower() == choice.lower()]
    if matches:
        return field.getScalarField(componentLabel=abaqus_native_string(matches[0]))
    raise ValueError("Unknown invariant/component: " + choice)


def _node_values(field, region, name, choice, reduce_method, nodal, element_nodal):
    scoped = field.getSubset(region=region) if region is not None else field
    try:
        subset = scoped.getSubset(position=nodal, readOnly=True)
    except Exception:
        subset = None
    if subset is None or not len(subset.values):
        subset = scoped.getSubset(position=element_nodal, readOnly=True)
    if not len(subset.values):
        return {}
    subset = _scalar_field(subset, choice)
    sums, counts, maxima = {}, {}, {}
    for value in subset.values:
        value_name = getattr(getattr(value, "instance", None), "name", "")
        if name:
            if value_name and value_name.lower() != name.lower():
                continue
        elif value_name and value_name.upper() != "ASSEMBLY":
            continue
        try:
            data = value.data
        except Exception:
            data = value.dataDouble
        try:
            scalar = float(data)
        except (TypeError, ValueError):
            raise ValueError("Field is not scalar; specify var_choose (Mises, Magnitude, S11, ...).")
        if math.isnan(scalar) or math.isinf(scalar):
            continue
        label = int(value.nodeLabel)
        if reduce_method == "max":
            maxima[label] = max(maxima.get(label, scalar), scalar)
        else:
            sums[label] = sums.get(label, 0.0) + scalar
            counts[label] = counts.get(label, 0) + 1
    if reduce_method == "max":
        return maxima
    return dict((label, total / counts[label]) for label, total in sums.items())


def _csv_file(path):
    if sys.version_info[0] < 3:
        return open(path, "wb")
    return io.open(path, "w", encoding="utf-8-sig", newline="")


def _write_row(writer, values):
    if sys.version_info[0] < 3:
        values = [value.encode("utf-8") if isinstance(value, type(u"")) else value for value in values]
    writer.writerow(values)


def _requires_node_mapping(export_mode, instance_names):
    return export_mode == "assembly" and len(set(name.lower() for name in instance_names)) > 1


def export_nodal_table_csv_transposed_sorted(
    odbpath, var, var_choose=None, out_csv=None, instance_name=None,
    step_limit=None, frame_stride=1, reduce_method="avg",
    export_mode="instance", inp_path=None, log_callback=None, progress_callback=None,
):
    """One frame per row; preserve INP node order and fill missing values with NaN."""
    from odbAccess import openOdb
    from abaqusConstants import NODAL, ELEMENT_NODAL
    if int(frame_stride) != frame_stride or frame_stride < 1:
        raise ValueError("frame_stride must be a positive integer.")
    if step_limit is not None and (int(step_limit) != step_limit or step_limit < 1):
        raise ValueError("step_limit must be a positive integer or None.")
    if reduce_method not in ("avg", "max"):
        raise ValueError("reduce_method must be 'avg' or 'max'.")
    if export_mode == "assembly" and instance_name:
        raise ValueError("instance_name must be None for assembly export.")
    started = time.time()

    def report(message):
        if log_callback is None:
            print(message)
        else:
            log_callback(message)

    odb = openOdb(abaqus_native_string(odbpath), readOnly=True)
    try:
        var = abaqus_native_string(var)
        order, grouped = _export_order(odb, export_mode, instance_name, inp_path)
        write_mapping = _requires_node_mapping(export_mode, grouped)
        steps = [name for name in odb.steps.keys() if name.lower() != "initial"]
        if step_limit is not None:
            steps = steps[:int(step_limit)]
        if not steps:
            raise ValueError("ODB has no selected analysis steps.")
        stride = int(frame_stride)
        total_frames = sum((len(odb.steps[name].frames) + stride - 1) // stride for name in steps)
        if progress_callback is not None:
            progress_callback(0, total_frames, None)
        if out_csv is None:
            directory = os.path.join(os.path.dirname(os.path.abspath(odbpath)), "reports_csv",
                                     os.path.splitext(os.path.basename(odbpath))[0])
            scope = "assembly" if export_mode == "assembly" else order[0][0]
            filename = "{}{}_{}".format(var, "_" + var_choose if var_choose else "", scope)
            out_csv = os.path.join(directory, re.sub(r'[<>:"/\\|?*]', "_", filename) + ".csv")
        directory = os.path.dirname(os.path.abspath(out_csv))
        if not os.path.isdir(directory):
            os.makedirs(directory)
        mapping_path = os.path.splitext(out_csv)[0] + "_nodes.csv"
        report(u"导出对象：{}".format(u"整个装配体" if export_mode == "assembly" else u"指定实例"))
        report(u"实例：{}".format(", ".join(name or "ASSEMBLY" for name in grouped)))
        report(u"节点数：{}；输出：{}".format(len(order), out_csv))
        if write_mapping:
            with _csv_file(mapping_path) as stream:
                writer = csv.writer(stream)
                _write_row(writer, ["DataColumn", "InternalNodeID", "Instance", "NodeLabel"])
                for index, (name, label) in enumerate(order):
                    _write_row(writer, [index, index + 1, name or "ASSEMBLY", label])
        frame_count, missing_total = 0, 0
        with _csv_file(out_csv) as stream:
            writer = csv.writer(stream)
            _write_row(writer, ["Step-Frame"] + ["{}.Node-{}".format(name or "ASSEMBLY", label)
                                                for name, label in order])
            for step_name in steps:
                frames = odb.steps[step_name].frames
                for frame_id in range(0, len(frames), stride):
                    frame = frames[frame_id]
                    frame_label = "{}-frame{}".format(step_name, frame_id)
                    data = {}
                    if var in frame.fieldOutputs:
                        field = frame.fieldOutputs[var]
                        for name in grouped:
                            region = odb.rootAssembly.instances[name] if name else None
                            values = _node_values(field, region, name, var_choose, reduce_method, NODAL, ELEMENT_NODAL)
                            data.update(((name, label), value) for label, value in values.items())
                    else:
                        report(u"帧 {} 缺少物理场 {}，填入 NaN。".format(frame_label, var))
                    missing = sum(key not in data for key in order)
                    missing_total += missing
                    _write_row(writer, [frame_label] + [data.get(key, float("nan")) for key in order])
                    frame_count += 1
                    report(u"已处理 {}：{} 个节点，{} 个缺失值。".format(frame_label, len(order), missing))
                    if progress_callback is not None:
                        progress_callback(frame_count, total_frames, frame_label)
        report(u"导出完成：{} 帧，{} 个缺失值，耗时 {:.2f} 秒。".format(frame_count, missing_total, time.time() - started))
        if write_mapping:
            report(u"节点映射表：{}".format(mapping_path))
        return out_csv
    finally:
        odb.close()


# GUI protocol, ODB inspection, upgrade and batch orchestration.
class ExportCancelled(Exception):
    pass


class UpgradeDeclined(Exception):
    pass


def source_signature(path):
    stat = os.stat(path)
    return [stat.st_size, stat.st_mtime]


def upgrade_required(path, exc):
    """Only offer conversion for a confirmed older-release database."""
    message = str(exc).lower()
    if "more recent release" in message or "installation must be upgraded" in message:
        return False
    if "previous release" not in message and not (
            "upgrade" in message and "-job" in message and "-odb" in message):
        return False
    try:
        from odbAccess import isUpgradeRequiredForOdb
        return bool(isUpgradeRequiredForOdb(abaqus_native_string(path)))
    except Exception:
        # An inconclusive check must not turn an ordinary read error into an upgrade offer.
        return False


def ask_upgrade(path, request):
    if request.get("_upgrade_remaining"):
        return
    decision_path = request.get("upgrade_decision_file")
    if not decision_path:
        raise ValueError(u"该 ODB 需要升级，请通过 ODB Exporter 确认升级副本。")
    if os.path.exists(decision_path):
        os.remove(decision_path)
    emit("upgrade_required", odb_path=path,
         batch=bool(request.get("batch")),
         message=u"该 ODB 来自较旧版本，当前 Abaqus 已确认需要升级。")
    while True:
        check_cancel(request)
        if os.path.isfile(decision_path):
            with io.open(decision_path, "r", encoding="utf-8") as stream:
                decision = json.load(stream)
            os.remove(decision_path)
            if not decision.get("upgrade"):
                raise UpgradeDeclined(u"已取消升级：该 ODB 与当前 Abaqus 版本不兼容，当前流程已终止；原文件未修改。")
            request["_upgrade_remaining"] = bool(decision.get("apply_remaining"))
            return
        time.sleep(0.1)


def inspect_for_request(path, request):
    """Preserve source identity while using a confirmed upgraded copy for reading."""
    check_cancel(request)
    copies = request.setdefault("upgraded_files", {})
    cached = copies.get(path)
    if cached and cached.get("signature") == source_signature(path) and os.path.isfile(cached["path"]):
        try:
            return cached["path"], inspect_odb(cached["path"], request.get("instance_name"), request)
        except ExportCancelled:
            raise
        except ValueError:
            raise
        except Exception:
            # Retry the source if a cached copy was removed, damaged or is incompatible.
            copies.pop(path, None)
    try:
        return path, inspect_odb(path, request.get("instance_name"), request)
    except ExportCancelled:
        raise
    except Exception as exc:
        if not upgrade_required(path, exc):
            raise
    signature = source_signature(path)
    ask_upgrade(path, request)
    check_cancel(request)
    directory = os.path.join(os.path.dirname(path), "odb_upgraded")
    if not os.path.isdir(directory):
        os.makedirs(directory)
    folder = tempfile.mkdtemp(prefix="upgrade_", dir=directory)
    destination = os.path.join(folder, os.path.basename(path))
    emit("upgrade_started", odb_path=path)
    emit("log", message=u"正在升级副本：{}；原 ODB 保留。".format(path))
    try:
        from odbAccess import upgradeOdb
        upgradeOdb(existingOdbPath=abaqus_native_string(path),
                   upgradedOdbPath=abaqus_native_string(destination))
        check_cancel(request)
        if source_signature(path) != signature:
            raise ValueError(u"升级期间原 ODB 已发生变化，请等待计算结束后重新读取。")
        info = inspect_odb(destination, request.get("instance_name"), request)
    except Exception:
        # Leave the conversion log for diagnosis; never advertise an incomplete copy.
        if os.path.isfile(destination):
            os.remove(destination)
        raise
    cached = {"path": destination, "signature": signature}
    copies[path] = cached
    emit("upgraded", odb_path=path, copy=cached)
    emit("log", message=u"升级副本已保存：{}；继续原处理流程。".format(destination))
    return destination, info


def error_message(exc):
    try:
        text = type(u"")(exc)
    except UnicodeError:
        text = str(exc).decode(sys.getfilesystemencoding() or "utf-8", "replace")
    lowered = text.lower()
    if "more recent release" in lowered or "installation must be upgraded" in lowered:
        return u"该 ODB 由更高版本的 Abaqus 生成，当前环境无法读取。请选择生成该 ODB 的版本；使用更高版本时，可能需要先升级 ODB 副本。"
    if "previous release" in lowered or ("-upgrade" in lowered and "odb" in lowered):
        return u"该 ODB 来自较旧的 Abaqus 版本，当前环境要求先升级数据库。请使用生成它的版本，或用当前版本升级一个 ODB 副本后再读取；原文件未修改。"
    if "unicode" in lowered and "recognized type" in lowered:
        return u"旧版 Abaqus 接口不接受 Unicode 参数，请确认后台脚本已更新。"
    return text


def emit(kind, **values):
    values["event"] = kind
    sys.stdout.write(EVENT_PREFIX + json.dumps(values, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def check_cancel(request):
    if os.path.exists(request.get("cancel_file", "")):
        raise ExportCancelled()


def field_info(field):
    scalar = str(field.type) == "SCALAR"
    components = list(getattr(field, "componentLabels", ()))
    choices = [INVARIANTS[str(value)] for value in field.validInvariants
               if str(value) in INVARIANTS]
    for label in components:
        if label not in choices:
            choices.append(label)
    return {"scalar": scalar, "choices": choices}


def inspect_odb(path, instance_name=None, request=None):
    from odbAccess import openOdb
    odb = openOdb(abaqus_native_string(path), readOnly=True)
    try:
        instance_keys = list(odb.rootAssembly.instances.keys())
        instances = [{"name": name, "nodes": len(odb.rootAssembly.instances[name].nodes)}
                     for name in instance_keys]
        region = None
        if instance_name:
            matches = [name for name in instance_keys
                       if name.lower() == instance_name.lower()]
            if len(matches) != 1:
                raise ValueError(u"该 ODB 不包含所选实例：{}".format(instance_name))
            region = odb.rootAssembly.instances[matches[0]]
        fields = {}
        for step_name in odb.steps.keys():
            if step_name.lower() == "initial":
                continue
            for frame in odb.steps[step_name].frames:
                if request is not None:
                    check_cancel(request)
                for name in frame.fieldOutputs.keys():
                    field = frame.fieldOutputs[name]
                    info = field_info(field)
                    # 已见过同样的字段定义时，不重复读取实例数据。
                    previous = fields.get(name)
                    if previous is not None and previous["scalar"] == info["scalar"] and all(
                            choice in previous["choices"] for choice in info["choices"]):
                        continue
                    subset = field.getSubset(region=region) if region is not None else field
                    if not len(subset.values):
                        continue
                    if previous is None:
                        fields[name] = info
                    else:
                        previous["scalar"] = previous["scalar"] and info["scalar"]
                        previous["choices"].extend(
                            choice for choice in info["choices"]
                            if choice not in previous["choices"])
        return {"instances": instances, "fields": fields}
    finally:
        odb.close()


def safe_filename(variable, choice):
    name = variable + ("_" + choice if choice else "")
    return re.sub(r'[<>:"/\\|?*]', "_", name).rstrip(" .") + ".csv"


def export_all(request):
    files = request["files"]
    tasks = request["tasks"]
    if not files or not tasks:
        raise ValueError(u"请选择 ODB 文件和至少一个物理场。")
    batch = request.get("batch", len(files) > 1)
    template = request.get("inp_path")
    if batch and (not template or not os.path.isfile(template)
                  or os.path.splitext(template)[1].lower() != ".inp"):
        raise ValueError(u"批量导出需要有效的模板 INP；所有 ODB 共用该模板，不再查找各自的同名 INP。")
    if batch:
        emit("log", message=u"批量共用模板 INP：{}".format(template))
    success = skipped = failures = 0
    total = len(files) * len(tasks)
    done = 0
    for odb_path in files:
        check_cancel(request)
        emit("log", message=u"正在检查：{}".format(odb_path))
        inp_path = template if batch else (template or os.path.splitext(odb_path)[0] + ".inp")
        if not os.path.isfile(inp_path):
            emit("log", level="warning",
                 message=u"跳过文件：找不到配套 INP：{}".format(inp_path))
            skipped += len(tasks)
            done += len(tasks)
            emit("progress", value=int(done * 100 / total))
            continue
        try:
            read_path, info = inspect_for_request(odb_path, request)
            write_mapping = _requires_node_mapping(
                request["object_mode"],
                [name for name, label in read_inp_node_order(inp_path)]
                if request["object_mode"] == "assembly" else [])
        except (ExportCancelled, UpgradeDeclined):
            raise
        except Exception as exc:
            failures += len(tasks)
            done += len(tasks)
            emit("log", level="error",
                 message=u"跳过文件：无法读取模型或所选实例。{}".format(error_message(exc)))
            emit("progress", value=int(done * 100 / total))
            continue
        folder = os.path.join(request["output_dir"],
                              os.path.splitext(os.path.basename(odb_path))[0])
        for task in tasks:
            check_cancel(request)
            variable, choice = task["variable"], task.get("choice")
            field = info["fields"].get(variable)
            if field is None or (choice and choice not in field["choices"]) or (
                    not choice and field is not None and not field["scalar"]):
                skipped += 1
                done += 1
                emit("log", level="warning",
                     message=u"跳过 {}：所选对象没有物理场或分量 {} / {}。".format(
                         os.path.basename(odb_path), variable, choice or u"无"))
                emit("progress", value=int(done * 100 / total))
                continue
            filename = safe_filename(variable, choice)
            destination = os.path.join(folder, filename)
            mapping_destination = os.path.splitext(destination)[0] + "_nodes.csv"
            if not request.get("overwrite") and (
                    os.path.exists(destination) or (write_mapping and os.path.exists(mapping_destination))):
                skipped += 1
                done += 1
                emit("log", level="warning", message=u"跳过已有结果：{}".format(destination))
                emit("progress", value=int(done * 100 / total))
                continue
            if not os.path.isdir(folder):
                os.makedirs(folder)
            staging = tempfile.mkdtemp(prefix=".odb_export_", dir=folder)

            def log(message):
                check_cancel(request)
                emit("log", message=message.replace(staging, folder))

            last_progress = [0.0]

            def frame_progress(completed, frame_total, frame_label):
                check_cancel(request)
                now = time.time()
                if completed not in (0, frame_total) and now - last_progress[0] < 0.1:
                    return
                last_progress[0] = now
                # Reserve the last 5% of each task for closing and publishing its files.
                fraction = 0.95 * completed / frame_total if frame_total else 0.0
                emit("progress", value=(done + fraction) * 100.0 / total,
                     message=u"{} · {} · {}/{} 帧".format(
                         os.path.basename(odb_path), os.path.splitext(filename)[0],
                         completed, frame_total))

            try:
                log(u"开始导出：{} / {}".format(variable, choice or u"无"))
                staged_csv = os.path.join(staging, filename)
                export_nodal_table_csv_transposed_sorted(
                    odbpath=read_path, var=variable, var_choose=choice,
                    out_csv=staged_csv, export_mode=request["object_mode"],
                    instance_name=request.get("instance_name"), inp_path=inp_path,
                    frame_stride=request.get("frame_stride", 1),
                    reduce_method=request.get("reduce_method", "avg"), log_callback=log,
                    progress_callback=frame_progress)
                check_cancel(request)
                staged_mapping = os.path.splitext(staged_csv)[0] + "_nodes.csv"
                outputs = [(staged_csv, destination)]
                if write_mapping:
                    outputs.insert(0, (staged_mapping, mapping_destination))
                for source, target in outputs:
                    if hasattr(os, "replace"):
                        os.replace(source, target)
                    else:
                        if os.path.exists(target):
                            os.remove(target)
                        os.rename(source, target)
                if not write_mapping and request.get("overwrite") and os.path.isfile(mapping_destination):
                    os.remove(mapping_destination)
                success += 1
                emit("log", message=u"已保存：{}".format(destination))
            except ExportCancelled:
                raise
            except Exception as exc:
                failures += 1
                emit("log", level="error",
                     message=u"导出 {} / {} 失败：{}".format(
                         variable, choice or u"无", error_message(exc)))
            finally:
                shutil.rmtree(staging, ignore_errors=True)
            done += 1
            emit("progress", value=int(done * 100 / total))
    emit("summary", success=success, skipped=skipped, failures=failures)


def main(request_path):
    with io.open(request_path, "r", encoding="utf-8") as stream:
        request = json.load(stream)
    try:
        action = request["action"]
        if action == "probe":
            from odbAccess import openOdb
            if not callable(openOdb):
                raise ValueError(u"该 Python 环境无法打开 ODB。")
            emit("probe", version=sys.version.split()[0])
        elif action == "inspect":
            _, info = inspect_for_request(request["odb_path"], request)
            emit("metadata", **info)
        elif action == "export":
            export_all(request)
        else:
            raise ValueError(u"未知后台操作。")
        emit("done")
        return 0
    except ExportCancelled:
        emit("cancelled", message=u"处理已取消；当前未完成的结果不会保存。")
        return 0
    except UpgradeDeclined as exc:
        emit("cancelled", message=type(u"")(exc), reason="upgrade_declined")
        return 0
    except Exception as exc:
        emit("error", message=u"Abaqus 处理失败：{}".format(error_message(exc)),
             details=traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[-1]))
