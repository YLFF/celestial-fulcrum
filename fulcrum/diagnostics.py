"""Chinese presentation for domain diagnostics; technical IDs stay stable."""

from __future__ import annotations

import re

MESSAGES = {
    "Mark absence and node completion are not confirmed from one screenshot.": "单张截图不能确认所有节点是否已完成，也不能因未识别到标记就判定标记不存在；请核对后导入。",
    "merchantRepeatFactor is superseded by per-node merchantViewedShelves": "旧版重复商店系数已停用，改按该节点已查看货柜面数计分",
    "Unknown operator rarity: threshold uses confirmed six-stars only; add rarity or teamCounts": "部分干员星级未确认，战力门槛仅统计已确认六星；请补充星级或人数",
    "Some component appraisals are unknown; merchant economy includes known appraisals only": "部分零件估价未填写，商店经济只计算已知估价",
    "Unconfirmed dystopia coverage has no policy adjustment until reviewed": "实托邦范围存在待确认节点，确认前不应用其方针影响",
    "Held recruitment ticket missing name; end-node recruitment utility is partial": "留存招募券缺少名称，尽头招募分未能完整计算",
    "Remembrance event weights use ordinary IV evidence; node-distance frequencies stay separate": "追忆四层的事件权重暂沿用普通四层统计，节点距离频次仍独立计算",
    "planned tribute needs two held natural components": "自然物不足2件，无法按计划上贡",
    "random tribute assumes uniform selection of two held natural-component instances": "随机上贡按当前自然物实例等概率选2件估计",
    "tribute item identities remain frozen during search; confirm inventory and replan": "上贡物品按当前库存估算，实际结果确认后重新规划",
    "tribute appraisal uses confirmed values only": "部分自然物估价未填写，损失参考仅含已知估价",
    "variable combat cash distribution unpriced": "该战斗的随机现金分布尚未量化",
    "empty event penalty pending": "空过事件的惩罚分尚未设置",
    "no seed/controller: empty event penalty pending": "没有种子或笼控器，红苔无法获得沃土；空过惩罚分尚未设置",
    "eligible events missing weight": "部分合资格事件缺少统计权重",
    "empty sampled encounter pool": "没有可用的不期而遇统计样本",
    "no nonzero category evidence; no invented posterior": "候选节点没有非零统计证据，无法估分",
    "unclassified node; confirm its category before interpreting its utility": "节点类型尚未确认，请先核对类别",
    "No exit node is identified; only treehole branch routes may be available": "没有确认出口节点，可能只能给出进入树洞的分支路线",
    "Treehole entry consumes the listed processing item; routes continuing past that node decline entry": "进入树洞会消耗列出的加工品；继续规划本层表示经过但不进入树洞",
    "Unknown node outcomes, combat results, and item/relic side effects are not simulated; replan after changes": "未知节点结果、战斗结果及零件或藏品副作用不完整模拟，状态变化后请重新规划",
    "Blind-zone planning uses at most 1 AP and one movement; refresh the map before the next plan": "全知者盲区最多规划1行动力、一次移动，下一次规划前请刷新地图",
    "Resident occupancy is from the confirmed snapshot; future resident movement is not simulated": "居民位置采用已确认快照，不预测之后的居民移动",
    "Danger-end recruitment utility is unconfigured; no recruitment points are added there": "尽头招募收益未配置，本次没有计入该部分分数",
    "template ID is absent from the local catalog; fixed-template evidence was skipped": "模板不在本地目录中，未采用固定模板的位置信息",
    "unresolved visual categories can make known-type counts incomplete": "部分节点视觉类别未确认，已知类别计数可能不完整",
    "some newly observed categories conflict with confirmed map state": "新识别的节点类别与已确认地图有冲突",
    "missing six-stars/promotion only; other roster slots may use free recruits; dual-squad home cost proxy": "仅估算缺少六星及进阶所需希望，其他人数可用免费招募补足；职业队采用本家费用近似",
    "confirmed inventory minus planned known tributes; unknown acquired items not simulated": "使用已确认库存并扣除计划上贡，不模拟尚未确认的零件获取",
    "ordinary reward conditions and type/event probabilities frozen at latest snapshot": "普通奖励条件、节点类别与事件概率按最近确认快照估算",
    "merchant score uses mean prefix cash, not the full nonlinear outcome distribution": "商店按路线预测的平均经济计分，不展开所有随机经济分支",
    "prefix movement adds 1 expected ingot for forecast economy, including policy cash costs": "每次移动按配置增加预期源石锭，方针现金损失会扣减预测经济",
    "shops spend/reset predicted cash and appraisal; shelf stock and investment persist in search labels": "到店后预测现金与估价归零，货柜余量与取钱预算继续维护",
    "unknown shop outcomes use probability-weighted economy resets, not a full conditional state tree": "未知商店按概率加权更新平均经济，不构建完整条件状态树",
    "expected action/item rewards do not change executable movement budget/inventory": "期望行动力和零件奖励只计分，不增加本次可执行的移动预算或库存",
    "selected tribute goals use reference-only loss; unselected mandatory cash tribute deducts utility; payments reduce predicted shop economy": "选定上贡目标的损失只作参考，未选定的强制现金上贡扣分；支付仍扣减预测商店经济",
    "covered arrivals settle policy before node rewards; the ideal source disables policy after its own arrival": "覆盖节点先结算方针再结算节点奖励；理想源被击破后移除方针影响",
    "benefit uses confirmed natural inventory minus known planned tributes, not unknown future item acquisitions": "增益只按已确认自然物扣除计划上贡计算，不预测未知零件的入库",
    "reward-pool candidate selection uses IID approximation; incomplete utility terms remain listed": "旧结果使用了可重复的独立候选近似；当前二选一已改为同池不重复候选，请重新评分",
    "reward-pool candidate selection uses weighted sampling without replacement; joint pair frequencies unavailable": "二选一按同池不同物品的经验权重不放回估算；真实候选组合的联合频次尚未取得",
    "Special battle requires an unambiguous stage and variant": "特殊战斗需要确认具体关卡及普通或紧急类型",
    "No reward is defined for this battle/region": "该区域的战斗奖励尚未配置",
    "Stage does not belong to the selected reward region": "关卡不属于当前选择的奖励层",
    "Treehole rewards require the actual stage; do not use the entry floor": "树洞战斗需确认实际关卡，不能直接使用进入层奖励",
    "Unsupported treehole area": "不支持该树洞区域",
    "Treehole battle must be ordinary or explicitly special": "树洞战斗需确认普通、紧急或具体特殊关卡",
    "Ordinary pursuit is not defined for this area": "该区域没有普通追猎奖励",
    "service restarted; submit against the current snapshot": "服务已重启，请基于当前状态重新提交任务",
    "no current area; confirm a map first": "当前没有地图，请先识别并确认地图",
    "too many active jobs; wait or cancel": "正在运行的任务过多，请等待或取消部分任务",
    "job not found": "找不到该任务，请重新执行",
    "select a completed recognition job for this run": "请选择本局已完成的地图识别结果",
    "select a completed relic recognition job for this run": "请选择本局已完成的藏品识别结果",
    "relic row was not located": "没有找到藏品图标栏，请换用完整截图",
    "selected relic is not a recognition candidate": "所选藏品不在本次识别候选中",
    "confirmed area must match recognition request": "确认的层数必须与识别时选择的层数一致",
    "map recognition is unresolved; review template or confirm resources only": "地图匹配尚未确认，请核对模板或仅导入资源",
    "choose an area key, including the treehole parent floor": "请选择层数，树洞需注明从哪一层进入",
    "unsupported resource observation field": "不支持该资源识别字段",
    "multiple true fate nodes; confirm the truth mark before scoring": "出现多个真命运所指，请先修正谜底标记",
}


def message(text: str) -> str:
    if text in MESSAGES:
        return MESSAGES[text]
    for prefix, label in {
        "Events without sampled weights are not silently redistributed: ": "下列合资格事件缺少统计权重，未擅自分摊概率：",
        "event not priced: ": "事件收益尚未量化：",
        "Unsupported battle mode: ": "不支持的战斗类型：",
        "Unknown stage region: ": "未知战斗所属区域：",
        "missing reward frequencies for ": "奖励池缺少统计频次：",
        "unpriced reward in ": "奖励尚未量化：",
        "unsupported reward selection in ": "奖励池选择方式尚不支持：",
    }.items():
        if text.startswith(prefix):
            return label + text[len(prefix):]
    match = re.fullmatch(r"confirmed (.+) count (\d+) exceeds the floor maximum (\d+); the count cap is not used to exclude further candidates", text)
    if match:
        return f"已确认类别 {match[1]} 的数量为{match[2]}，超过本层上限{match[3]}；暂不按此上限排除候选"
    if text.endswith(" is random; excluded from guaranteed routes"):
        return text.split(" is random;")[0] + "具有随机落点，不加入确定性路线"
    review = re.fullmatch(r"(\d+) node categories require review\.", text)
    if review:
        return f"{review[1]}个节点类别需核对，请检查节点识别候选；这不是完成状态提醒。"
    return text


def localize_result(value):
    if isinstance(value, list):
        return [localize_result(row) for row in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        if key in {"warnings", "missingTerms", "modelLimitations", "assumptions"} and isinstance(child, list):
            result[key] = [message(row) if isinstance(row, str) else localize_result(row) for row in child
                           if row != "free-visit target consumption not simulated; confirm and replan"]
        elif key == "missingTermsByNode" and isinstance(child, dict):
            result[key] = {node: [message(row) for row in rows] for node, rows in child.items()}
        elif key in {"hopeCostAssumption", "naturalInventoryAssumption"} and isinstance(child, str):
            result[key] = message(child)
        else:
            result[key] = localize_result(child)
    return result


def public_error(error: Exception) -> str:
    text = message(str(error))
    if any("\u4e00" <= char <= "\u9fff" for char in text):
        return text
    if isinstance(error, FileNotFoundError):
        return "找不到所需文件或记录，请重新选择后重试"
    if isinstance(error, ValueError):
        return "输入或当前对局状态不合法，请核对资源、地图和选项后重试"
    return "操作未完成，请检查截图、运行环境或重试；技术详情保留在任务诊断中"
