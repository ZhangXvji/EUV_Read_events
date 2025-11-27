#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 EUV 事件脚本和本地化文件中生成可读的事件说明文本。

- 自动解析 /in_game/events/DHE/flavor_TAG.txt（TAG 大小写都尝试）
- 自动加载 simp_chinese 目录下所有 *_l_simp_chinese.yml（包括 laws_and_policies_l_simp_chinese.yml）
- 输出到当前运行目录: read_events_tag.txt

使用前请修改下面的 GAME_ROOT / COUNTRY_TAG / COUNTRY_NAME / RULER_NAME。
"""

import os
import re
import glob

# ======= 需要你自己修改的配置 =======

# 游戏主路径
GAME_ROOT = r"/home/zhangxuji/eu5_read_events/fake/Europa Universalis V"

# 国家 tag（不区分大小写，如 FRA / fra）
COUNTRY_TAG = "FRA"

# 用于替换 [ROOT.GetCountry.GetName] 之类的占位符
COUNTRY_NAME = "法兰西"
RULER_NAME = "路易十四"

# ======= 根据 TAG 派生的一些变量 =======

TAG_UPPER = COUNTRY_TAG.upper()
TAG_LOWER = COUNTRY_TAG.lower()
EVENT_PREFIX = f"flavor_{TAG_LOWER}"  # 如 flavor_fra
RULER_SCOPE_1 = f"ruler_{TAG_LOWER}"    # 如 ruler_fra
RULER_SCOPE_2 = f"{TAG_LOWER}_ruler"    # 如 fra_ruler

# 匹配类似 estate_type:burghers_estate / c:NAP / policy:permanent_tax 这样的结构
COLON_KEY_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z0-9_]+)")

# ① 主语映射：你想怎么翻就怎么写，之后只改这里就行
SUBJECT_MAP = {
    "stability": "稳定度",
    "legitimacy": "正统性",
    "cultural_influence": "文化影响",
    "pop_satisfaction": "人群满意度",
    "prestige":"威望",
    "estate_satisfaction":"阶级满意度",
    "war_exhaustion":"厌战度",
    "government_power":"正统性",
    "liberty_desire":"独立倾向",
    # 想到再加，例如：
    # "gold_effect": "金钱变化",
}

# ② 强度映射
LEVEL_MAP = {
    "weak": "轻微",
    "mild": "小幅",
    "severe": "严重",
    "extreme": "极大",
    "ultimate": "极端",   # 你也可以改成“极端”/“毁灭性”之类
}

# ③ 正负映射
SIGN_MAP = {
    "bonus": "提升",
    "penalty": "降低",
    "plus":"增加",
}

# ④ 匹配 subject_level_sign 这种结构
#    比如 stability_mild_penalty、cultural_influence_extreme_bonus
SUBJECT_LEVEL_SIGN_RE = re.compile(
    r"^([a-zA-Z_]+)_(weak|mild|severe|extreme|ultimate)_(bonus|penalty|plus)$"
)

def beautify_logic_line(content: str, text: str) -> str:
    """
    仅对 OR / AND / NOT 这类逻辑块的“块头行”做统一的中文处理。
    其他行（包括右括号）一律不动。
    
    content: 原始脚本行（已 strip() 的那部分）
    text   : render_text / replace_colon_keys / translate_code_tokens 之后的中文行
    """
    s_content = content.strip()
    s_text = text.strip()

    if not s_text:
        return text

    # 单独的 { / } 一律不改
    if s_text in ("{", "}"):
        return text

    # 如果原始这一行同时包含 { 和 }，说明是“一行块”（NOT = { in_union_with = c:NAP }）
    # 为了避免吃掉里面的条件，这里不做块头替换。
    if "{" in s_content and "}" in s_content:
        return text

    # 只处理“块头行”：OR = { / AND = { / NOT = {
    if re.match(r"OR\s*=\s*\{", s_content):
        # 或 -> 满足以下任一条件
        return "满足以下任一条件："

    if re.match(r"AND\s*=\s*\{", s_content):
        # 且 -> 同时满足以下全部条件
        return "同时满足以下全部条件："

    if re.match(r"NOT\s*=\s*\{", s_content):
        # 非 -> 不满足以下条件
        return "不满足以下条件："

    # 其他行不处理
    return text

def cleanup_empty_scopes(lines):
    """
    lines: 列表，每个元素是 dict:
      {
        "leading": 原缩进（空格/Tab）
        "content": 原始脚本（去掉行首空白后的内容）
        "text":    经过 humanize/render/翻译后要输出的内容（可以是 ""）
      }

    功能：
      找出形如 xxx ?= { ... } 这种块，如果块内所有行 text 都是空，就把整块删掉。
    """
    to_delete = set()
    n = len(lines)
    i = 0

    while i < n:
        c = lines[i]["content"].strip()
        # 匹配例如 "ruler ?= {"、"ruler_or_regent ?= {"、"character:xxx ?= {"
        if re.match(r".*\?\s*=\s*\{", c):
            # 向后找到与之配对的第一个单独的 "}"
            j = i + 1
            while j < n and lines[j]["content"].strip() != "}":
                j += 1

            if j < n and lines[j]["content"].strip() == "}":
                # 检查 i+1 .. j-1 之间是否有“需要显示”的行
                has_visible = False
                for k in range(i + 1, j):
                    if lines[k]["text"] and lines[k]["text"].strip():
                        has_visible = True
                        break

                # 如果没有任何可见内容，这个作用域就可以整个删掉
                if not has_visible:
                    for k in range(i, j + 1):
                        to_delete.add(k)
                    i = j + 1
                    continue   # 继续从下一个位置扫

        i += 1

    # 实际删除：重建列表
    if to_delete:
        new_lines = [info for idx, info in enumerate(lines) if idx not in to_delete]
        lines[:] = new_lines
        
def replace_colon_keys(text: str, loc: dict) -> str:
    """
    将 text 中所有 prefix:key 形式的片段，用 key 在 loc 中查找并替换。
    例如：
      estate_type:burghers_estate -> loc['burghers_estate'] 或原样保留
      c:NAP                      -> loc['NAP'] 或原样保留
    """

    def repl(m: re.Match) -> str:
        prefix = m.group(1)   # 比如 estate_type / c / policy
        key = m.group(2)      # 比如 burghers_estate / NAP / permanent_tax
        val = loc.get(key)
        if val:
            return (f"「{val}」")        # 用本地化
        return m.group(0)     # 找不到就原样保留，不瞎改

    return COLON_KEY_RE.sub(repl, text)

TOKEN_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")

def translate_code_tokens(line: str) -> str:
    def repl(m: re.Match) -> str:
        token = m.group(0)

        # 1️⃣ 先处理 subject_level_sign 这种组合 token
        m_sls = SUBJECT_LEVEL_SIGN_RE.match(token)
        if m_sls:
            subject_en = m_sls.group(1)   # stability / cultural_influence / ...
            level_en   = m_sls.group(2)   # weak / mild / severe / extreme / ultimate
            sign_en    = m_sls.group(3)   # bonus / penalty

            subject_zh = SUBJECT_MAP.get(subject_en, subject_en)
            level_zh   = LEVEL_MAP.get(level_en, level_en)
            sign_zh    = SIGN_MAP.get(sign_en, sign_en)

            # 最终中文写法：可以根据口味改
            # 比如“稳定度小幅降低”/“文化影响极大提升”
            return f"{subject_zh}{level_zh}{sign_zh}"

        # 2️⃣ 再用普通关键字映射（has_ruler / in_union_with / OR / NOT 等）
        return CODE_TOKEN_MAP.get(token, token)

    return TOKEN_RE.sub(repl, line)

# ======= 本地化读取相关 =======

def load_localization(path):
    """
    读取单个 yml 本地化文件，返回 dict: key -> 文本

    支持：
      key: "文本"
      key:0 "文本"
    会跳过注释和语言头 l_simp_chinese: 等。
    """
    data = {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line.strip():
                    continue
                if line.lstrip().startswith("#"):
                    continue
                if ":" not in line:
                    continue

                key_part, value_part = line.split(":", 1)
                key = key_part.strip()
                value_part = value_part.strip()

                # 语言头
                if key.lower().startswith("l_"):
                    continue

                if not value_part:
                    continue

                # 处理 key:0 "xxx"
                if value_part[0].isdigit():
                    parts = value_part.split(None, 1)
                    if len(parts) == 2:
                        value_part = parts[1]
                    else:
                        continue

                # 去掉首尾引号
                if value_part.startswith('"') and value_part.endswith('"'):
                    value = value_part[1:-1]
                else:
                    # 尽量保守处理
                    if value_part.startswith('"'):
                        value = value_part[1:]
                    else:
                        value = value_part

                # 将 "" 还原为 "
                value = value.replace('""', '"')

                data[key] = value
    except FileNotFoundError:
        print(f"[警告] 找不到本地化文件: {path}")
    except Exception as e:
        print(f"[警告] 读取本地化文件出错: {path} ({e})")

    return data


def load_all_localizations(game_root):
    """
    从 simp_chinese 及 simp_chinese/events/DHE 下加载所有 *_l_simp_chinese.yml。
    """
    loc = {}
    simp_dir = os.path.join(game_root, "game", "main_menu", "localization", "simp_chinese")
    paths = []

    if os.path.isdir(simp_dir):
        paths.extend(glob.glob(os.path.join(simp_dir, "*_l_simp_chinese.yml")))
        dhe_dir = os.path.join(simp_dir, "events", "DHE")
        location_names_dir = os.path.join(simp_dir, "location_names")
        if os.path.isdir(dhe_dir):
            paths.extend(glob.glob(os.path.join(dhe_dir, "*_l_simp_chinese.yml")))
        if os.path.isdir(location_names_dir):
            paths.extend(glob.glob(os.path.join(location_names_dir, "*_l_simp_chinese.yml")))

    # 去重
    uniq_paths = []
    seen = set()
    for p in paths:
        if p not in seen:
            uniq_paths.append(p)
            seen.add(p)

    if not uniq_paths:
        print("[警告] 没有找到任何本地化 yml 文件。")
        return {}

    for p in uniq_paths:
        part = load_localization(p)
        loc.update(part)

    print(f"[信息] 已加载 {len(uniq_paths)} 个本地化文件，共 {len(loc)} 条键值。")
    return loc


# ======= 事件脚本解析相关 =======

def find_matching_brace(text, start_pos):
    """
    从 start_pos（一个 '{' 的位置）开始找与之匹配的 '}'。
    """
    depth = 0
    for i in range(start_pos, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return -1


def extract_block(text, keyword):
    pattern = re.compile(r"%s\s*=\s*\{" % re.escape(keyword))
    m = pattern.search(text)
    if not m:
        return None

    brace_start = text.find("{", m.end() - 1)
    if brace_start == -1:
        return None
    brace_end = find_matching_brace(text, brace_start)
    if brace_end == -1:
        return None

    inner = text[brace_start + 1:brace_end]
    # 原来是：return inner.strip()
    # ✅ 改成只去掉首尾的换行（也可以什么都不做）
    return inner.strip("\r\n")
    # 或者干脆：
    # return inner


def extract_option_blocks(text):
    """
    从事件主体 text 中提取所有 option = { ... } 块。
    返回列表，每个元素包含：
    {
        "name": 选项 key (如 flavor_fra.1.a)，可能为 None，
        "lines": [去掉 name/custom_tooltip 后保留的代码行],
        "tooltips": [custom_tooltip 的 key 列表]
    }
    """
    res = []
    pattern = re.compile(r"option\s*=\s*\{")
    pos = 0
    while True:
        m = pattern.search(text, pos)
        if not m:
            break

        brace_start = text.find("{", m.end() - 1)
        if brace_start == -1:
            break
        brace_end = find_matching_brace(text, brace_start)
        if brace_end == -1:
            break

        block_text = text[brace_start + 1:brace_end].strip()
        pos = brace_end + 1

        name_key = None
        lines_keep = []
        tooltips = []

        for raw_line in block_text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()

            if not stripped:
                continue
            if stripped.startswith("#"):
                # 保留注释行
                lines_keep.append(raw_line)
                continue

            # name = flavor_fra.1.a
            m_name = re.match(r"name\s*=\s*([^\s#]+)", stripped)
            if m_name:
                name_key = m_name.group(1)
                continue

            # custom_tooltip = enables_xxx
            m_tip = re.match(r"custom_tooltip\s*=\s*([^\s#]+)", stripped)
            if m_tip:
                tooltips.append(m_tip.group(1))
                continue

            lines_keep.append(raw_line)

        res.append({"name": name_key, "lines": lines_keep, "tooltips": tooltips})

    return res


def get_assignment_key(block, field):
    """
    在 block 中寻找 `field = xxx`，返回右侧的 xxx。
    """
    m = re.search(r"\b%s\s*=\s*([^\s#]+)" % re.escape(field), block)
    if m:
        return m.group(1)
    return None


def parse_events(code_text):
    """
    从整个代码文本中提取所有 EVENT_PREFIX.X 事件。
    返回列表：[{"id": "flavor_fra.1", "num": 1, "block": "..."}]
    """
    events = []
    pattern = re.compile(r"(%s\.\d+)\s*=" % re.escape(EVENT_PREFIX))

    for m in pattern.finditer(code_text):
        event_id = m.group(1)
        brace_start = code_text.find("{", m.end())
        if brace_start == -1:
            continue
        brace_end = find_matching_brace(code_text, brace_start)
        if brace_end == -1:
            continue

        block = code_text[brace_start + 1:brace_end]

        try:
            num = int(event_id.split(".")[1])
        except Exception:
            num = 0

        events.append({"id": event_id, "num": num, "block": block})

    events.sort(key=lambda e: e["num"])
    return events


def indent_lines(text, indent="\t"):
    """
    给多行文本每行加缩进。
    """
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        if line.strip():
            lines.append(indent + line.strip())
        else:
            lines.append("")
    return "\n".join(lines)


# ======= 文本和效果的人类可读化 =======
def render_text(text, loc):
    if not text:
        return text

    # 0) 清理 #italic / #!
    text = re.sub(r"#italic\s*", "", text)
    text = text.replace("#!", "")

    # 1) 定义一些“纯代码宏”的直接替换（国家名 / 君主名等）
    static_macros = {
        "ROOT.GetCountry.GetName": COUNTRY_NAME,
        "ROOT.GetCountry.GetNameWithNoTooltip": COUNTRY_NAME,
        "ruler_fra.GetName": RULER_NAME,
        "ruler_fra.GetShortNameWithNoTooltip": RULER_NAME,
        # 你还可以按需加别的，比如 ruler_nap 等
    }

    def repl_bracket(m: re.Match) -> str:
        inner = m.group(1)

        # 1) 完全匹配静态宏
        if inner in static_macros:
            return (f"「{static_macros[inner]}」")

        # 2) 如果里面有 'key'，就把 key 当作本地化键
        m_key = re.search(r"'([^']+)'", inner)
        if m_key:
            key = m_key.group(1)
            val = loc.get(key)
            if val:
                return (f"「{val}」")

        # 3) 否则原样保留
        return m.group(0)

    # 把所有 [ ... ] 都走一遍
    text = re.sub(r"\[([^\]]+)\]", repl_bracket, text)

    text = re.sub(
        r"\[(target_character)\.[^\]]+\]",
        r"[\1]",
        text,
    )

    return text

CODE_TOKEN_MAP = {
    # ===== 基本逻辑 / 布尔 =====
    "OR": "或",
    "AND": "且",
    "NOT": "非",
    "if": "如果",
    "else": "否则",
    "yes": "是",
    "no": "否",

    # ===== 通用字段 / 比较 =====
    "tag": "标签",
    "value": "数值",
    "count": "数量",
    "min": "最小值",
    "max": "最大值",
    "order_by": "排序依据",
    "scale": "倍率",

    # ===== 条件 / 状态 =====
    "is_situation_active": "处于局势",
    "has_ruler": "存在统治者",
    "has_regent": "存在摄政",
    "country_exists": "存在国家",
    "dynasty_exists": "存在宗族",
    "dynasty": "宗族",
    "owns": "拥有",
    "own_entire_province": "完全拥有省份",
    "any_owned_location": "拥有任一地块",
    "any_owned_rural_location": "拥有任一乡村地块",
    "every_owned_location": "所有已拥有地块",
    "every_owned_rural_location": "所有已拥有乡村地块",
    "add_country_modifier": "添加国家修正",
    "has_country_modifier": "拥有国家修正",
    "has_variable": "存在变量",
    "has_global_variable": "拥有全局变量",
    "has_a_parliamentary_system": "拥有议会制度",
    "any_active_disaster": "任一激活灾难",
    "has_estate_privilege": "拥有阶级特权",
    "has_estate": "拥有阶级",
    "has_location_modifier": "拥有省份修正",
    "has_building": "拥有建筑",
    "has_building_with_at_least_one_level": "拥有至少一级建筑",
    "has_mutual_scripted_relation": "拥有自定义关系",
    "has_character_modifier": "拥有角色修正",
    "has_trait": "拥有特质",
    "has_tribal_government": "为部落政体",
    "has_colonial_charters": "拥有殖民宪章",
    "has_unlocked_global_law_trigger": "已解锁全局法律",
    "has_rebel": "存在叛军",
    "has_heir": "拥有继承人",
    "has_consort": "拥有配偶",
    "has_policy": "拥有政策",
    "has_reform": "拥有改革",
    "has_law": "拥有法律",
    "exists": "存在",

    # ===== 外交 / 附庸 / 组织 =====
    "in_union_with": "联统",
    "is_subject_of": "宗主国为",
    "is_independent_or_autonomous_subject": "为独立或自治国家",
    "is_allied_with": "与…结盟",
    "is_rival_of": "视为劲敌",
    "is_neighbor_of": "是邻国",
    "create_alliance": "建立同盟",
    "add_casus_belli": "添加宣战理由",
    "add_opinion": "添加态度",
    "add_opinion_mutual_effect": "相互添加态度",
    "reverse_add_opinion": "反向添加态度",
    "add_antagonism": "添加敌意",
    "any_neighbor_country": "任一邻国",
    "every_neighbor_country": "所有邻国",
    "any_country": "任何国家",
    "every_country": "所有国家",
    "every_other_country": "所有其他国家",
    "any_other_country": "任一其他国家",
    "every_known_country": "所有已知国家",
    "every_subject": "所有附属国",
    "any_international_organizations_member_of": "任一所属国际组织",
    "add_country_to_international_organization": "加入国际组织",
    "has_member": "存在成员国",
    "is_ai": "由 AI 控制",
    "is_subject":"是属国",
    "great_power_score":"列强分",
    "is_member_of_international_organization":"是国际组织成员",
    "add_trust":"添加信任",
    "add_liberty_desire":"独立倾向变化",

    # ===== 战争 / 经济 / 资源 =====
    "stability": "稳定度",
    "at_war": "处于战争",
    "is_at_war_with": "与…处于战争",
    "is_during_bankruptcy": "处于破产状态",
    "num_loans": "贷款数量",
    "gold": "金钱",
    "add_gold": "金钱变化",
    "change_gold_effect": "金钱变化效果",
    "add_inflation": "通货膨胀变化",
    "government_power": "政府权力",
    "add_government_power": "政府权力变化",
    "research_progress": "科研进度",
    "add_research_progress": "科研进度变化",
    "add_rebel_progress": "叛乱进度变化",
    "add_army_tradition": "陆军传统变化",
    "add_core": "获得核心",
    "add_migration": "迁移变化",
    "add_pop_size": "人口规模变化",
    "add_temporary_demand": "增加临时需求",
    "change_prosperity": "繁荣度变化",
    "change_variable": "变量变化",
    "change_societal_value": "社会价值观变化",
    "change_government_type": "更改政体",
    "change_province_integration": "省份融入度变化",
    "change_integration_level": "整合等级变化",
    "add_stability": "稳定度变化",
    "add_legitimacy": "正统性变化",
    "add_estate_satisfaction": "阶级满意度变化",
    "add_pop_satisfaction": "人群满意度变化",
    "add_prestige": "威望变化",
    "add_war_exhaustion":"厌战度变化",
    "in_civil_war":"处于内战",
    "construct_building":"修建建筑",
    "building_type":"建筑类型",
    "destroy_building":"摧毁建筑",
    "in_siege":"在围攻中",


    # ===== 人物 / 作用域 =====
    "add_adm": "增加行政",
    "add_dip": "增加外交",
    "add_mil": "增加军事",
    "create_character": "创建角色",
    "create_mercenary": "创建雇佣兵团",
    "create_rebel": "创建叛军",
    "create_named_dynasty": "创建命名宗族",
    "create_country_from_location": "从地点创建国家",
    "create_location_country_from_province": "从省份创建地点国家",
    "first_name": "名",
    "last_name": "姓",
    "adm": "行政",
    "dip": "外交",
    "mil": "军事",
    "birth_date": "出生日期",
    "birth_location": "出身地点",
    "artist_skill": "艺术家能力",
    "artist": "艺术家类型",
    "estate": "阶级",
    "any_child": "任一孩子",
    "random_child": "随机孩子",
    "any_cardinal_in_country": "任一境内枢机主教",
    "is_sibling_of": "是兄弟姐妹",
    "is_child_of": "是…的子女",
    "is_alive": "存活",
    "is_female": "女性",
    "is_male": "男性",
    "is_adult": "成年人",
    "age_in_years": "年龄",
    "is_ruler": "是统治者",
    "is_heir": "是继承人",
    "is_courtier": "是廷臣",
    "heir": "继承人",
    "owner": "所有者",
    "father": "父亲",
    "mother": "母亲",
    "add_trait": "添加特质",
    "kill_character_silently": "悄然杀死角色",
    "banish_character": "放逐角色",
    "move_country": "迁往国家",
    "set_new_ruler": "设置新统治者",
    "set_regent": "设为摄政",
    "set_nickname": "设置绰号",
    "character":"角色",
    "target_character":"目标角色",
    "add_character_modifier":"添加角色修正",
    "create_in_limbo":"火星人",

    # ===== 宗教 / 文化 =====
    "religion": "宗教",
    "culture": "文化",
    "religion_percentage": "宗教人口比例",
    "religion_percentage_in_country": "国家宗教百分比",
    "add_cultural_influence": "文化影响变化",
    "add_religious_influence": "宗教影响力变化",
    "religious_influence": "宗教影响力",
    "change_pop_allegiance": "人群效忠变化",
    "create_art": "创建艺术品",
    "quality": "品质",
    "has_embraced_institution": "已接纳思潮",
    "is_religion_enabled": "宗教已启用",
    "change_character_religion":"改变角色宗教",
    "change_character_culture":"改变角色文化",
    "every_pop":"所有人群",
    "has_advance":"拥有革新",

    # ===== 地理 / 省份 / 地点 =====
    "province_definition": "省份",
    "region": "大区",
    "area": "区域",
    "continent": "洲",
    "location": "地点",
    "capital": "首都",
    "is_capital": "为首都",
    "is_coastal": "为沿海",
    "is_core_of": "为核心省份",
    "is_city": "为城市",
    "has_discovered": "已发现",
    "is_discovered_by": "被…发现",
    "is_huron_country": "为休伦国家",
    "is_iroquois_country": "为易洛魁国家",
    "any_location_in_region": "区域内任一地点",
    "any_location_in_area": "地区内任一地点",
    "any_location_in_province": "省内任一地点",
    "any_exploration_from_country": "任一本国探险",
    "random_location_in_area": "区域内随机地点",
    "random_location_in_region": "大区内随机地点",
    "every_location_in_area": "区域内所有地点",
    "every_location_in_province": "省内所有地点",
    "work_of_art_exists": "存在艺术品",
    "any_work_of_art_in_location": "地点内任一艺术品",
    "every_work_of_art_in_location": "地点内所有艺术品",
    "ordered_owned_location": "排序后的已拥有地点",
    "ordered_country": "排序后的国家",
    "market": "市场",
    "every_province":"任何省份",
    "province":"省",

    # ===== 事件 / 触发 / AI =====
    "historical_option": "历史选项",
    "root": "本国",
    "this": "该对象",
    "ruler": "统治者",
    "regent": "摄政",
    "ruler_or_regent": "统治者或摄政",
    "set_variable": "设置变量",
    "set_global_variable": "设置全局变量",
    "remove_variable": "移除变量",
    "target": "目标",
    "type": "类型",
    "limit": "限制范围",
    "modifier": "修正",
    "group": "组",
    "years": "年限",
    "months": "月数",
    "mode": "模式",
    "add": "添加",
    "ai_chance": "AI倾向",
    "factor": "强度",
    "hidden_effect": "隐藏效果",
    "base": "基础",
    "disaster_type": "灾难类型",
    "text": "文本",
    "random_list": "随机列表",
    "trigger_if": "条件触发",
    "trigger_else": "否则触发",
    "trigger_event_silently": "静默触发事件",
    "trigger_event_non_silently": "触发事件",
    "show_as_tooltip": "显示为提示",
    "remove_reform": "移除改革",
    "remove_relation": "移除关系",
    "unlock_estate_privilege_effect": "解锁阶级特权",
    "unlock_government_reform_effect": "解锁政府改革",
    "unlock_law_effect": "解锁法律",
    "unlock_policy_effect": "解锁政策",
    "add_policy":"添加政策",
    "save_scope_as":"保存作用域",
    "amount":"数量",
    "scope":"作用域",
    "percent":"百分比",
    "controller":"控制者",
    "societal_value_move_to_right":"向右偏移",
    "societal_value_move_to_left":"向左偏移",
}


def humanize_code_line(line, loc):
    """
    尝试把一行脚本翻译成自然语言。
    返回：
      - ""  -> 这行不输出（比如完全不想显示的内部逻辑，且不会破坏括号结构）
      - 其他字符串 -> 翻译后文本
      - None -> 保持原样，由外层按原行输出（再走 render_text）
    """
    s = line.strip()
    if not s:
        return ""


    # ========= tag&时间 相关 =========
    
    # monthly_chance = 10  ->  月触发概率10%。
    m = re.match(r"monthly_chance\s*=\s*([-\d]+)", s)
    if m:
        val = m.group(1)
        return f"月触发概率{val}%"

    # ========= 要求（trigger）相关 =========

    # ========= 立即触发（immediate）相关 =========
    #key = philosophical_letters
    m = re.match(r"key\s*=\s*([^\s#]+)", s)
    if m:
        key = m.group(1)
        name = loc.get(key, key)
        return f"作品 = 「{name}」"

    m = re.match(r"modifier\s*=\s*([^\s#]+)", s)
    if m:
        key = m.group(1)
        name = loc.get(key, key)
        return f"修正 = 「{name}」"

    m = re.match(r"type\s*=\s*([^\s#]+)", s)
    if m:
        key = m.group(1)
        name = loc.get(key, key)
        return f"类型 = 「{name}」"

    # 内部处理
    if s.startswith("event_illustration_estate_effect"):
        return ""
    if s.startswith("event_illustration_government_estate_effect"):
        return ""
    if s.startswith("event_illustration_poptype_effect"):
        return ""

    if s.startswith("save_scope_as"):
        return ""

    # ========= 选项效果相关 =========

    return None

def strip_braces(text: str) -> str:
    """
    删除行中的所有 { 和 }，并去掉行尾空白。
    """
    return text.replace("{", "").replace("}", "").replace("=",":").replace("?","").replace("非","不满足").rstrip()

# ======= 输出单个事件 =======

def write_event(out, event, loc):
    """
    将单个事件写入输出文件 out。
    """
    event_id = event["id"]
    block = event["block"]

    # 标题 / 描述 / 历史信息
    title_key = get_assignment_key(block, "title")
    desc_key = get_assignment_key(block, "desc")
    hist_key = get_assignment_key(block, "historical_info")

    title_text_raw = loc.get(title_key, title_key or event_id)
    desc_text = loc.get(desc_key, "") if desc_key else ""
    hist_text = loc.get(hist_key, "") if hist_key else ""

    title_text = render_text(title_text_raw, loc)

    # 事件标题
    out.write(f"{event_id}-{title_text}\n")

    # 描述
    if desc_text:
        out.write("描述:\n")
        out.write(indent_lines(render_text(desc_text, loc)) + "\n")
        out.write("\n")
    # 历史信息
    if hist_text:
        out.write("历史信息：\n")
        out.write(indent_lines(render_text(hist_text, loc)) + "\n")
        out.write("\n")
    # dynamic_historical_event 块
    dhe_block = extract_block(block, "dynamic_historical_event")
    if dhe_block:
        out.write("tag&时间：\n")
        for line in dhe_block.splitlines():
            raw = line.rstrip("\r\n")
            if not raw.strip():
                continue

            leading = raw[:len(raw) - len(raw.lstrip())]
            content = raw.strip()

            human = humanize_code_line(content, loc)
            if human is None:
                text = render_text(content, loc)
                text = replace_colon_keys(text, loc)
                text = translate_code_tokens(text)
                text = beautify_logic_line(content, text)   # ★ 逻辑美化
                text = strip_braces(text)
                out.write("\t" + leading + text + "\n")
            elif human != "":
                text = translate_code_tokens(human)
                text = beautify_logic_line(content, text)   # ★ 逻辑美化
                text = strip_braces(text)
                out.write("\t" + leading + text + "\n")
        out.write("\n")
    # trigger 块（要求）
    trigger_block = extract_block(block, "trigger")
    if trigger_block:
        out.write("要求：\n")
        for line in trigger_block.splitlines():
            raw = line.rstrip("\r\n")
            if not raw.strip():
                continue

            leading = raw[:len(raw) - len(raw.lstrip())]
            content = raw.strip()

            human = humanize_code_line(content, loc)
            if human is None:
                text = render_text(content, loc)
                text = replace_colon_keys(text, loc)
                text = translate_code_tokens(text)
                text = beautify_logic_line(content, text)   # ★
                text = strip_braces(text)
                out.write("\t" + leading + text + "\n")
            elif human != "":
                text = translate_code_tokens(human)
                text = beautify_logic_line(content, text)   # ★
                text = strip_braces(text)
                out.write("\t" + leading + text + "\n")

        out.write("\n")

    immediate_block = extract_block(block, "immediate")
    if immediate_block:
        out.write("立即触发：\n")

        tmp_lines = []  # 每个元素：{"leading", "content", "text"}

        for line in immediate_block.splitlines():
            raw = line.rstrip("\r\n")
            if not raw.strip():
                continue

            leading = raw[:len(raw) - len(raw.lstrip())]
            content = raw.strip()

            human = humanize_code_line(content, loc)

            if human is None:
                text = render_text(content, loc)
                text = replace_colon_keys(text, loc)
                text = translate_code_tokens(text)
                text = beautify_logic_line(content, text)
                text = strip_braces(text)
            elif human != "":
                text = translate_code_tokens(human)
                text = beautify_logic_line(content, text)
                text = strip_braces(text)
            else:
                text = ""

            # ★ 在这里做逻辑美化（仅 OR/AND/NOT 等）
            if text:
                text = beautify_logic_line(content, text)

            tmp_lines.append({
                "leading": leading,
                "content": content,
                "text": text,
            })

        cleanup_empty_scopes(tmp_lines)

        for info in tmp_lines:
            if info["text"] and info["text"].strip():
                out.write("\t" + info["leading"] + info["text"] + "\n")

        out.write("\n")

    # 选项
    options = extract_option_blocks(block)
    for opt in options:
        name_key = opt["name"]
        opt_title_raw = loc.get(name_key, name_key or "")
        opt_title = render_text(opt_title_raw, loc)

        if name_key:
            out.write(f"{name_key}-{opt_title}\n")
        else:
            out.write("选项：\n")

        # 先探测这个选项内部代码的“基础缩进”
        option_leading = ""
        for raw_line in opt["lines"]:
            if raw_line.strip():
                m_tabs = re.match(r"^(\t*)", raw_line)
                option_leading = m_tabs.group(1) if m_tabs else ""
                break

        # custom_tooltip 对应的中文 —— 用和其他效果一样的缩进
        for tip_key in opt["tooltips"]:
            tip_text = loc.get(tip_key, tip_key)
            out.write("\t" + option_leading + render_text(tip_text, loc) + "\n")

        # 选项内部效果行
        for raw_line in opt["lines"]:
            raw = raw_line.rstrip("\r\n")
            if not raw.strip():
                continue

            leading = raw[:len(raw) - len(raw.lstrip())]
            content = raw.strip()

            human = humanize_code_line(content, loc)
            if human is None:
                text = render_text(content, loc)
                text = replace_colon_keys(text, loc)
                text = translate_code_tokens(text)
                text = beautify_logic_line(content, text)   # ★
                text = strip_braces(text)
                out.write("\t" + leading + text + "\n")
            elif human != "":
                text = translate_code_tokens(human)
                text = beautify_logic_line(content, text)   # ★
                text = strip_braces(text)
                out.write("\t" + leading + text + "\n")

        out.write("\n")

    out.write("\n\n")  # 事件之间空两行


# ======= 主程序 =======

def main():
    print("=== EUV 事件阅读器 ===")
    print(f"游戏路径: {GAME_ROOT}")
    print(f"国家 tag: {COUNTRY_TAG} (lower={TAG_LOWER})")
    print(f"国家名称: {COUNTRY_NAME}")
    print(f"统治者名称: {RULER_NAME}")
    print(f"事件前缀: {EVENT_PREFIX}.*")
    print("")

    # 选择事件脚本文件（尝试大写/小写）
    candidates = [
        os.path.join(GAME_ROOT, "game", "in_game", "events", "DHE", f"flavor_{TAG_UPPER}.txt"),
        os.path.join(GAME_ROOT, "game", "in_game", "events", "DHE", f"flavor_{TAG_LOWER}.txt"),
    ]

    code_path = None
    for p in candidates:
        if os.path.isfile(p):
            code_path = p
            break

    if not code_path:
        print("[错误] 找不到事件代码文件，请检查 GAME_ROOT 或文件名 (flavor_TAG.txt)。")
        return

    print(f"[信息] 使用事件代码文件: {code_path}")

    with open(code_path, "r", encoding="utf-8-sig") as f:
        code_text = f.read()

    events = parse_events(code_text)
    if not events:
        print(f"[错误] 没有找到任何事件（形如 {EVENT_PREFIX}.X = {{ ... }}）。")
        return

    print(f"[信息] 共找到 {len(events)} 个事件。")

    # 加载本地化
    loc = load_all_localizations(GAME_ROOT)

    # 输出文件，放在当前运行目录
    out_name = f"read_events_{TAG_LOWER}.txt"
    out_path = os.path.join(os.getcwd(), out_name)

    with open(out_path, "w", encoding="utf-8") as out:
        for ev in events:
            write_event(out, ev, loc)

    print(f"[完成] 已生成: {out_path}")


if __name__ == "__main__":
    main()
