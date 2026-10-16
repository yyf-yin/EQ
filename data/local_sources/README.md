# 本地资料

新真实研究使用固定表合同：公司身份优先从本次上传年报确认；这里可补充其他证券数据，股数注明 shares_unit（股、万股、百万股等），股价注明 quote_date。公司年报仅由用户通过初始页“添加文件”上传，放在此目录不会自动采用，缺失不转 web 补数。年报结构化副本也须上传，声明 document_type=annual_report，推荐 field_id。完整示例见 [固定表使用与验收](../../docs/FIXED_DATA_SLOTS_ACCEPTANCE.md) 和 [用户年报入口](../../docs/USER_ANNUAL_REPORTS.md)。

证券主档及其它非年报参考资料可放在本目录，或通过 CDR_LOCAL_SOURCES 指定目录。已识别的年报文件/行在真实固定表索引中排除。索引不会读取目录外符号链接，不读取可执行文件。

上传的年报结构化副本使用 company_id、document_type、field_id、period、value、unit、scope 等字段；不是本目录自动取数入口。公司标识须与证券主档一致，年度、币种、单位和合并/母公司/分部口径应明确。

合成示例位于 examples/fixtures，不在此目录，真实模式不会自动加载模拟材料。
