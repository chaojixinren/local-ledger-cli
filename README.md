# 本地记账 CLI

在终端记录个人收入和支出，按自然月查看收入、支出及净额。使用 Python 3.10+ 和标准库 SQLite，无需联网或安装依赖。

所有命令均在本 README 所在的 `src` 目录执行。

## 使用方法

```sh
python3 -m ledger --help
python3 -m ledger add --help

python3 -m ledger add --kind income --amount 5000 --category 工资 --date 2026-09-01 --note 九月工资
python3 -m ledger add --kind expense --amount 35.50 --category 餐饮 --date 2026-09-02 --note 午餐
python3 -m ledger list
python3 -m ledger summary --month 2026-09
```

录入成功后显示新记录的 ID。省略 `--date` 时使用本机当地日期，省略 `--note` 时备注为空。`list` 包含 ID、日期、类型、分类、金额、备注，先按日期、再按 ID 升序排列。空库显示“暂无记账记录”。列表为带表头的制表符分隔文本，含制表符或换行的字段会按 CSV 规则加引号。

示例汇总：

```text
月份：2026-09
收入：5000.00
支出：35.50
净额：4964.50
```

净额是该月收入减支出，不包含之前月份的余额；无记录的月份三项均显示 `0.00`。


## 筛选记录与分类汇总

`list` 和 `export` 都支持可选的 `--month`、`--kind`、`--category`。多个条件按 AND 组合；省略条件即不按该项筛选，全部省略时仍查询全部记录。筛选后仍按日期、ID 升序排列。

```sh
python3 -m ledger list --month 2026-09
python3 -m ledger list --month 2026-09 --kind expense --category 餐饮
python3 -m ledger summary --month 2026-09 --category 餐饮
```

分类去除首尾空白后精确匹配；例如 `--category " 餐饮 "` 匹配“餐饮”，不匹配“餐饮其他”。`%`、`_` 等字符按原文字面值处理。显式传入空字符串或纯空白分类会报错。月份沿用严格的 `YYYY-MM` 校验，不接受 `2026-13` 或 `2026-9`。

`summary --category` 仅统计指定自然月和分类内的收入、支出与净额。没有匹配记录时三项均为 `0.00`；不传分类时保持整月汇总行为。

## 导出 CSV

```sh
python3 -m ledger export --output exports/all.csv
python3 -m ledger export --output exports/2026-09-food.csv --month 2026-09 --kind expense --category 餐饮
python3 -m ledger --db data/personal.db export --output exports/personal.csv --month 2026-09
```

输出使用 UTF-8 编码，固定表头为：

```csv
id,date,kind,category,amount,note
```

金额始终为两位小数字符串。逗号、双引号、多行备注按 CSV 标准引用，原文内容保留；即使没有匹配记录，也会导出表头。导出与 `list` 共用查询和金额格式化逻辑。

输出路径必须位于 `src` 内，相对路径以 `src` 为基准。缺少的父目录会自动创建；路径本身及任何父目录中的符号链接均被拒绝。目标已存在时返回非零退出码并保留原内容，不提供覆盖开关；数据库不能作为导出目标。例如第二次运行完全相同的导出命令会报告“导出目标已存在”，需要改用新的文件名。

导出先在目标目录写入临时文件，完整写入后才生成最终文件，并在失败时清理临时文件。最后生成目标文件的步骤也禁止覆盖，因此在导出期间被其他进程创建的目标仍会受到保护。安全导出使用 macOS/Linux 的目录文件描述符和硬链接接口；文件系统不支持硬链接时会报错并清理临时文件。普通 CSV 导出不会修改数据库内容或结构。

## 输入规则

- `--kind` 必须为 `income`（收入）或 `expense`（支出）。
- 金额必须大于零，最多两位小数，例如 `12`、`12.3`、`12.30` 或 `.50`。不接受负数、零、科学计数法、非数值、千位分隔符及超过两位小数的金额。金额首尾空白会被移除。
- 单笔金额上限为 `92233720368547758.07`，对应 SQLite 的有符号 64 位整数上限。
- 日期必须严格使用 `YYYY-MM-DD` 格式且真实有效，例如 `2024-02-29` 有效、`2025-02-29` 无效。
- 月份必须严格使用 `YYYY-MM` 格式，年份范围为 `0001`–`9999`，月份范围为 `01`–`12`。
- 分类去除首尾空白后不能为空；备注保留原文。
- 输入、数据库或导出错误会显示说明并返回非零退出码，不显示 traceback；正常命令及帮助返回 `0`。

## 存储方式

默认数据库是 `src/ledger.db`，首次运行会自动建库建表，后续运行继续使用已有记录。数据库是本地 SQLite 文件，金额以整数“分”存储，金额解析、计算和展示均不使用二进制浮点数。

可使用全局 `--db` 指定另一份数据库，参数须放在子命令前：

```sh
python3 -m ledger --db data/personal.db add --kind expense --amount 9.90 --category 交通
python3 -m ledger --db data/personal.db list
python3 -m ledger --db data/personal.db summary --month 2026-09
```

相对数据库路径以 `src` 为基准，缺少的子目录会自动创建。绝对路径也必须位于 `src` 内；解析符号链接后指向目录外的路径会被拒绝。退出命令后可直接备份数据库文件。

## 项目结构

```text
ledger/
  __main__.py      模块入口
  cli.py           参数解析和终端输出
  storage.py       SQLite 持久化、记录查询、月度汇总
  validation.py    金额、日期、月份、分类及数据库路径校验
  exporting.py     安全生成 UTF-8 CSV，不覆盖已有文件
  __init__.py
tests/
  test_ledger.py   核心功能及边界测试
  test_cli.py      命令行、退出码及跨进程持久化测试
  test_filters.py  组合筛选、精确分类及月份边界测试
  test_export.py   CSV 内容、路径保护、已有文件保护和失败清理测试
```

## 运行测试

```sh
python3 -m unittest discover -v
python3 -m compileall -q ledger tests
```

测试只使用 `src/.test-data/` 下的临时数据库及导出文件，测试结束后自动清理，不读写默认 `ledger.db`。测试覆盖原有金额与日期边界、持久化、默认行为，以及组合筛选、自然月边界、分类精确匹配、CSV 特殊字符、空结果、路径和符号链接保护、数据库内容保护、目标文件并发创建和写入失败清理。
