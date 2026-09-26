# 电台播出与版权窗口排程

一个不依赖第三方包、使用 SQLite 和标准库 HTTP 服务的电台排程项目。系统把“计划排期”和“实际播出”分开保存，支持地区授权、日期窗口、禁播时段、节目冷却、赞助商间隔、直播临时替换、实播对账与版权越界检查，并提供应急停播：按地区、日期和起止时间登记后，窗口内尚未实播的同地区排期自动转为取消并记录原节目和原时段；窗口与实播记录重叠时整笔拒绝并列出冲突；相同窗口重复提交沿用首次结果；恢复时把排期还原到原节目和原时段，原时段被占用则拒绝。停播规则在 `suspension.py`，记录保存在 `database.py`，页面操作在 `static/index.html`。

## 运行

需要 Python 3.11+。

```bash
python app.py
```

默认端口为 `8111`，页面地址是 <http://127.0.0.1:8111>。第一次启动会创建 `radio.db` 并写入三条演示排期。也可以设置端口和数据库位置：

```bash
PORT=9000 RADIO_DB=/tmp/radio.db python app.py
```

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖完整流程：排期、临时替换、播放日志、按日期对账；同时覆盖时间重叠、未授权地区和实播错节目等失败场景。

## 主要 API

- `GET /api/state`：节目、排期和最近对账异常
- `POST /api/programs`：创建节目并授权地区
- `POST /api/programs/{id}/regions`：追加地区授权
- `POST /api/schedule`：创建排期
- `POST /api/slots/{id}/replace`：替换计划节目并重新校验
- `POST /api/playout`：登记实播记录
- `POST /api/reconcile`：按日期生成漏播、错播、时长偏差和超授权异常
- `POST /api/suspensions`：登记应急停播（`region`、`air_date`、`start_time`、`end_time`、`reason`），窗口内未实播排期转为取消；与实播冲突整笔拒绝；相同窗口重复提交沿用原结果
- `GET /api/suspensions`：停播列表及影响范围（原节目、原时段）
- `POST /api/suspensions/{id}/restore`：恢复停播，把受影响排期还原到原节目和原时段

准备排期时填写 `air_date`、`start_time`、`program_id`、`region`。页面会直接显示校验错误，不会保存失败的排期。
