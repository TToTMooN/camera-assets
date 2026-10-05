# KIWI integration

这些模型可以直接用于 KIWI 的相机安装布局、载荷比较、碰撞和遮挡检查，以及
采集设备选型。相机本体、GO Action Pod 和 GO 2 Charging Case 分开建模；
ONE R / ONE RS 按完整的镜头、核心和电池配置建模。
RealSense D435i／D455、ZED 2i 和原版 OAK-D 用于深度／双目硬件的安装布局；
对应的驱动、标定和深度输出需要由 KIWI 集成另行提供。

```bash
python scripts/viewer.py --list
python scripts/viewer.py --model go3s
python scripts/build_assets.py --model all
python scripts/validate.py --model all
python scripts/sensor_manifest.py --model all --check
pip install -r requirements-sim.txt
python -m unittest discover -s tests -v
```

先在 viewer 中比较外形和碰撞包络，再将对应 `models/<id>/` 文件夹复制到
KIWI 项目。URDF 位于 `urdf/insta360_<id>.urdf`；MuJoCo 文件位于
`mjcf/insta360_<id>.xml`。保持相对路径和 meshes 文件夹结构。

URDF 的长度单位为米，质量单位为千克。坐标轴为 X 深度、Y 宽度、Z 高度，
底部安装参考点是模型原点。这个参考点和几何镜头表面帧可用于初步放置相机，
实际支架接触面、安装孔位置和相机到机器人之间的变换需按硬件确认。
所有镜头表面参考帧的局部 +Z 沿表面朝外；这仍不表示其原点已标定为光学中心。

`catalog/cameras.json` 中的 `status: ready` 表示几何资产已生成，可进入安装和
仿真布局流程。它不表示 KIWI 已完成驱动、同步、录制、标定或真实设备测试。
X5 保留原有详细外观，其余 27 个配置已按厂商图片与手册重做各自结构、镜头、
屏幕、控制件、接缝和材质。GLB 提供微表面法线与 PBR 材质；URDF／MJCF
保留实体细节和颜色，但具体渲染器的玻璃反光与材质表现会有所不同。

这些资产不提供相机内参、畸变、双镜头拼接、光学中心、曝光、滚动快门或
RGB-D 模型。镜头表面帧没有标定为 optical frame。用于视觉或 real-to-sim
评估时，需另行添加实测标定和相应的成像模型。

每个模型的 `config/sensors.json` 已列出独立成像单元、几何候选映射、逐模式
参数、光学外参及模拟器状态。未知值保持 `null`；RealSense 投射器单独记为
发射器，360 全景和深度是派生输出。模板生成只创建缺失文件，不覆盖既有标定。
`--check --require-calibrated` 会拒绝未标定的成像设备；配件没有此要求。
详细清单、坐标/单位转换和 Isaac／MuJoCo／Gazebo 接入要求见
[仿真接入与传感器参数](SIMULATION.md)。

质量来自官方对应配置，质心和惯量来自简化几何估计。GO 配件质量不含相机；
配件仅表示屏幕折叠或盒体闭合状态，不提供插入相机后的装配、铰链运动或连接
机构。ONE R / ONE RS 模块也保持固定。载荷和动力学敏感的实验应替换为实测参数。

MuJoCo 默认导出固定安装的本体，`--free` 可用于独立自由物体。网格引用会随
整个模型目录一起搬迁。测试覆盖加载、惯量、包络、参考帧以及自由物体落地后的
接触和动能变化；这些是数值烟测，不代表真实硬件的动力学参数已经验证。
`build_assets.py` 每次构建会刷新 mounted MJCF；若需要自由根关节，请在构建
后再运行 `export_mjcf.py --free`。

各字段的官方来源、估计值和硬件版本限制见 [来源说明](SOURCES.md) 和
[相机目录](../catalog/cameras.json)。
