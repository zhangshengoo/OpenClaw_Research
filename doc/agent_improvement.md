GPT-Researcher 深度检索亮点（200字内）：
递归广度×深度搜索树：通过 breadth（每层子查询数）和 depth（递归层数）两个参数控制探索规模，每层递减广度（breadth//2），逐层聚焦。
LLM 驱动的自动子查询派生：每层由 Strategic LLM（推理模型）自动生成搜索查询和后续研究问题，实现"问题→搜索→提炼→新问题"的自主闭环。
Semaphore 并发控制：asyncio.Semaphore 限制并发数，每个子查询实例化独立的 GPTResearcher 完整执行检索流程，兼顾效率与稳定性。
学习要点提取 + 引用溯源：从搜索结果中提取 learnings 并关联源 URL，确保可溯源。
上下文词量裁剪：trim_context_to_word_limit 保留最新内容，保证不超 25k 词上限。

AI-Researcher 自动化迭代实验亮点（200字内）：
ML Agent + Judge Agent 双Agent迭代闭环：ML Agent 在 Docker 中生成完整代码并执行，Judge Agent 逐条对照学术创新点审查实现完整性，输出修复建议后回传 ML Agent 重新修改，形成"实现→审查→修复"自动循环（max_iter_times 控制轮次）。
Docker 沙箱隔离执行：通过 TCP 协议与容器内通信，支持 GPU、实际数据集下载、流式输出，确保实验环境可复现。
禁止占位符的强约束：ML Agent 指令明确禁止 pass/.../NotImplementedError，强制生成完整可运行代码。
Exp Analyser 二次迭代：实验提交后由独立分析Agent进行结果分析+进一步实验规划（消融实验、可视化），实现"初步实现→提交→分析→精炼"的两层迭代。
FlowModule + AgentModule 缓存编排：flowcache.py 提供工作流缓存与断点续跑能力。