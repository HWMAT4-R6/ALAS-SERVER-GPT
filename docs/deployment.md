# 从零部署：Windows 10 IoT LTSC 2021 / P620

## 1. 系统与图形环境

确认系统确为Windows 10 **IoT Enterprise LTSC 2021**；普通Enterprise LTSC生命周期不同。[微软产品页](https://learn.microsoft.com/lifecycle/products/windows-10-iot-enterprise-ltsc-2021)。开启BIOS Intel VT，使用正规NVIDIA P620驱动，运行doctor记录OS、驱动和CPU虚拟化状态。P620官方列OpenGL4.5/DirectX12与Windows10支持，不能据此替代服务器模拟器实测。[官方资料](https://www.nvidia.com/content/dam/en-zz/Solutions/design-visualization/productspage/quadro/quadro-desktop/quadro-pascal-p620-data-sheet-us-nv-704415-r1.pdf)。

初始单实例4vCPU/4GB RAM、1280×720，游戏稳定优先；不因64GB内存给模拟器分配全部CPU。此为建议起点，记录CPU/GPU占用、帧率、ADB截图耗时后调整。采用显示缩放不改变游戏截图分辨率的配置，不能把原1280×720点击坐标用于另一分辨率。

## 2. 模拟器、游戏与ALAS

从[雷电官网](https://www.ldplayer.net/)安装与系统兼容的版本，记录版本、安卓版本和安装路径。[官方最低环境要求](https://www.ldplayer.net/support/pc-system-requirements-for-android-emulator.html?n=55531286)。不要自动禁用Hyper-V/VBS；如VT检测失败，按当前版本官方指南检查冲突并由操作者决定修改。

启用模拟器ADB调试，使用其自带adb.exe；安装对应渠道的碧蓝航线，人工登录、完成更新，停主页。所有账号登录只在用户自己的环境完成。另一设备登录会顶掉本机，先暂停再切手机。

从[ALAS官方Releases](https://github.com/LmeSzinc/AzurLaneAutoScript/releases)安装适用的AlasApp；按其安装说明更新依赖。旧实践采用AlasApp_0.4.10_fullcn，这不是当前推荐版本承诺。记录下载文件SHA256、安装版本、ALAS Git提交、更新日期；升级可恢复到备份。

## 3. ADB连通性

```powershell
& 'D:/LDPlayer/adb.exe' connect 127.0.0.1:5555
& 'D:/LDPlayer/adb.exe' devices
& 'D:/LDPlayer/adb.exe' -s 127.0.0.1:5555 get-state
```

端口由实际实例决定，不假定5555永远正确。在线结果应为device；unauthorized/offline需在模拟器确认或诊断，不能把截图空文件当在线。ADB仅本机使用，不将调试端口暴露到公网。

在ALAS界面填写serial与当前游戏包/渠道，验证截图和点击方式；不要复制本机历史alas.json。第一次通过ALAS界面单任务执行，确认截图识别、账号和语言一致，再用本项目守护。

## 4. 项目环境

按README创建Python3.11 venv并安装Pillow，编辑配置路径。ALAS执行使用 `alas_python`（它自己的toolkit/python.exe），项目脚本使用 `.venv`，两者不能互相覆盖依赖。模型可选；API故障不应停止纯ALAS训练。

设置ALAS策略：Main/Event默认关、大世界未验收关；Tactical已有两槽优先T1、AddNewStudent；日常/困难/演习按解锁情况；油1000储备与OilLimit1250；calculate/prevent_green_face；关闭未验证委托推荐、保护稀有舰船。具体字段以当前ALAS版本界面为准，模板不自动写配置。

## 5. 会话与开机

模拟器需要已登录的交互式桌面。先手动开启，不作为Session0服务；本项目也不保存密码实现自动登录。可在Windows任务计划程序配置“用户登录时”“仅用户登录时运行”的伴随程序，路径与工作目录正确；启用前确保模拟器由用户开启并完成主页检查。无需默认开机自动启动游戏。

分别测试本地桌面、远程连接、断开远程、锁屏10分钟后ADB截屏；发现黑屏或渲染停顿，先检查NVIDIA驱动/会话环境。不要未经证据安装虚拟显示驱动或修改安全设置。断开≠注销，注销可能结束应用。

## 6. 首次验收记录

记录系统/驱动/VT、模拟器/游戏/ALAS/Python版本、ADBserial、截图SHA256、实际主页与账号、两槽开始结束时刻、日常单项日志与领取证据。服务器24h未测之前只标记“已安装/单项通过”。安装包和游戏属于上游，仓库不打包分发。
