"""Read-only inventory for already converted document directories."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from document_to_markdown.repair.markdown import markdown_signature, sha256_file


SOURCE_SUFFIXES = {".epub", ".pdf", ".docx"}


@dataclass(frozen=True)
class ImageRecord:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class SourceRecord:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class DocumentInventory:
    root: str
    markdown: str
    markdown_sha256: str
    originals: tuple
    images: tuple
    signature: dict

    def to_dict(self):
        data = asdict(self)
        data["originals"] = [asdict(item) for item in self.originals]
        data["images"] = [asdict(item) for item in self.images]
        return data


def resolve_markdown(path):
    path = Path(path).resolve()
    if path.is_file():
        if path.suffix.casefold() != ".md":
            raise ValueError("并行修复输入必须是已转换目录或 Markdown 文件: {}".format(path))
        return path
    if not path.is_dir():
        raise ValueError("输入路径不存在: {}".format(path))
    preferred = path / (path.name + ".md")
    if preferred.is_file():
        return preferred
    candidates = sorted(path.glob("*.md"), key=lambda item: item.name.casefold())
    if len(candidates) != 1:
        raise ValueError("目录中必须能唯一确定一个 Markdown 文件: {}".format(path))
    return candidates[0]


def inventory_document(path):
    markdown = resolve_markdown(path)
    root = markdown.parent
    originals = tuple(
        SourceRecord(
            path=str(item.relative_to(root).as_posix()),
            size=item.stat().st_size,
            sha256=sha256_file(item),
        )
        for item in sorted(root.iterdir(), key=lambda item: item.name.casefold())
        if item.is_file() and item.suffix.casefold() in SOURCE_SUFFIXES
    )
    image_root = root / "images"
    images = []
    if image_root.is_dir():
        for item in sorted(image_root.rglob("*"), key=lambda value: str(value).casefold()):
            if item.is_file():
                images.append(
                    ImageRecord(
                        path=str(item.relative_to(image_root).as_posix()),
                        size=item.stat().st_size,
                        sha256=sha256_file(item),
                    )
                )
    text = markdown.read_text(encoding="utf-8")
    return DocumentInventory(
        root=str(root),
        markdown=str(markdown),
        markdown_sha256=sha256_file(markdown),
        originals=originals,
        images=tuple(images),
        signature=markdown_signature(text).to_dict(),
    )
