# 库存物料活跃度 MVP 数据质量与验收报告

源文件：机械装备企业ERP报表_4亿产值.xlsx

工作表：物料进出库明细报表

源文件 SHA256：`a7f3cf47c392afba5d0890585bb113a9f711015daeec741e0936b6d9d97538b5`

运行标识：`4f10d2c38d5b067b830ae30d004c38967fd24ece7d735ccd3f328b683d6504d4`

观察日：2025-12-31

声明的数据覆盖窗口：2025-01-01 ～ 2025-12-31

实际有效事件日期：2025-01-01 ～ 2025-12-31

频率统计窗口：2025-01-01 ～ 2025-12-31

策略：slow-moving-default-180d，DaysSinceLastMovement >= 180 天。

## 数据质量

| 项目 | ACTUAL |
|---|---:|
| 总流水数 | 12794 |
| 有效流水数（去除明确重复后） | 12794 |
| 无效流水数 | 0 |
| 整行重复数量 | 0 |
| 存在错误或警告的原始行数 | 12790 |
| Material 数量 | 820 |
| 入库笔数 | 5194 |
| 出库笔数 | 7600 |
| 当前策略候选数量 | 13 |
| >=90 天 Material 数 | 73 |
| >=180 天 Material 数 | 13 |
| 观察日后事件数 | 0 |
| 声明覆盖窗口外事件数 | 0 |
| 无法评估/策略不适用物料数 | 0 |
| 主数据属性冲突物料数 | 816 |
| 年度出库数量总量不可用物料数（单位冲突） | 531 |

主数据冲突按物料编码保留原始事实，显示名称/规格取观察日前末次记录，不代表完成主数据清洗。
单位冲突时 AnnualOutboundQuantity 为 null，并提供 annual_outbound_quantity_by_unit；在获得换算关系或纠正主数据前，不能声称所有物料数量合计已可用。

总流水数 = 有效流水数 + 无效流水数 + 明确重复数。异常记录数可能与这三类重叠。
原始行全部保留，金额缺失不补零；金额类指标不可用时输出 null。CSV 对公式起始文本添加单引号，精确原值见 JSON/RDF。

## 末次动用天数分布

分位数使用线性插值 `(n-1)*p`。

| 统计 | 天数 |
|---|---:|
| min | 0 |
| median | 21.0 |
| p75 | 42.0 |
| p90 | 85.0 |
| max | 342 |

## Review 基线交叉检查

基线只作对照，不作为数据过滤条件或强制断言。

| 指标 | EXPECTED | ACTUAL | DIFF | 原因 |
|---|---:|---:|---:|---|
| total_records | 12794 | 12794 | 0 | 与 Review 基线一致 |
| material_count | 820 | 820 | 0 | 与 Review 基线一致 |
| inbound_count | 5194 | 5194 | 0 | 与 Review 基线一致 |
| outbound_count | 7600 | 7600 | 0 | 与 Review 基线一致 |
| ge_180_count | 13 | 13 | 0 | 与 Review 基线一致 |

## Existing Design / Conflict / Proposed Resolution

| Existing Design | Conflict | Proposed Resolution |
|---|---|---|
| 入库金额减出库金额被称为库存总资金 | 无期初/期末快照，净流量不等于库存 | 新链路只输出活动指标，不重建余额 |
| 最后出库日 + 净金额 + 只有入库即疑似呆滞 | 与末次任意动用和候选语义不一致 | 独立 DaysSinceLastMovement 和配置策略 |
| 只保存任务汇总，原始 Excel 不保存 | 缺少原始行证据链 | 保存源文件、行快照、事件和全部指标证据 |
| LLM 生成健康结论 | 超出确定性诊断范围 | MVP API 不调用 LLM，解释由证据生成 |
| 未发现现有 ontology、46 个冻结 L1 或完整指标图谱 | 无法核实外部编号定义 | 仅保留 M6-01-02 的诊断支持关系，不声明 ITR 等价或子类 |

## 本体对齐

IOF 仅使用 `rdfs:seeAlso` 参考 MaterialLocationChangeProcess，不推断 ERP 记录满足全部物理过程公理，不导入 APS。
参考：[IOF Release 202502](https://spec.industrialontologies.org/portal/release/202502/core/MaterialLocationChangeProcess.html)。
`https://example.org/` 是本 MVP 的应用命名空间，部署到企业图谱时可统一迁移；不声称它是现有冻结指标图谱的正式 IRI。

## 观察边界

- 候选仅表示达到无交易天数阈值；缺少当前库存余额，不能据此确认存在库存或判断库存健康。
- 左截断：本数据只覆盖给定窗口，全年无流水的物料可能未出现；365 天以上状态无法完整观测。
- 同日交易缺少时间戳，末次日期并列的事件全部保留；展示行号顺序不代表业务发生先后。
- 指标只基于通过校验的事件；被拒绝的记录可能影响完整性，请结合数据质量明细复核。
- 同一编码的主数据冲突保留并警告；数量单位不一致时不跨单位相加，按单位分别提供数量。

## 候选与追溯示例

BZ118 最后交易日期 2025-01-23，截至 2025-12-31 为 342 天。策略 slow-moving-default-180d 使用 >= 180 天，达到阈值，列为长期无交易物料候选。

- `source/008173a720c9567cd81c1ade088aba74ac7ed8c11b9f73e614462d37d7f8168d`，Excel 第 12184 行。

BZ060 最后交易日期 2025-02-06，截至 2025-12-31 为 328 天。策略 slow-moving-default-180d 使用 >= 180 天，达到阈值，列为长期无交易物料候选。

- `source/8518394d7d913266e070e359cf9b8c6e883ad6b3ee0d883fef8c799c27a0ba2e`，Excel 第 1904 行。

BZ020 最后交易日期 2025-03-07，截至 2025-12-31 为 299 天。策略 slow-moving-default-180d 使用 >= 180 天，达到阈值，列为长期无交易物料候选。

- `source/18f60b689f881d327fbf7c554dac189ab0dabeadbe1cde2eed5e6c04a79bcb12`，Excel 第 2211 行。

GC010 最后交易日期 2025-12-08，截至 2025-12-31 为 23 天。策略 slow-moving-default-180d 使用 >= 180 天，未达到阈值，不列为长期无交易物料候选。
需求中的 217 天案例是示意，不覆盖真实数据。

## 复核入口

- `source_records.jsonl`：逐行 raw/normalized 值、状态、错误/警告与去重关系。
- `movement_events.jsonl`：每个有效交易的独立事件及来源。
- `metric_observations.jsonl`：统计窗口、数值、单位、全部参与事件。
- `activity_assessments.csv`：候选清单与阈值，便于人工验算。
- `inventory-activity.ttl`：完整本体和实例；`queries/` 提供四类 SPARQL 验收查询。
- `manifest.json` 和 `policy.json`：输入指纹、运行配置、策略快照。
