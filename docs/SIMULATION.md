# 仿真接入与传感器参数

本库的相机几何可用于安装布局、碰撞、遮挡和载荷比较。URDF 提供外观、碰撞、
名义质量、估计惯量及固定参考帧；MJCF 保留对应几何和参考 sites。生成这些文件
不会自动创建能输出图像的相机。真实设备的成像标定、全景拼接、深度算法、时间
同步和模拟器传感器配置需要另行提供。

`catalog/cameras.json` 的 `status: ready` 描述几何资产；每个模型的
`config/sensors.json` 描述传感器参数。两者状态分别记录，不能互相替代。
成像设备的初始传感器状态为 `uncalibrated`，配件为 `not_applicable`。
模拟器是否完成接入和验证由 `backends` 记录。

## 当前已有与待补内容

| 内容 | 当前已有 | 接入时仍需确认 |
| --- | --- | --- |
| 机械几何 | 外观网格、碰撞包络、厂商名义尺寸 | 实物安装面、支架、线缆与插头所需空间 |
| 物理参数 | 名义质量、简化几何估计的质心和惯量 | 实测质量分布、支架参数及接触设置 |
| 本体参考 | 底部安装原点、URDF 固定帧、MJCF sites | 相机到机器人安装外参 |
| 镜头几何 | 镜头表面位置及方向参考 | 光学中心位置、实际成像单元的语义对应 |
| 光学与模式 | 未提供标定数字 | 内参、畸变、分辨率、裁切和帧率 |
| 传感器输出 | 未定义成像相机与输出流 | 图像、全景、深度、时间戳及同步配置 |
| 模拟器 | 可导入的几何描述与 MuJoCo 几何烟测 | 相机节点、渲染、发布及成像验证 |

`*_lens_surface` 是几何表面参考，不能直接认定为光学中心。现有名称中的
`left/right` 是模型命名约定，映射到厂商 SDK 的左右成像单元前必须核对。
RealSense 的 `*_projector_lens_surface` 表示投射器，属于 `emitters`，
不能作为相机生成图像流。外形相似的镜头、投射器和其他窗口也不能只凭网格
名称确定传感器语义。

## 参数文件与工作流程

传感器模板位于 `models/<id>/config/sensors.json`；结构定义位于
[sensor_manifest.schema.json](../catalog/sensor_manifest.schema.json)。模板包含：

| 字段 | 用途 |
| --- | --- |
| `schema_version`、`model_id` | 文件格式版本及对应几何模型 |
| `sensor_class`、`status` | 单目、双目、全景等分类及标定状态 |
| `geometry_frames` | 已有几何参考帧，保留其原始名称和估计性质 |
| `imagers` | 实际成像单元、待确认的几何映射与逐模式参数 |
| `emitters` | 投射器等发射单元，与成像单元分开 |
| `derived_outputs` | 全景、深度等由多个输入或算法产生的输出 |
| `calibration` | 标定出处、设备与模式信息 |
| `backends` | 模拟器版本、接入配置和验证状态 |

创建尚未存在的模板：

```bash
python scripts/sensor_manifest.py --model all --write-template
```

该命令只创建缺失文件，保留已经存在的模板和标定数据。也可把 `all` 换成
`go3s`、`x6`、`realsense_d435i` 等模型 ID。

检查文件结构和模型引用：

```bash
python scripts/sensor_manifest.py --model all --check
```

要求成像设备具备必要标定字段：

```bash
python scripts/sensor_manifest.py --model all --check --require-calibrated
```

初始模板含有未标定字段，因此最后一条命令预期报告缺项并失败。配件没有成像
标定要求。结构检查通过不证明参数数值正确，也不证明相机已在模拟器运行；
必需字段齐全后仍要完成标定质量检查和各 backend 的实际验证。

未知值保留 `null`。`null` 不能解释成零畸变、零外参、默认帧率或厂商标准模式。
不要用示例程序中的内参、网格镜头直径、宣传 FOV 或其他同型号设备的标定结果
补齐实物标定。需要先选择具体设备、拍摄模式和期望输出，再填对应参数。

## 坐标、单位和安装外参

几何本体使用 X 深度、Y 宽度、Z 高度；URDF/MJCF 长度为米、质量为千克。
目录中的机械尺寸为毫米。GLB 为 Y-up，viewer 的显示转换不能替代模拟器导入
时的坐标检查。

| 参考系 | 轴约定 |
| --- | --- |
| 本库机械本体 | X 深度、Y 宽度、Z 高度 |
| ROS optical | +X 图像右、+Y 图像下、+Z 向前 |
| USD / MuJoCo Camera | +X 图像右、+Y 图像上、−Z 向前 |

ROS optical 原点应为光学中心，图像消息的 frame 与采集时间戳也应对应真实
成像单元。[ROS CameraInfo 定义](https://github.com/ros2/common_interfaces/blob/rolling/sensor_msgs/msg/CameraInfo.msg)

把外参方向写清楚。例如 `T_body_optical` 表示把 optical 坐标转换为本体坐标：

```text
p_body = R_body_optical · p_optical + t_body_optical
```

记录平移单位、旋转表示和四元数分量顺序。若使用 `quaternion_xyzw`，接口要求
`wxyz` 时需要显式重排。ROS optical 与 USD/MuJoCo Camera 的方向转换为
`diag(1, -1, -1)`；这是同一光学中心下的轴变换，不会补上未知的光学中心位置。
不要原样复制几何表面帧的旋转作为 Camera 节点旋转。
[OpenUSD Camera 坐标](https://openusd.org/dev/api/class_usd_geom_camera.html)、
[MuJoCo Camera 坐标](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-camera)

安装到机器人还需独立的 `T_robot_body`，与设备内部的 `T_body_optical` 分开。
导入器合并固定关节后，原来的参考帧名称或路径可能改变，接入层须检查导入后的
实际节点与变换。

USD 相机的 focal length 和 filmback/aperture 使用**十分之一 stage unit**；
clip range 等使用 scene units。厘米 stage 下前一组值等效为毫米，米制 stage
下不能直接照抄毫米数。明确 `metersPerUnit`、up axis，并统一转换所有相关值。
[OpenUSD 相机单位](https://openusd.org/dev/api/class_usd_geom_camera.html#details)

## 按设备与成像模式准备标定

单个机型可以有多个模式。每个用于实验的模式应记录分辨率、帧率、裁切/缩放、
旋转、raw 或 rectified 输出、软件去畸变、稳定和变焦设置。分辨率或裁切改变
后，原来的像素内参不能直接沿用。宣传页的最大分辨率和最大帧率也不代表二者
可以在同一个模式同时使用。

每个成像单元至少需要对应模式的 `fx`、`fy`、`cx`、`cy`，明确内参矩阵排列；
畸变需保存模型名称、系数顺序和适用图像状态。针孔的径向/切向系数与鱼眼系数
不能混用。OpenCV 标定接口明确区分 pinhole 与 fisheye 模型。
[OpenCV 标定接口](https://docs.opencv.org/doc/doxygen/html/d4/d93/group__calib.html)

标定出处应包含设备序列号、硬件/镜头版本、固件/SDK 版本、模式、日期、工具、
原始文件路径或哈希，以及重投影误差等质量记录。实物安装后的相机到机器人
外参需另存测量依据。标称参数、实物标定和人为选择的仿真参数应能区分。

### 普通单目与广角相机

GO、Ace 和单镜头 ONE R/RS 配置需要一个成像单元的内外参。广角不意味着一定
使用某种鱼眼模型，应以实际 raw/处理后输出与标定结果确定。还需按实验需求
记录曝光时间、滚动/全局快门、行读出方向和时间、白平衡、响应曲线、噪声及
压缩。自动曝光、电子稳定和动态裁切会影响真实图像与固定仿真相机的对应。

初步几何投影实验可以明确选择理想成像模型；需要匹配真实图像时，进一步加入
实测快门、曝光和图像处理参数。理想模型的选取不能被标为实物标定。

### 360° 全景与双鱼眼

X 系列及双镜头 ONE R/RS 配置应区分两个成像输入与最终全景输出。分别准备
两个镜头的鱼眼投影/畸变、光学中心与完整相对外参；再记录覆盖区域、重叠区、
拼接映射、接缝/融合、曝光匹配、全景朝向、稳定和裁切模式。

全景输出需指定投影（例如等距柱状）、分辨率、经纬方向、零经线、接缝位置、
旋转约定及所用拼接算法版本。它属于 `derived_outputs`，不能用一个普通针孔
相机和一个 FOV 数字描述。若选择从理想 cube map 生成全景，需明确其与实物
双鱼眼/厂商拼接的差别；这只是可选集成方案，本库没有实现该处理链。

### 双目与 RGB-D

ZED 2i 的左右 RGB、OAK-D 的左右单色及 RGB、RealSense 的左右红外及 RGB
应各有独立模式与标定。双目还需要完整相对旋转/平移、时间同步、整流矩阵与
整流后投影参数。标称基线或机械镜头间距不能替代这些数据。

ZED SDK 区分 raw 与 rectified 标定；两种参数对应不同图像，启动时的
self-calibration 也可能更新结果。保存实际用于采集的那组参数和设置。
[ZED 标定与模式说明](https://www.stereolabs.com/docs/development/zed-sdk/modules/camera/camera-calibration)

深度是派生输出，还需逐项确定：

- 输入成像单元和参考 optical frame。
- `z-depth`（到图像平面的轴向距离）、`radial range`（到光学中心的距离）或
  disparity（视差）的语义；这三者不能互换。
- 像素编码、量化尺度、单位、无效像素/超量程值和有效范围。
- 输出是否已注册到 RGB；注册后的分辨率、内参和 frame 应对应目标图像。
- 匹配/滤波/孔洞处理、置信度、遮挡、材质及光照相关失效、噪声和延迟模型。
- 多流同步方式、时间偏移、采集时间戳及深度算法/SDK 版本。

RealSense Z16 为设备尺度的 16 位整数，单位需从设备读取；SDK 文档还说明了
无效值和深度到颜色的转换。这些语义应保留在导出的数据中。
[RealSense SDK 投影、外参与深度格式](https://github.com/realsenseai/librealsense/wiki/Projection-in-RealSense-SDK-2.0)

真实 D435i/D455、ZED 和 OAK 的深度经过设备或 SDK 的处理。渲染器直接输出的
理想深度只能作为明确标记的基准；要评价真实深度感知，需要匹配处理链与失效
行为。RealSense 投射器若要模拟主动立体视觉，也需独立的投射、光谱和材料
响应模型，不能简单替换为普通 RGB 灯。

若同时使用设备 IMU，还需独立的 IMU 外参、频率、时间偏移、单位、轴方向、
偏置和噪声参数；相机外观文件不提供这些数据。

## 模拟器接入要求

### Isaac Sim：固定具体版本

版本信息核对于 2026-10-04。官方 [6.0.0 下载页](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/installation/download.html)
列出 2026 年 6 月发布的 6.0.0；[发布说明](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/overview/release_notes.html)
同时保留历史的 “6.0.0 Early Developer Release” 段落。因此不能把所有 6.0
页面都理解为早期开发版，也不能只凭 `latest` 路径判断用户安装的版本。
5.x 的具体已发布版本可参考 [5.1.0 下载记录](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/installation/download.html)
（2025 年 10 月）；[5.1.0 文档首页](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/index.html)
目前标记该版本不再支持。这里不把 5.1.0 称为当前受支持的稳定版。

5.1 的 [Camera 接口](https://docs.isaacsim.omniverse.nvidia.com/5.1.0/sensors/isaacsim_sensors_camera.html)
与 6.0 的 [RtxCamera / CameraSensor 接口](https://docs.isaacsim.omniverse.nvidia.com/6.0.0/sensors/isaacsim_sensors_camera.html)
不同。6.0 文档将旧 `isaacsim.sensors.camera` 扩展标为 deprecated，并使用
`isaacsim.sensors.experimental.rtx`。接入层应记录完整应用版本与扩展版本，按
对应版本创建相机，而不是混用两代示例。

Isaac 接入需完成以下工作：

1. 将机械资产导入 USD，核对网格、材质、碰撞、质量、单位与参考变换。
2. 在确认的光学中心创建 Camera prim，转换 optical 坐标和内参/畸变。
3. 为指定分辨率建立 render product，配置所需图像/深度 annotator 与采样率。
4. 明确理想深度或所选深度模拟管线；全景另接投影/拼接处理。
5. 配置输出、ROS frame/topic、模拟时钟、时间戳和同步，验证实际数据。

URDF 导入后的传感器设置仍需添加；几何导入成功不验证成像。
[官方 URDF 导入流程](https://docs.isaacsim.omniverse.nvidia.com/latest/importer_exporter/import_urdf.html)
本文未提供未经运行验证的 Isaac 集成脚本，也未将内置传感器或其示例参数
声明为本库某一实物的标定结果。

### MuJoCo

现有 MJCF 的 sites 是几何参考。成像接入需另加 `<camera>`，指定光学中心 pose
及相机内参，运行时设置实际 render context 的尺寸与采样节奏。相机节点的
`resolution` 元数据不能替代运行时渲染尺寸。[MJCF Camera 规范](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-camera)

针孔模型可按目标 MuJoCo 版本映射 FOV 或焦距/主点/传感器尺寸。原生 MJCF
投影为 perspective/orthographic；鱼眼、镜头畸变、全景拼接以及具体设备深度
处理链需要额外实现并验证。读取深度时还需核对所用 API 返回的是轴向深度、
径向距离还是需要转换的渲染缓冲数据。

本库固定安装和自由物体的加载/接触烟测只验证几何和物理数值一致性，不验证
图像、标定或真实设备动力学。

### Gazebo / SDFormat

需要添加 SDF sensor/camera 及目标 Gazebo 版本的传感器系统，配置 pose、
更新率、图像宽高/格式、剪裁、内参/投影、畸变、输出 topic 和 camera info。
双目和 RGB-D 的多流、注册与算法也需独立配置。SDF 1.12 将普通相机内参与
宽角投影区分；不能假定所有后端支持同一套畸变模型和参数。
[SDFormat 1.12 sensor/camera 规范](https://sdformat.org/spec/1.12/sensor/)

导入本库 URDF 不会自动创建这些 SDF 传感器。记录 Gazebo、gz-sensors、
渲染器及 bridge 的实际版本，再检查图像和 CameraInfo 是否一致。

## 接入验证与 real-to-sim 边界

完成一个选定模式后，先用已知位置的目标检查朝向、像素投影和重投影误差，再
检查左右语义、整流、RGB-D 注册、深度单位及边缘遮挡。验证采集频率、时间戳
和多流同步，并将模拟器、配置版本与结果记录到 `backends`。参数文件通过
结构或完整性检查不等于这些实验已经通过。

模型的表面材质用于外观表现。模拟器对 PBR、法线、玻璃和颜色的支持可能不同；
这些材质没有经过真实光谱/反射率或红外响应测量。曝光、光照、噪声和 ISP
需要另行匹配。网格本身也不应充当真实镜头光学追迹模型。

质心和惯量是简化估计；安装参考、端口及小特征也不是实物计量结果。与实际
机器人装配时，支架、线缆载荷、安装偏差和结构遮挡需加入场景。校准、动力学
或感知评估的结论应说明使用的是名义几何、理想传感器，还是经过实物验证的
设备模型。机械参数的来源与限制见 [SOURCES.md](SOURCES.md)。
