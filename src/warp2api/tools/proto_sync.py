#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Proto sync/check tooling for warp2api."""

from __future__ import annotations

import argparse
import difflib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable

from grpc_tools import protoc


ROOT_DIR = Path(__file__).resolve().parents[3]
PROTO_DIR = ROOT_DIR / "src" / "warp2api" / "proto"
DEFAULT_EXTRACT_REPO = "https://github.com/CrazyMelody/Warp.dev-Proto-Extract.git"
REQUIRED_PROTO_FILES = (
    "request.proto",
    "response.proto",
    "task.proto",
    "attachment.proto",
    "file_content.proto",
    "input_context.proto",
    "citations.proto",
)


def _list_proto_files(base: Path) -> list[Path]:
    return sorted(base.glob("*.proto"))


def _assert_required_files(base: Path) -> None:
    missing = [name for name in REQUIRED_PROTO_FILES if not (base / name).exists()]
    if missing:
        raise RuntimeError(f"missing required proto files: {', '.join(missing)}")


def _grpc_include_dir() -> Path:
    from importlib.resources import files as pkg_files

    return Path(str(pkg_files("grpc_tools").joinpath("_proto")))


def _compile_descriptor(base: Path) -> None:
    files = _list_proto_files(base)
    if not files:
        raise RuntimeError(f"no .proto files found in {base}")

    outdir = Path(tempfile.mkdtemp(prefix="w2a_desc_"))
    out = outdir / "bundle.pb"
    args = [
        "protoc",
        f"-I{base}",
        f"-I{_grpc_include_dir()}",
        f"--descriptor_set_out={out}",
        "--include_imports",
        *[str(p) for p in files],
    ]
    rc = protoc.main(args)
    if rc != 0 or not out.exists():
        raise RuntimeError("protoc compile failed")


def cmd_check(_: argparse.Namespace) -> int:
    _assert_required_files(PROTO_DIR)
    _compile_descriptor(PROTO_DIR)
    print(f"[ok] proto check passed: {PROTO_DIR}")
    return 0


def _diff_file(a: Path, b: Path) -> Iterable[str]:
    a_lines = a.read_text(encoding="utf-8").splitlines(keepends=True)
    b_lines = b.read_text(encoding="utf-8").splitlines(keepends=True)
    return difflib.unified_diff(
        a_lines,
        b_lines,
        fromfile=str(a),
        tofile=str(b),
    )


def cmd_diff(args: argparse.Namespace) -> int:
    against = Path(args.against).expanduser().resolve()
    if not against.exists():
        print(f"[err] against path not found: {against}", file=sys.stderr)
        return 2

    project_files = {p.name: p for p in _list_proto_files(PROTO_DIR)}
    other_files = {p.name: p for p in _list_proto_files(against)}

    all_names = sorted(set(project_files.keys()) | set(other_files.keys()))
    changes = 0

    for name in all_names:
        p = project_files.get(name)
        o = other_files.get(name)
        if p is None:
            print(f"[add] only in against: {name}")
            changes += 1
            continue
        if o is None:
            print(f"[del] only in project: {name}")
            changes += 1
            continue
        if p.read_bytes() != o.read_bytes():
            print(f"[mod] {name}")
            if args.show_patch:
                for line in _diff_file(p, o):
                    sys.stdout.write(line)
            changes += 1

    if changes == 0:
        print("[ok] no proto diff")
        return 0
    print(f"[warn] proto diff count: {changes}")
    return 1


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _copy_proto_files(from_dir: Path, to_dir: Path) -> int:
    to_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in sorted(from_dir.glob("*.proto")):
        shutil.copy2(src, to_dir / src.name)
        copied += 1
    return copied


def cmd_extract(args: argparse.Namespace) -> int:
    out = Path(args.output).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    tmp = Path(tempfile.mkdtemp(prefix="w2a_extract_"))
    repo_dir = tmp / "extractor"
    _run(["git", "clone", "--depth=1", args.repo, str(repo_dir)])

    extractor = repo_dir / "extract_warp_protos.py"
    if not extractor.exists():
        raise RuntimeError("extract_warp_protos.py not found in extractor repo")

    cmd = [sys.executable, str(extractor), "--output", str(out)]
    if args.warp_binary:
        cmd.append(str(Path(args.warp_binary).expanduser().resolve()))
    _run(cmd, cwd=repo_dir)

    if args.apply:
        copied = _copy_proto_files(out, PROTO_DIR)
        print(f"[ok] applied {copied} proto files to {PROTO_DIR}")
    else:
        print(f"[ok] extracted proto files to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="warp2api proto sync/check utility")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="validate required files and protoc compile")
    p_check.set_defaults(func=cmd_check)

    p_diff = sub.add_parser("diff", help="diff project proto with another proto directory")
    p_diff.add_argument("--against", required=True, help="path to proto directory for compare")
    p_diff.add_argument("--show-patch", action="store_true", help="print unified diff")
    p_diff.set_defaults(func=cmd_diff)

    p_extract = sub.add_parser("extract", help="extract proto files from Warp binary")
    p_extract.add_argument(
        "--repo",
        default=DEFAULT_EXTRACT_REPO,
        help="proto extractor repository url",
    )
    p_extract.add_argument(
        "--output",
        default=str(ROOT_DIR / ".cache" / "warp_proto_extract"),
        help="directory to store extracted proto files",
    )
    p_extract.add_argument(
        "--warp-binary",
        default="",
        help="path to Warp binary, use extractor default when empty",
    )
    p_extract.add_argument("--apply", action="store_true", help="copy extracted proto into project")
    p_extract.set_defaults(func=cmd_extract)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()

