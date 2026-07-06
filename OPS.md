# Ops Notes

## Update Installed Extension Remotely

When ComfyUI Manager does not show `ComfyUI-Model-Uploader` in the UI, use the Manager API from the browser console on the ComfyUI page:

```js
await fetch("/api/v2/manager/queue/batch", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({
    update: [{
      id: "ComfyUI-Model-Uploader",
      title: "ComfyUI-Model-Uploader",
      version: "unknown",
      files: ["https://github.com/brandonm4/ComfyUI-Model-Uploader"],
      repository: "https://github.com/brandonm4/ComfyUI-Model-Uploader",
      ui_id: "ComfyUI-Model-Uploader",
      channel: "default",
      mode: "cache"
    }],
    batch_id: "model-uploader-manual-update"
  })
});
```

Verify the installed commit:

```js
const installed = await (await fetch("/api/v2/customnode/installed")).json();
console.log(installed["ComfyUI-Model-Uploader"]?.ver);
```

After the commit changes, restart ComfyUI from Manager so Python reloads `__init__.py`, then hard-refresh the browser tab so the frontend reloads `web/modelUploader.js`.

## Read Debug Events

Fetch recent Model Uploader backend events:

```js
const data = await (await fetch("/model-uploader/debug/events")).json();
console.log(data.events);
```

Filter by the request id shown in the sidebar error:

```js
const requestId = "paste-request-id-here";
const data = await (await fetch("/model-uploader/debug/events")).json();
console.log(data.events.filter((event) => event.requestId === requestId));
```

Useful fields:

- `operation`: `folders`, `tree`, `upload:init`, `upload:chunk`, `upload:complete`, or `upload:cancel`
- `message`: short error or status
- `context`: route inputs and path context
- `traceback`: backend stack trace for unexpected errors
