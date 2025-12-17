#-*- coding: UTF-8 -*- 

from abaqus import *
from abaqusConstants import *
from viewerModules import *
from driverUtils import executeOnCaeStartup

import os
import csv

# 获取节点的值
def odb_values(odbpath,step_num,var,var_choose):   

    """
    根据输入的ODB文件路径、分析步总数、物理场变量名称及选项，导出对应的节点场数据并保存为文本文件。
    
    :param odbpath: 待分析的ODB文件路径
    :param step_num: 分析步总数
    :param var: 待导出的物理场变量名称
    :param var_choose: 物理场变量的选项（如应力的'Mises'等），若无选项则传入None
    """

    # 程序开始运行提示
    if var_choose:
        print(">>> Program started: Extracting data for variable '{}/{}'...".format(var, var_choose))
    else:
        print(">>> Program started: Extracting data for variable '{}'...".format(var))

    # 设置ODB文件路径并在Visualization模块中打开
    odb = session.openOdb(odbpath) # 打开ODB文件（确保路径正确）

    session.viewports['Viewport: 1'].setValues(displayedObject=odb) # 在Visualization模块中打开ODB文件

    # 设置输出文件夹路径
    # ABAQUS中使用Python脚本默认的输出文件夹路径为当前工作文件夹，此处在输出场数据文件前
    # 先将当前工作文件夹切换到指定的输出文件夹路径下，便于管理输出文件

    original_dir = os.getcwd() # 获取当前工作文件夹路径
    print("Current working directory: {}".format(original_dir)) 

    odb_dir = os.path.dirname(odbpath) # 获取ODB文件所在文件夹路径
    target_dir = os.path.join(odb_dir, "reports", var) # 定义物理场数据输出文件夹路径
    
    if not os.path.exists(target_dir): # 若输出文件夹不存在可创建
        os.makedirs(target_dir)
    
    os.chdir(target_dir)   # 切换到输出文件夹
    print("Switched working directory to: {}\n".format(os.getcwd()))

    # 遍历所有分析步与帧，导出指定物理场数据
    step_names = list(odb.steps.keys()) # 获取所有分析步的名称列表
    print("Found steps in ODB file: {}\n".format(step_names))

    step_index = 0 # 分析步索引
    
    # 遍历所有分析步（排除初始步 'Initial'，按需选择）
    for step_name in step_names:
    
        if step_name == 'Initial':
            continue  # 初始步通常没有帧数据
        
        current_step = odb.steps[step_name] # 获取当前分析步对象
        frames = len(current_step.frames) # 获取当前步的帧数
        
        print("Processing step: '{}'. It contains {} frames.".format(step_name, frames))
        
        # 遍历所有帧
        for frame_num in range(frames):

            # 物理场数据为张量的情况
            if var_choose != None:
                filename = str(var) + '_' + str(var_choose)+ '_' + str(step_name)+ '_' + str(frame_num)+  '.rpt'
                variable_tuple = ((var, INTEGRATION_POINT, ((INVARIANT, var_choose), )),)

            # 物理场数据为标量的情况
            else:
                filename = str(var) + '_' + str(step_name)+ '_' + str(frame_num)+  '.rpt'
                variable_tuple = ((var, INTEGRATION_POINT), )
            
            # 写入场变量报告（按需调整参数）
            session.writeFieldReport(
                fileName=filename,
                append=OFF,  # 若需追加数据可设为ON
                sortItem='Node Label',  # 节点数据
                odb=odb,
                step=step_index,
                frame=frame_num,
                outputPosition=NODAL, # 节点位置
                variable=variable_tuple
            )

        # 增加步索引
        step_index = step_index + 1
        # 达到指定步数则退出
        if step_index == step_num:
            break
    
    # 关闭ODB文件
    odb.close() 

    # 恢复原工作文件夹路径
    os.chdir(original_dir)   # 切换到原工作文件夹，便于后续ABAQUS操作
    print("Restored working directory to: {}\n".format(os.getcwd()))      

    # 程序运行结束提示及输出路径
    if var_choose:
        print(">>> Program finished: Data for variable '{}/{}' has been saved to path: {}".format(var, var_choose, target_dir))
    else:
        print(">>> Program finished: Data for variable '{}' has been saved to path: {}".format(var, target_dir))
    print("- " * 80) # 打印分割线，分隔两次函数调用

# 主程序入口
# odbpath = 'C:/Users/zx_ec/Documents/ABAQUS/model/Steam_Turbine_Rotor/ST-01-100-V2/ST-01-100-V2.odb'  # 该模型分析步数为1
odbpath = 'C:/Users/zx_ec/Documents/ABAQUS/model/Engine_Turbine_Disk/M12-4h/M12-4h.odb'  # 该模型分析步数为3
step_num = 3 # 分析步总数，此处的数值和ABAQUS中Step数量应该一致

# 定义需要导出的物理场变量及其选项的列表
export_tasks = [
    ('TEMP', None), # 导出温度场数据 (标量)
    ('S', 'Mises'), # 导出应力场数据（张量）
    ('E', 'Max. Principal') # 导出最大主应变数据 (张量）
]

# 遍历任务列表，依次执行导出操作
for var, var_choose in export_tasks:
    odb_values(odbpath, step_num, var, var_choose)