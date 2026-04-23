"""git_review.py — md↔docx 审校桥的 git 封装层。

所有函数都走 subprocess 调真实 git 命令，不依赖 GitPython。
保持无状态：任何需要 repo 定位的函数都接受 `repo=` 参数。
"""
import json
import os
import subprocess
from typing import Optional, Tuple


class GitReviewError(RuntimeError):
    """git_review 层的错误。"""


# ──────────────────────────────────────────────────────────
# subprocess 辅助
# ──────────────────────────────────────────────────────────

def _git(args, repo: str, *, input_bytes: Optional[bytes] = None,
         env: Optional[dict] = None, capture: bool = True) -> bytes:
    """运行 git 命令，抛 GitReviewError 时带 stderr。"""
    try:
        proc = subprocess.run(
            ['git'] + list(args),
            cwd=repo,
            input=input_bytes,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE,
            env={**os.environ, **(env or {})},
            check=True,
        )
        return proc.stdout
    except subprocess.CalledProcessError as e:
        raise GitReviewError(
            f'git {" ".join(args)} failed: {e.stderr.decode("utf-8", "replace").strip()}'
        ) from e


def _rev_parse(ref: str, repo: str) -> str:
    out = _git(['rev-parse', '--verify', f'{ref}^{{commit}}'], repo=repo)
    return out.decode('ascii').strip()


# ──────────────────────────────────────────────────────────
# read_at
# ──────────────────────────────────────────────────────────

def read_at(sha: str, path: str, repo: str = '.') -> str:
    """`git show <sha>:<path>` 的 UTF-8 文本形式。"""
    out = _git(['show', f'{sha}:{path}'], repo=repo)
    return out.decode('utf-8')


# ──────────────────────────────────────────────────────────
# resolve_range
# ──────────────────────────────────────────────────────────

def resolve_range(arg: str, repo: str = '.',
                  state_path: str = '.review_state.json') -> Tuple[str, str]:
    """解析 CLI 传入的 commit 范围参数，返回 (base_sha, head_sha) 全 40 位。

    支持：
      - `<commit>`             → (<commit>^, <commit>)
      - `<base>..<head>`       → (<base>, <head>)
      - `--since-last-review`  → (state.last_exported_sha, HEAD)
    """
    if arg == '--since-last-review':
        if not os.path.exists(state_path):
            raise GitReviewError(
                f'--since-last-review 需要 {state_path}，但文件不存在')
        with open(state_path, 'r', encoding='utf-8') as f:
            state = json.load(f)
        last = state.get('last_exported_sha')
        if not last:
            raise GitReviewError(
                '--since-last-review: .review_state.json 里没有 last_exported_sha，'
                '请先运行一次具体 commit 的 export-review')
        head = _rev_parse('HEAD', repo=repo)
        base = _rev_parse(last, repo=repo)
        return base, head

    if '..' in arg:
        base_ref, head_ref = arg.split('..', 1)
        if not base_ref or not head_ref:
            raise GitReviewError(f'无效的 range 语法: {arg!r}')
        return _rev_parse(base_ref, repo=repo), _rev_parse(head_ref, repo=repo)

    head = _rev_parse(arg, repo=repo)
    base = _rev_parse(f'{arg}^', repo=repo)
    return base, head


# ──────────────────────────────────────────────────────────
# docx custom.xml 元数据
# ──────────────────────────────────────────────────────────

import zipfile
import shutil
from lxml import etree

_CUSTOM_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/custom-properties'
_VT_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'
_PROPS_FMTID = '{D5CDD505-2E9C-101B-9397-08002B2CF9AE}'
_CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
_RELS_NS = 'http://schemas.openxmlformats.org/package/2006/relationships'

_METADATA_KEYS = ('SourceGitCommit', 'SourceBaseCommit',
                  'SourcePath', 'ReviewExportedAt')


def _build_custom_xml(props: dict) -> bytes:
    nsmap = {None: _CUSTOM_NS, 'vt': _VT_NS}
    root = etree.Element('{%s}Properties' % _CUSTOM_NS, nsmap=nsmap)
    pid = 2  # pid 1 是保留值
    for name in _METADATA_KEYS:
        if name not in props:
            continue
        p = etree.SubElement(root, '{%s}property' % _CUSTOM_NS)
        p.set('fmtid', _PROPS_FMTID)
        p.set('pid', str(pid))
        p.set('name', name)
        v = etree.SubElement(p, '{%s}lpwstr' % _VT_NS)
        v.text = props[name]
        pid += 1
    return etree.tostring(root, xml_declaration=True,
                          encoding='UTF-8', standalone=True)


def stamp_docx_metadata(docx_path: str,
                        source_git_commit: str,
                        source_base_commit: str,
                        source_path: str,
                        exported_at: str) -> None:
    """把 4 项元数据写入 docx 的 docProps/custom.xml（必要时也更新
    [Content_Types].xml 与 _rels/.rels，使 Word 能识别该 part）。"""
    props = {
        'SourceGitCommit':   source_git_commit,
        'SourceBaseCommit':  source_base_commit,
        'SourcePath':        source_path,
        'ReviewExportedAt':  exported_at,
    }
    new_xml = _build_custom_xml(props)

    tmp_path = docx_path + '.tmp'
    with zipfile.ZipFile(docx_path, 'r') as zin, \
         zipfile.ZipFile(tmp_path, 'w', zipfile.ZIP_DEFLATED) as zout:
        # 1. 复制除 custom.xml / [Content_Types].xml / _rels/.rels 外的全部文件
        for item in zin.infolist():
            if item.filename in ('docProps/custom.xml',
                                 '[Content_Types].xml',
                                 '_rels/.rels'):
                continue
            zout.writestr(item, zin.read(item.filename))

        # 2. 写新的 custom.xml
        zout.writestr('docProps/custom.xml', new_xml)

        # 3. 更新 [Content_Types].xml 确保声明 custom.xml
        ct_src = zin.read('[Content_Types].xml')
        ct_root = etree.fromstring(ct_src)
        want_pn = '/docProps/custom.xml'
        already_declared = any(
            o.get('PartName') == want_pn
            for o in ct_root.findall('{%s}Override' % _CT_NS)
        )
        if not already_declared:
            o = etree.SubElement(ct_root, '{%s}Override' % _CT_NS)
            o.set('PartName', want_pn)
            o.set('ContentType',
                  'application/vnd.openxmlformats-officedocument.custom-properties+xml')
        zout.writestr('[Content_Types].xml',
                      etree.tostring(ct_root, xml_declaration=True,
                                     encoding='UTF-8', standalone=True))

        # 4. 更新 _rels/.rels 确保有 Relationship 指向 custom.xml
        rels_src = zin.read('_rels/.rels')
        rels_root = etree.fromstring(rels_src)
        want_target = 'docProps/custom.xml'
        have = any(
            r.get('Target') == want_target
            for r in rels_root.findall('{%s}Relationship' % _RELS_NS)
        )
        if not have:
            existing_ids = [r.get('Id') for r in rels_root
                            if r.get('Id') and r.get('Id').startswith('rId')]
            max_id = max((int(x[3:]) for x in existing_ids), default=0)
            rel = etree.SubElement(rels_root, '{%s}Relationship' % _RELS_NS)
            rel.set('Id', f'rId{max_id + 1}')
            rel.set('Type', 'http://schemas.openxmlformats.org/'
                           'officeDocument/2006/relationships/custom-properties')
            rel.set('Target', want_target)
        zout.writestr('_rels/.rels',
                      etree.tostring(rels_root, xml_declaration=True,
                                     encoding='UTF-8', standalone=True))

    shutil.move(tmp_path, docx_path)


def read_docx_metadata(docx_path: str) -> dict:
    """回读 docProps/custom.xml 的 4 个键；若 part 不存在返回 {}"""
    try:
        with zipfile.ZipFile(docx_path, 'r') as z:
            if 'docProps/custom.xml' not in z.namelist():
                return {}
            data = z.read('docProps/custom.xml')
    except zipfile.BadZipFile as e:
        raise GitReviewError(f'不是合法的 docx（zip）文件: {docx_path}') from e

    root = etree.fromstring(data)
    result = {}
    for p in root.findall('{%s}property' % _CUSTOM_NS):
        name = p.get('name')
        val_el = p.find('{%s}lpwstr' % _VT_NS)
        if name in _METADATA_KEYS and val_el is not None and val_el.text:
            result[name] = val_el.text
    return result


# ──────────────────────────────────────────────────────────
# resolve_baseline 四级回退
# ──────────────────────────────────────────────────────────

import re

_FILENAME_SHA_RE = re.compile(r'_([0-9a-f]{7,40})\.docx$', re.IGNORECASE)


def _try_rev_parse(ref: str, repo: str) -> Optional[str]:
    try:
        return _rev_parse(ref, repo=repo)
    except GitReviewError:
        return None


def _path_exists_at(sha: str, path: str, repo: str) -> bool:
    try:
        _git(['cat-file', '-e', f'{sha}:{path}'], repo=repo)
        return True
    except GitReviewError:
        return False


def resolve_baseline(docx_path: str,
                     repo: str = '.',
                     cli_base: Optional[str] = None,
                     cli_path: Optional[str] = None) -> Tuple[str, str, str]:
    """四级回退确定基线：
      1. custom.xml 中的 SourceGitCommit / SourcePath
      2. 文件名匹配 *_<sha7+>.docx；path 走 cli_path
      3. sidecar 文件 <docx_path>.base（首行 sha）；path 走 cli_path
      4. cli_base + cli_path
    全都失败 → GitReviewError。
    返回 (base_sha_full40, source_path, source_kind)。
    """
    # 1. metadata
    try:
        meta = read_docx_metadata(docx_path)
    except GitReviewError:
        meta = {}
    if meta.get('SourceGitCommit') and meta.get('SourcePath'):
        sha = _try_rev_parse(meta['SourceGitCommit'], repo=repo)
        if sha is not None:
            if not _path_exists_at(sha, meta['SourcePath'], repo=repo):
                raise GitReviewError(
                    f"metadata 的 SourceGitCommit={meta['SourceGitCommit'][:7]} "
                    f"在仓库里存在，但其 SourcePath={meta['SourcePath']} 不存在；"
                    "sha 与 path 不匹配")
            return sha, meta['SourcePath'], 'metadata'

    # 2. 文件名
    m = _FILENAME_SHA_RE.search(os.path.basename(docx_path))
    if m and cli_path:
        sha = _try_rev_parse(m.group(1), repo=repo)
        if sha is not None and _path_exists_at(sha, cli_path, repo=repo):
            return sha, cli_path, 'filename'

    # 3. sidecar
    sidecar = docx_path + '.base'
    if os.path.exists(sidecar) and cli_path:
        with open(sidecar, 'r', encoding='utf-8') as f:
            content = f.readline().strip()
        sha = _try_rev_parse(content, repo=repo)
        if sha is not None and _path_exists_at(sha, cli_path, repo=repo):
            return sha, cli_path, 'sidecar'

    # 4. CLI
    if cli_base and cli_path:
        sha = _try_rev_parse(cli_base, repo=repo)
        if sha is not None and _path_exists_at(sha, cli_path, repo=repo):
            return sha, cli_path, 'cli'

    raise GitReviewError(
        'resolve_baseline 四级回退全部失败：metadata/filename/sidecar/cli 都未命中。'
        '请使用 --base <sha> --path <relpath> 明确指定。'
    )
