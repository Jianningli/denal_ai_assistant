# Release Usage

This folder contains the packaged desktop release for the Dental AI app.

## What's in this folder

- `_internal.7z`: the packaged release archive.

## How to run the release

1. Extract `_internal.7z` to a normal folder using 7-Zip or another tool that supports `.7z` files.
2. Open a Command Prompt or PowerShell window.
3. Start Ollama by running:

```bash
ollama
```

4. Leave that terminal open so Ollama stays available.
5. In the extracted release folder, double-click the app `.exe` file to launch the GUI.

## Important notes

- Keep the extracted files together in the same folder structure after unpacking.
- The packaged app still depends on a local Ollama installation and locally available models.
- If the app reports a missing model, install or create the required models before launching again.

## Required local models

The app expects these models to be available in Ollama:

```bash
ollama pull llama3:8b
ollama pull gemma4:e4b
ollama create personaldentalassistantadvanced_xml -f system_prompt/personaldentalassistant.modelfile
```

## Troubleshooting

- If the app does not open, make sure the archive was fully extracted before launching the `.exe`.
- If features fail to answer, confirm that Ollama is running and the required models are installed.
- If Windows shows a security prompt for the executable, review the prompt and allow the app only if you trust this build.
