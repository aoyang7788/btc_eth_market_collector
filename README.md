# BTC/ETH 三周期市场数据采集与决策系统 V2

用于替代手动截图，自动采集 BTCUSDT / ETHUSDT 的 15m、1h、4h 市场结构，并生成结构化报告。

## 功能范围

- 采集 Binance Futures 数据：
  - 15m / 1h / 4h / 1d K线
  - 24h ticker
  - 资金费率与下一次资金费率时间
  - OI 持仓量
  - 多空比
- 计算指标：
  - EMA5 / EMA13
  - MA50 / MA200
  - 布林带 20,2
  - MACD 12,26,9
  - 当前K线成交量 / 最近20根平均成交量
- V1 预留但不实现：
  - 爆仓数据
  - 清算地图关键区域

缺失数据会写为 `missing` 或 `null`，不会用 `0` 假装存在。

## 安装

```bash
cd btc_eth_market_collector
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 配置

复制 `.env.example` 为 `.env`：

```bash
copy .env.example .env
```

默认配置：

```env
BINANCE_FUTURES_BASE_URL=https://fapi.binance.com
COINGLASS_BASE_URL=https://open-api-v4.coinglass.com
COINGLASS_API_KEY=
OUTPUT_DIR=outputs
RUN_INTERVAL_MINUTES=15
REQUEST_TIMEOUT_SECONDS=10
```

没有 `COINGLASS_API_KEY` 时，清算地图会正常标记为 `missing`，程序不会报错。

## 运行

立即采集一次：

```bash
python main.py --once
```

每 15 分钟循环更新：

```bash
python main.py --loop --interval 15
```

只基于已有 `outputs/market_snapshot.json` 重新生成决策文件：

```bash
python main.py --decision-only
```

## 输出文件

生成在 `outputs/`：

- `market_snapshot.json`
- `market_report.md`
- `signal_summary.csv`
- `market_decision.json`
- `market_decision.md`
- `signal_history.csv`
- `performance_report.md`
- `signal_statistics.json`
- `health/status.json`

## V2 三周期决策引擎

V2 新增 `decision_engine.py`，只基于 `market_snapshot.json` 做市场状态判断。

决策输出内容：

- 15m结构判断
- 1h结构判断
- 4h结构判断
- 三周期一致性判断
- 是否允许做多
- 是否允许做空
- 是否允许交易
- 风险等级
- 建议动作
- 详细原因列表 `reason[]`

允许动作只有：

- `LOOK_FOR_LONG`
- `LOOK_FOR_SHORT`
- `WAIT`
- `NO_TRADE`

决策引擎不会预测价格，不输出涨跌目标，不连接交易所，不下单。

使用的数据：

- EMA5 / EMA13
- MA50 / MA200
- MACD
- 布林带
- OI
- 资金费率
- 多空比

## Telegram 预留接口

`main.py` 中提供：

```python
def get_latest_market_report() -> dict:
    ...
```

返回最新 JSON、Markdown、CSV 路径和一句简要摘要，后续可以接入 Telegram Bot 推送。

同时提供：

```python
def get_latest_market_decision() -> dict:
    ...
```

返回最新决策 JSON、Markdown 路径和一句决策摘要。

## V3 Telegram 只读查询模式

V3 新增 `telegram_bot.py`，用于 Telegram 查询现有报告。

重要边界：

- 只读取 `outputs/` 下已有文件
- 不负责采集数据
- 不调用 Binance / CoinGlass
- 不连接交易所下单
- 不自动开仓

先生成报告：

```bash
python main.py --once
```

在 `.env` 中配置：

```env
TELEGRAM_BOT_TOKEN=你的TelegramBotToken
```

启动只读机器人：

```bash
python telegram_bot.py
```

支持命令：

- `/market`：BTC 和 ETH 简版总览
- `/btc`：BTCUSDT 详细报告
- `/eth`：ETHUSDT 详细报告
- `/decision`：当前决策摘要
- `/files`：显示报告文件路径
- `/health`：Collector 健康状态

如果没有先生成报告，机器人会返回：

```text
报告尚未生成，请先运行 python main.py --once
```

## V4 信号追踪与复盘系统

V4 新增历史信号追踪，不下单、不连接交易所账户，只记录三周期决策结果和后续市场表现。

新增输出：

- `outputs/signal_history.csv`
- `outputs/performance_report.md`
- `outputs/signal_statistics.json`

`signal_history.csv` 会记录：

- timestamp
- symbol
- action
- price
- risk_level
- reason
- after_1h_return_pct
- after_4h_return_pct
- after_24h_return_pct
- after_72h_return_pct
- after_7d_return_pct

同时额外记录周期结构组合，用于后续统计哪个周期组合更有效：

- structure_15m
- structure_1h
- structure_4h
- three_period_consistency

复盘逻辑：

- 每次运行 `python main.py --once` 会追加当前 BTC/ETH 决策信号。
- 对已经到期的旧信号，系统会用当前最新价格回填 1h / 4h / 24h / 72h / 7d 收益。
- 未到期字段保持空值，不用 `0` 伪装。
- 累计不足100次信号前，只做观察，不判断稳定优势。

统计内容：

- `LOOK_FOR_LONG`：次数、胜率、平均涨幅、最大涨幅、最大回撤
- `LOOK_FOR_SHORT`：次数、胜率、平均跌幅、最大跌幅、最大反向波动
- `WAIT`：次数
- `NO_TRADE`：次数
- 周期组合胜率与平均有利波动

## V5 自动运行守护与健康监控

V5 让 Collector 可以长期自动运行，每 15 分钟采集一次数据，并持续记录日志和健康状态。

新增目录：

- `logs/`
- `health/`

新增文件：

- `logs/collector.log`
- `health/status.json`

健康状态字段：

- `status`
- `last_run_at`
- `last_success_at`
- `last_error_at`
- `last_error_message`
- `consecutive_success`
- `consecutive_failures`
- `next_run_at`
- `outputs`

运行一次并更新健康状态：

```bash
python main.py --once
```

长期循环运行：

```bash
python main.py --loop --interval 15
```

查看健康状态：

```bash
python main.py --health
```

V5 loop 模式行为：

- 单轮异常不会导致程序退出。
- API 失败会写入 `logs/collector.log`。
- 连续失败次数会写入 `health/status.json`。
- 成功后连续失败归零。
- 支持 `Ctrl+C` 正常退出。

### Windows 启动脚本

已提供：

```text
run_collector_loop.bat
```

功能：

- 进入 `btc_eth_market_collector` 项目目录
- 执行 `python main.py --loop --interval 15`
- 窗口标题设置为 `Market Collector V5`

### Windows 任务计划程序开机自启

目标：电脑开机或用户登录后自动运行 Collector。

步骤：

1. 打开 Windows “任务计划程序”。
2. 点击“创建基本任务”。
3. 名称填写：`BTC ETH Market Collector V5`。
4. 触发器选择：“用户登录时”。
5. 操作选择：“启动程序”。
6. 程序或脚本选择：

```text
btc_eth_market_collector\run_collector_loop.bat
```

建议使用完整路径，例如：

```text
C:\Users\zunli\Documents\Codex\2026-05-15\btc-ev-1-btcusdt-k-15\btc_eth_market_collector\run_collector_loop.bat
```

7. 保存任务。

检查运行状态：

- 查看日志：`logs/collector.log`
- 查看健康状态：`health/status.json`
- 命令行执行：`python main.py --health`

Telegram 只读查询也支持：

```text
/health
```

注意：V5 仍然只是自动运行守护系统，不是交易系统；不接交易账户，不自动下单。

## V6 云端 systemd 自动运行

V6 新增两个 systemd 服务模板：

- `deploy/systemd/market-collector.service`
- `deploy/systemd/market-telegram.service`

目标部署目录：

```text
/opt/btc_eth_market_collector
```

运行边界：

- 不接交易所账户
- 不下单
- 不自动交易
- 不修改 `/opt/arthur_tron_bot`
- 不影响当前 TRON 机器人运行

### .env 配置

在 `/opt/btc_eth_market_collector/.env` 中配置：

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
BINANCE_FUTURES_BASE_URL=https://fapi.binance.com
COINGLASS_BASE_URL=https://open-api-v4.coinglass.com
COINGLASS_API_KEY=
OUTPUT_DIR=outputs
RUN_INTERVAL_MINUTES=15
REQUEST_TIMEOUT_SECONDS=10
```

如果 `TELEGRAM_BOT_TOKEN` 为空，`telegram_bot.py` 会明确提示缺失并退出，不会崩溃刷屏。

### Telegram 自动推送

Collector 每次完成分析后，会尝试向 `TELEGRAM_CHAT_ID` 推送 BTC/ETH 简版结果：

- BTC 结果
- ETH 结果
- 风险等级
- 建议动作
- 是否允许交易
- 当前价格
- EMA5 / EMA13 / EMA50 / EMA200
- MACD 状态
- 布林带位置
- 资金费率
- 多空比
- 持仓量 OI
- 15m / 1h / 4h 方向
- 综合评分 0-100
- 为什么允许交易 / 为什么不允许交易

推送失败不会影响主程序采集和循环运行，只会记录到：

```text
logs/telegram.log
```

测试 Telegram 推送：

```bash
cd /opt/btc_eth_market_collector
source .venv/bin/activate
python3 telegram_bot.py --test
```

如果缺少 `TELEGRAM_BOT_TOKEN` 或 `TELEGRAM_CHAT_ID`，命令会输出失败原因，并在 `logs/telegram.log` 中记录。

### 云端手动验收命令

```bash
cd /opt/btc_eth_market_collector
source .venv/bin/activate
python3 main.py --once
python3 main.py --health
```

### 安装 systemd 服务

```bash
cd /opt/btc_eth_market_collector
sudo cp deploy/systemd/market-collector.service /etc/systemd/system/market-collector.service
sudo cp deploy/systemd/market-telegram.service /etc/systemd/system/market-telegram.service
sudo systemctl daemon-reload
```

### 启动 Collector 自动采集服务

```bash
sudo systemctl enable market-collector
sudo systemctl start market-collector
sudo systemctl status market-collector
```

Collector 服务执行：

```bash
/opt/btc_eth_market_collector/.venv/bin/python main.py --loop --interval 15
```

### 启动 Telegram 只读查询服务

```bash
sudo systemctl enable market-telegram
sudo systemctl start market-telegram
sudo systemctl status market-telegram
```

Telegram 服务执行：

```bash
/opt/btc_eth_market_collector/.venv/bin/python telegram_bot.py
```

### 查看运行日志

Collector 应用日志：

```bash
tail -n 100 /opt/btc_eth_market_collector/logs/collector.log
```

Collector systemd 日志：

```bash
sudo journalctl -u market-collector -n 100 --no-pager
```

Telegram systemd 日志：

```bash
sudo journalctl -u market-telegram -n 100 --no-pager
```

Telegram 推送日志：

```bash
tail -n 100 /opt/btc_eth_market_collector/logs/telegram.log
```

实时查看日志：

```bash
sudo journalctl -u market-collector -f
sudo journalctl -u market-telegram -f
```

### 查看健康状态

```bash
cd /opt/btc_eth_market_collector
source .venv/bin/activate
python3 main.py --health
cat health/status.json
```

也可以在 Telegram 中输入：

```text
/health
```

### 确认每 15 分钟自动更新

方式一：查看应用日志中是否持续出现 `ROUND_SUCCESS`：

```bash
tail -n 200 /opt/btc_eth_market_collector/logs/collector.log
```

方式二：查看输出文件修改时间：

```bash
ls -lh --time-style=long-iso /opt/btc_eth_market_collector/outputs/
```

方式三：查看健康状态中的 `last_success_at` 和 `next_run_at`：

```bash
cat /opt/btc_eth_market_collector/health/status.json
```

### 停止或重启服务

```bash
sudo systemctl restart market-collector
sudo systemctl restart market-telegram
sudo systemctl stop market-collector
sudo systemctl stop market-telegram
```

## V1 判断逻辑

单周期结构：

- `bullish`：EMA5 > EMA13 且当前价格 > EMA13
- `bearish`：EMA5 < EMA13 且当前价格 < EMA13
- `neutral`：其他情况
- `missing`：数据不足或接口失败

交易环境：

- 多头环境：4h bullish 且 1h 不为 bearish
- 空头环境：4h bearish 且 1h 不为 bullish
- V1 只做信息采集，`allow_open` 默认 `false`
- 如果关键数据缺失、周期冲突、资金费率/OI/多空比缺失、清算地图缺失，则 `forbid_trade=true`
