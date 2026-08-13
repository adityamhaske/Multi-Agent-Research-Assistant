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

/// Keeps the child handle alive so `RunEvent::Exit` can kill it.
struct SidecarChild(Mutex<Option<Child>>);

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
///   2. Release builds: `research-sidecar` next to the current executable — that is
///      where the bundler drops the PyInstaller one-dir output (M9-D).
///   3. Debug builds: run the sidecar from source with the repo's python3.
fn sidecar_command() -> Result<(PathBuf, Vec<String>), String> {
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
    let bundled = exe_dir.join(name);
    if bundled.exists() {
        return Ok((bundled, Vec::new()));
    }

    Err(format!(
        "no sidecar found: set DESKTOP_SIDECAR or bundle `{name}` next to the executable"
    ))
}

/// Spawn the sidecar and wait for its handshake line. The sidecar prints exactly one
/// JSON line before uvicorn starts; anything else on stdout first is a bug we fail
/// loudly rather than paper over.
fn spawn_sidecar() -> Result<(Handshake, Child), String> {
    let (program, args) = sidecar_command()?;
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
    // Spawn before the event loop: if the sidecar cannot start there is no app.
    let (handshake, child) = match spawn_sidecar() {
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
        .manage(SidecarChild(Mutex::new(Some(child))))
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
        .build(tauri::generate_context!())
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
        }
    });
}
