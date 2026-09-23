"""DOCX validation, Pandoc conversion, and publication."""

import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree

from document_to_markdown.core import ConversionResult
from document_to_markdown.outline import (
    apply_heading_policy,
    count_heading_levels,
    resolve_heading_policy,
    validate_heading_policy,
)


IMAGE_LINK_RE = re.compile(r"!\[[^]]*\]\((?:<([^>]+)>|([^\s)]+))")
HTML_IMAGE_RE = re.compile(r'<img\b[^>]*\bsrc="([^"]+)"[^>]*/?>', re.IGNORECASE)
METAFILE_SUFFIXES = {".emf", ".wmf"}


def validate_docx(source):
    source = Path(source)
    if not zipfile.is_zipfile(source):
        raise ValueError("DOCX 不是有效的 ZIP 归档")
    try:
        with zipfile.ZipFile(source) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError("DOCX ZIP 成员损坏: {}".format(bad_member))
            if "word/document.xml" not in archive.namelist():
                raise ValueError("DOCX 缺少 word/document.xml")
    except zipfile.BadZipFile as exc:
        raise ValueError("DOCX ZIP 无法读取: {}".format(exc)) from exc


def read_docx_title(source):
    validate_docx(source)
    with zipfile.ZipFile(source) as archive:
        try:
            root = ElementTree.fromstring(archive.read("docProps/core.xml"))
        except (KeyError, ElementTree.ParseError):
            return Path(source).stem
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "title":
                title = " ".join("".join(element.itertext()).split())
                if title:
                    return title
    return Path(source).stem


def _validate_local_images(markdown, root):
    text = markdown.read_text(encoding="utf-8")
    root = root.resolve()
    for angle_target, plain_target in IMAGE_LINK_RE.findall(text):
        raw_target = angle_target or plain_target
        parsed = urlparse(raw_target)
        if parsed.scheme or raw_target.startswith("#"):
            continue
        resolved = (root / unquote(parsed.path)).resolve()
        if root != resolved and root not in resolved.parents:
            raise RuntimeError("DOCX 图片路径越出输出目录: {}".format(raw_target))
        if not resolved.is_file():
            raise RuntimeError("DOCX 图片缺失: {}".format(raw_target))


def _convert_metafile(source, target):
    script = Path(__file__).resolve().parents[2] / "convert_metafile.ps1"
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        raise RuntimeError("未找到 PowerShell，无法将 {} 转换为 PNG".format(source.name))
    command = [
        powershell,
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
        "-Source",
        str(source),
        "-Target",
        str(target),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        diagnostic = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError("DOCX 矢量图片转 PNG 失败: {}".format(diagnostic)) from exc
    if not target.is_file():
        raise RuntimeError("DOCX 矢量图片未生成 PNG: {}".format(target))


def _normalize_images(markdown, root):
    """Convert local EMF/WMF images to PNG and use Markdown image links."""
    root = Path(root).resolve()
    text = Path(markdown).read_text(encoding="utf-8")

    text = HTML_IMAGE_RE.sub(lambda match: "![]({})".format(match.group(1)), text)
    text = re.sub(
        r"<figure>\s*(!\[[^]]*\]\([^\n]+\))\s*<figcaption><p>(.*?)</p></figcaption>\s*</figure>",
        lambda match: "{}\n\n> {}".format(match.group(1), match.group(2)),
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    replacements = {}
    for angle_target, plain_target in IMAGE_LINK_RE.findall(text):
        raw_target = angle_target or plain_target
        if raw_target in replacements:
            continue
        parsed = urlparse(raw_target)
        if parsed.scheme or raw_target.startswith("#"):
            continue
        relative = unquote(parsed.path)
        source = (root / relative).resolve()
        if root != source and root not in source.parents:
            raise RuntimeError("DOCX 图片路径越出输出目录: {}".format(raw_target))
        if source.suffix.lower() not in METAFILE_SUFFIXES:
            continue
        target = source.with_suffix(".png")
        if not source.is_file() and target.is_file():
            replacements[raw_target] = target.relative_to(root).as_posix()
            continue
        if not source.is_file():
            raise RuntimeError("DOCX 图片缺失: {}".format(raw_target))
        if not target.exists():
            _convert_metafile(source, target)
        source.unlink()
        new_relative = target.relative_to(root).as_posix()
        replacements[raw_target] = new_relative

    for old, new in replacements.items():
        text = text.replace("({})".format(old), "({})".format(new))
        text = text.replace("(<{}>)".format(old), "(<{}>)".format(new))
    Path(markdown).write_text(text, encoding="utf-8")


def _run_pandoc(source, staging, markdown_name):
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("未找到 Pandoc，无法转换 DOCX")
    command = [
        pandoc,
        "-f",
        "docx",
        "-t",
        "gfm",
        "--wrap=none",
        "--extract-media=images",
        "-o",
        markdown_name,
        str(source),
    ]
    try:
        subprocess.run(command, cwd=staging, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        diagnostic = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError("Pandoc DOCX 转换失败: {}".format(diagnostic)) from exc


def convert(source, options):
    source = Path(source)
    output_dir = None
    try:
        title = read_docx_title(source)
        book = source.stem.rstrip(" .") or "document"
        output_dir = source.parent / book
        staging = source.parent / "temp" / "docx_trans" / book
        if output_dir.exists():
            raise RuntimeError("final output directory already exists, refusing to overwrite: {}".format(output_dir))
        if staging.exists():
            raise RuntimeError("DOCX staging directory already exists, refusing to overwrite: {}".format(staging))
        staging.mkdir(parents=True)

        markdown_name = book + ".md"
        _run_pandoc(source.resolve(), staging, markdown_name)
        staged_markdown = staging / markdown_name
        if not staged_markdown.is_file():
            raise RuntimeError("Pandoc 未生成 DOCX Markdown: {}".format(staged_markdown))

        heading_policy = resolve_heading_policy(
            staged_markdown, "docx", options.heading_policy
        )
        apply_heading_policy(staged_markdown, title, heading_policy)
        _normalize_images(staged_markdown, staging)
        _validate_local_images(staged_markdown, staging)
        counts = count_heading_levels(staged_markdown)
        if not validate_heading_policy(staged_markdown, heading_policy):
            raise RuntimeError(
                "DOCX Markdown H1 不符合 {} 策略: {}".format(
                    heading_policy, counts[1]
                )
            )

        output_dir.mkdir()
        markdown = output_dir / markdown_name
        shutil.move(str(staged_markdown), str(markdown))
        if (staging / "images").is_dir():
            shutil.move(str(staging / "images"), str(output_dir / "images"))
        shutil.move(str(source), str(output_dir / (book + ".docx")))
        try:
            staging.rmdir()
        except OSError:
            pass
        return ConversionResult(source, "docx", True, output_dir, markdown)
    except Exception as exc:
        return ConversionResult(
            source=source,
            format="docx",
            ok=False,
            output_dir=output_dir if output_dir and output_dir.exists() else None,
            diagnostic=str(exc),
        )
