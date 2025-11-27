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
GAME_ROOT = r"/path/to/Europa Universalis V"

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

COUNTRY_TAG_RE = re.compile(r"c:([A-Z]{3})")

def get_country_name_from_tag(tag: str, loc: dict) -> str:
    """
    根据 TAG（如 'FRA', 'NAP'）从 loc 里找国家名。
    你可以根据自己游戏的本地化键规则在这里再加几种尝试。
    """
    # 1) 最简单：直接用 TAG 当 key，比如 NAP: "那不勒斯"
    if tag in loc:
        return loc[tag]

    # 2) 有的本地化可能用 c:NAP
    key2 = f"c:{tag}"
    if key2 in loc:
        return loc[key2]
    
    # 找不到就沿用 TAG 本身
    return tag

def replace_country_tags(text: str, loc: dict) -> str:
    """
    将整段文本里的 c:TAG 替换成对应国家名。
    """

    def repl(m: re.Match) -> str:
        tag = m.group(1)
        name = get_country_name_from_tag(tag, loc)
        return name

    return COUNTRY_TAG_RE.sub(repl, text)

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
    """
    对描述/历史信息/tooltip 中的 [xxx] 做替换：
      - [ShowPolicyName('key')] / [ShowPolicyNameWithNoTooltip('key')]
      - [ShowLawName('key')] / [ShowLawNameWithNoTooltip('key')]
      - [ShowDynastyName('key')] / [ShowDynastyNameWithNoTooltip('key')]
      - [ROOT.GetCountry.GetGovernment.GetEstateName('estate')]
      - 一些简单宏 [ROOT.GetCountry.GetName] / [ROOT.GetCountry.GetNameWithNoTooltip] /
        [ruler_xxx.GetName] / [ruler_xxx.GetShortNameWithNoTooltip]
        ......
    """
    if not text:
        return text

    return text



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

    return None



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

    # 历史信息
    if hist_text:
        out.write("历史信息：\n")
        out.write(indent_lines(render_text(hist_text, loc)) + "\n")

    # dynamic_historical_event 块
    dhe_block = extract_block(block, "dynamic_historical_event")
    if dhe_block:
        out.write("tag&时间：\n")
        for line in dhe_block.splitlines():
            raw = line.rstrip("\r\n")
            if not raw.strip():
                continue

            # raw 是原始这一行（已经去掉行尾 \r\n）
            if not raw.strip():
                continue

            # ✅ 使用所有前导空白（包括 Tab 和空格）作为缩进
            leading = raw[:len(raw) - len(raw.lstrip())]
            content = raw.strip()
            human = humanize_code_line(content, loc)
            if human is None:
                out.write("\t" + leading + render_text(content, loc) + "\n")
            elif human != "":
                out.write("\t" + leading + human + "\n")

    # trigger 块（要求）
    trigger_block = extract_block(block, "trigger")
    if trigger_block:
        out.write("要求：\n")
        for line in trigger_block.splitlines():
            raw = line.rstrip("\r\n")
            if not raw.strip():
                continue

            # raw 是原始这一行（已经去掉行尾 \r\n）
            if not raw.strip():
                continue

            # ✅ 使用所有前导空白（包括 Tab 和空格）作为缩进
            leading = raw[:len(raw) - len(raw.lstrip())]
            content = raw.strip()

            human = humanize_code_line(content, loc)
            if human is None:
                out.write("\t" + leading + render_text(content, loc) + "\n")
            elif human != "":
                out.write("\t" + leading + human + "\n")

    # immediate 块（立即触发）
    immediate_block = extract_block(block, "immediate")
    if immediate_block:
        out.write("立即触发：\n")
        for line in immediate_block.splitlines():
            raw = line.rstrip("\r\n")
            if not raw.strip():
                continue
            # raw 是原始这一行（已经去掉行尾 \r\n）
            if not raw.strip():
                continue

            # ✅ 使用所有前导空白（包括 Tab 和空格）作为缩进
            leading = raw[:len(raw) - len(raw.lstrip())]
            content = raw.strip()

            human = humanize_code_line(content, loc)
            if human is None:
                out.write("\t" + leading + render_text(content, loc) + "\n")
            elif human != "":
                out.write("\t" + leading + human + "\n")


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

            # raw 是原始这一行（已经去掉行尾 \r\n）
            if not raw.strip():
                continue

            # ✅ 使用所有前导空白（包括 Tab 和空格）作为缩进
            leading = raw[:len(raw) - len(raw.lstrip())]
            content = raw.strip()

            human = humanize_code_line(content, loc)
            if human is None:
                out.write("\t" + leading + render_text(content, loc) + "\n")
            elif human != "":
                out.write("\t" + leading + human + "\n")

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
