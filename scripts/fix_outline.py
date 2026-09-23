"""阶段2：大纲层级修复（代码块感知）。

读 temp/清理冗余/<book>/<book>.md，应用确定性规则修复标题层级，写 <book>/<book>.md，
复制 images/，并把源 PDF 移动为 <book>/<book>.pdf。
**代码块（``` 围栏内）的行不动**——Python 注释 `# ...` 不会被误判为标题，也不会被规则改坏。

规则（同 SKILL.md，先深后浅）:
    1. 删 Article / Article N 残留
    2. 节号深度降级：X.Y.Z→H4, X.Y→H3, X→H2
    3. 第N章 / Chapter N → H2

可选:
    --ocr          扫描书 OCR 预处理（畅→., 去点后空格, 第 N 章→第N章）
    --demote TXT   含 TXT 的 H1 降为 H2（可重复，剔除系列名/英文标题等非正文标题）

用法:
    python scripts/fix_outline.py <pdf_or_folder>
    python scripts/fix_outline.py <pdf_or_folder> --ocr
    python scripts/fix_outline.py <pdf_or_folder> --ocr --demote "高等院校信息科学系列教材" --demote "Methods and Applications"
"""

import re
import sys
import shutil
from pathlib import Path

from document_to_markdown.outline import (
    apply_heading_policy,
    count_heading_levels,
    ensure_h1,
    heading_parts,
    is_fence,
    normalize_under_title,
    resolve_heading_policy,
)


SKILL_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR_NAME = 'temp'
CLEAN_DIR_NAME = '清理冗余'


def structural_major(title):
    match = re.match(r'^([0-9]+)\.[0-9]+', title)
    if match:
        return match.group(1)
    match = re.match(r'^([A-Z])\.[0-9]+', title)
    if match:
        return match.group(1)
    return None


def is_numbered_or_appendix_title(title):
    return bool(re.match(r'^([0-9]+|[A-Z])\.', title))


def next_heading(lines, start_index):
    in_block = False
    for line in lines[start_index + 1:]:
        if is_fence(line):
            in_block = not in_block
            continue
        if in_block:
            continue
        parts = heading_parts(line)
        if parts:
            return parts
    return None


def has_structured_body_headings(lines):
    in_block = False
    for line in lines:
        if is_fence(line):
            in_block = not in_block
            continue
        if in_block:
            continue
        parts = heading_parts(line)
        if parts and structural_major(parts[1]) and parts[0] in (3, 4):
            return True
    return False


def repair_unnumbered_h2(lines):
    """正文开始后，无编号 H2 只有作为新章标题时保留；否则降级。"""
    repaired = []
    in_block = False
    has_structured_body = has_structured_body_headings(lines)
    body_started = False
    front_matter_parent_seen = False
    front_matter_group_opened = False
    current_major = None
    current_depth = 0
    end_section_titles = {'文献注释', '参考文献', '习题', 'References', 'Bibliography'}
    front_matter_metadata = {
        'PEARSON',
        '内容提要',
        '版权声明',
        '图灵计算机科学丛书',
        '本书特色',
    }

    def is_front_matter_top(title):
        if title in {'前言', '目录', '致谢', '摘要', 'Abstract', 'Preface', 'Foreword', 'Contents', 'Acknowledgements', 'Acknowledgments'}:
            return True
        if title.endswith('序'):
            return True
        if title.startswith(('Preface ', 'Foreword ')):
            return True
        return False

    def append_front_matter_item(title):
        nonlocal front_matter_group_opened, current_depth
        if not front_matter_group_opened:
            repaired.append('## 图书信息')
            front_matter_group_opened = True
            current_depth = 2
        repaired.append('### ' + title)
        current_depth = 3

    for idx, line in enumerate(lines):
        if is_fence(line):
            in_block = not in_block
            repaired.append(line)
            continue
        if in_block:
            repaired.append(line)
            continue

        parts = heading_parts(line)
        if not parts:
            repaired.append(line)
            continue

        level, title = parts
        if level == 2 and title in front_matter_metadata:
            append_front_matter_item(title)
            continue
        if (
            level == 2
            and has_structured_body
            and not body_started
            and not is_numbered_or_appendix_title(title)
            and not is_front_matter_top(title)
        ):
            if front_matter_parent_seen:
                line = '### ' + title
                current_depth = 3
            else:
                append_front_matter_item(title)
                continue
            repaired.append(line)
            continue

        major = structural_major(title)
        if major and level in (3, 4):
            body_started = True
            current_major = major
            current_depth = level
            repaired.append(line)
            continue

        if level == 2 and not body_started and is_front_matter_top(title):
            front_matter_parent_seen = True

        if level == 2 and body_started and not is_numbered_or_appendix_title(title):
            nxt = next_heading(lines, idx)
            next_level = nxt[0] if nxt else 0
            next_major = structural_major(nxt[1]) if nxt else None
            is_new_chapter = next_level == 3 and next_major and next_major != current_major
            if not is_new_chapter:
                if title in end_section_titles:
                    target_depth = 3
                else:
                    target_depth = min(max(current_depth + 1, 3), 6)
                line = ('#' * target_depth) + ' ' + title
                level = target_depth

        current_depth = level
        repaired.append(line)

    return repaired


def trim_windows_name(value):
    return value.rstrip(' .')


def stem_before_pdf(name):
    lowered = name.lower()
    pos = lowered.find('.pdf')
    if pos == -1:
        trimmed = trim_windows_name(name)
    else:
        trimmed = trim_windows_name(name[:pos])
    return trimmed or trim_windows_name(name)


def book_stem_for_pdf(pdf_path):
    return stem_before_pdf(Path(pdf_path).name)


def is_internal_pdf(pdf_path):
    parts = {part.lower() for part in pdf_path.parts}
    if TEMP_DIR_NAME.lower() in parts:
        return True
    sibling_md = pdf_path.parent / (pdf_path.stem + '.md')
    return pdf_path.parent.name == pdf_path.stem and sibling_md.exists()


def ensure_absent(path, label):
    path = Path(path)
    if path.exists():
        raise RuntimeError("{} already exists, refusing to overwrite: {}".format(label, path))


def fix_outline(src_md, dest_md, ocr=False, demote_substrings=None):
    """读 src_md，应用规则，写 dest_md。代码块感知（围栏内的行原样保留）。"""
    text = src_md.read_text(encoding='utf-8')
    lines = text.split('\n')
    out = []
    in_block = False
    structural_depth = 0

    for line in lines:
        if is_fence(line):
            in_block = not in_block
            out.append(line)
            continue
        if in_block:
            out.append(line)
            continue

        # 规则1: 删 Article / Article N 残留
        if re.match(r'^Article$', line) or re.match(r'^Article [0-9]+$', line):
            continue

        # OCR 预处理（仅标题行：畅→., 去点后空格, 第 N 章→第N章）
        if ocr and line.startswith('#'):
            line = line.replace('畅', '.')
            line = re.sub(r'\. ([0-9])', r'.\1', line)
            line = re.sub(r'第 ([0-9]+) 章', r'第\1章', line)

        # H1 降级（含指定子串的 H1 → H2，用于剔除系列名/英文标题等）
        if line.startswith('# ') and demote_substrings:
            if any(s in line for s in demote_substrings):
                line = '## ' + line[2:]

        # 规则2: 节号深度降级。结构化编号会更新上下文；局部 1./2. 标题按上下文再降一级。
        if re.match(r'^## ([0-9]+\.[0-9]+\.[0-9]+\.? )', line):
            line = re.sub(r'^## ([0-9]+\.[0-9]+\.[0-9]+\.? )', r'#### \1', line)
            structural_depth = 4
        elif re.match(r'^## ([0-9]+\.[0-9]+\.? )', line):
            line = re.sub(r'^## ([0-9]+\.[0-9]+\.? )', r'### \1', line)
            structural_depth = 3
        elif re.match(r'^## ([A-Z]\.[0-9]+\.[0-9]+\.? )', line):
            line = re.sub(r'^## ([A-Z]\.[0-9]+\.[0-9]+\.? )', r'#### \1', line)
            structural_depth = 4
        elif re.match(r'^## ([A-Z]\.[0-9]+\.? )', line):
            line = re.sub(r'^## ([A-Z]\.[0-9]+\.? )', r'### \1', line)
            structural_depth = 3
        elif re.match(r'^## ([0-9]+\.? )', line) and structural_depth >= 3:
            depth = min(structural_depth + 1, 6)
            line = ('#' * depth) + line[2:]
        elif re.match(r'^# ([0-9]+\.? )', line):
            line = re.sub(r'^# ([0-9]+\.? )', r'## \1', line)
            structural_depth = 2

        # 规则3: 第N章 / Chapter N → H2
        line = re.sub(r'^# (第[一二三四五六七八九十百0-9]+章)', r'## \1', line)
        line = re.sub(r'^# (Chapter [0-9]+)', r'## \1', line)

        out.append(line)

    out = repair_unnumbered_h2(out)
    dest_md.write_text('\n'.join(out), encoding='utf-8')


def count_headings(md_path):
    """兼容旧调用：返回 H1-H4。"""
    counts = count_heading_levels(md_path)
    h1 = counts[1]
    h2 = counts[2]
    h3 = counts[3]
    h4 = counts[4]
    return h1, h2, h3, h4


def first_h1_title(md_path):
    """Return the first real H1 title outside fenced code."""
    in_block = False
    for line in md_path.read_text(encoding='utf-8').split('\n'):
        if is_fence(line):
            in_block = not in_block
            continue
        if in_block:
            continue
        parts = heading_parts(line)
        if parts and parts[0] == 1 and parts[1].strip():
            return parts[1].strip()
    return None


def process_one(pdf_path, ocr, demote_substrings, heading_policy="auto"):
    """对一个 PDF，读 temp/清理冗余/<book>/<book>.md，产最终 <book>/。"""
    book = book_stem_for_pdf(pdf_path)
    parent = pdf_path.parent
    clean_dir = parent / TEMP_DIR_NAME / CLEAN_DIR_NAME / book
    src_md = clean_dir / (book + '.md')
    if not src_md.exists():
        print("  SKIP (no temp/{}/{}/{}.md): {}".format(CLEAN_DIR_NAME, book, book, pdf_path.name))
        return False

    out_dir = parent / book
    dest_md = out_dir / (book + '.md')
    dest_pdf = out_dir / (book + '.pdf')
    ensure_absent(out_dir, "final output directory")

    out_dir.mkdir(parents=True)

    img_src = clean_dir / 'images'
    if img_src.is_dir():
        img_dst = out_dir / 'images'
        shutil.copytree(img_src, img_dst)

    fix_outline(src_md, dest_md, ocr, demote_substrings)
    initial_counts = count_heading_levels(dest_md)
    if initial_counts[1] > 1:
        title = first_h1_title(dest_md)
        if title:
            policy = resolve_heading_policy(dest_md, "pdf", heading_policy)
            if policy == "chapter-h1":
                # H1 超过 H6 溢出或显式指定时，保留并列章节 H1，不再压到书名 H1 之下
                apply_heading_policy(dest_md, title, policy)
            else:
                normalize_under_title(dest_md, title)
    ensure_h1(dest_md, book)
    shutil.move(str(pdf_path), str(dest_pdf))

    counts = count_heading_levels(dest_md)
    h1 = counts[1]
    note = ""
    if h1 != 1:
        note = "  [H1={}, expected 1 - consider --demote]".format(h1)
    elif counts[2] > 80:
        note = "  [H2={}, inspect H2 samples; H2 is a scarce outline level]".format(counts[2])
    print(
        "  FIXED: {} (H1={} H2={} H3={} H4={} H5={} H6={}){}".format(
            book, counts[1], counts[2], counts[3], counts[4], counts[5], counts[6], note
        )
    )
    return True


def collect_pdfs(path):
    p = Path(path)
    if p.is_file():
        if p.suffix.lower() != '.pdf':
            raise ValueError("不是 PDF 文件：{}".format(path))
        return [p]
    if p.is_dir():
        return sorted(
            f for f in p.rglob('*')
            if f.is_file() and f.suffix.lower() == '.pdf' and not is_internal_pdf(f)
        )
    raise ValueError("路径不存在：{}".format(path))


def run(path, ocr=False, demote_substrings=(), heading_policy="auto"):
    """Run the established PDF outline and publication stage."""
    pdfs = collect_pdfs(path)
    print("Found {} PDF(s)".format(len(pdfs)))
    if not pdfs:
        print("No PDFs found")
        return 0

    fixed = 0
    for pdf in pdfs:
        if process_one(pdf, ocr, demote_substrings, heading_policy):
            fixed += 1

    print("\n=== OUTLINE FIX SUMMARY ===")
    print("Fixed: {} / {}".format(fixed, len(pdfs)))
    return fixed


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="阶段2 大纲修复（代码块感知）。读 temp/清理冗余/<book>/<book>.md，写最终 <book>/。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('path', help="PDF 文件路径，或文件夹路径（递归找 PDF，查其 temp/清理冗余/<book>/<book>.md）")
    parser.add_argument('--ocr', action='store_true', help="扫描书 OCR 预处理（畅→. 等）")
    parser.add_argument('--demote', action='append', default=[], metavar='TXT',
                        help="含此子串的 H1 降为 H2（可重复）")
    parser.add_argument('--heading-policy', choices=('auto', 'single-title', 'chapter-h1'),
                        default='auto',
                        help="auto：H6 溢出时自动改用 chapter-h1，否则唯一书名 H1；也可显式指定")
    args = parser.parse_args()

    try:
        run(args.path, ocr=args.ocr, demote_substrings=args.demote,
            heading_policy=args.heading_policy)
    except (RuntimeError, ValueError) as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
