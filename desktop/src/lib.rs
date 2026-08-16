//! Tauri shell for the local-first desktop build (docs/12 M9, docs/13 §7).
//!
//! Responsibilities — deliberately the entire list:
//!   1. Spawn the Python sidecar (PyInstaller `research-sidecar` one-dir build in
//!      production, `python backend/desktop/sidecar.py` in development).
//!   2. Parse the handshake line the sidecar prints before anything else:
//!      `{"ready": true, "host": "127.0.0.1", "port": N, "token": "…"}`.
//!   3. Build the window with `window.__DESKTOP__ = { baseUrl, token }` injected
//!      before any page script runs — that is the whole frontend integration.
//!   4. Kill the sidecar on exit. Nothing survives the app closing.
//!
//! Security posture (docs/13 §7): the sidecar binds 127.0.0.1 only and every
//! request carries the per-launch bearer token. The WebView CSP below allows
//! connecting to loopback only; there is no remote content anywhere in this shell.

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use serde::Deserialize;
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

/// Keeps the child handle alive so `RunEvent::Exit` can kill it.
struct SidecarChild(Mutex<Option<Child>>);

/// Tracks the `ollama serve` process this app started via the "Start local models"
/// button, if any — separate from `SidecarChild` above, which is the Python sidecar
/// this app *always* spawns at launch. A server the user started themselves outside
/// the app (or before clicking the button) is never touched by `stop_local_server`:
/// this state starts `None` and is only ever set by a successful `start_local_server`.
///
/// UNVERIFIED (docs/07 §2, Phase 2b): this struct, both commands below, the
/// `tauri-plugin-shell` dependency, and the matching `capabilities/default.json`
/// scope were all written to the plan's spec and never compiled — this environment
/// has no Rust/Tauri toolchain. `cargo build` and a real desktop launch must confirm
/// this before it ships.
///
/// This is also a second mechanism for the same job the Python sidecar's
/// `start_local_server`/`stop_local_server` endpoints already do via
/// `asyncio.create_subprocess_exec` (desktop/sidecar.py) — that path needs no Tauri
/// permission at all, since the sidecar is a plain OS process outside the WebView
/// sandbox, and it is tested and working today. Whether the frontend should call
/// this Tauri command (`invoke("start_local_server")`) or keep using the sidecar's
/// HTTP endpoint is an open decision this file does not resolve.
struct LocalLLMChild(Mutex<Option<CommandChild>>);

/// Start `ollama serve`, scoped by `capabilities/default.json`'s `shell:allow-execute`
/// entry to exactly that command — the shell's `core:default`-only posture is widened
/// deliberately for this one binary, not opened up generally (docs/13 §7).
///
/// No-ops if this app already started one — mirrors the sidecar endpoint's own
/// "check live state, not a stale flag" reasoning. It deliberately does NOT probe
/// whether a server is already reachable (unlike the sidecar's HTTP counterpart,
/// which does): that check lives in `local_llm.probe()` on the Python side, and
/// duplicating it here in Rust would be a third copy of one fact.
#[tauri::command]
fn start_local_server(
    app: tauri::AppHandle,
    state: tauri::State<LocalLLMChild>,
) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    if guard.is_some() {
        return Ok(());
    }
    // UNVERIFIED: `.command("ollama")` assumes tauri-plugin-shell's scoped-execute API
    // resolves against the `cmd` value declared in the capability file above. Confirm
    // this against the installed plugin version's docs/schema — the exact method name
    // and capability shape have changed across Tauri 2.x point releases.
    let (_rx, child) = app
        .shell()
        .command("ollama")
        .args(["serve"])
        .spawn()
        .map_err(|e| format!("failed to start ollama serve: {e}"))?;
    *guard = Some(child);
    Ok(())
}

/// Stop the server this app started. A server the user started themselves is never
/// touched, because `guard` is only ever populated by `start_local_server` above.
#[tauri::command]
fn stop_local_server(state: tauri::State<LocalLLMChild>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    if let Some(child) = guard.take() {
        child.kill().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[derive(Debug, Deserialize)]
struct Handshake {
    host: String,
    port: u16,
    token: String,
}

impl Handshake {
    fn base_url(&self) -> String {
        format!("http://{}:{}", self.host, self.port)
    }
}

/// Resolve the sidecar command. Order:
///   1. `DESKTOP_SIDECAR` env — explicit override (used by CI and power users).
///   2. Debug builds: run the sidecar from source with the repo's python3.
///   3. Release builds: the `sidecar/` resource directory (M9-D).
///
/// The resource dir, not "next to the executable", is where a bundled sidecar actually
/// lands, and getting that wrong shipped an app that could not start. PyInstaller emits a
/// *one-dir* build — a launcher plus `_internal/` — and Tauri's `externalBin`, which does
/// copy next to the executable, takes a single file. Only `bundle.resources` can carry a
/// directory, and it targets `Contents/Resources` on macOS, `../lib/<name>` on Linux, and
/// the executable's own folder on Windows. `resource_dir()` is what reconciles those three.
///
/// The old exe-adjacent path is kept as a fallback so a hand-assembled layout still works,
/// but it is no longer what the bundler produces.
fn sidecar_command(
    package_info: &tauri::utils::PackageInfo,
) -> Result<(PathBuf, Vec<String>), String> {
    if let Some(path) = std::env::var_os("DESKTOP_SIDECAR") {
        return Ok((PathBuf::from(path), Vec::new()));
    }

    let exe = std::env::current_exe().map_err(|e| e.to_string())?;
    let exe_dir = exe.parent().ok_or("current exe has no parent dir")?;

    if cfg!(debug_assertions) {
        // From desktop/target/debug/research-desktop up to the repo root. Prefer the
        // repo venv (it has fastapi/uvicorn/etc.); fall back to plain python3.
        let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
        let script = repo.join("backend").join("desktop").join("sidecar.py");
        if script.exists() {
            let venv_python = repo
                .join("backend")
                .join(".venv")
                .join("bin")
                .join("python");
            let python = if venv_python.exists() {
                venv_python
            } else {
                PathBuf::from("python3")
            };
            return Ok((python, vec![script.display().to_string()]));
        }
    }

    let name = if cfg!(windows) {
        "research-sidecar.exe"
    } else {
        "research-sidecar"
    };
    let mut looked_in: Vec<String> = Vec::new();

    if let Ok(resource_dir) =
        tauri::utils::platform::resource_dir(package_info, &tauri::utils::Env::default())
    {
        let bundled = resource_dir.join("sidecar").join(name);
        if bundled.exists() {
            return Ok((bundled, Vec::new()));
        }
        looked_in.push(bundled.display().to_string());
    }

    let adjacent = exe_dir.join(name);
    if adjacent.exists() {
        return Ok((adjacent, Vec::new()));
    }
    looked_in.push(adjacent.display().to_string());

    // Name every path tried. The failure this replaces said only "bundle it next to the
    // executable", which described a layout the bundler never produced.
    Err(format!(
        "no sidecar found: set DESKTOP_SIDECAR, or ship `{name}` as a bundled resource. \
         Looked in: {}",
        looked_in.join(", ")
    ))
}

/// Spawn the sidecar and wait for its handshake line. The sidecar prints exactly one
/// JSON line before uvicorn starts; anything else on stdout first is a bug we fail
/// loudly rather than paper over.
fn spawn_sidecar(
    package_info: &tauri::utils::PackageInfo,
) -> Result<(Handshake, Child), String> {
    let (program, args) = sidecar_command(package_info)?;
    // Supervision is bidirectional: the shell kills the sidecar on graceful exit, and
    // --shell-pid makes the sidecar exit on its own if the shell is hard-killed.
    let shell_pid = std::process::id().to_string();
    let mut full_args = args;
    full_args.push("--shell-pid".to_string());
    full_args.push(shell_pid);
    let mut child = Command::new(&program)
        .args(&full_args)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit()) // sidecar errors should be visible during development
        .spawn()
        .map_err(|e| format!("failed to spawn {}: {e}", program.display()))?;

    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "sidecar stdout not captured".to_string())?;

    // Don't hang forever if the sidecar dies before printing the handshake.
    let mut line = String::new();
    let mut reader = BufReader::new(stdout);
    match reader.read_line(&mut line) {
        Ok(0) => return Err("sidecar exited before printing the handshake".into()),
        Ok(_) => {}
        Err(e) => return Err(format!("reading sidecar handshake: {e}")),
    }

    // Return the reader's pipe to the child so the sidecar never blocks on a full
    // stdout buffer later (we stop reading after the handshake).
    child.stdout = Some(reader.into_inner());

    let handshake: Handshake = serde_json::from_str(line.trim())
        .map_err(|e| format!("bad sidecar handshake line {line:?}: {e}"))?;
    if handshake.host != "127.0.0.1" {
        // The token threat model assumes loopback only (docs/13 §7). Fail closed.
        return Err(format!(
            "sidecar handshake host is {} — must be 127.0.0.1",
            handshake.host
        ));
    }

    // Give uvicorn a beat to bind the port it already reserved.
    std::thread::sleep(Duration::from_millis(150));
    Ok((handshake, child))
}

pub fn run() {
    // Built before the spawn purely to borrow its `PackageInfo`: locating a bundled
    // resource needs the product name and version, and the sidecar has to be up before
    // the builder runs, since the handshake supplies the URL the window loads.
    let context = tauri::generate_context!();

    // Spawn before the event loop: if the sidecar cannot start there is no app.
    let (handshake, child) = match spawn_sidecar(context.package_info()) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("research-desktop: {e}");
            std::process::exit(1);
        }
    };
    let base_url = handshake.base_url();

    // The handshake travels as an injected global, read once by lib/desktop.ts —
    // SPA navigations never lose it, and it never appears in the URL (no history,
    // no logs, no referer leakage).
    let init_script = format!(
        "window.__DESKTOP__ = {{ baseUrl: {}, token: {} }};",
        serde_json::to_string(&base_url).unwrap(),
        serde_json::to_string(&handshake.token).unwrap(),
    );

    let app = tauri::Builder::default()
        // UNVERIFIED (docs/07 §2, Phase 2b) — see the `LocalLLMChild` doc comment above.
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarChild(Mutex::new(Some(child))))
        .manage(LocalLLMChild(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![start_local_server, stop_local_server])
        .setup(move |app| {
            WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
                .title("Research Assistant")
                .inner_size(1280.0, 840.0)
                .min_inner_size(900.0, 600.0)
                .initialization_script(&init_script)
                .build()?;
            eprintln!("research-desktop: sidecar ready at {base_url}");
            Ok(())
        })
        .build(context)
        .expect("error while building the desktop shell");

    app.run(|app_handle, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = app_handle.try_state::<SidecarChild>() {
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(child) = guard.as_mut() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                    *guard = None;
                }
            }
            // Nothing survives the app closing (see the module doc comment) — a local
            // model server this app started is no exception. A server the user started
            // themselves was never put in this state, so it is never touched here.
            if let Some(state) = app_handle.try_state::<LocalLLMChild>() {
                if let Ok(mut guard) = state.0.lock() {
                    if let Some(child) = guard.take() {
                        let _ = child.kill();
                    }
                }
            }
        }
    });
}
