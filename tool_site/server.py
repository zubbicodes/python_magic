from __future__ import annotations

import ast
import base64
import json
import mimetypes
import os
import shlex
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


WEB_DIR = Path(__file__).resolve().parent
SCRIPTS_ROOT = WEB_DIR.parent

EXCLUDED_DIR_NAMES = {
    ".venv",
    "venv",
    "__pycache__",
    "site-packages",
    "tool_site",
}

DEFAULT_TIMEOUT_SECONDS = 300
MAX_OUTPUT_CHARS = 200_000
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
API_KEY = os.environ.get("TOOL_SITE_API_KEY", "").strip()


@dataclass(frozen=True)
class ScriptInfo:
    rel_path: str
    name: str
    folder: str
    description: str | None
    display_name: str
    summary: str | None
    ui: dict[str, Any] | None


TOOL_CATALOG: dict[str, dict[str, Any]] = {
    "WEBP/convert.py": {
        "displayName": "Convert Images to WebP",
        "summary": "Upload images and get a ZIP of .webp outputs.",
        "ui": {
            "mode": "guided",
            "inputs": [
                {
                    "key": "images",
                    "label": "Images",
                    "type": "files",
                    "required": True,
                    "accept": [
                        ".png",
                        ".jpg",
                        ".jpeg",
                        ".bmp",
                        ".tif",
                        ".tiff",
                        ".gif",
                        ".webp",
                    ],
                    "multiple": True,
                },
                {"key": "quality", "label": "Quality (0-100)", "type": "number", "min": 0, "max": 100, "value": 80},
                {"key": "method", "label": "Method (0-6)", "type": "number", "min": 0, "max": 6, "value": 6},
                {"key": "lossless", "label": "Lossless", "type": "boolean", "value": False},
            ],
            "artifact": {"filename": "webp_output.zip", "mime": "application/zip"},
        },
    },
    "XLXS_JSON/convert.py": {
        "displayName": "Excel (.xlsx) to JSON",
        "summary": "Upload an Excel file and download JSON.",
        "ui": {
            "mode": "guided",
            "inputs": [
                {"key": "xlsx", "label": "Excel file (.xlsx)", "type": "file", "required": True, "accept": [".xlsx"]},
                {"key": "outputName", "label": "Output filename", "type": "text", "value": "output.json"},
            ],
            "artifact": {"filenameFromInputKey": "outputName", "mime": "application/json"},
        },
    },
    "WEBP/getinfo.py": {
        "displayName": "Website Text Extract (Markdown)",
        "summary": "Crawl a website and export visible text to a .md file.",
        "ui": {
            "mode": "guided",
            "inputs": [
                {"key": "url", "label": "Website URL", "type": "url", "required": True, "value": "https://adsons.net/"},
                {"key": "outputName", "label": "Output filename", "type": "text", "value": "info.md"},
            ],
            "artifact": {"filenameFromInputKey": "outputName", "mime": "text/markdown"},
        },
    },
}


def _safe_relpath(path: Path, root: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except Exception:
        return str(path.name)
    return rel.as_posix()


def _read_module_docstring_first_line(py_path: Path) -> str | None:
    try:
        source = py_path.read_text(encoding="utf-8")
    except Exception:
        try:
            source = py_path.read_text(encoding="utf-8-sig")
        except Exception:
            return None

    try:
        module = ast.parse(source)
    except Exception:
        return None

    doc = ast.get_docstring(module)
    if not doc:
        return None
    first = doc.strip().splitlines()[0].strip()
    return first or None


def _title_from_stem(stem: str) -> str:
    stem = stem.replace("-", " ").replace("_", " ").strip()
    if not stem:
        return "Python Script"
    return " ".join(word.capitalize() for word in stem.split())


def list_python_scripts() -> list[ScriptInfo]:
    scripts: list[ScriptInfo] = []

    for dirpath, dirnames, filenames in os.walk(SCRIPTS_ROOT, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]

        for filename in filenames:
            if not filename.lower().endswith(".py"):
                continue

            py_path = Path(dirpath) / filename
            if py_path.resolve() == Path(__file__).resolve():
                continue

            rel_path = _safe_relpath(py_path, SCRIPTS_ROOT)
            tool_meta = TOOL_CATALOG.get(rel_path)
            display_name = tool_meta.get("displayName") if isinstance(tool_meta, dict) else None
            if not display_name:
                display_name = _title_from_stem(py_path.stem)
            summary = tool_meta.get("summary") if isinstance(tool_meta, dict) else None
            ui = tool_meta.get("ui") if isinstance(tool_meta, dict) else None
            scripts.append(
                ScriptInfo(
                    rel_path=rel_path,
                    name=py_path.stem,
                    folder=_safe_relpath(py_path.parent, SCRIPTS_ROOT),
                    description=_read_module_docstring_first_line(py_path),
                    display_name=str(display_name),
                    summary=str(summary) if isinstance(summary, str) else None,
                    ui=ui if isinstance(ui, dict) else None,
                )
            )

    scripts.sort(key=lambda s: s.rel_path.lower())
    return scripts


def _is_under_root(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except Exception:
        return False
    return True


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + "\n\n[output truncated]"


def _b64_decode(data_b64: str) -> bytes:
    return base64.b64decode(data_b64.encode("utf-8"), validate=False)


def _b64_encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _guess_mime(filename: str, fallback: str) -> str:
    mt, _ = mimetypes.guess_type(filename)
    return mt or fallback


def _python_for_script(script_path: Path) -> Path:
    venv_dir = script_path.parent / ".venv"
    if os.name == "nt":
        candidate = venv_dir / "Scripts" / "python.exe"
    else:
        candidate = venv_dir / "bin" / "python"
    if candidate.exists():
        return candidate
    return Path(sys.executable).resolve()


def _write_uploaded_files(temp_dir: Path, files: Any) -> dict[str, list[Path]]:
    if files is None:
        return {}
    if not isinstance(files, dict):
        raise ValueError("files must be an object")

    total_bytes = 0
    written: dict[str, list[Path]] = {}

    for key, entries in files.items():
        if not isinstance(key, str):
            continue
        if entries is None:
            continue
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            raise ValueError(f"files.{key} must be a list")

        out_list: list[Path] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"files.{key} entry must be an object")
            name = entry.get("name")
            data_b64 = entry.get("base64")
            if not isinstance(name, str) or not name:
                raise ValueError(f"files.{key}.name is required")
            if not isinstance(data_b64, str) or not data_b64:
                raise ValueError(f"files.{key}.base64 is required")

            raw = _b64_decode(data_b64)
            total_bytes += len(raw)
            if total_bytes > MAX_UPLOAD_BYTES:
                raise ValueError("Upload too large")

            safe_name = Path(name).name
            out_path = temp_dir / safe_name
            out_path.write_bytes(raw)
            out_list.append(out_path)

        written[key] = out_list

    return written


def _zip_dir_to_bytes(dir_path: Path) -> bytes:
    with zipfile.ZipFile(
        os.path.join(tempfile.gettempdir(), f"tool_site_{time.time_ns()}.zip"),
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as zf:
        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue
            arcname = file_path.relative_to(dir_path).as_posix()
            zf.write(file_path, arcname=arcname)
        zf_path = Path(zf.filename)
    raw = zf_path.read_bytes()
    try:
        zf_path.unlink(missing_ok=True)
    except Exception:
        pass
    return raw


def _run_subprocess(cmd: list[str], cwd: Path, timeout_seconds: int) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=os.fspath(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "cmd": cmd,
            "cwd": os.fspath(cwd),
            "returnCode": proc.returncode,
            "durationMs": duration_ms,
            "stdout": _truncate(proc.stdout or ""),
            "stderr": _truncate(proc.stderr or ""),
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = int((time.perf_counter() - started) * 1000)
        return {
            "cmd": cmd,
            "cwd": os.fspath(cwd),
            "returnCode": None,
            "durationMs": duration_ms,
            "stdout": _truncate((exc.stdout or "") if isinstance(exc.stdout, str) else ""),
            "stderr": _truncate((exc.stderr or "") if isinstance(exc.stderr, str) else ""),
            "error": f"Timed out after {timeout_seconds}s",
        }


def _run_guided_tool(
    tool_rel: str,
    inputs: dict[str, Any],
    files: Any,
    timeout_seconds: int,
) -> dict[str, Any]:
    tool = TOOL_CATALOG.get(tool_rel)
    if not isinstance(tool, dict):
        raise ValueError("Unknown tool")

    script_path = (SCRIPTS_ROOT / Path(tool_rel)).resolve()
    if not _is_under_root(script_path, SCRIPTS_ROOT):
        raise ValueError("Invalid script path")
    if not script_path.exists():
        raise FileNotFoundError("Script not found")

    with tempfile.TemporaryDirectory(prefix="tool_site_") as tmp:
        tmp_dir = Path(tmp)

        uploaded = _write_uploaded_files(tmp_dir, files)
        artifacts: list[dict[str, Any]] = []

        if tool_rel == "XLXS_JSON/convert.py":
            xlsx_paths = uploaded.get("xlsx", [])
            if len(xlsx_paths) != 1:
                raise ValueError("Please upload one .xlsx file")
            input_path = xlsx_paths[0]

            output_name = inputs.get("outputName", "output.json")
            if not isinstance(output_name, str) or not output_name.strip():
                output_name = "output.json"
            output_name = Path(output_name).name
            if not output_name.lower().endswith(".json"):
                output_name = output_name + ".json"
            output_path = tmp_dir / output_name

            cmd = [
                os.fspath(_python_for_script(script_path)),
                os.fspath(script_path),
                os.fspath(input_path),
                os.fspath(output_path),
            ]
            run = _run_subprocess(cmd, cwd=script_path.parent, timeout_seconds=timeout_seconds)
            if run.get("returnCode") not in (0, None):
                stderr = str(run.get("stderr") or "")
                if "No module named 'openpyxl'" in stderr or "Missing dependency: openpyxl" in stderr:
                    run["error"] = "Missing dependency: openpyxl (install it in the tool's .venv)."

            if output_path.exists():
                raw = output_path.read_bytes()
                artifacts.append(
                    {
                        "filename": output_name,
                        "mime": _guess_mime(output_name, "application/json"),
                        "base64": _b64_encode(raw),
                    }
                )

            return {**run, "artifacts": artifacts}

        if tool_rel == "WEBP/getinfo.py":
            url = inputs.get("url")
            if not isinstance(url, str) or not url.strip():
                raise ValueError("URL is required")

            output_name = inputs.get("outputName", "info.md")
            if not isinstance(output_name, str) or not output_name.strip():
                output_name = "info.md"
            output_name = Path(output_name).name
            if not output_name.lower().endswith(".md"):
                output_name = output_name + ".md"
            output_path = tmp_dir / output_name

            cmd = [
                os.fspath(_python_for_script(script_path)),
                os.fspath(script_path),
                "--url",
                url,
                "--output",
                os.fspath(output_path),
            ]
            run = _run_subprocess(cmd, cwd=script_path.parent, timeout_seconds=timeout_seconds)
            if run.get("returnCode") not in (0, None):
                stderr = str(run.get("stderr") or "")
                if "No module named 'playwright'" in stderr:
                    run["error"] = "Missing dependency: playwright (install it in WEBP/.venv, then install a browser)."

            if output_path.exists():
                raw = output_path.read_bytes()
                artifacts.append(
                    {
                        "filename": output_name,
                        "mime": _guess_mime(output_name, "text/markdown"),
                        "base64": _b64_encode(raw),
                    }
                )

            return {**run, "artifacts": artifacts}

        if tool_rel == "WEBP/convert.py":
            images = uploaded.get("images", [])
            if not images:
                raise ValueError("Please upload one or more images")

            target_dir = tmp_dir / "target"
            out_dir = tmp_dir / "output"
            target_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)

            for img_path in images:
                (target_dir / img_path.name).write_bytes(img_path.read_bytes())

            quality = inputs.get("quality", 80)
            method = inputs.get("method", 6)
            lossless = bool(inputs.get("lossless", False))

            try:
                quality_int = int(quality)
            except Exception:
                quality_int = 80
            try:
                method_int = int(method)
            except Exception:
                method_int = 6
            quality_int = max(0, min(100, quality_int))
            method_int = max(0, min(6, method_int))

            cmd = [
                os.fspath(_python_for_script(script_path)),
                os.fspath(script_path),
                "--target",
                os.fspath(target_dir),
                "--output",
                os.fspath(out_dir),
                "--quality",
                str(quality_int),
                "--method",
                str(method_int),
                "--force",
            ]
            if lossless:
                cmd.append("--lossless")

            run = _run_subprocess(cmd, cwd=script_path.parent, timeout_seconds=timeout_seconds)
            if run.get("returnCode") not in (0, None):
                stderr = str(run.get("stderr") or "")
                if "Missing dependency: Pillow" in stderr or "No module named 'PIL'" in stderr:
                    run["error"] = "Missing dependency: Pillow (install it in WEBP/.venv)."

            raw_zip = _zip_dir_to_bytes(out_dir)
            artifacts.append(
                {
                    "filename": "webp_output.zip",
                    "mime": "application/zip",
                    "base64": _b64_encode(raw_zip),
                }
            )

            return {**run, "artifacts": artifacts}

        raise ValueError("Unsupported tool")


class ToolHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not self._authorize_request():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
            return
        if parsed.path == "/api/scripts":
            self._handle_list_scripts()
            return
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not self._authorize_request():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
            return
        if parsed.path == "/api/tool/run":
            self._handle_run_tool()
            return
        if parsed.path == "/api/run":
            self._handle_run_script()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self) -> Any:
        length_str = self.headers.get("Content-Length", "0")
        try:
            length = int(length_str)
        except ValueError:
            length = 0
        body = self.rfile.read(max(0, length))
        if not body:
            return None

    def _authorize_request(self) -> bool:
        if not API_KEY:
            return True
        provided = (self.headers.get("X-Api-Key") or "").strip()
        return provided == API_KEY
        try:
            return json.loads(body.decode("utf-8"))
        except Exception:
            return None

    def _handle_list_scripts(self) -> None:
        scripts = list_python_scripts()
        self._send_json(
            HTTPStatus.OK,
            {
                "root": str(SCRIPTS_ROOT),
                "scripts": [
                    {
                        "relPath": s.rel_path,
                        "name": s.name,
                        "folder": s.folder,
                        "description": s.description,
                        "displayName": s.display_name,
                        "summary": s.summary,
                        "ui": s.ui,
                    }
                    for s in scripts
                ],
            },
        )

    def _handle_run_tool(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            timeout_seconds = int(qs.get("timeout", [str(DEFAULT_TIMEOUT_SECONDS)])[0])
        except ValueError:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        timeout_seconds = max(1, min(timeout_seconds, 3600))

        req = self._read_json_body()
        if not isinstance(req, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body"})
            return

        tool_rel = req.get("toolRelPath")
        inputs = req.get("inputs", {})
        files = req.get("files", None)
        if not isinstance(tool_rel, str) or not tool_rel.strip():
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "toolRelPath is required"})
            return
        if not isinstance(inputs, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "inputs must be an object"})
            return

        try:
            result = _run_guided_tool(tool_rel.strip(), inputs=inputs, files=files, timeout_seconds=timeout_seconds)
            self._send_json(HTTPStatus.OK, result)
        except FileNotFoundError as exc:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
        except ValueError as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})

    def _handle_run_script(self) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            timeout_seconds = int(qs.get("timeout", [str(DEFAULT_TIMEOUT_SECONDS)])[0])
        except ValueError:
            timeout_seconds = DEFAULT_TIMEOUT_SECONDS
        timeout_seconds = max(1, min(timeout_seconds, 3600))

        req = self._read_json_body()
        if not isinstance(req, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON body"})
            return

        script_rel = req.get("scriptRelPath")
        args_text = req.get("args", "")
        if not isinstance(script_rel, str) or not script_rel.strip():
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "scriptRelPath is required"})
            return
        if not isinstance(args_text, str):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "args must be a string"})
            return

        script_path = (SCRIPTS_ROOT / Path(script_rel)).resolve()
        if not _is_under_root(script_path, SCRIPTS_ROOT):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Invalid script path"})
            return
        if not script_path.exists() or not script_path.is_file() or script_path.suffix.lower() != ".py":
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Script not found"})
            return

        try:
            split_args = shlex.split(args_text, posix=os.name != "nt")
        except Exception:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "Could not parse args"})
            return

        cmd = [os.fspath(_python_for_script(script_path)), os.fspath(script_path), *split_args]
        try:
            result = _run_subprocess(cmd, cwd=script_path.parent, timeout_seconds=timeout_seconds)
            self._send_json(HTTPStatus.OK, result)
        except Exception as exc:
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})


def main() -> int:
    host = os.environ.get("TOOL_SITE_HOST", "127.0.0.1")
    port = int(os.environ.get("TOOL_SITE_PORT") or os.environ.get("PORT") or "5179")

    server = ThreadingHTTPServer((host, port), ToolHandler)
    print(f"Tool site running: http://{host}:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
