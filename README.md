# odb-vtk-visualizer

基于 PyQt5 + VTK 的 Abaqus 物理场可视化工具。通过读取 Abaqus 输入文件（`.inp`）以及导出的物理场数据（`.csv`），实现物理场云图显示和动画播放。

## 项目结构

```text
odb-vtk-visualizer/
├─ assets/                        # 资源文件
├─ script/                        # Abaqus/ODB 数据导出脚本
├─ src/                           # 可视化程序
├─ requirements.txt
└─ README.md
```

## 环境依赖

- Python 3.x
- 安装依赖：

```bash
pip install -r requirements.txt
```

## 使用方法

### 数据准备

在 Abaqus/CAE 中执行脚本（File -> Run Script）：

- `script/odb_output_csv.py`：直接从 `.odb` 导出 `.csv`。
- `script/odb_output_rpt.py`：导出每一帧 `.rpt`，再用 `script/com_physical_field_matrix.py` 合并为 `.csv`。

脚本里的 `odbpath` / `var` / `var_choose` 等参数需要按实际模型配置。

### 运行可视化

- 单视窗：`python src/vtk_view.py`
  - 按界面提示加载 `.inp` 和 `.csv`。
- 双视窗：`python src/vtk_view_dual.py`
  - 依次加载 `.inp`、FOM `.csv`、ROM `.csv`。

软件运行效果如下图所示：

  ![软件界面2](/assets/example2.png)
