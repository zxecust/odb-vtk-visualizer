import os
import pandas as pd
import re
from typing import List, Tuple

def combine_field_reports(folder_path: str, output_csv_name: str, data_col_name: str, num_nodes: int = None) -> str:
    """
    读取指定文件夹下的一系列 .rpt 文件，精确识别数值数据区域，忽略文件头和尾部的统计信息，将每帧数据转换为一行，并按照“分析步-帧”的正确时序拼接成一个CSV文件。
    
    :param folder_path: 包含 .rpt 报告文件的文件夹路径。
    :param output_csv_name: 输出 CSV 文件的名称。
    :param data_col_name: 报告文件中物理量列的名称 (例如 'S.Mises')。
    :param num_nodes: 可选，预期的节点总数。
    :return: 输出 CSV 文件的完整路径。
    """
    
    print(f"--- Starting data processing in folder: {folder_path} ---")
    
    # 1. 获取所有待处理的文件列表，并按时序（Step -> Frame）排序
    file_list = [f for f in os.listdir(folder_path) if f.endswith('.rpt')]
    
    def get_step_and_frame_number(filename: str) -> Tuple[int, int]:
        """
        从文件名中提取分析步号和帧号，作为排序键。
        预期格式例如：var_varchoose_Step-1_1.rpt
        """
        # 正则表达式解释:
        # Step- : 匹配字面量 "Step-"
        # (\d+) : 捕获第一个数字（分析步号，Group 1）
        # _     : 匹配下划线
        # (\d+) : 捕获第二个数字（帧号，Group 2）
        # \.rpt$: 匹配文件扩展名结束
        match = re.search(r'Step-(\d+)_(\d+)\.rpt$', filename, re.IGNORECASE)
        
        if match:
            # 返回一个元组：(分析步号, 帧号)。Python 会先比较元组的第一个元素，再比较第二个。
            step_num = int(match.group(1))
            frame_num = int(match.group(2))
            
            return (step_num, frame_num)
        else:
            # 如果不匹配预期格式，返回一个特殊的、较大的元组，将其排在末尾或跳过。
            print(f"Warning: Filename {filename} does not match Step/Frame pattern.")
            # 使用 (-1, -1) 或 (9999, 9999) 确保其在排序中的位置可控。
            return (9999, 9999) 

    # 使用新的排序函数，现在排序是基于 (Step 号, Frame 号) 的双重标准。
    file_list.sort(key=get_step_and_frame_number)

    frames_data: List[pd.DataFrame] = []
    node_labels = [] # 用于记录第一帧的节点标签
    
    # 2. 遍历文件并提取数据
    for i, filename in enumerate(file_list):
        file_path = os.path.join(folder_path, filename)
        
        # --- 精确定位数据区域 ---
        skip_rows = 0 # 数据起始行 (跳过的行数)
        data_end_line = None # 数据结束行 (文件中的行索引)
        
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
            # 查找数据起始行 (列名分隔符的下一行)
            for line_num, line in enumerate(lines):
                if line.strip() == '---------------------------------':
                    skip_rows = line_num + 1
                    break
            
            # 查找数据结束行 (统计信息开始的行)
            if skip_rows > 0:
                for line_num in range(skip_rows, len(lines)):
                    # 识别统计信息（如 'Minimum', 'Total'）作为数据结束标记
                    stripped_line = lines[line_num].strip()
                    if stripped_line.startswith('Minimum') or stripped_line.startswith('Total'):
                        data_end_line = line_num
                        break
            
        if skip_rows == 0:
            print(f"Warning: Could not find data start in {filename}. Skipping.")
            continue
            
        # 计算需要读取的有效数据行数
        nrows_to_read = None
        if data_end_line is not None:
            nrows_to_read = data_end_line - skip_rows
            
        if nrows_to_read is not None and nrows_to_read <= 0:
            print(f"Warning: Calculated zero/negative rows for data in {filename}. Skipping.")
            continue

        # --- 使用 Pandas 读取数据 ---
        try:
            df = pd.read_csv(
                file_path, 
                sep=r'\s+', # 使用一个或多个空白字符作为分隔符
                skiprows=skip_rows,
                nrows=nrows_to_read, # 精确限制读取行数以避开统计信息
                header=None,
                names=['Node Label', data_col_name],
                engine='python',
                on_bad_lines='skip' # 忽略可能导致错误的行
            )
        except Exception as e:
            print(f"Fatal Error parsing {filename}: {e}. Skipping this file.")
            continue
        
        # --- 数据清洗与重构 ---
        df = df.dropna(subset=['Node Label', data_col_name])
        df[data_col_name] = pd.to_numeric(df[data_col_name], errors='coerce')
        df['Node Label'] = pd.to_numeric(df['Node Label'], errors='coerce')
        df = df.dropna()
        df['Node Label'] = df['Node Label'].astype(int)
        df = df.set_index('Node Label')
        
        # 检查所有帧的节点数是否一致
        if i == 0:
            node_labels = df.index.tolist()
            if num_nodes and len(node_labels) != num_nodes:
                print(f"Warning: First file has {len(node_labels)} nodes, expected {num_nodes}.")
        elif len(df) != len(node_labels):
            print(f"Error: Frame {i} ({filename}) has {len(df)} nodes, expected {len(node_labels)}. Skipping this frame.")
            continue

        # 构造更明确的帧 ID: 'StepX_FrameY'
        step_frame = get_step_and_frame_number(filename)
        # 如果解析失败 (返回 (9999, 9999))，则跳过
        if step_frame == (9999, 9999):
            continue 

        # 命名当前帧的 Series。例如：'Frame_1_1'
        frame_id_name = f'Step{step_frame[0]}_Frame{step_frame[1]}'
        current_frame_series = df[data_col_name].rename(frame_id_name)
        
        # 转化为 DataFrame，准备拼接
        frame_row = pd.DataFrame(current_frame_series).T
        frames_data.append(frame_row)
        
        if (i + 1) % 10 == 0:
            print(f"Processed {i+1}/{len(file_list)} files...")

    if not frames_data:
        print("Error: No valid data frames were processed.")
        return ""
        
    # 4. 拼接所有帧数据
    combined_df = pd.concat(frames_data)

    # 打印输出 CSV 矩阵的形状
    rows, cols = combined_df.shape 
    print(f"Combined data matrix shape: {rows} rows x {cols} columns.")

    # 5. 格式化和保存
    combined_df.columns = [f'Node_{label}' for label in node_labels] 
    
    output_path = os.path.join(folder_path, output_csv_name)
    # 行索引现在是 'StepX_FrameY'，完美代表了时序。
    combined_df.to_csv(output_path, index=True, index_label='Frame_ID') 

    print(f"--- Data combination finished. ---")
    print(f"CSV saved to: {output_path}")
    return output_path

# --- 主程序入口 ---
if __name__ == '__main__':
    # 1. 定义输入文件路径
    # field_data_folder = 'C:/Users/zx_ec/Documents/ABAQUS/model/Steam_Turbine_Rotor/reports/300MW-V5/S' 
    # field_data_folder = 'C:/Users/zx_ec/Documents/ABAQUS/model/Steam_Turbine_Rotor/reports/300MW-V5/TEMP' 
    # field_data_folder = 'C:/Users/zx_ec/Documents/ABAQUS/model/Aero-engine_Turbine_Disk/reports/M12-4h/S' 
    # field_data_folder = 'C:/Users/zx_ec/Documents/ABAQUS/model/Aero-engine_Turbine_Disk/reports/M12-4h/TEMP' 
    field_data_folder = 'C:/Users/zx_ec/Documents/ABAQUS/model/Aero-engine_Turbine_Disk/reports/M12-4h/E' 
    
    # 2. 定义输出文件名和报告文件中的变量列名
    # output_file, variable_column = 'S_Mises.csv', 'S.Mises'
    # output_file, variable_column = 'TEMP.csv', 'TEMP' 
    output_file, variable_column = 'E.csv', 'Max.Principal' 
    
    # 3. 执行函数
    combine_field_reports(field_data_folder, output_file, variable_column)