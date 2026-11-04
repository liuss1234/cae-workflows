# 安装与文件契约

整个技能文件夹放到Codex skills目录即可发现。脚本不依赖原作者盘符/用户名；普通工具Python3.9+，历史分析/打包仅用标准库；多面体检查需numpy/h5py，Gmsh/FreeCAD/STAR/QFlux各自安装。QFlux脚本使用兼容API的Python（已验证Windows CPython3.8 x64），不从PyPI获取厂商DLL。

普通环境可安装 `python -m pip install -r assets/requirements.txt`。FreeCAD脚本使用能够 `import FreeCAD, Part` 的解释器；STAR宏由匹配版本的STAR执行，QFlux用其API匹配的独立解释器。`assets/environment.example.json`仅记录这些本机安装位置，不随案例自动安装商业软件。

```text
python scripts/fan_case.py init --case "work/new fan" --source "input/fan.step"
# 编辑case.json后：
python scripts/fan_case.py validate --case "work/new fan"
python scripts/render_star_macro.py --case "work/new fan" --mesh-dir "work/new fan/02工程及计算结果文件/01网格文件/R01" --log-dir "work/new fan/03日志脚本/01日志与检查/R01" --output "work/new fan/03日志脚本/02脚本/R01/MeshCeilingFan.java"
```

每款三个一级目录：`01模型文件`放原始/清理CAD及流体域，`02工程及计算结果文件`放网格、QFX及阶段结果，`03日志脚本`放日志、脚本、配置。版本放对应子目录。rpm为正幅值，direction接受clockwise/counterclockwise（从+Z向下）；顺时针ωz=−rpmπ/30。网格必须实际m制；检测面使用真实扫掠D。

`fan_case.py run --manifest commands.json`默认只显示命令，加`--execute`才运行。格式：

```json
{"cwd":"/absolute/software","commands":[["solver","-q","/new/input.qfx","-o","/new/result","-n","4"]],"log":"/new/log/solver.log"}
```

通过参数数组执行，不经过shell；远端目标和调度器由用户环境提供。Windows SSH里Start-Process可能随连接退出，用WMI隐藏独立作业后查进程、状态和迭代增长；Linux用目标平台支持链路。

## 不含客户数据的几何迁移演示

用FreeCAD解释器执行：

```text
<FreeCAD Python> scripts/create_synthetic_case.py --output work/synthetic-smoke
```

它在全新目录生成矩形三叶封闭实体、三个一级目录、已填写的演示配置、内外屏和MRF双区，检查实体和体积闭合；再次使用同一目录会拒绝覆盖。叶片没有气动设计，不能用其风量代表任何真实产品。

再用安装了Gmsh的普通Python检查面清单（以下路径从技能目录执行）：

```text
python scripts/gmsh_surfaces.py inspect --case work/synthetic-smoke/case --domain work/synthetic-smoke/case/01模型文件/02清理后几何模型/synthetic/流体域 --output work/synthetic-smoke/faces.json
```

`faces.json`记录当次Gmsh/OCC生成的面号、面心、面积和包围盒。按[网格说明](mesh.md)显式标面后执行mesh；演示面号也不能跨版本硬编码。几何演示不自动运行STAR或QFlux，商业网格与物理仍需分别验收。

交付清单格式`{"files":["01模型文件/.../fan.FCStd","02工程及计算结果文件/.../fan.qfx","02工程及计算结果文件/.../fan-02000.dat"]}`。`fan_case.py pack --case CASE --manifest delivery.json --output new.zip`后用`verify --archive new.zip`验证CRC和全部SHA256。拒绝越界、重复、软链接、已存在输出及常见凭据/二进制；物理有效性须另行验收。
