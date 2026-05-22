"""PR 审校 — 手册/文档对齐（启发式 + Agent 兜底）。

自动从 PR 文件列表中识别任意格式的文档文件并完成 en↔zh 配对。
"""
import json
import re
from typing import Any

from src import config as cfg
from src.logging import info, warn


# ── 启发式: _zh_cn 子目录约定 ──

def _heuristic_align(
    changed_files: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """启发式文档发现: 检测 _zh_cn 子目录约定进行配对。

    扫描非 lang/ 目录的 .md/.json 文件，识别 _zh_cn/ 子目录配对。
    返回 (matched_pairs, unmatched_files)。
    """
    # 收集非 lang 目录的文档文件路径集合
    doc_paths: dict[str, dict[str, Any]] = {}
    for f in changed_files:
        filename = f.get("filename", "")
        if not filename.endswith((".md", ".json")):
            continue
        if "/lang/" in filename:
            continue
        doc_paths[filename] = f

    pairs: list[dict[str, Any]] = []
    matched_paths: set[str] = set()

    # 从 zh 文件出发寻找 en 配对
    for zh_path, zh_file in doc_paths.items():
        if "/_zh_cn/" not in zh_path:
            continue
        # 去除 _zh_cn/ 得到 en 路径
        en_path = zh_path.replace("/_zh_cn/", "/")
        en_file = doc_paths.get(en_path)
        if not en_file:
            continue

        # 提取 guide_dir: _zh_cn 前面的目录名
        idx = zh_path.rindex("/_zh_cn/")
        guide_dir = zh_path[:idx].rsplit("/", 1)[-1]

        # 提取 rel_path: _zh_cn 之后的部分
        rel_path = zh_path[idx + len("/_zh_cn/"):]

        pairs.append({
            "en_file": en_file,
            "zh_file": zh_file,
            "guide_dir": guide_dir,
            "rel_path": rel_path,
        })
        matched_paths.add(zh_path)
        matched_paths.add(en_path)

    unmatched = [f for f in changed_files
                 if f.get("filename", "") in doc_paths
                 and f.get("filename") not in matched_paths]

    return pairs, unmatched


# ── Agent 兜底 ──

_DOC_DISCOVERY_PROMPT = [
    "你是文档翻译对齐专家。请分析以下 PR 变更文件列表，找出其中的手册/文档翻译文件，完成英文和中文的配对。",
    "",
    "约定：",
    "- 语言标识: zh_cn/zh-hans/zh 是中文，en_us/en 是英文",
    "- 文档文件通常在非 lang/ 目录下",
    "- 中英文文件路径有明确的对应关系（如子目录、文件名后缀等）",
    "- 多个不同的文档格式可能同时存在，每种格式使用不同的 key 前缀",
    "",
    "## 未匹配的文件列表",
    "{file_list}",
    "",
    "请输出 JSON 数组，每条配对包含:",
    "- en_path: 英文文件完整路径",
    "- zh_path: 中文文件完整路径",
    "- guide_dir: 手册格式的目录名（如 ae2guide, docs, guide）",
    "- rel_path: 相对路径（guide_dir 之后的部分）",
    "- key: 建议的 key 值（格式: {guide_dir}:{rel_path}）",
    "- namespace: 从路径中推断的命名空间（如 slug 名）",
    "",
    "仅输出 JSON 数组，不要输出其他内容。",
]


def _build_agent_prompt(files: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for f in files:
        lines.append(f.get("filename", ""))
    file_list = "\n".join(lines)
    prompt = "\n".join(_DOC_DISCOVERY_PROMPT)
    return prompt.format(file_list=file_list)


def _parse_agent_response(response: str) -> list[dict[str, Any]] | None:
    """解析 Agent 响应，支持 markdown 代码块包裹。返回 None 表示解析失败。"""
    text = response.strip()
    # 1. 直接解析
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    # 2. 剥离 markdown 代码块
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1).strip())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    # 3. 正则提取 JSON 数组
    m = re.search(r"\[.*]", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group())
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return None


_RETRY_PROMPT_SUFFIX = [
    "",
    "上一轮你输出了以下内容，但 JSON 解析失败：",
    "错误: {error}",
    "上一轮输出:",
    "{previous}",
    "",
    "请修正格式，仅输出 JSON 数组，不要输出 markdown 代码块或其他说明。",
]


def _agent_discover(
    unmatched_files: list[dict[str, Any]],
    llm_call_fn,
    max_retries: int = 2,
) -> list[dict[str, Any]]:
    """Agent 兜底: 调用 LLM 从未匹配文件中发现文档配对。

    解析失败时带错误上下文重试。
    """
    if not unmatched_files:
        return []

    prompt = _build_agent_prompt(unmatched_files)
    response = ""

    for attempt in range(1, max_retries + 1):
        try:
            response = llm_call_fn(prompt)
            parsed = _parse_agent_response(response)
            if parsed is not None:
                return parsed
        except Exception as e:
            warn(f"  [文档发现·Agent] 第 {attempt} 次调用失败: {e}")
            if attempt == max_retries:
                return []
            continue

        if attempt < max_retries:
            # 解析失败，构建带错误上下文的 retry prompt
            error_msg = "响应不是有效的 JSON 数组"
            try:
                json.loads(response)
            except json.JSONDecodeError as je:
                error_msg = str(je)
            retry_suffix = "\n".join(_RETRY_PROMPT_SUFFIX).format(
                error=error_msg, previous=response[:2000],
            )
            prompt = prompt + retry_suffix
            warn(f"  [文档发现·Agent] JSON 解析失败，重试第 {attempt + 1} 次: {error_msg[:80]}")

    return []


# ── 验证层 ──

def _validate_pairs(
    agent_pairs: list[dict[str, Any]],
    changed_files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """验证 Agent 输出的配对: 检查路径在 PR 文件列表中真实存在。"""
    valid_paths: set[str] = {f.get("filename", "") for f in changed_files}
    valid: list[dict[str, Any]] = []
    for pair in agent_pairs:
        en_path = pair.get("en_path", "")
        zh_path = pair.get("zh_path", "")
        if en_path in valid_paths and zh_path in valid_paths:
            valid.append(pair)
        else:
            warn(f"  [文档发现·验证] 跳过无效配对: {en_path} / {zh_path}")
    return valid


# ── 条目构建 ──

def _build_manual_entries(
    pairs: list[dict[str, Any]],
    raw_base: str,
    raw_head: str,
    raw_get_fn,
    token: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """根据配对信息拉取文件内容并构建 EntryDict 列表。"""
    entries: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for pair in pairs:
        guide_dir = pair.get("guide_dir", "")
        rel_path = pair.get("rel_path", "")
        en_path = pair.get("en_path") or pair.get("en_file", {}).get("filename", "")
        zh_path = pair.get("zh_path") or pair.get("zh_file", {}).get("filename", "")
        namespace = pair.get("namespace", guide_dir)

        if not en_path or not zh_path:
            continue

        try:
            new_en = raw_get_fn(f"{raw_head}/{en_path}", token)
            new_zh = raw_get_fn(f"{raw_head}/{zh_path}", token)
        except RuntimeError as e:
            warnings.append({"key": rel_path, "type": "fetch_error", "message": str(e)})
            continue

        key = f"{guide_dir}:{rel_path}"
        entry: dict[str, Any] = {
            "key": key,
            "en": new_en,
            "zh": new_zh,
            "namespace": namespace,
            "format": "manual",
            "version": "",
            "file_path": en_path,
            "slug": namespace,
            "review_type": "normal",
        }
        entries.append(entry)

    return entries, warnings


# ── 主入口 ──

def align(
    changed_files: list[dict[str, Any]],
    raw_base: str,
    raw_head: str,
    raw_get_fn,
    token: str,
    llm_call_fn=None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """主入口：执行文档发现 + 对齐。

    返回 (entries, warnings) 与 _guideme.align 接口兼容。
    """
    # Step 1: 启发式
    heuristic_pairs, unmatched = _heuristic_align(changed_files)

    # Step 2: Agent 兜底
    agent_pairs: list[dict[str, Any]] = []
    if unmatched and llm_call_fn:
        raw_pairs = _agent_discover(unmatched, llm_call_fn)
        agent_pairs = _validate_pairs(raw_pairs, changed_files)

    all_pairs = heuristic_pairs + agent_pairs

    if heuristic_pairs:
        info(f"  [文档发现·启发式] {len(heuristic_pairs)} 对")
    if agent_pairs:
        info(f"  [文档发现·Agent] {len(agent_pairs)} 对")

    # Step 3: 拉取内容 + 构建条目
    entries, warnings = _build_manual_entries(all_pairs, raw_base, raw_head, raw_get_fn, token)

    if entries:
        info(f"  [文档发现] 共 {len(entries)} 条变更")

    return entries, warnings
