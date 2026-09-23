"""Conservative checks for unmistakable Traditional Chinese residue."""

from __future__ import annotations


TRADITIONAL_TO_SIMPLIFIED = {
    "體": "体", "臺": "台", "灣": "湾", "專": "专", "領": "领", "檔": "档",
    "歸": "归", "資": "资", "訊": "讯", "軟": "软", "儲": "储", "網": "网",
    "頁": "页", "裡": "里", "個": "个", "這": "这", "會": "会", "為": "为",
    "與": "与", "從": "从", "後": "后", "還": "还", "讓": "让", "應": "应",
    "該": "该", "將": "将", "來": "来", "過": "过", "學": "学", "習": "习",
    "實": "实", "務": "务", "開": "开", "關": "关", "項": "项", "達": "达",
    "標": "标", "題": "题", "圖": "图", "書": "书", "讀": "读", "寫": "写",
    "備": "备", "錄": "录", "環": "环", "組": "组", "織": "织", "數": "数",
    "據": "据", "處": "处", "簡": "简", "轉": "转", "換": "换", "錯": "错",
    "誤": "误", "與": "与", "線": "线", "類": "类", "區": "区", "層": "层",
    "級": "级", "現": "现", "發": "发", "獨": "独", "審": "审", "視": "视",
    "鏈": "链", "結": "结", "維": "维", "護": "护", "啟": "启", "請": "请",
}


def find_traditional_residue(text, whitelist=None):
    whitelist = set(whitelist or ())
    findings = []
    for line_number, line in enumerate(text.splitlines(), 1):
        for column, char in enumerate(line, 1):
            if char in TRADITIONAL_TO_SIMPLIFIED and char not in whitelist:
                findings.append(
                    {
                        "line": line_number,
                        "column": column,
                        "traditional": char,
                        "simplified": TRADITIONAL_TO_SIMPLIFIED[char],
                    }
                )
    return findings
