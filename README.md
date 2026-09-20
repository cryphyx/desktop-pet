# 闪光少女桌宠

<p align="center"><strong>让桌面多一位会回应你的小伙伴</strong></p>

<p align="center">Windows · Python · PySide6 · Pillow</p>

一个可直接运行的 Windows 2D 本地桌宠。透明置顶窗口承载逐帧角色动画，鼠标互动、持续动作和轻量系统面板整合在同一个小程序中。仓库包含完整运行源码、最终角色素材与素材生成脚本。

<p align="center"><img src="qa-supplemental.png" width="720" alt="角色动作与猫咪形态预览"></p>

## 已实现的功能

| 体验 | 实现内容 |
| --- | --- |
| 直接互动 | 拖动定位；点击头部眨眼、身体鞠躬、脚部跳跃 |
| 角色动作 | 招手、跳跃、揉肚子、害羞、跳舞、喝茶，以及银蓝色猫咪形态 |
| 持续状态 | 坐下、站立、看书、敲键盘；重启后恢复上次选择 |
| 桌面工具 | 可选 CPU、内存、磁盘和网络状态面板 |
| 使用体验 | 20%～100% 缩放、启动与退出动画、自动屏幕边界约束 |

角色采用高分辨率透明素材，运行时按屏幕 DPI 缩放；看书时的细微呼吸与敲键盘的逐帧循环由定时器驱动。设置保存在当前用户的应用数据目录。本版本为本地互动程序，未接入大语言模型或联网聊天。

## 运行

在 Windows 上安装 Python 3.11 或更新版本，然后在项目目录执行：

```powershell
python -m pip install -r requirements.txt
python yuli_deluxe_qt.pyw
```

可先检查素材是否齐全：

```powershell
python yuli_deluxe_qt.pyw --smoke-test
```

用 PyInstaller 生成单文件程序：

```powershell
python -m pip install pyinstaller
python -m PyInstaller "桌宠.spec"
```

## 项目结构

- `yuli_deluxe_qt.pyw`：桌宠程序。
- `assets/`：运行所需的最终角色素材。
- `generated/`：用于制作最终动作素材的原始绘制图。
- `prepare_flash_assets.py`：从绘制图生成 `assets/` 的工具。
- `make_qa_sheet.py`、`qa-supplemental.png`：动作检查图的生成脚本与预览。
- `桌宠.spec`：PyInstaller 打包配置。

## 验证

已对素材完整性、动画图集的非空帧和程序的短时启动运行进行检查。具体互动效果仍建议在 Windows 桌面环境下查看。

这是个人作品的源码展示。暂未添加开源许可证；转载、改编或商用请先征得作者同意。
