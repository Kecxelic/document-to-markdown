"""MinerU API PDF→MD 转换管道（阶段1）。

功能:
    - 接受文件或文件夹路径（文件夹递归找所有 PDF）
    - 超过 --chunk-size 页的 PDF 自动分块上传，结果合并
    - 批量上传到 MinerU API（vlm 模型，支持公式+表格）
    - 轮询解析结果
    - 下载 ZIP 解压
    - 原始 MinerU 结果写到 <pdf所在目录>/temp/minerU_trans/<book>/
    - 清理结果写到 <pdf所在目录>/temp/清理冗余/<book>/<book>.md + images/

阶段2（大纲修复 + 最终发布）由 fix_outline.py 执行，不在本脚本范围。

Token:
    仅从 ~/.mineru/mineru.conf 读取（写一行：mineru_token=<your_token>）。
    未找到 token 时拒绝执行 PDF→MD 转换。

用法:
    python scripts/mineru_convert.py <pdf_or_folder>
    python scripts/mineru_convert.py <pdf_or_folder> --no-upload

可选:
    --model          MinerU 模型版本（默认 vlm）
    --language       文档语言（默认 en）
    --chunk-size     超页 PDF 分块页数（默认 180，MinerU 当前 API 管理文档单文件上限 200 页）
    --no-upload      跳过上传，只处理已下载的 ZIP（重试用）
    --work-dir       中间工作目录（默认 <输入目录>/temp/minerU_trans/.work/）
"""

import json
import hashlib
import os
import time
import shutil
import zipfile
import urllib.request
import urllib.error
import http.client
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    from pypdf import PdfReader, PdfWriter
    _HAS_PYPDF = True
except ImportError:
    _HAS_PYPDF = False


BASE_URL = "https://mineru.net"
FILE_URLS_BATCH = "/api/v4/file-urls/batch"
BATCH_RESULTS = "/api/v4/extract-results/batch"
FINISHED_STATES = {"done", "failed"}

# skill 目录：scripts/ 的父目录
SKILL_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR_NAME = "temp"
RAW_DIR_NAME = "minerU_trans"
CLEAN_DIR_NAME = "清理冗余"


def load_token():
    """从 ~/.mineru/mineru.conf 读取 token；找不到则拒绝执行。

    仅此一个来源。无 token 时 PDF→MD 转换不允许执行。
    """
    conf = Path.home() / ".mineru" / "mineru.conf"
    if conf.exists():
        try:
            text = conf.read_text(encoding="utf-8")
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("mineru_token="):
                    tok = line.split("=", 1)[1].strip()
                    if tok:
                        return tok
        except OSError:
            pass

    raise RuntimeError(
        "MinerU token 未找到，PDF→MD 转换不允许执行。\n"
        "请到 https://mineru.net/apiManage/token 创建 key，然后创建配置文件（唯一方式）：\n"
        "  {conf}\n"
        "内容写一行：mineru_token=<your_token>".format(conf=conf)
    )


def collect_pdfs(path):
    """返回要转换的 PDF Path 列表。文件→单个；文件夹→递归所有 PDF。"""
    p = Path(path)
    if p.is_file():
        if p.suffix.lower() != ".pdf":
            raise ValueError("不是 PDF 文件：{}".format(path))
        return [p]
    if p.is_dir():
        return sorted(
            f for f in p.rglob("*")
            if f.is_file() and f.suffix.lower() == ".pdf" and not is_internal_pdf(f)
        )
    raise ValueError("路径不存在：{}".format(path))


def is_internal_pdf(pdf_path):
    """跳过 temp 中间产物和已发布到 <book>/<book>.pdf 的成品 PDF。"""
    parts = {part.lower() for part in pdf_path.parts}
    if TEMP_DIR_NAME.lower() in parts:
        return True
    sibling_md = pdf_path.parent / (pdf_path.stem + ".md")
    return pdf_path.parent.name == pdf_path.stem and sibling_md.exists()


def trim_windows_name(value):
    """Windows 目录/文件名不应以空格或点结尾。"""
    return value.rstrip(" .")


def stem_before_pdf(name):
    """沿用旧 C++ 工具规则：目录名里第一次 .pdf 之前的部分作为书名。"""
    lowered = name.lower()
    pos = lowered.find(".pdf")
    if pos == -1:
        trimmed = trim_windows_name(name)
    else:
        trimmed = trim_windows_name(name[:pos])
    return trimmed or trim_windows_name(name)


def book_stem_for_pdf(pdf_path):
    return stem_before_pdf(Path(pdf_path).name)


def stage1_paths(pdf_path):
    pdf_path = Path(pdf_path)
    book = book_stem_for_pdf(pdf_path)
    temp_dir = pdf_path.parent / TEMP_DIR_NAME
    raw_dir = temp_dir / RAW_DIR_NAME / book
    clean_dir = temp_dir / CLEAN_DIR_NAME / book
    clean_md = clean_dir / (book + ".md")
    return book, raw_dir, clean_dir, clean_md


def default_work_dir(input_path):
    p = Path(input_path)
    base = p.parent if p.is_file() else p
    return base / TEMP_DIR_NAME / RAW_DIR_NAME / ".work"


def ensure_absent(path, label):
    path = Path(path)
    if path.exists():
        raise RuntimeError("{} already exists, refusing to overwrite: {}".format(label, path))


def count_pdf_pages(pdf_path):
    """用 pypdf 数 PDF 页数。pypdf 不可用或解析失败返回 -1（按单文件处理交给 MinerU 判）。"""
    if not _HAS_PYPDF:
        return -1
    try:
        reader = PdfReader(str(pdf_path))
        return len(reader.pages)
    except Exception as e:
        print("  WARN: cannot count pages for {}: {}".format(pdf_path.name, e))
        return -1


def split_pdf(pdf_path, chunk_size, dest_dir):
    """把 PDF 按 chunk_size 页切成多份，返回 chunk 文件路径列表。"""
    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)
    chunks = []
    idx = 0
    for start in range(0, total, chunk_size):
        idx += 1
        writer = PdfWriter()
        for page in reader.pages[start:start + chunk_size]:
            writer.add_page(page)
        chunk_path = dest_dir / "{}_part{:02d}.pdf".format(pdf_path.stem, idx)
        with open(chunk_path, "wb") as f:
            writer.write(f)
        chunks.append(chunk_path)
    return chunks


def prepare_jobs(pdfs, chunk_size, work_dir):
    """每个 PDF → 1 或多个 job（超 chunk_size 页的分块）。返回 job 列表。

    job = {pdf, upload_path, name, part, total_parts, stem}
    """
    if not _HAS_PYPDF:
        print("  (pypdf 未安装，跳过超页分块；>200 页的 PDF 可能会 MinerU 端失败)")
    work_dir = Path(work_dir)
    chunks_dir = work_dir / "chunks"
    jobs = []
    for pdf in pdfs:
        pages = count_pdf_pages(pdf)
        if pages <= 0 or pages <= chunk_size:
            jobs.append({
                "pdf": pdf, "upload_path": pdf, "name": pdf.name,
                "part": 1, "total_parts": 1, "stem": pdf.stem,
            })
        else:
            print("  {} : {} pages, splitting by {}...".format(pdf.name, pages, chunk_size))
            chunks_dir.mkdir(parents=True, exist_ok=True)
            chunk_paths = split_pdf(pdf, chunk_size, chunks_dir)
            total = len(chunk_paths)
            for i, cp in enumerate(chunk_paths, 1):
                name = "{}_part{:02d}of{:02d}.pdf".format(pdf.stem, i, total)
                jobs.append({
                    "pdf": pdf, "upload_path": cp, "name": name,
                    "part": i, "total_parts": total, "stem": pdf.stem,
                })
            print("    -> {} parts".format(total))
    return jobs


def api_request(method, endpoint, token, payload=None, timeout=60):
    url = BASE_URL + endpoint
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    headers = {"Authorization": "Bearer " + token, "Accept": "*/*"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        msg = "HTTP {} {}: {}".format(exc.code, url, body[:300])
        if exc.code == 401:
            msg += (
                "\nMinerU token 缺失或已过期。"
                "请到 https://mineru.net/apiManage/token 重新创建 key，"
                "并更新 ~/.mineru/mineru.conf 中的 mineru_token。"
            )
        raise RuntimeError(msg)


def upload_to_signed_url(upload_url, file_path):
    parsed = urlsplit(upload_url)
    path_query = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(parsed.netloc, timeout=300)
    try:
        with open(file_path, "rb") as f:
            # 2026-09-23 实测：MinerU 预签名 URL 的签名不含 Content-Type，
            # PUT 时带任何 Content-Type 都会被 OSS 拒绝（403/SignatureDoesNotMatch），必须裸 PUT
            conn.request("PUT", path_query, body=f.read())
        resp = conn.getresponse()
        resp.read()
        if resp.status not in (200, 201, 204):
            raise RuntimeError("Upload failed HTTP {}: {}".format(resp.status, file_path))
    finally:
        conn.close()


def data_id_for_job(job):
    """Return a stable MinerU data_id within the API's 128-character limit."""
    identity = "{}|{}|{}".format(
        job.get("upload_path", job["name"]),
        job.get("part", 1),
        job.get("total_parts", 1),
    )
    digest = hashlib.sha256(str(identity).encode("utf-8")).hexdigest()
    return "document-{}-p{}of{}".format(
        digest,
        job.get("part", 1),
        job.get("total_parts", 1),
    )


def batch_upload_and_convert(jobs, token, model, language, work_dir):
    """上传 job 批次并等待解析完成，返回结果列表。"""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # 分批（MinerU 限 50 文件/分钟，用 40 留余量）
    batches = [jobs[i:i + 40] for i in range(0, len(jobs), 40)]
    all_results = []

    for bi, batch in enumerate(batches):
        print("\n=== Batch {}/{} ({} files) ===".format(bi + 1, len(batches), len(batch)))
        files_payload = [{"name": j["name"], "data_id": data_id_for_job(j)} for j in batch]
        payload = {
            "files": files_payload,
            "model_version": model,
            "enable_formula": True,
            "enable_table": True,
            "language": language,
        }
        resp = api_request("POST", FILE_URLS_BATCH, token, payload)
        if resp.get("code") != 0:
            print("ERROR: batch apply failed:", resp)
            if bi < len(batches) - 1:
                print("  waiting 60s before retry...")
                time.sleep(60)
            continue

        batch_id = resp["data"]["batch_id"]
        upload_urls = resp["data"]["file_urls"]
        print("batch_id:", batch_id)

        for j, url in zip(batch, upload_urls):
            print("  uploading:", j["name"])
            upload_to_signed_url(url, str(j["upload_path"]))

        print("  polling for results...")
        results = poll_batch(batch_id, token)
        all_results.extend(results)

        if bi < len(batches) - 1:
            print("  waiting 30s before next batch...")
            time.sleep(30)

    return all_results


def poll_batch(batch_id, token, poll_interval=15, timeout=7200):
    deadline = time.monotonic() + timeout
    endpoint = BATCH_RESULTS + "/" + batch_id
    while True:
        resp = api_request("GET", endpoint, token)
        if resp.get("code") != 0:
            print("  poll error:", resp.get("msg", ""))
            time.sleep(poll_interval)
            continue
        results = resp.get("data", {}).get("extract_result", [])
        if results and all(r.get("state") in FINISHED_STATES for r in results):
            done = sum(1 for r in results if r.get("state") == "done")
            failed = sum(1 for r in results if r.get("state") == "failed")
            print("  COMPLETE: {} done, {} failed".format(done, failed))
            return results
        states = ["{}={}".format(r.get("file_name", "?")[:20], r.get("state", "?")) for r in results[:5]]
        print("  [{}s] {}".format(int(time.monotonic() % 60), ", ".join(states)))
        if time.monotonic() > deadline:
            raise TimeoutError("Batch {} timed out".format(batch_id))
        time.sleep(poll_interval)


def download_zip(url, out_path, max_retries=3):
    """用 http.client 下载 ZIP（urllib 对某些 CDN SSL 有问题）。"""
    parsed = urlsplit(url)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    path_query = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    last_err = None
    for attempt in range(max_retries):
        conn = conn_cls(parsed.netloc, timeout=300)
        try:
            conn.request("GET", path_query, headers={"Accept": "*/*"})
            resp = conn.getresponse()
            data = resp.read()
            if resp.status == 200 and len(data) > 100:
                with open(out_path, "wb") as f:
                    f.write(data)
                return
            last_err = "HTTP {} size {}".format(resp.status, len(data))
        except Exception as e:
            last_err = str(e)
            time.sleep(3)
        finally:
            conn.close()
    raise RuntimeError("Download failed after {} retries: {} ({})".format(max_retries, url[:80], last_err))


def find_full_md_dir(extract_dir):
    """递归找含 full.md 的目录。"""
    for root, dirs, files in os.walk(extract_dir):
        if "full.md" in files:
            return root
    return None


def merge_chunk_outputs(chunk_mineru_dirs, dest_dir):
    """合并多个 chunk 的 MinerU 输出到 dest_dir。

    - full.md: 按部分顺序拼接
    - images/: 合并（SHA-256 命名，基本不冲突）
    - parts/: 每个 chunk 的完整原始输出保留
    """
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    # 合并 full.md（按 part 顺序拼接）
    merged_md = dest / "full.md"
    with open(merged_md, "wb") as out:
        for i, mdir in enumerate(chunk_mineru_dirs):
            fmd = Path(mdir) / "full.md"
            if fmd.exists():
                if i > 0:
                    out.write(b"\n\n")
                out.write(fmd.read_bytes())

    # 合并 images/
    dest_images = dest / "images"
    dest_images.mkdir(exist_ok=True)
    for mdir in chunk_mineru_dirs:
        src_images = Path(mdir) / "images"
        if src_images.is_dir():
            for img in src_images.iterdir():
                dst_img = dest_images / img.name
                if not dst_img.exists():
                    shutil.copy2(img, dst_img)

    # parts/ 保留每个 chunk 的完整原始输出（审计/重跑用）
    parts_dir = dest / "parts"
    parts_dir.mkdir(exist_ok=True)
    for i, mdir in enumerate(chunk_mineru_dirs, 1):
        part_dest = parts_dir / "part{:02d}".format(i)
        if part_dest.exists():
            shutil.rmtree(part_dest)
        shutil.copytree(mdir, part_dest)


def create_clean_output(raw_dir, pdf_path):
    """从原始 MinerU 目录产出 temp/清理冗余/<book>/<book>.md + images/。

    只保留阶段2需要的 Markdown 和图片；JSON、PDF、分块审计目录留在 minerU_trans。
    """
    raw_dir = Path(raw_dir)
    book, _, clean_dir, clean_md = stage1_paths(pdf_path)
    ensure_absent(clean_dir, "clean output directory")
    src_md = raw_dir / "full.md"
    if not src_md.exists():
        raise RuntimeError("full.md not found in raw MinerU output: {}".format(raw_dir))

    clean_dir.mkdir(parents=True)
    shutil.copy2(src_md, clean_md)

    img_src = raw_dir / "images"
    if img_src.is_dir():
        shutil.copytree(img_src, clean_dir / "images")

    return clean_dir


def process_all(jobs, results, work_dir):
    """下载 ZIP → 提取 → 合并（多部分）→ 写 temp/minerU_trans + temp/清理冗余。"""
    work_dir = Path(work_dir)

    # 按原 PDF 分组 jobs
    pdf_to_jobs = {}
    for job in jobs:
        pdf_to_jobs.setdefault(job["pdf"], []).append(job)

    converted = []
    for pdf in pdf_to_jobs:
        pdf_jobs = sorted(pdf_to_jobs[pdf], key=lambda j: j["part"])

        # 收集成功的 part 结果
        part_results = []
        for job in pdf_jobs:
            r = next((r for r in results if r.get("file_name") == job["name"]), None)
            if r is None:
                continue
            if r.get("state") != "done":
                print("SKIP ({}): {}".format(r.get("state"), job["name"]))
                continue
            part_results.append((job, r))

        if not part_results:
            print("SKIP (no successful parts): {}".format(pdf.name))
            continue

        # 下载 + 提取每个 part
        chunk_mineru_dirs = []
        for job, r in part_results:
            zip_url = r.get("full_zip_url", "")
            if not zip_url:
                continue
            part_stem = Path(job["name"]).stem
            zip_path = work_dir / (part_stem + ".zip")
            extract_dir = work_dir / "extracted" / part_stem
            if not extract_dir.exists():
                print("  downloading:", job["name"])
                download_zip(zip_url, str(zip_path))
                extract_dir.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(extract_dir)
            mdir = find_full_md_dir(extract_dir)
            if mdir:
                chunk_mineru_dirs.append(mdir)

        if not chunk_mineru_dirs:
            print("  WARNING: no full.md in any part of {}".format(pdf.name))
            continue

        # 输出到 <pdf所在目录>/temp/minerU_trans/<book>/
        book, raw_dir, _, _ = stage1_paths(pdf)
        ensure_absent(raw_dir, "raw MinerU output directory")

        if len(chunk_mineru_dirs) == 1:
            raw_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(chunk_mineru_dirs[0], raw_dir)
        else:
            merge_chunk_outputs(chunk_mineru_dirs, raw_dir)

        clean_dir = create_clean_output(raw_dir, pdf)
        print("  minerU_trans:", raw_dir)
        print("  clean:", clean_dir)

        nparts = len(chunk_mineru_dirs)
        converted.append({"stem": book, "pdf": str(pdf), "parts": nparts})
        print("  CONVERTED: {}{}".format(book, " ({} parts merged)".format(nparts) if nparts > 1 else ""))

    return converted


def run(path, model="vlm", language="en", chunk_size=180, no_upload=False, work_dir=None):
    """Run the established MinerU stage and return converted item records."""
    work_dir = Path(work_dir) if work_dir else default_work_dir(path)

    pdfs = collect_pdfs(path)
    print("Found {} PDF(s) to convert".format(len(pdfs)))
    for pdf in pdfs:
        print("  ", pdf)

    if not pdfs:
        print("No PDFs found")
        return []

    jobs = prepare_jobs(pdfs, chunk_size, work_dir)
    if len(jobs) > len(pdfs):
        print("\n{} PDF(s) split into {} parts total".format(len(pdfs), len(jobs)))

    if not no_upload:
        token = load_token()
        results = batch_upload_and_convert(jobs, token, model, language, work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)
        with open(work_dir / "last_results.json", "w") as output:
            json.dump(results, output, indent=2)
    else:
        with open(work_dir / "last_results.json", "r") as saved:
            results = json.load(saved)

    converted = process_all(jobs, results, work_dir)

    print("\n=== CONVERSION SUMMARY ===")
    print("Converted: {} / {}".format(len(converted), len(pdfs)))
    for item in converted:
        suffix = " ({} parts merged)".format(item["parts"]) if item["parts"] > 1 else ""
        print("  ", item["stem"] + suffix, "->", item["pdf"])
    return converted


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MinerU PDF→MD 转换（阶段1）。输出 temp/minerU_trans 和 temp/清理冗余。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", help="PDF 文件路径，或文件夹路径（递归其下所有 PDF）")
    parser.add_argument("--model", default="vlm", help="MinerU 模型（默认 vlm）")
    parser.add_argument("--language", default="en", help="文档语言（默认 en）")
    parser.add_argument("--chunk-size", type=int, default=180, help="超页 PDF 分块页数（默认 180，MinerU 当前 API 管理文档上限 200 页）")
    parser.add_argument("--no-upload", action="store_true", help="跳过上传，只处理已下载的 ZIP")
    parser.add_argument("--work-dir", default=None, help="中间工作目录（默认 <输入目录>/temp/minerU_trans/.work/）")
    args = parser.parse_args()

    try:
        run(
            args.path,
            model=args.model,
            language=args.language,
            chunk_size=args.chunk_size,
            no_upload=args.no_upload,
            work_dir=args.work_dir,
        )
    except (RuntimeError, ValueError) as e:
        print("ERROR:", e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
