# odb-vtk-visualizer

本项目基于pyqt和vtk实现通过读取ABAQUS输入文件（.inp）和物理场文件（.csv）可视化物理场云图。

## 项目结构

```bash
vtk-visualizer/
├── data/              # 物理场数据（.csv）
├── model/             # 有限元模型（.inp）
├── script/            # ABAQUS python脚本
├── src/               # 程序源代码
├── pic/               # 输出图像
└── README.md
```

## 环境依赖

python版本：3.12.9

请确保安装以下模块：

```bash
pip install -r requirements.txt
```

## 使用方法

### 数据准备

启动ABAQUS CAE，选择File-Run Script，选中`/script/odb-output-csv.py`或`/script/odb-output-rpt.py`并运行（脚本文件中的`odbpath`、`var`、`varchoose`三个变量需要设置正确）。

1. 若运行`/script/odb-output-csv.py`会将所选模型的`.odb`文件的数据导出为`.csv`文件，文件第一行为节点编号，第一列为帧索引，其余部分为节点数据；

2. 若运行`/script/odb-output-rpt.py`会将所选模型的`.odb`文件的数据导出到相应文件夹，每一帧数据保存为一个`.rpt`文件，此时需要再次运行`/src/com_physical_filed_matrix`（文件中的`field_data_folder`、`output_file`、`variable_column`三个变量需要设置正确）将所选文件夹下所有的`.rpt`文件合成为`.csv`文件，文件第一行为节点编号，第一列为帧索引，其余部分为节点数据。

### 软件运行

运行`/src/vtk_visualizer.py`，在主界面依次选择“加载文件-加载INP文件”和“加载文件-加载CSV文件”，即可显示物理场云图。可以通过滑块手动选择播放帧或循环播放物理场云图演变过程。

![UI界面](pic\ui.png)
