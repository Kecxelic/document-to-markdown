"""Format discovery, adapter routing, and batch result aggregation."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional, Tuple


@dataclass(frozen=True)
class ConversionOptions:
    model: str = "vlm"
    language: str = "en"
    chunk_size: int = 180
    no_upload: bool = False
    work_dir: Optional[Path] = None
    ocr: bool = False
    demote: Tuple[str, ...] = ()
    heading_policy: str = "auto"


@dataclass(frozen=True)
class ConversionResult:
    source: Path
    format: str
    ok: bool
    output_dir: Optional[Path] = None
    markdown: Optional[Path] = None
    diagnostic: str = ""


Adapter = Callable[[Path, ConversionOptions], ConversionResult]
Registry = Mapping[str, Adapter]


def _normalized_suffixes(suffixes):
    return {suffix.lower() if suffix.startswith(".") else "." + suffix.lower() for suffix in suffixes}


def _is_internal_source(source, scan_root):
    relative_parent_parts = source.relative_to(scan_root).parts[:-1]
    if "temp" in {part.lower() for part in relative_parent_parts}:
        return True
    sibling_md = source.parent / (source.stem + ".md")
    return source.parent.name == source.stem and sibling_md.exists()


def discover_sources(path, suffixes):
    """Return supported input files, excluding temp and published outputs."""
    source = Path(path)
    supported = _normalized_suffixes(suffixes)

    if source.is_file():
        if source.suffix.lower() not in supported:
            raise ValueError("不支持的文档格式: {}".format(source))
        return [source]

    if source.is_dir():
        found = [
            item
            for item in source.rglob("*")
            if item.is_file()
            and item.suffix.lower() in supported
            and not _is_internal_source(item, source)
        ]
        return sorted(found, key=lambda item: str(item).casefold())

    raise ValueError("路径不存在: {}".format(source))


def run_batch(path, options, registry):
    """Route all supported inputs and retain one result per source."""
    normalized_registry = {
        suffix.lower() if suffix.startswith(".") else "." + suffix.lower(): adapter
        for suffix, adapter in registry.items()
    }
    sources = discover_sources(path, normalized_registry.keys())
    results = []

    for source in sources:
        suffix = source.suffix.lower()
        try:
            result = normalized_registry[suffix](source, options)
        except Exception as exc:
            result = ConversionResult(
                source=source,
                format=suffix.lstrip("."),
                ok=False,
                diagnostic=str(exc),
            )
        results.append(result)

    return results
