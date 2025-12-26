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
    var_choose=None,        # 张量不变量：'Mises'/'MaxPrincipal'...；标量传 None
    out_csv=None,
    instance_name=None,      # 不填默认第一个 instance
    step_limit=None,         # 只导前 N 个非 Initial step；不填全导
    frame_stride=1,          # 每隔多少帧导一次
    reduce_method="avg"      # ELEMENT_NODAL 同一节点多值合并：'avg' 或 'max'
):
    """
    输出 CSV（横纵互换 + 正确排序）：
        行：Step-Frame
        列：NodeLabel
        第 1 列为 Step-Frame 标签
    并打印导出耗时。
    """

    print("--- Starting ODB data export ---")
    print("ODB Path:", odbpath)
    print("Variable (Field Output):", var)
    if var_choose:
        print("Invariant/Component:", var_choose)
    print("Reduction Method (for ELEMENT_NODAL):", reduce_method)
    if step_limit:
        print("Step Limit (excluding Initial):", step_limit)
    print("Frame Stride:", frame_stride)
    
    t0 = time.time()

    try:
        odb = openOdb(odbpath, readOnly=True)
        print("Opened ODB:", odb.name)
    except Exception as e:
        print("!!! Error opening ODB:", e)
        return

    try:
        asm = odb.rootAssembly
        
        # 确定 Instance
        if instance_name and instance_name in asm.instances:
            inst = asm.instances[instance_name]
        else:
            # 默认第一个 instance
            inst_list = asm.instances.values()
            if inst_list:
                inst = inst_list[0]
                instance_name = inst.name
            else:
                print("!!! No instances found in ODB.")
                odb.close()
                return

        print("Target Instance:", instance_name)

        # 输出路径
        if out_csv is None:
            odb_dir = os.path.dirname(odbpath)
            odb_name = os.path.splitext(os.path.basename(odbpath))[0]
            out_dir = os.path.join(odb_dir, "reports_csv", odb_name)
            if not os.path.exists(out_dir):
                os.makedirs(out_dir)
                print("Created output directory:", out_dir)
            fname = var if var_choose is None else "{}_{}".format(var, var_choose)
            out_csv = os.path.join(out_dir, fname + ".csv")
        
        print("Output CSV Path:", out_csv)

        data = {}   # data[node][col] = value
        cols = []   # Step-Frame 列名

        # Step 遍历
        all_steps = [k for k in odb.steps.keys() if k != "Initial"]
        step_names = all_steps
        if step_limit is not None:
            step_names = all_steps[:int(step_limit)]
        
        print("Total non-Initial Steps found:", len(all_steps))
        print("Steps to process:", len(step_names))
        
        processed_frames_count = 0

        for step_name in step_names:
            step = odb.steps[step_name]
            frames = step.frames
            print("--- Processing Step '{}' with {} frames...".format(step_name, len(frames)))

            # 帧遍历
            frame_indices_to_process = range(0, len(frames), max(1, int(frame_stride)))
            
            for frame_id in frame_indices_to_process:
                frame = frames[frame_id]

                col = "{}-frame{}".format(step_name, frame_id)
                cols.append(col)

                if var not in frame.fieldOutputs:
                    print("!!! Warning: Field Output '{}' not found in {}-frame{}".format(var, step_name, frame_id))
                    continue

                fo = frame.fieldOutputs[var]
                
                # 尝试获取 NODAL 或 ELEMENT_NODAL 子集
                subset = None
                
                try:
                    # 1) NODAL
                    subset = fo.getSubset(position=NODAL)
                    if len(subset.values) == 0:
                        subset = None
                    else:
                        position_type = "NODAL"
                except:
                    subset = None

                if subset is None:
                    try:
                        # 2) ELEMENT_NODAL
                        subset = fo.getSubset(position=ELEMENT_NODAL)
                        if len(subset.values) == 0:
                            subset = None
                        else:
                            position_type = "ELEMENT_NODAL"
                    except:
                        subset = None

                if subset is None:
                    print("!!! Warning: No valid NODAL or ELEMENT_NODAL data found for {} in {}-frame{}".format(var, step_name, frame_id))
                    continue

                # print("Processing {}-frame{} (Data Position: {})".format(step_name, frame_id, position_type))
                
                # 合并容器
                acc_sum, acc_cnt, acc_max = {}, {}, {}

                for v in subset.values:
                    node = v.nodeLabel

                    # 取值
                    if var_choose is not None:
                        key = var_choose.strip().lower()
                        # ... (省略原有的取值逻辑)
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
                    if position_type == "ELEMENT_NODAL":
                        if reduce_method == "max":
                            if (node not in acc_max) or (val > acc_max[node]):
                                acc_max[node] = val
                        else:
                            # 默认 avg
                            acc_sum[node] = acc_sum.get(node, 0.0) + val
                            acc_cnt[node] = acc_cnt.get(node, 0) + 1
                    else:
                        # NODAL 不需要聚合
                        acc_max[node] = val 


                # 写入 data
                if position_type == "ELEMENT_NODAL" and reduce_method == "avg":
                    for node in acc_sum:
                        data.setdefault(node, {})[col] = acc_sum[node] / float(acc_cnt[node])
                else:
                    # 包含 ELEMENT_NODAL/max 和 NODAL
                    for node, val in acc_max.items():
                        data.setdefault(node, {})[col] = val

                processed_frames_count += 1
        
        print("--- Data extraction complete. Total frames extracted:", processed_frames_count)

        # ========= 正确排序（按 step 数字 + frame 数字）=========
        def _col_key(c):
            # ... (省略原有的排序逻辑)
            m = re.search(r"Step-(\d+)-frame(\d+)$", c)
            if m:
                return (int(m.group(1)), int(m.group(2)))
            m2 = re.search(r"^(.*)-frame(\d+)$", c)
            if m2:
                return (m2.group(1), int(m2.group(2)))
            return (c, 0)

        cols = sorted(set(cols), key=_col_key)
        nodes = sorted(data.keys())
        
        print("Total unique frames to write (after sorting):", len(cols))
        print("Total unique nodes to write:", len(nodes))

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

        print("\n==============================================")
        print(">>> Export finished: **{}**".format(out_csv))
        print(">>> Frames written:", len(cols))
        print(">>> Nodes written:", len(nodes))
        print(">>> Time cost: **{:.2f} s ({:.2f} min)**".format(elapsed, elapsed / 60.0))
        print("==============================================")
        return out_csv

    except Exception as e:
        print("\n!!! An unexpected error occurred during processing:")
        print("!!! Error detail:", e)
        return

    finally:
        try:
            odb.close()
            print("Closed ODB.")
        except:
            pass


# ---------------- 直接运行示例 ----------------
# odbpath = r"C:\Users\zx_ec\Documents\ABAQUS\model\Steam_Turbine_Rotor\ST-01-100-V1\ST-01-100-V1.odb"
odbpath = r"C:\Users\zx_ec\Documents\ABAQUS\model\Engine_Turbine_Disk\M12-4h\M12-4h.odb"

export_nodal_table_csv_transposed_sorted(
    odbpath=odbpath,
    var="S",
    var_choose="Mises",
    step_limit=90,
    frame_stride=1,
    reduce_method="avg"
)

print("\n" + "="*50 + "\n") # 用于分隔两次调用的输出

export_nodal_table_csv_transposed_sorted(
    odbpath=odbpath,
    var="TEMP",
    var_choose=None,
    step_limit=90,
    frame_stride=1,
    reduce_method="avg"
)