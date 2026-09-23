"""EPUB validation, Pandoc conversion, and publication."""

import re
import hashlib
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


CONTAINER_PATH = "META-INF/container.xml"
IMAGE_LINK_RE = re.compile(r"!\[[^]]*\]\((?:<([^>]+)>|([^\s)]+))")


def _book_stem(source):
    return source.stem.rstrip(" .") or source.stem


def _safe_name(value, max_length=64):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    value = " ".join(value.split()).rstrip(" .") or "document"
    if len(value) <= max_length:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]
    return "{}-{}".format(value[: max_length - 9].rstrip(" ."), digest)


def _output_book_name(source, title):
    stem = _book_stem(source)
    projected_markdown = source.parent / stem / (stem + ".md")
    if len(str(projected_markdown)) < 240:
        return stem
    return _safe_name(title or stem)


def validate_epub(source):
    """Reject unreadable ZIP data and non-EPUB containers."""
    source = Path(source)
    if not zipfile.is_zipfile(source):
        raise ValueError("EPUB 不是有效的 ZIP 归档")
    try:
        with zipfile.ZipFile(source) as archive:
            bad_member = archive.testzip()
            if bad_member:
                raise ValueError("EPUB ZIP 成员损坏: {}".format(bad_member))
            if CONTAINER_PATH not in archive.namelist():
                raise ValueError("EPUB ZIP 缺少 {}".format(CONTAINER_PATH))
    except zipfile.BadZipFile as exc:
        raise ValueError("EPUB ZIP 无法读取: {}".format(exc)) from exc


def _local_name(tag):
    return tag.rsplit("}", 1)[-1]


def read_epub_title(source):
    """Read the first non-empty package title, falling back to the stem."""
    source = Path(source)
    validate_epub(source)
    with zipfile.ZipFile(source) as archive:
        container_root = ElementTree.fromstring(archive.read(CONTAINER_PATH))
        rootfile = next(
            (
                element
                for element in container_root.iter()
                if _local_name(element.tag) == "rootfile"
                and element.attrib.get("full-path")
            ),
            None,
        )
        if rootfile is None:
            raise ValueError("EPUB container.xml 缺少 rootfile")

        package_path = rootfile.attrib["full-path"]
        try:
            package_root = ElementTree.fromstring(archive.read(package_path))
        except KeyError as exc:
            raise ValueError("EPUB ZIP 缺少包文档: {}".format(package_path)) from exc

        for element in package_root.iter():
            if _local_name(element.tag) != "title":
                continue
            value = " ".join("".join(element.itertext()).split())
            if value:
                return value

    return _book_stem(source)


def _ensure_absent(path, label):
    if path.exists():
        raise RuntimeError("{} already exists, refusing to overwrite: {}".format(label, path))


def _validate_local_images(markdown, root):
    text = markdown.read_text(encoding="utf-8")
    root = root.resolve()
    for angle_target, plain_target in IMAGE_LINK_RE.findall(text):
        raw_target = angle_target or plain_target
        parsed = urlparse(raw_target)
        if parsed.scheme or raw_target.startswith("#"):
            continue
        target = unquote(parsed.path)
        resolved = (root / target).resolve()
        if root != resolved and root not in resolved.parents:
            raise RuntimeError("EPUB 图片路径越出输出目录: {}".format(raw_target))
        if not resolved.is_file():
            raise RuntimeError("EPUB 图片缺失: {}".format(raw_target))


def _run_pandoc(source, staging, markdown_name):
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("未找到 Pandoc，无法转换 EPUB")
    command = [
        pandoc,
        "-f",
        "epub",
        "-t",
        "gfm",
        "--wrap=none",
        "--extract-media=images",
        "-o",
        markdown_name,
        str(source),
    ]
    try:
        subprocess.run(
            command,
            cwd=staging,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        diagnostic = (exc.stderr or exc.stdout or str(exc)).strip()
        raise RuntimeError("Pandoc EPUB 转换失败: {}".format(diagnostic)) from exc


def convert(source, options):
    source = Path(source)
    output_dir = None
    try:
        validate_epub(source)
        title = read_epub_title(source)
        book = _output_book_name(source, title)
        output_dir = source.parent / book
        markdown_name = book + ".md"
        markdown = output_dir / markdown_name
        staging = source.parent / "temp" / "epub_trans" / book
        _ensure_absent(output_dir, "final output directory")
        _ensure_absent(staging, "EPUB staging directory")
        staging.mkdir(parents=True)

        _run_pandoc(source.resolve(), staging, markdown_name)
        staged_markdown = staging / markdown_name
        if not staged_markdown.is_file():
            raise RuntimeError("Pandoc 未生成 EPUB Markdown: {}".format(staged_markdown))

        heading_policy = resolve_heading_policy(
            staged_markdown, "epub", options.heading_policy
        )
        apply_heading_policy(staged_markdown, title, heading_policy)
        _validate_local_images(staged_markdown, staging)
        counts = count_heading_levels(staged_markdown)
        if not validate_heading_policy(staged_markdown, heading_policy):
            raise RuntimeError(
                "EPUB Markdown H1 不符合 {} 策略: {}".format(
                    heading_policy, counts[1]
                )
            )

        output_dir.mkdir()
        shutil.move(str(staged_markdown), str(markdown))
        staged_images = staging / "images"
        if staged_images.is_dir():
            shutil.move(str(staged_images), str(output_dir / "images"))
        shutil.move(str(source), str(output_dir / (book + ".epub")))

        try:
            staging.rmdir()
        except OSError:
            pass

        return ConversionResult(
            source=source,
            format="epub",
            ok=True,
            output_dir=output_dir,
            markdown=markdown,
        )
    except Exception as exc:
        return ConversionResult(
            source=source,
            format="epub",
            ok=False,
            output_dir=output_dir if output_dir and output_dir.exists() else None,
            diagnostic=str(exc),
        )
