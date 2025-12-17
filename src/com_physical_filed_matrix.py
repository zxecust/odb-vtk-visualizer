import os
import pandas as pd
import re
from typing import List, Tuple, Dict


def parse_step_and_frame(
    filename: str,
    fallback_index: int,
    step_name_to_id: Dict[str, int]
) -> Tuple[int, int, int, str]:
    """
    从文件名中解析 Step 和 Frame。

    支持：
    - Step-1_10.rpt
    - Step-StartUp_1.rpt
    - Step-CreepHold_100.rpt

    返回：
    (step_id, frame_id, fallback_index, step_name)
    """

    match = re.search(r'Step-([^_]+)_(\d+)\.rpt$', filename, re.IGNORECASE)

    if not match:
        print(f"Warning: Cannot parse Step/Frame from {filename}, using fallback order.")
        return (9999, fallback_index, fallback_index, "Unknown")

    step_raw = match.group(1)
    frame_num = int(match.group(2))

    # Step 是数字
    if step_raw.isdigit():
        step_id = int(step_raw)
        step_name = step_raw
    else:
        # Step 是字符串，按出现顺序编号
        if step_raw not in step_name_to_id:
            step_name_to_id[step_raw] = len(step_name_to_id)
        step_id = step_name_to_id[step_raw]
        step_name = step_raw

    return (step_id, frame_num, fallback_index, step_name)


def combine_field_reports(
    folder_path: str,
    output_csv_name: str,
    data_col_name: str,
    num_nodes: int = None
) -> str:
    """
    读取文件夹下的 .rpt 文件，提取物理场数据，
    按 Step → Frame 时序组合成一个 CSV 文件。
    """

    print(f"--- Starting data processing in folder: {folder_path} ---")

    # 1. 收集文件
    file_list = [f for f in os.listdir(folder_path) if f.endswith('.rpt')]

    if not file_list:
        print("Error: No .rpt files found.")
        return ""

    # Step 名到 ID 的映射（用于字符串 Step）
    step_name_to_id: Dict[str, int] = {}

    # 排序（Step → Frame → 原始顺序兜底）
    parsed_info = {
        f: parse_step_and_frame(f, i, step_name_to_id)
        for i, f in enumerate(file_list)
    }

    file_list.sort(key=lambda f: parsed_info[f][:3])

    frames_data: List[pd.DataFrame] = []
    node_labels = []

    # 2. 逐文件处理
    for i, filename in enumerate(file_list):
        file_path = os.path.join(folder_path, filename)

        skip_rows = 0
        data_end_line = None

        # 精确定位数据区域
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

            for line_num, line in enumerate(lines):
                if line.strip() == '---------------------------------':
                    skip_rows = line_num + 1
                    break

            if skip_rows > 0:
                for line_num in range(skip_rows, len(lines)):
                    stripped = lines[line_num].strip()
                    if stripped.startswith('Minimum') or stripped.startswith('Total'):
                        data_end_line = line_num
                        break

        if skip_rows == 0:
            print(f"Warning: Cannot find data start in {filename}, skipped.")
            continue

        nrows_to_read = None
        if data_end_line is not None:
            nrows_to_read = data_end_line - skip_rows
            if nrows_to_read <= 0:
                print(f"Warning: Invalid data rows in {filename}, skipped.")
                continue

        # 读取数据
        try:
            df = pd.read_csv(
                file_path,
                sep=r'\s+',
                skiprows=skip_rows,
                nrows=nrows_to_read,
                header=None,
                names=['Node Label', data_col_name],
                engine='python',
                on_bad_lines='skip'
            )
        except Exception as e:
            print(f"Fatal error reading {filename}: {e}")
            continue

        # 数据清洗
        df = df.dropna(subset=['Node Label', data_col_name])
        df['Node Label'] = pd.to_numeric(df['Node Label'], errors='coerce')
        df[data_col_name] = pd.to_numeric(df[data_col_name], errors='coerce')
        df = df.dropna()
        df['Node Label'] = df['Node Label'].astype(int)
        df = df.set_index('Node Label')

        # 节点一致性检查
        if i == 0:
            node_labels = df.index.tolist()
            if num_nodes and len(node_labels) != num_nodes:
                print(f"Warning: Expected {num_nodes} nodes, got {len(node_labels)}.")
        elif len(df) != len(node_labels):
            print(f"Error: Node count mismatch in {filename}, skipped.")
            continue

        # 构造帧 ID
        step_id, frame_id, _, step_name = parsed_info[filename]
        frame_index_name = f"Step-{step_name}_Frame{frame_id}"

        frame_series = df[data_col_name].rename(frame_index_name)
        frames_data.append(pd.DataFrame(frame_series).T)

        if (i + 1) % 10 == 0 or i == len(file_list) - 1:
            print(f"Processed {i + 1}/{len(file_list)} files.")

    if not frames_data:
        print("Error: No valid frames processed.")
        return ""

    # 3. 拼接
    combined_df = pd.concat(frames_data)

    print(f"Combined data matrix shape: {combined_df.shape[0]} x {combined_df.shape[1]}")

    # 列名统一
    combined_df.columns = [f'Node_{nid}' for nid in node_labels]

    # 4. 保存
    output_path = os.path.join(folder_path, output_csv_name)
    combined_df.to_csv(output_path, index=True, index_label='Frame_ID')

    print(f"--- Data combination finished ---")
    print(f"CSV saved to: {output_path}")

    return output_path


# ------------------------------
# 主程序入口
# ------------------------------
if __name__ == '__main__':

    field_data_folder = (
        # r"C:\Users\zx_ec\Documents\ABAQUS\model\Steam_Turbine_Rotor\ST-01-100-V2\reports\S"
        r"C:\Users\zx_ec\Documents\ABAQUS\model\Engine_Turbine_Disk\M12-4h\reports\S"
    )

    output_file = 'S_Mises.csv' # S_Mises.csv, TEMP.csv, E_Max_Pri.csv
    variable_column = 'S.Mises' # S.Mises, TEMP, Max.Principal

    combine_field_reports(
        folder_path=field_data_folder,
        output_csv_name=output_file,
        data_col_name=variable_column
    )