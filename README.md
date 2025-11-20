# Langmuir Probe RF I‑V 模拟套件

面向射频等离子体探针实验的浏览器 + FastAPI 工具。后端提供时域求解器，模拟 RF 调制下的探针电位与电流；前端通过流式接口展示 Ie、Ii、I_total 随 Vp 的演化并保存结果。

## 项目结构
- `backend/`：FastAPI 应用，物理内核在 `app/iv_simulation/`（`electron.py`、`ion.py`、`solver.py` 等）。
- `frontend/`：Vite + React + TypeScript 单页应用，页面 `src/pages/LangmuirIVSimulator.tsx` 调用流式接口绘图。
- `docs/langmuir_iv.md`：早期接口说明（信息部分已被本 README 覆盖）。
- `iv_exports/`：每次 API 调用都会写入的电压-电流数据文件。
- 脚本：`start_stack.ps1`（同时启动前后端）、`test_api_call.py/.ps1`（简单调用与导出检查）、`plot_iv_data.py`（离线绘图）。

## 物理模型（代码实际做了什么）
- **电子支路** (`electron.py`)：Maxwell–Boltzmann 分布，`Ie = I_es · exp[e(Vp−Vs)/kTe]`，当 `Vp>Vs` 时增加软饱和限制避免发散。
- **离子支路** (`ion.py`，`IonModel`)：
  - `OML`：柱形探针的轨道运动限制采样，冷离子。
  - `ABR` / `BRL`：在 OML 基础上乘以几何对数因子 `1 + a·ln(1+ξ_p)`（a=0.1/0.2）以近似 Allen–Boyd–Reynolds 与 Bernstein–Rabinowitz–Laframboise 剂量。
  - `ChildLangmuir`：启发式 `I ∝ (V_f−Vp)^{4/3}`，用于模拟高密等离子体的 Child–Langmuir 趋势，占位性质。
  - 元数据同时给出 Bohm 饱和电流参考（`ion_saturation_current`）。
- **时域/扫描求解** (`solver.py`)：
  - 积分 `dVp/dt = I(Vp,t)/(C_probe + C_sheath)`，积分器可选 Euler 或 RK4。
  - `C_sheath` 以 Debye 长度估计，并随偏置 `sqrt((Vs−Vp)/Te)` 缓慢放大/压缩，引入频率响应。
  - RF 调制：`ne`、`Te`、`Vs` 以正弦形式 `base + A sin(2πft)` 改变；强制 Nyquist 检查 `dt < 1/(2f)`。
  - 电压模式：连续线性扫描或按 RF 周期阶梯扫描；若未给 `vp_final` 则求浮动电位演化。
- **流式输出** (`/api/iv/dynamic/stream`)：以 SSE 推送分块数据并同步写入 `iv_exports/<timestamp>.txt`。

## 假设
- 电子为 Maxwellian，离子为冷等离子体（声速 `sqrt(kTe/mi)`），无离子温度和漂移。
- 无磁场、无碰撞、无二次电子发射；未考虑端面效应，仅使用柱形几何。
- RF 只通过 `ne/Te/Vs` 调制体等离子体；鞘层运动用简化电容近似。

## 限制（需注意）
- ABR/BRL 几何因子和 Child–Langmuir 都为平滑占位模型，未使用 Poisson/Laframboise/PIC 查表。
- 电子饱和软上限为经验处理，未包含有限均值自由程或俘获电子效应。
- 未考虑磁化、碰撞、离子温度/漂移、二极化效应；只做了 RF Nyquist 检查，未检查 RC 或鞘层时间尺度。
- 流式接口每块都写盘，长时间运行会迅速累积 `iv_exports`。
- 电压阶梯/扫描未做参数合理性验证，极端步长可能导致数值伪振荡。

## 快速开始
### 后端
```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
健康检查：`http://localhost:8000/health`

### 前端
```powershell
cd frontend
copy .env.example .env   # 可在其中设置 VITE_API_BASE_URL
npm install
npm run dev -- --open    # 默认 http://localhost:5173
```
`VITE_API_BASE_URL` 需指向后端地址，默认 `http://localhost:8000`。

### 一键脚本
`start_stack.ps1`（仓库根目录）会寻找空闲端口并同时启动前后端，前端环境变量自动指向后端端口。

## API 速览
首选流式端点：`POST /api/iv/dynamic/stream`（SSE）；同步端点：`/api/iv/dynamic`。
示例负载：
```json
{
  "plasma": { "ne": 5e15, "te_eV": 3.0, "vs": 0.0, "gas_type": "Ar" },
  "probe":  { "area": 1e-6, "radius": 1e-3, "length": 5e-3, "capacitance": 1e-12 },
  "rf":     { "frequency_hz": 13.56e6, "te_amplitude_ev": 0.5, "ne_amplitude": 1e14, "vs_amplitude_v": 2.0 },
  "time_range": { "total_time_s": 1e-6, "dt_s": 1e-9, "voltage_step_rf_cycles": null },
  "vp_initial": -10.0,
  "vp_final": 20.0,
  "model": "ABR",
  "integrator": "rk4"
}
```
流式响应以 `data: {...}` 推送进度与数据，并在 `metadata.saved_file` 返回导出路径。

## 开发与测试
- 后端测试：`cd backend && pytest`
- 物理解算示例：`python backend/compare_rf.py` 对比不同 RF 频率影响。
- 场景报告：`python -m app.iv_simulation.report_cases` 生成 `backend/iv_results.txt`。
- API 小验收：`python test_api_call.py` 或 `test_api_call.ps1`。

## 进一步改进方向
- 用查表或 PIC/Poisson 结果替换 ABR/BRL/Child–Langmuir 占位模型，引入碰撞/漂移/磁化。
- 增加数值稳定性与时间尺度检查（RC、鞘层响应），并提供可选抑振或自适应步长。
- 为流式导出增加开关与清理策略，避免长跑占满磁盘。
