import logging
import os
import threading
import time
import uuid

from aiohttp import web

import folder_paths
from server import PromptServer


WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

EXCLUDED_MODEL_TYPES = {"configs", "custom_nodes"}
CHUNK_SIZE = 32 * 1024 * 1024
UPLOAD_TTL_SECONDS = 24 * 60 * 60

_UPLOADS = {}
_UPLOAD_LOCK = threading.Lock()


def _json_error(status, message):
    return web.json_response({"error": message}, status=status)


def _map_model_type(model_type):
    map_legacy = getattr(folder_paths, "map_legacy", lambda value: value)
    return map_legacy(str(model_type or ""))


def _validate_model_type(model_type):
    model_type = _map_model_type(model_type)
    if not model_type:
        raise web.HTTPBadRequest(reason="Missing model type.")
    if model_type in EXCLUDED_MODEL_TYPES:
        raise web.HTTPForbidden(reason="This model type cannot be managed by Model Uploader.")
    if model_type not in folder_paths.folder_names_and_paths:
        raise web.HTTPNotFound(reason="Unknown model type.")
    return model_type


def _parse_path_index(value):
    try:
        path_index = int(value)
    except (TypeError, ValueError):
        raise web.HTTPBadRequest(reason="Invalid path index.")
    if path_index < 0:
        raise web.HTTPBadRequest(reason="Invalid path index.")
    return path_index


def _get_root(model_type, path_index):
    roots = folder_paths.get_folder_paths(model_type)
    if path_index >= len(roots):
        raise web.HTTPNotFound(reason="Unknown model root.")
    return os.path.abspath(roots[path_index])


def _normalize_relative_path(value):
    raw = "" if value is None else str(value)
    raw = raw.replace("\\", "/")
    if raw in ("", "."):
        return ""
    if "\x00" in raw:
        raise web.HTTPBadRequest(reason="Invalid folder path.")
    if raw.startswith("/") or (len(raw) >= 3 and raw[1] == ":" and raw[2] == "/"):
        raise web.HTTPBadRequest(reason="Folder path must be relative.")

    parts = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise web.HTTPBadRequest(reason="Folder path cannot contain '..'.")
        parts.append(part)
    return "/".join(parts)


def _clean_filename(value):
    raw = "" if value is None else str(value)
    raw = raw.replace("\\", "/")
    if "\x00" in raw:
        raise web.HTTPBadRequest(reason="Invalid filename.")
    filename = raw.rsplit("/", 1)[-1]
    if filename in ("", ".", ".."):
        raise web.HTTPBadRequest(reason="Invalid filename.")
    return filename


def _join_relative(root, relative_path):
    if not relative_path:
        return root
    return os.path.join(root, *relative_path.split("/"))


def _get_directory(model_type, path_index, relative_path):
    root = _get_root(model_type, path_index)
    target_dir = _join_relative(root, relative_path)
    if not folder_paths.is_within_directory(root, target_dir):
        raise web.HTTPForbidden(reason="Folder path escapes the model root.")
    return root, target_dir


def _relative_file_path(relative_path, filename):
    if relative_path:
        return f"{relative_path}/{filename}"
    return filename


def _unique_destination(target_dir, filename):
    candidate = os.path.join(target_dir, filename)
    if not os.path.exists(candidate):
        return candidate, filename

    stem, ext = os.path.splitext(filename)
    for index in range(1, 10000):
        next_name = f"{stem} ({index}){ext}"
        candidate = os.path.join(target_dir, next_name)
        if not os.path.exists(candidate):
            return candidate, next_name

    token = uuid.uuid4().hex[:8]
    next_name = f"{stem} ({token}){ext}"
    return os.path.join(target_dir, next_name), next_name


def _is_writable_path(path):
    current = path
    while current and not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return os.path.isdir(current) and os.access(current, os.W_OK)


def _clear_model_caches(model_type):
    try:
        cache = getattr(folder_paths, "filename_list_cache", None)
        if isinstance(cache, dict):
            cache.pop(model_type, None)
    except Exception:
        logging.exception("Model Uploader failed to clear folder_paths cache.")

    try:
        manager = getattr(PromptServer.instance, "model_file_manager", None)
        if manager is not None and hasattr(manager, "clear_cache"):
            manager.clear_cache()
    except Exception:
        logging.exception("Model Uploader failed to clear model manager cache.")


def _cleanup_uploads():
    now = time.time()
    stale = []
    with _UPLOAD_LOCK:
        for upload_id, upload in list(_UPLOADS.items()):
            if now - upload["created"] > UPLOAD_TTL_SECONDS:
                stale.append((upload_id, upload.get("part_path")))
                _UPLOADS.pop(upload_id, None)

    for _upload_id, part_path in stale:
        if part_path and os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                logging.warning("Model Uploader could not remove stale part file: %s", part_path)


def _tree_entry_path(relative_path, name):
    return f"{relative_path}/{name}" if relative_path else name


def _format_stat(path):
    stat = os.stat(path)
    return {
        "size": stat.st_size,
        "modified": stat.st_mtime,
        "created": stat.st_ctime,
    }


routes = PromptServer.instance.routes


@routes.get("/model-uploader/folders")
async def get_model_uploader_folders(request):
    _cleanup_uploads()
    folders = []
    for model_type in folder_paths.folder_names_and_paths.keys():
        if model_type in EXCLUDED_MODEL_TYPES:
            continue

        roots = []
        for path_index, root in enumerate(folder_paths.get_folder_paths(model_type)):
            root_path = os.path.abspath(root)
            roots.append(
                {
                    "pathIndex": path_index,
                    "path": root_path,
                    "exists": os.path.isdir(root_path),
                    "writable": _is_writable_path(root_path),
                }
            )

        folders.append({"name": model_type, "roots": roots})

    return web.json_response({"folders": folders, "chunkSize": CHUNK_SIZE})


@routes.get("/model-uploader/tree")
async def get_model_uploader_tree(request):
    try:
        model_type = _validate_model_type(request.query.get("model_type"))
        path_index = _parse_path_index(request.query.get("path_index"))
        relative_path = _normalize_relative_path(request.query.get("path"))
        root, target_dir = _get_directory(model_type, path_index, relative_path)
    except web.HTTPException as exc:
        return _json_error(exc.status, exc.reason)

    if not os.path.isdir(target_dir):
        if relative_path == "":
            return web.json_response(
                {
                    "modelType": model_type,
                    "pathIndex": path_index,
                    "path": relative_path,
                    "rootPath": root,
                    "exists": False,
                    "dirs": [],
                    "files": [],
                }
            )
        return _json_error(404, "Folder does not exist.")

    dirs = []
    files = []
    try:
        with os.scandir(target_dir) as entries:
            for entry in entries:
                if entry.name == ".git" or entry.name.startswith(".model-uploader-"):
                    continue
                if not folder_paths.is_within_directory(root, entry.path):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=True):
                        dirs.append(
                            {
                                "name": entry.name,
                                "path": _tree_entry_path(relative_path, entry.name),
                                "modified": entry.stat(follow_symlinks=True).st_mtime,
                            }
                        )
                    elif entry.is_file(follow_symlinks=True):
                        info = _format_stat(entry.path)
                        files.append(
                            {
                                "name": entry.name,
                                "path": _tree_entry_path(relative_path, entry.name),
                                **info,
                            }
                        )
                except OSError:
                    logging.warning("Model Uploader could not inspect path: %s", entry.path)
    except OSError as exc:
        logging.exception("Model Uploader could not read folder: %s", target_dir)
        return _json_error(500, f"Could not read folder: {exc}")

    dirs.sort(key=lambda item: item["name"].lower())
    files.sort(key=lambda item: item["name"].lower())

    return web.json_response(
        {
            "modelType": model_type,
            "pathIndex": path_index,
            "path": relative_path,
            "rootPath": root,
            "exists": True,
            "dirs": dirs,
            "files": files,
        }
    )


@routes.post("/model-uploader/upload/init")
async def init_model_uploader_upload(request):
    _cleanup_uploads()
    try:
        payload = await request.json()
    except Exception:
        return _json_error(400, "Expected a JSON request body.")

    try:
        model_type = _validate_model_type(payload.get("modelType"))
        path_index = _parse_path_index(payload.get("pathIndex"))
        relative_path = _normalize_relative_path(payload.get("subfolder"))
        filename = _clean_filename(payload.get("filename"))
        size = int(payload.get("size"))
        if size < 0:
            raise web.HTTPBadRequest(reason="Invalid file size.")

        root, target_dir = _get_directory(model_type, path_index, relative_path)
        os.makedirs(target_dir, exist_ok=True)
        if not folder_paths.is_within_directory(root, target_dir):
            raise web.HTTPForbidden(reason="Folder path escapes the model root.")

        final_path, final_name = _unique_destination(target_dir, filename)
        if not folder_paths.is_within_directory(root, final_path):
            raise web.HTTPForbidden(reason="File path escapes the model root.")

        upload_id = uuid.uuid4().hex
        part_path = os.path.join(target_dir, f".model-uploader-{upload_id}.part")
        with open(part_path, "wb"):
            pass

        upload = {
            "created": time.time(),
            "model_type": model_type,
            "path_index": path_index,
            "relative_path": relative_path,
            "root": root,
            "target_dir": target_dir,
            "final_path": final_path,
            "final_name": final_name,
            "part_path": part_path,
            "size": size,
            "received": 0,
            "busy": False,
        }
        with _UPLOAD_LOCK:
            _UPLOADS[upload_id] = upload
    except web.HTTPException as exc:
        return _json_error(exc.status, exc.reason)
    except OSError as exc:
        logging.exception("Model Uploader could not initialize upload.")
        return _json_error(500, f"Could not initialize upload: {exc}")
    except (TypeError, ValueError):
        return _json_error(400, "Invalid file size.")

    return web.json_response(
        {
            "uploadId": upload_id,
            "chunkSize": CHUNK_SIZE,
            "finalName": final_name,
            "relativePath": _relative_file_path(relative_path, final_name),
        }
    )


@routes.post("/model-uploader/upload/chunk/{upload_id}")
async def upload_model_uploader_chunk(request):
    upload_id = request.match_info.get("upload_id")
    try:
        offset = int(request.headers.get("X-Upload-Offset", "0"))
    except ValueError:
        return _json_error(400, "Invalid upload offset.")

    with _UPLOAD_LOCK:
        upload = _UPLOADS.get(upload_id)
        if upload is None:
            return _json_error(404, "Unknown upload.")
        if upload["busy"]:
            return _json_error(409, "Upload is already receiving a chunk.")
        if offset != upload["received"]:
            return _json_error(409, f"Expected offset {upload['received']}.")
        upload["busy"] = True

    written = 0
    try:
        with open(upload["part_path"], "r+b") as handle:
            handle.seek(offset)
            async for block in request.content.iter_chunked(1024 * 1024):
                if not block:
                    continue
                written += len(block)
                if offset + written > upload["size"]:
                    raise web.HTTPBadRequest(reason="Chunk exceeds declared file size.")
                handle.write(block)

        if written <= 0 and upload["size"] > 0:
            raise web.HTTPBadRequest(reason="Empty chunk.")

        with _UPLOAD_LOCK:
            current = _UPLOADS.get(upload_id)
            if current is not None:
                current["received"] = offset + written
                current["busy"] = False
                received = current["received"]
                total = current["size"]
            else:
                received = offset + written
                total = upload["size"]
    except web.HTTPException as exc:
        with _UPLOAD_LOCK:
            current = _UPLOADS.get(upload_id)
            if current is not None:
                current["busy"] = False
        return _json_error(exc.status, exc.reason)
    except OSError as exc:
        with _UPLOAD_LOCK:
            current = _UPLOADS.get(upload_id)
            if current is not None:
                current["busy"] = False
        logging.exception("Model Uploader could not write chunk.")
        return _json_error(500, f"Could not write chunk: {exc}")

    return web.json_response({"received": received, "total": total})


@routes.post("/model-uploader/upload/complete/{upload_id}")
async def complete_model_uploader_upload(request):
    upload_id = request.match_info.get("upload_id")
    with _UPLOAD_LOCK:
        upload = _UPLOADS.get(upload_id)
        if upload is None:
            return _json_error(404, "Unknown upload.")
        if upload["busy"]:
            return _json_error(409, "Upload is still receiving a chunk.")
        if upload["received"] != upload["size"]:
            return _json_error(409, "Upload is incomplete.")
        _UPLOADS.pop(upload_id, None)

    try:
        actual_size = os.path.getsize(upload["part_path"])
        if actual_size != upload["size"]:
            return _json_error(409, "Uploaded file size does not match the declared size.")

        final_path = upload["final_path"]
        final_name = upload["final_name"]
        if os.path.exists(final_path):
            final_path, final_name = _unique_destination(upload["target_dir"], final_name)

        if not folder_paths.is_within_directory(upload["root"], final_path):
            return _json_error(403, "File path escapes the model root.")

        os.replace(upload["part_path"], final_path)
        _clear_model_caches(upload["model_type"])
    except OSError as exc:
        logging.exception("Model Uploader could not complete upload.")
        return _json_error(500, f"Could not complete upload: {exc}")

    return web.json_response(
        {
            "finalName": final_name,
            "relativePath": _relative_file_path(upload["relative_path"], final_name),
            "size": upload["size"],
        }
    )


@routes.post("/model-uploader/upload/cancel/{upload_id}")
async def cancel_model_uploader_upload(request):
    upload_id = request.match_info.get("upload_id")
    with _UPLOAD_LOCK:
        upload = _UPLOADS.pop(upload_id, None)

    if upload is not None:
        part_path = upload.get("part_path")
        if part_path and os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                logging.warning("Model Uploader could not remove canceled part file: %s", part_path)

    return web.json_response({"ok": True})
