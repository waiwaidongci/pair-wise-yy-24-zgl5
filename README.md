# 电台播出与版权窗口排程

一个不依赖第三方包、使用 SQLite 和标准库 HTTP 服务的电台排程项目。系统把“计划排期”和“实际播出”分开保存，支持地区授权、日期窗口、禁播时段、节目冷却、赞助商间隔、直播临时替换、实播对账与版权越界检查。

突发停播由独立的规则层处理：登记地区、日期和起止时间后，窗口内同地区尚未播出的计划排期整体转为取消；已登记实播的排期保持原样，窗口与实播时段重叠时整笔拒绝并列出冲突。原节目和原时段会随停播记录保存，运营可一键恢复。代码按职责分层：规则在 `blackout.py`、记录保存在 `database.py`、页面与接口操作在 `app.py` / `static/index.html`。

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
- `POST /api/blackouts`：登记应急停播（`region`、`air_date`、`start_time`、`end_time`、`reason`）。未播出的重叠排期转为取消并保存原节目/原时段；与实播重叠时返回 409 和 `conflicts` 冲突清单；相同窗口重复提交沿用原结果（`reused: true`）
- `POST /api/blackouts/{id}/restore`：撤销停播，按快照把受影响排期恢复为原状态

准备排期时填写 `air_date`、`start_time`、`program_id`、`region`。页面会直接显示校验错误，不会保存失败的排期。应急停播区会展示停播列表、每条记录的影响范围（原节目与原时段）以及生效中记录的恢复入口。
