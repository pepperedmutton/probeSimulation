# 朗缪尔探针鞘层仿真 WebUI

本项目基于经典朗缪尔探针理论，实现了一个**零维无碰撞鞘层仿真**的 Web 交互界面。采用完整的鞘层输运物理模型，包括预鞘层加速、玻姆判据、麦克斯韦速度分布积分等，准确模拟探针 I-V 特性曲线。

## 物理模型特点

- **零维仿真**：计算特征尺度参数，无空间网格和粒子追踪
- **完整的输运模型**：考虑 bulk plasma → 预鞘层 → 鞘层边界 → 探针的完整物理过程
- **玻姆判据**：离子以玻姆速度 $v_B = \sqrt{k_B T_e / m_i}$ 进入鞘层
- **麦克斯韦分布**：电子电流基于速度分布积分，正确反映势垒效应
- **准中性假设**：bulk plasma 保持 $n_i \approx n_e$
- **薄鞘层理论**：假设 $\lambda_D \ll$ 探针尺寸
- **冷离子近似**：$T_i \ll T_e$

## 目录结构

```
probeSimu/
├── backend/        # FastAPI 服务，提供鞘层求解 API
│   ├── app/
│   │   └── main.py # 物理模型与 /simulate, /health 接口
│   ├── requirements.txt
│   └── .venv/      # 建议创建的虚拟环境（不提交）
└── frontend/       # 基于 Vite 的 React + TypeScript 单页界面
    ├── src/
    │   ├── App.tsx # 参数输入与结果展示
    │   └── lib/api.ts
    └── .env.example
```

## 后端：FastAPI 鞘层求解

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`POST /simulate` 请求字段：

| 字段 | 说明 |
| --- | --- |
| `neutral_gas_pressure_pa` | 中性气体压强 (Pa，默认 300 K 理想气体换算密度) |
| `ionization_fraction` | 电离率 (0-1) |
| `ion_species` | `Ar` / `Xe`，可按需扩展其它离子 |
| `ion_density_cm3` | （可选）离子密度；一旦设置则电子密度随之确定 |
| `electron_density_cm3` | （可选）电子密度；一旦设置则离子密度随之确定 |
| `ion_energy_ev` | 离子温度 (eV)，当前假设 $T_i \ll T_e$ |
| `electron_energy_ev` | 电子温度 (eV) |
| `plasma_potential_v` | 等离子体空间电势 (V) |

**后端求解流程：**

1. **密度计算**：压强 → 中性密度（理想气体，300K）→ 等离子体密度（×电离率）
2. **准中性约束**：强制 $n_i = n_e$，禁止同时手动设置
3. **特征参数**：
   - 德拜长度：$\lambda_D = \sqrt{\epsilon_0 k_B T_e / (n_e e^2)}$
   - 玻姆速度：$v_B = \sqrt{k_B T_e / m_i}$
   - 鞘层厚度：$s \approx \sqrt{\frac{2 \epsilon_0 \Delta V}{e n_i}}$（Child-Langmuir 平板近似）
   - 浮动电位：$V_f = V_p - \frac{T_e}{2} \ln\left(\frac{m_i}{2\pi m_e}\right)$
4. **饱和电流与温升**：
   - 离子饱和：$I_{i,sat} = 0.61 \cdot e n_i A \sqrt{\frac{k_B(T_e + T_i)}{m_i}}$
   - 探针温升：$P = |I_{i,sat} \cdot (V_p - V_f)|$，再由对流系数换算温度

**输出参数：**
- 电子德拜长度、鞘层厚度、离子声速、浮动电位
- 等离子体频率（电子/离子）、准中性比
- 离子饱和电流、探针温度估算

`POST /pic-slice` 请求字段：

| 字段 | 说明 |
| --- | --- |
| `patch_width_mm` | 模拟截面宽度 (mm) |
| `conductor_thickness_mm`/`sheath_thickness_mm`/`presheath_thickness_mm`/`bulk_thickness_mm` | 垂直层厚 (mm) |
| `ion_density_cm3`/`electron_density_cm3` | 局部等离子体数密度 (cm⁻³) |
| `ion_temperature_ev`/`electron_temperature_ev` | 温度/动能 (eV) |
| `plasma_potential_v`/`probe_bias_v` | 等离子体电势与探针偏压 (V) |
| `neutral_pressure_pa` | 中性气体压强 (Pa) |
| `ion_species` | `Ar` / `Xe` |

## 前端：React 单页交互

```powershell
cd frontend
cp .env.example .env        # 如需连接远端后端，可修改 VITE_API_BASE_URL
npm install
npm run dev                 # http://localhost:5173
```

**界面功能：**

1. **参数设置面板**
   - 背景气体压强、电离率、离子种类
   - 离子/电子温度、等离子体电势
   - 密度模式：自动推导 / 手动设置电子密度 / 手动设置离子密度
   - 快速预设：低电离率、高电离率、重置

2. **虚拟探针操作台**
   - **I-V 曲线绘制**：前端通过 WebSocket 订阅 PIC 仿真返回的 `iv_point` 消息，逐点绘制偏压-电流
   - **关键指标显示**：基于输入参数推导密度、德拜长度、等离子体频率、玻姆速度
   - **扫描参数控制**：电压范围、采样点数、扫描时间
   - 预计扫描耗时自动计算

3. **I-V 曲线物理特性**
   - 正/负偏压区电流均由宏粒子统计得到，自动缓存最近的平均值
   - 实时查看不同偏压下的瞬时电流波动

构建生产版本：`npm run build`。

## 2D PIC 切片

- 新增 `/pic-slice` 端点，对探针表面的一小段横向截面运行二维 PIC。
- 域沿垂直方向划分为导体、鞘层、预鞘层、bulk plasma，多层位势由解析模型给出。
- 使用宏粒子表示离子/电子，时间积分考虑局部电场；当前假设无碰撞鞘层，不包含显式碰撞模型。
- 返回势场、电场、线电荷密度、粒子轨迹等，用于分析局部鞘层结构。
- **网格与求解器**：使用全局均匀网格，单元尺寸固定为 $\lambda_D/10$。场解采用 FFT 型光谱 Poisson 求解器，仅考虑电场（无磁场项），粒子推进遵循标准 Boris/leapfrog 步进。
- **无碰撞假设**：针对无碰撞鞘层，暂不包含粒子-中性碰撞或能量耗散机制，只保留电场驱动。

### 参考：PIC Skeleton Codes

根目录新增 `PIC-skeleton-codes/` 目录，收录 UCLA PICKSC 发布的 PIC 教学/测试代码，可帮助我们实现更完整的自洽求解与 GPU 加速，并验证上面采用的光谱求解策略：

- **目录涵盖** `serial`、`vectorization`、`openmp`、`mpi`、`openmp_mpi`、`gpu` 等，每个子目录都是可独立构建的迷你 PIC。
- **算法内容**：展示粒子推进、荷质沉积、Poisson/Maxwell 求解等完整流程，支持电静、电磁、Darwin 等模型及 1D/2D/3D 版本。
- **GPU 实践**：`gpu/` 子目录提供 CUDA C/Fortran 双栈实现，特点是线程块 tiling + SIMD vectorization；`gpuppic2` 等示例还结合 MPI 做多 GPU 域分解，达到三层并行。
- **资料与教程**：内含 GPU-PIC、EMModels 等 PDF 说明 CUDA 内核设计、共享内存使用与性能数据，可作为后续扩展（碰撞模型、磁场耦合等）的参考。

可以在相应子目录执行 `make` 快速体验；如需了解更多算法细节，可查阅目录附带 README 及引用的 Decyk 等文献。

## I-V 曲线获取方式

- **唯一来源：PIC 仿真**。后端 `/pic/jobs` 根据前端输入创建一个偏压扫描任务，并通过 WebSocket 将 `snapshot` 与 `iv_point` 消息推送给前端。
- **电流估计**：每个偏压点只需运行指定步数，记录该时间窗口内的瞬时电流并求平均，即可得到最终 I-V 数据。无需额外的 0D 模型或拟合。
- **实时绘图**：前端在收到新的 `iv_point` 时立即刷新曲线，从低偏压到高偏压依次补点，可在运行中观察趋势。

## 典型参数范围

**低压射频放电**（默认场景）：
- 压强：0.01-0.1 Pa
- 电离率：0.1%-5%
- 等离子体密度：1e8-1e10 cm⁻³
- 电子温度：2-5 eV
- 探针电流：0.1-100 mA

**霍尔推进器羽流**：
- 压强：0.001-0.01 Pa
- 电离率：10%-30%
- 等离子体密度：1e10-1e12 cm⁻³
- 电子温度：5-20 eV

**电弧放电**（高密度）：
- 压强：1-100 Pa
- 电离率：1%-50%
- 等离子体密度：1e10-1e13 cm⁻³
- 探针电流：10 mA - 10 A（需大探针）

## 物理假设的有效范围

**适用条件：**
- ✅ 低气压（无碰撞鞘层）：$\lambda_{mfp} \gg \lambda_D$
- ✅ 薄鞘层：$\lambda_D \ll$ 探针尺寸
- ✅ 冷离子：$T_i \ll T_e$
- ✅ 单电荷离子：Ar⁺, Xe⁺
- ✅ 稳态均匀等离子体

**不适用条件：**
- ❌ 高压放电（碰撞主导）
- ❌ 小探针（球形鞘层）
- ❌ 热离子等离子体
- ❌ 多电荷离子主导
- ❌ 快速瞬态过程

## 技术细节

**探针几何**：
- 圆柱形探针：直径 1 mm，长度 5 mm
- 收集面积：$A = \pi d L \approx 1.57 \times 10^{-5}$ m²

**物理常数**：
- 元电荷：$e = 1.602 \times 10^{-19}$ C
- 电子质量：$m_e = 9.109 \times 10^{-31}$ kg
- 玻尔兹曼常数：$k_B = 1.381 \times 10^{-23}$ J/K
- 真空介电常数：$\epsilon_0 = 8.854 \times 10^{-12}$ F/m

## 开发与扩展

**扩展离子种类**：
```python
# backend/app/main.py
ION_MASS_MAP = {
    IonSpecies.AR: 39.948 * AMU,
    IonSpecies.XE: 131.293 * AMU,
    IonSpecies.KR: 83.798 * AMU,  # 添加新离子
}
```

**调整探针尺寸**：
```tsx
// frontend/src/App.tsx
const PROBE_DIAMETER_M = 1e-3;  // 直径 (m)
const PROBE_LENGTH_M = 5e-3;    // 长度 (m)
```

**物理模型改进方向**：
- 碰撞效应：加入碰撞频率，修正电流收集
- 磁场效应：考虑拉莫尔半径对鞘层的影响
- 球形/柱形鞘层：修正几何因子
- 多电荷离子：加权平均质量和电荷态

## 参考文献

1. **Chen, F. F.** (2016). *Introduction to Plasma Physics and Controlled Fusion*. 3rd ed. Springer.
2. **Lieberman, M. A., & Lichtenberg, A. J.** (2005). *Principles of Plasma Discharges and Materials Processing*. 2nd ed. Wiley.
3. **Langmuir, I.** (1929). "The Interaction of Electron and Positive Ion Space Charges in Cathode Sheaths". *Physical Review*, 33(6), 954-989.
4. **Bohm, D.** (1949). "Minimum Ionic Kinetic Energy for a Stable Sheath". In *The Characteristics of Electrical Discharges in Magnetic Fields*, ed. A. Guthrie and R. K. Wakerling. McGraw-Hill.

## 故障排除

**问题：I-V 曲线显示异常（出现跳变或尖峰）**
- 检查电离率是否过高（建议 < 10%）
- 确认压强在合理范围（0.01-1 Pa）
- 验证前后端参数一致性

**问题：电流数值过大（> 100 mA）**
- 降低中性气体压强
- 降低电离率
- 检查探针尺寸设置

**问题：曲线不平滑**
- 增加扫描采样点数（建议 > 60）
- 检查电压范围是否合理

**问题：后端连接失败**
- 确认 FastAPI 服务已启动（端口 8000）
- 检查 CORS 配置
- 查看浏览器控制台错误信息

## 许可与贡献

本项目仅供学习和研究使用。欢迎提出问题和改进建议。

---

**最后更新：2025年11月17日**
