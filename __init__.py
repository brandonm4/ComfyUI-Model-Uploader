import logging
import os
import threading
import time
import traceback
import uuid
from collections import deque

from aiohttp import web

import folder_paths
from server import PromptServer


WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

EXCLUDED_MODEL_TYPES = {"configs", "custom_nodes"}
CHUNK_SIZE = 32 * 1024 * 1024
UPLOAD_TTL_SECONDS = 24 * 60 * 60
DEBUG_EVENT_LIMIT = 200

_UPLOADS = {}
_UPLOAD_LOCK = threading.Lock()
_DEBUG_EVENTS = deque(maxlen=DEBUG_EVENT_LIMIT)
_DEBUG_LOCK = threading.Lock()
_LOGGER = logging.getLogger("ComfyUI.ModelUploader")


def _request_id(request):
    header_value = request.headers.get("X-Request-ID") if request is not None else None
    if header_value:
        return header_value[:80]
    return uuid.uuid4().hex[:12]


def _safe_debug_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_debug_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_debug_value(item) for item in value]
    return str(value)


def _record_event(level, operation, request_id=None, message="", **fields):
    event = {
        "time": time.time(),
        "level": level,
        "operation": operation,
        "requestId": request_id,
        "message": message,
    }
    event.update({key: _safe_debug_value(value) for key, value in fields.items()})
    with _DEBUG_LOCK:
        _DEBUG_EVENTS.append(event)
    return event


def _json_error(status, message, request_id=None):
    payload = {"error": message}
    if request_id:
        payload["requestId"] = request_id
    return web.json_response(payload, status=status)


def _unexpected_error(operation, request_id, exc, **context):
    safe_context = {key: _safe_debug_value(value) for key, value in context.items()}
    _record_event(
        "error",
        operation,
        request_id,
        str(exc),
        errorType=exc.__class__.__name__,
        context=safe_context,
        traceback=traceback.format_exc(),
    )
    _LOGGER.exception(
        "Model Uploader %s failed [request_id=%s] context=%s",
        operation,
        request_id,
        safe_context,
    )
    return _json_error(500, f"Internal error while handling {operation}.", request_id)


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


def _is_within_directory(directory, target):
    helper = getattr(folder_paths, "is_within_directory", None)
    if helper is not None:
        return helper(directory, target)

    try:
        directory = os.path.realpath(directory)
        target = os.path.realpath(target)
        return os.path.commonpath((directory, target)) == directory
    except (OSError, ValueError):
        return False


def _get_directory(model_type, path_index, relative_path):
    root = _get_root(model_type, path_index)
    target_dir = _join_relative(root, relative_path)
    if not _is_within_directory(root, target_dir):
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
    request_id = _request_id(request)
    try:
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
    except Exception as exc:
        return _unexpected_error("folders", request_id, exc)

    _record_event(
        "info",
        "folders",
        request_id,
        "Listed model folders.",
        folderCount=len(folders),
        rootCount=sum(len(folder.get("roots", [])) for folder in folders),
    )
    return web.json_response({"folders": folders, "chunkSize": CHUNK_SIZE, "requestId": request_id})


@routes.get("/model-uploader/tree")
async def get_model_uploader_tree(request):
    request_id = _request_id(request)
    query_context = {
        "modelType": request.query.get("model_type"),
        "pathIndex": request.query.get("path_index"),
        "path": request.query.get("path"),
    }
    try:
        model_type = _validate_model_type(request.query.get("model_type"))
        path_index = _parse_path_index(request.query.get("path_index"))
        relative_path = _normalize_relative_path(request.query.get("path"))
        root, target_dir = _get_directory(model_type, path_index, relative_path)
    except web.HTTPException as exc:
        _record_event("warning", "tree", request_id, exc.reason, status=exc.status, query=query_context)
        return _json_error(exc.status, exc.reason, request_id)
    except Exception as exc:
        return _unexpected_error("tree", request_id, exc, query=query_context)

    if not os.path.isdir(target_dir):
        if relative_path == "":
            _record_event(
                "info",
                "tree",
                request_id,
                "Model root does not exist.",
                modelType=model_type,
                pathIndex=path_index,
                rootPath=root,
                targetDir=target_dir,
            )
            return web.json_response(
                {
                    "modelType": model_type,
                    "pathIndex": path_index,
                    "path": relative_path,
                    "rootPath": root,
                    "exists": False,
                    "dirs": [],
                    "files": [],
                    "requestId": request_id,
                }
            )
        _record_event(
            "warning",
            "tree",
            request_id,
            "Folder does not exist.",
            status=404,
            modelType=model_type,
            pathIndex=path_index,
            rootPath=root,
            targetDir=target_dir,
            relativePath=relative_path,
        )
        return _json_error(404, "Folder does not exist.", request_id)

    dirs = []
    files = []
    try:
        with os.scandir(target_dir) as entries:
            for entry in entries:
                if entry.name == ".git" or entry.name.startswith(".model-uploader-"):
                    continue
                if not _is_within_directory(root, entry.path):
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
                    _LOGGER.warning("Model Uploader could not inspect path: %s", entry.path)
    except OSError as exc:
        _record_event(
            "error",
            "tree",
            request_id,
            f"Could not read folder: {exc}",
            status=500,
            modelType=model_type,
            pathIndex=path_index,
            rootPath=root,
            targetDir=target_dir,
            relativePath=relative_path,
            errorType=exc.__class__.__name__,
        )
        _LOGGER.exception("Model Uploader could not read folder [request_id=%s]: %s", request_id, target_dir)
        return _json_error(500, f"Could not read folder: {exc}", request_id)
    except Exception as exc:
        return _unexpected_error(
            "tree",
            request_id,
            exc,
            modelType=model_type,
            pathIndex=path_index,
            rootPath=root,
            targetDir=target_dir,
            relativePath=relative_path,
        )

    dirs.sort(key=lambda item: item["name"].lower())
    files.sort(key=lambda item: item["name"].lower())

    _record_event(
        "info",
        "tree",
        request_id,
        "Listed folder contents.",
        modelType=model_type,
        pathIndex=path_index,
        rootPath=root,
        targetDir=target_dir,
        relativePath=relative_path,
        dirCount=len(dirs),
        fileCount=len(files),
    )
    return web.json_response(
        {
            "modelType": model_type,
            "pathIndex": path_index,
            "path": relative_path,
            "rootPath": root,
            "exists": True,
            "dirs": dirs,
            "files": files,
            "requestId": request_id,
        }
    )


@routes.get("/model-uploader/debug/events")
async def get_model_uploader_debug_events(request):
    request_id = _request_id(request)
    try:
        with _DEBUG_LOCK:
            events = list(_DEBUG_EVENTS)
    except Exception as exc:
        return _unexpected_error("debug:events", request_id, exc)

    return web.json_response(
        {
            "enabled": True,
            "eventLimit": DEBUG_EVENT_LIMIT,
            "events": events,
            "requestId": request_id,
        }
    )


@routes.post("/model-uploader/upload/init")
async def init_model_uploader_upload(request):
    request_id = _request_id(request)
    _cleanup_uploads()
    try:
        payload = await request.json()
    except Exception:
        _record_event("warning", "upload:init", request_id, "Expected a JSON request body.", status=400)
        return _json_error(400, "Expected a JSON request body.", request_id)

    if not isinstance(payload, dict):
        _record_event("warning", "upload:init", request_id, "Expected a JSON object.", status=400)
        return _json_error(400, "Expected a JSON object.", request_id)

    context = {
        "modelType": payload.get("modelType"),
        "pathIndex": payload.get("pathIndex"),
        "subfolder": payload.get("subfolder"),
        "filename": payload.get("filename"),
        "size": payload.get("size"),
    }

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
        if not _is_within_directory(root, target_dir):
            raise web.HTTPForbidden(reason="Folder path escapes the model root.")

        final_path, final_name = _unique_destination(target_dir, filename)
        if not _is_within_directory(root, final_path):
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
        _record_event("warning", "upload:init", request_id, exc.reason, status=exc.status, context=context)
        return _json_error(exc.status, exc.reason, request_id)
    except OSError as exc:
        _record_event(
            "error",
            "upload:init",
            request_id,
            f"Could not initialize upload: {exc}",
            status=500,
            context=context,
            errorType=exc.__class__.__name__,
        )
        _LOGGER.exception("Model Uploader could not initialize upload [request_id=%s].", request_id)
        return _json_error(500, f"Could not initialize upload: {exc}", request_id)
    except (TypeError, ValueError):
        _record_event("warning", "upload:init", request_id, "Invalid file size.", status=400, context=context)
        return _json_error(400, "Invalid file size.", request_id)
    except Exception as exc:
        return _unexpected_error("upload:init", request_id, exc, context=context)

    _record_event(
        "info",
        "upload:init",
        request_id,
        "Initialized upload.",
        uploadId=upload_id,
        modelType=model_type,
        pathIndex=path_index,
        rootPath=root,
        targetDir=target_dir,
        relativePath=relative_path,
        filename=filename,
        finalName=final_name,
        size=size,
    )
    return web.json_response(
        {
            "uploadId": upload_id,
            "chunkSize": CHUNK_SIZE,
            "finalName": final_name,
            "relativePath": _relative_file_path(relative_path, final_name),
            "requestId": request_id,
        }
    )


@routes.post("/model-uploader/upload/chunk/{upload_id}")
async def upload_model_uploader_chunk(request):
    request_id = _request_id(request)
    upload_id = request.match_info.get("upload_id")
    try:
        offset = int(request.headers.get("X-Upload-Offset", "0"))
    except ValueError:
        _record_event("warning", "upload:chunk", request_id, "Invalid upload offset.", status=400, uploadId=upload_id)
        return _json_error(400, "Invalid upload offset.", request_id)

    with _UPLOAD_LOCK:
        upload = _UPLOADS.get(upload_id)
        if upload is None:
            _record_event("warning", "upload:chunk", request_id, "Unknown upload.", status=404, uploadId=upload_id)
            return _json_error(404, "Unknown upload.", request_id)
        if upload["busy"]:
            _record_event(
                "warning",
                "upload:chunk",
                request_id,
                "Upload is already receiving a chunk.",
                status=409,
                uploadId=upload_id,
            )
            return _json_error(409, "Upload is already receiving a chunk.", request_id)
        if offset != upload["received"]:
            message = f"Expected offset {upload['received']}."
            _record_event(
                "warning",
                "upload:chunk",
                request_id,
                message,
                status=409,
                uploadId=upload_id,
                offset=offset,
                received=upload["received"],
            )
            return _json_error(409, message, request_id)
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
        _record_event(
            "warning",
            "upload:chunk",
            request_id,
            exc.reason,
            status=exc.status,
            uploadId=upload_id,
            offset=offset,
            written=written,
        )
        return _json_error(exc.status, exc.reason, request_id)
    except OSError as exc:
        with _UPLOAD_LOCK:
            current = _UPLOADS.get(upload_id)
            if current is not None:
                current["busy"] = False
        _record_event(
            "error",
            "upload:chunk",
            request_id,
            f"Could not write chunk: {exc}",
            status=500,
            uploadId=upload_id,
            offset=offset,
            written=written,
            partPath=upload.get("part_path"),
            errorType=exc.__class__.__name__,
        )
        _LOGGER.exception("Model Uploader could not write chunk [request_id=%s].", request_id)
        return _json_error(500, f"Could not write chunk: {exc}", request_id)
    except Exception as exc:
        with _UPLOAD_LOCK:
            current = _UPLOADS.get(upload_id)
            if current is not None:
                current["busy"] = False
        return _unexpected_error(
            "upload:chunk",
            request_id,
            exc,
            uploadId=upload_id,
            offset=offset,
            written=written,
            partPath=upload.get("part_path"),
        )

    _record_event(
        "info",
        "upload:chunk",
        request_id,
        "Received upload chunk.",
        uploadId=upload_id,
        offset=offset,
        written=written,
        received=received,
        total=total,
    )
    return web.json_response({"received": received, "total": total, "requestId": request_id})


@routes.post("/model-uploader/upload/complete/{upload_id}")
async def complete_model_uploader_upload(request):
    request_id = _request_id(request)
    upload_id = request.match_info.get("upload_id")
    with _UPLOAD_LOCK:
        upload = _UPLOADS.get(upload_id)
        if upload is None:
            _record_event("warning", "upload:complete", request_id, "Unknown upload.", status=404, uploadId=upload_id)
            return _json_error(404, "Unknown upload.", request_id)
        if upload["busy"]:
            _record_event(
                "warning",
                "upload:complete",
                request_id,
                "Upload is still receiving a chunk.",
                status=409,
                uploadId=upload_id,
            )
            return _json_error(409, "Upload is still receiving a chunk.", request_id)
        if upload["received"] != upload["size"]:
            _record_event(
                "warning",
                "upload:complete",
                request_id,
                "Upload is incomplete.",
                status=409,
                uploadId=upload_id,
                received=upload["received"],
                size=upload["size"],
            )
            return _json_error(409, "Upload is incomplete.", request_id)
        _UPLOADS.pop(upload_id, None)

    try:
        actual_size = os.path.getsize(upload["part_path"])
        if actual_size != upload["size"]:
            _record_event(
                "warning",
                "upload:complete",
                request_id,
                "Uploaded file size does not match the declared size.",
                status=409,
                uploadId=upload_id,
                actualSize=actual_size,
                declaredSize=upload["size"],
            )
            return _json_error(409, "Uploaded file size does not match the declared size.", request_id)

        final_path = upload["final_path"]
        final_name = upload["final_name"]
        if os.path.exists(final_path):
            final_path, final_name = _unique_destination(upload["target_dir"], final_name)

        if not _is_within_directory(upload["root"], final_path):
            _record_event(
                "warning",
                "upload:complete",
                request_id,
                "File path escapes the model root.",
                status=403,
                uploadId=upload_id,
                rootPath=upload["root"],
                finalPath=final_path,
            )
            return _json_error(403, "File path escapes the model root.", request_id)

        os.replace(upload["part_path"], final_path)
        _clear_model_caches(upload["model_type"])
    except OSError as exc:
        _record_event(
            "error",
            "upload:complete",
            request_id,
            f"Could not complete upload: {exc}",
            status=500,
            uploadId=upload_id,
            partPath=upload.get("part_path"),
            finalPath=upload.get("final_path"),
            errorType=exc.__class__.__name__,
        )
        _LOGGER.exception("Model Uploader could not complete upload [request_id=%s].", request_id)
        return _json_error(500, f"Could not complete upload: {exc}", request_id)
    except Exception as exc:
        return _unexpected_error(
            "upload:complete",
            request_id,
            exc,
            uploadId=upload_id,
            partPath=upload.get("part_path"),
            finalPath=upload.get("final_path"),
        )

    _record_event(
        "info",
        "upload:complete",
        request_id,
        "Completed upload.",
        uploadId=upload_id,
        modelType=upload["model_type"],
        pathIndex=upload["path_index"],
        finalPath=final_path,
        finalName=final_name,
        size=upload["size"],
    )
    return web.json_response(
        {
            "finalName": final_name,
            "relativePath": _relative_file_path(upload["relative_path"], final_name),
            "size": upload["size"],
            "requestId": request_id,
        }
    )


@routes.post("/model-uploader/upload/cancel/{upload_id}")
async def cancel_model_uploader_upload(request):
    request_id = _request_id(request)
    upload_id = request.match_info.get("upload_id")
    with _UPLOAD_LOCK:
        upload = _UPLOADS.pop(upload_id, None)

    if upload is not None:
        part_path = upload.get("part_path")
        if part_path and os.path.exists(part_path):
            try:
                os.remove(part_path)
            except OSError:
                _LOGGER.warning("Model Uploader could not remove canceled part file: %s", part_path)

    _record_event(
        "info",
        "upload:cancel",
        request_id,
        "Canceled upload." if upload is not None else "Cancel requested for unknown upload.",
        uploadId=upload_id,
        hadUpload=upload is not None,
    )
    return web.json_response({"ok": True, "requestId": request_id})
