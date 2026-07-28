# CFD Sentinel 中文说明

CFD Sentinel 是面向 CFD 科研计算的自动化守护与容灾工具。第一版支持
Windows 上的 ANSYS Fluent 显式 journal 命令。

它解决四个核心问题：

1. 运行前审计是否存在初始化快照。
2. 检查是否每 1000 步成对保存 `cas/dat`。
3. 缺失时生成独立的加固 journal，不修改原文件。
4. 运行期间监控迭代停滞和致命日志，并通过邮件报警。

## 三步使用

```powershell
cfd-sentinel audit "D:\work\case01\run.jou"
```

```powershell
New-Item -ItemType Directory "D:\work\case01\checkpoints" -Force
cfd-sentinel harden "D:\work\case01\run.jou" `
  --output "D:\work\case01\run.sentinel.jou" `
  --checkpoint-dir "D:/work/case01/checkpoints" `
  --prefix "case01"
```

检查生成的 `run.sentinel.jou` 后，用 `cfd-sentinel run` 启动 Fluent。
完整命令、邮箱设置和恢复文件校验方法见项目主页的英文 README。

## 重要边界

- CSV 导出成功不代表求解结果可恢复。
- 只有非空且配对的 `cas/dat` 才算有效检查点。
- 从检查点恢复时不应重新初始化。
- 工具不会修改物理模型、替用户判断收敛或自动上传 CFD 数据。
- 第一版只自动改写独立的 `/solve/initialize/initialize-flow` 和
  `/solve/iterate N` 命令；复杂 Scheme/GUI 流程会停止并要求人工复核。
