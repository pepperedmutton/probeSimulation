# Langmuir I‑V 前端（Vite + React + TypeScript）

本仓库的前端用于与后端 FastAPI 的 `/api/iv/dynamic` 和 `/api/iv/dynamic/stream` 交互，配置等离子体/探针参数，实时获取并绘制 Ie、Ii、I_total 随探针电压的动态曲线。

## 快速开始
```powershell
cd frontend
copy .env.example .env   # 如需自定义 API 基址
npm install
npm run dev -- --open    # 默认 http://localhost:5173
```
> 默认 API 地址为 `http://localhost:8000`，可在 `.env` 修改 `VITE_API_BASE_URL`。

## 主要功能
- 表单配置：等离子体密度/温度/空间电位、探针面积/半径/长度/电容、RF 频率与幅值、时间步长、线性或阶梯式电压扫描、积分器（RK4/Euler）、离子模型（OML/ABR/BRL/ChildLangmuir）。
- 流式计算：调用 `/api/iv/dynamic/stream`，按块推送数据并同步绘制，显示进度条。
- 可视化：Recharts 绘制 Vp‑I_total，并可切换显示 Ie/Ii；显示基本统计与后端保存的数据文件路径。

## 代码结构
- `src/pages/LangmuirIVSimulator.tsx`：主页面，表单、进度、图表逻辑。
- `src/api.ts`：封装 REST 与 SSE 请求（`fetchDynamicIV` / `fetchDynamicIVStream`）。
- `src/App.tsx` / `src/App.css`：整体布局与样式。
- `test_streaming.html`：独立的 SSE 调试页面，可用于验证后端推流。

## 与后端对接须知
- 时间步长需满足 Nyquist：`dt < 1/(2f_RF)`，否则后端会返回 400。
- 扫描模式：
  - 连续扫描：设置 `vp_initial/vp_final`，`voltage_step_rf_cycles` 为空。
  - 阶梯扫描：填写每步包含的 RF 周期数（如 10）。
- 后端会把每次调用写入 `iv_exports/<timestamp>.txt`，长时间运行请注意磁盘占用。

## 常用脚本
- `start_stack.ps1`（仓库根目录）：同时启动后端与前端，自动选择空闲端口并设置 `VITE_API_BASE_URL`。
- `console_test.js` / `test_streaming.html`：控制台或浏览器手动测试流式接口。

## 开发/调试提示
- 图表超过 100k 点会在前端自适应下采样以保证性能。
- 若需要快速切换静态测试数据，可将 `App.tsx` 中的 `showTestChart` 设为 `true` 使用 `TestChart`。
- 使用 TypeScript + eslint/vite 默认配置，若需类型感知的更严格规则，可自行调整 `eslint.config.js`（本项目暂未开启 React Compiler）。***
