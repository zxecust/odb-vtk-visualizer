# -*- coding: UTF-8 -*-

from odbAccess import openOdb
from abaqusConstants import NODAL, ELEMENT_NODAL
import os
import csv
import re
import time


def export_nodal_table_csv_transposed_sorted(
    odbpath,
    var,
    var_choose=None,          # 张量不变量：'Mises'/'MaxPrincipal'...；标量传 None
    out_csv=None,
    instance_name=None,       # 不填默认第一个 instance
    step_limit=None,          # 只导前 N 个非 Initial step；不填全导
    frame_stride=1,           # 每隔多少帧导一次
    reduce_method="avg"       # ELEMENT_NODAL 同一节点多值合并：'avg' 或 'max'
):
    """
    输出 CSV（横纵互换 + 正确排序）：
      行：Step-Frame
      列：NodeLabel
      第 1 列为 Step-Frame 标签
    并打印导出耗时。
    """

    t0 = time.time()

    odb = openOdb(odbpath, readOnly=True)
    try:
        asm = odb.rootAssembly
        inst = asm.instances[instance_name] if instance_name else asm.instances.values()[0]

        # 输出路径
        if out_csv is None:
            odb_dir = os.path.dirname(odbpath)
            odb_name = os.path.splitext(os.path.basename(odbpath))[0]
            out_dir = os.path.join(odb_dir, "reports_csv", odb_name)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
            fname = var if var_choose is None else "{}_{}".format(var, var_choose)
            out_csv = os.path.join(out_dir, fname + ".csv")

        data = {}   # data[node][col] = value
        cols = []   # Step-Frame 列名

        # Step 遍历（保持 odb.steps 的原始顺序）
        step_names = [k for k in odb.steps.keys() if k != "Initial"]
        if step_limit is not None:
            step_names = step_names[:int(step_limit)]

        for step_name in step_names:
            step = odb.steps[step_name]
            frames = step.frames

            for frame_id in range(0, len(frames), max(1, int(frame_stride))):
                frame = frames[frame_id]

                col = "{}-frame{}".format(step_name, frame_id)
                cols.append(col)

                if var not in frame.fieldOutputs:
                    continue

                fo = frame.fieldOutputs[var]

                # 1) NODAL
                subset = None
                try:
                    subset = fo.getSubset(position=NODAL)
                    if len(subset.values) == 0:
                        subset = None
                except:
                    subset = None

                # 2) ELEMENT_NODAL
                if subset is None:
                    try:
                        subset = fo.getSubset(position=ELEMENT_NODAL)
                        if len(subset.values) == 0:
                            subset = None
                    except:
                        subset = None

                if subset is None:
                    continue

                # 合并容器
                acc_sum, acc_cnt, acc_max = {}, {}, {}

                for v in subset.values:
                    node = v.nodeLabel

                    # 取值
                    if var_choose is not None:
                        key = var_choose.strip().lower()
                        if key == "mises":
                            val = v.mises
                        elif key == "maxprincipal":
                            val = v.maxPrincipal
                        elif key == "minprincipal":
                            val = v.minPrincipal
                        elif key == "tresca":
                            val = v.tresca
                        elif key == "pressure":
                            val = v.press
                        else:
                            # 不认识就 getattr（可能自定义）
                            val = getattr(v, var_choose)
                    else:
                        val = v.data

                    # 聚合
                    if reduce_method == "max":
                        if (node not in acc_max) or (val > acc_max[node]):
                            acc_max[node] = val
                    else:
                        acc_sum[node] = acc_sum.get(node, 0.0) + val
                        acc_cnt[node] = acc_cnt.get(node, 0) + 1

                # 写入 data
                if reduce_method == "max":
                    for node, val in acc_max.items():
                        data.setdefault(node, {})[col] = val
                else:
                    for node in acc_sum:
                        data.setdefault(node, {})[col] = acc_sum[node] / float(acc_cnt[node])

        # ========= 正确排序（按 step 数字 + frame 数字）=========
        def _col_key(c):
            m = re.search(r"Step-(\d+)-frame(\d+)$", c)
            if m:
                return (int(m.group(1)), int(m.group(2)))
            m2 = re.search(r"^(.*)-frame(\d+)$", c)
            if m2:
                return (m2.group(1), int(m2.group(2)))
            return (c, 0)

        cols = sorted(set(cols), key=_col_key)
        nodes = sorted(data.keys())

        # ========= 写 CSV（Python2 用 wb）=========
        with open(out_csv, "wb") as f:
            w = csv.writer(f)
            header = ["Step-Frame"] + ["Node-{}".format(n) for n in nodes]
            w.writerow(header)

            for c in cols:
                row = [c]
                for n in nodes:
                    row.append(data.get(n, {}).get(c, ""))
                w.writerow(row)

        t1 = time.time()
        elapsed = t1 - t0

        print(">>> Export finished:", out_csv)
        print(">>> Frames written:", len(cols))
        print(">>> Nodes written:", len(nodes))
        print(">>> Time cost: {:.2f} s ({:.2f} min)".format(elapsed, elapsed / 60.0))
        return out_csv

    finally:
        odb.close()


# ---------------- 直接运行示例 ----------------
odbpath = r"C:\Users\zx_ec\Documents\ABAQUS\model\Steam_Turbine_Rotor\300MW-V5.odb"

export_nodal_table_csv_transposed_sorted(
    odbpath=odbpath,
    var="S",
    var_choose="Mises",
    step_limit=90,
    frame_stride=1,
    reduce_method="avg"
)

# export_nodal_table_csv_transposed_sorted(
#     odbpath=odbpath,
#     var="PEEQ",
#     var_choose=None,
#     step_limit=90,
#     frame_stride=1,
#     reduce_method="avg"
# )

# export_nodal_table_csv_transposed_sorted(
#     odbpath=odbpath,
#     var="UVARM39",
#     var_choose=None,
#     step_limit=90,
#     frame_stride=1,
#     reduce_method="avg"
# )
