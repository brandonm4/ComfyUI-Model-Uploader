# ComfyUI Model Uploader

A portable ComfyUI extension that adds a real sidebar UI for uploading files into configured local model folders.

It registers no graph nodes. It adds:

- A `Model Uploads` sidebar tab in the current ComfyUI frontend.
- Server-side model-folder browsing based on ComfyUI's configured `folder_paths`.
- Chunked browser uploads into a selected model root or subfolder.
- Automatic filename suffixing when a file already exists.
- A refresh call after upload so ComfyUI model lists can pick up the new file.

## Requirements

- Current ComfyUI with the modern frontend sidebar extension API.
- Python packages already shipped with ComfyUI; this extension adds no external dependencies.

## Install

Clone this repository into `ComfyUI/custom_nodes`:

```bash
cd /path/to/ComfyUI/custom_nodes
git clone https://github.com/brandonm4/ComfyUI-Model-Uploader.git
```

Restart ComfyUI, then open the `Model Uploads` tab in the sidebar.

## Use

1. Expand a model type, root, or subfolder.
2. Select the destination folder.
3. Press `Upload` and choose a local file.

Uploads are written to a temporary `.model-uploader-*.part` file in the destination folder and renamed into place after all chunks are received.

## Notes

- This MVP intentionally does not restrict file extensions.
- Uploads are limited by ComfyUI's server upload size per request, so the extension sends files in 32 MiB chunks.
- The extension only writes inside ComfyUI model roots. It excludes `custom_nodes` and `configs`.
- If the destination filename exists, the server writes `name (1).ext`, `name (2).ext`, and so on.

## Debugging

Failed folder and upload requests return a `requestId` in the sidebar status. The same id is written to the ComfyUI server log with the backend stack trace.

The recent in-memory Model Uploader event log is available while testing at:

```text
GET /model-uploader/debug/events
```

## ComfyUI Manager

Once this package is published as a GitHub repository, install it through ComfyUI Manager with:

```text
https://github.com/brandonm4/ComfyUI-Model-Uploader
```
