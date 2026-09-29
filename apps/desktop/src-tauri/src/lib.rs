//! Desktop shell: starts the local Python backend on a free loopback port with a random
//! per-launch API token, hands both to the UI, and stops the backend when the app exits.

use std::net::{SocketAddr, TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{Manager, RunEvent, State};

#[derive(Clone, Serialize)]
struct BackendConfig {
    url: String,
    token: String,
}

struct Backend {
    config: BackendConfig,
    port: u16,
    child: Mutex<Option<Child>>,
    error: Mutex<Option<String>>,
}

fn random_token() -> String {
    let mut bytes = [0u8; 24];
    getrandom::getrandom(&mut bytes).expect("OS random number generator unavailable");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn free_port() -> u16 {
    if let Ok(p) = std::env::var("CLIP_FACTORY_PORT") {
        if let Ok(p) = p.parse() {
            return p;
        }
    }
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

/// Directory containing `clipfactory/` (the Python package). `CLIP_FACTORY_BACKEND_DIR` wins;
/// then the working directory and the executable's location are searched upwards; finally the
/// checkout the app was built from (so an installer built on your PC finds its backend).
fn backend_dir() -> Option<PathBuf> {
    if let Ok(d) = std::env::var("CLIP_FACTORY_BACKEND_DIR") {
        return Some(PathBuf::from(d));
    }
    let mut starts = vec![];
    if let Ok(cwd) = std::env::current_dir() {
        starts.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(p) = exe.parent() {
            starts.push(p.to_path_buf());
        }
    }
    starts.push(PathBuf::from(env!("CARGO_MANIFEST_DIR")));
    for start in starts {
        let mut cur: Option<&Path> = Some(start.as_path());
        while let Some(dir) = cur {
            let cand = dir.join("backend");
            if cand.join("clipfactory").join("__init__.py").is_file() {
                return Some(cand);
            }
            cur = dir.parent();
        }
    }
    None
}

/// Python interpreter: `CLIP_FACTORY_PYTHON`, else the backend's own virtualenv, else PATH.
fn python(backend: Option<&Path>) -> PathBuf {
    if let Ok(p) = std::env::var("CLIP_FACTORY_PYTHON") {
        return PathBuf::from(p);
    }
    if let Some(b) = backend {
        let venv = if cfg!(windows) {
            b.join(".venv").join("Scripts").join("python.exe")
        } else {
            b.join(".venv").join("bin").join("python")
        };
        if venv.is_file() {
            return venv;
        }
    }
    PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
}

fn spawn_backend(port: u16, token: &str) -> Result<Child, String> {
    let dir = backend_dir();
    let py = python(dir.as_deref());
    let mut cmd = Command::new(&py);
    cmd.args(["-m", "clipfactory.server"])
        .env("CLIP_FACTORY_HOST", "127.0.0.1")
        .env("CLIP_FACTORY_PORT", port.to_string())
        .env("CLIP_FACTORY_API_TOKEN", token)
        .env("CLIP_FACTORY_PARENT_PID", std::process::id().to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if let Some(d) = &dir {
        cmd.current_dir(d).env("PYTHONPATH", d);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd.spawn().map_err(|e| {
        format!(
            "Could not start the Python backend with '{}': {e}. Run the setup script (see docs/SETUP.md) or set CLIP_FACTORY_PYTHON.",
            py.display()
        )
    })
}

/// Returns the backend URL/token once the backend accepts connections (waits up to 40 s).
#[tauri::command]
async fn backend_config(state: State<'_, Backend>) -> Result<BackendConfig, String> {
    if let Some(e) = state.error.lock().unwrap().clone() {
        return Err(e);
    }
    let addr = SocketAddr::from(([127, 0, 0, 1], state.port));
    let deadline = Instant::now() + Duration::from_secs(40);
    while Instant::now() < deadline {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok() {
            return Ok(state.config.clone());
        }
        if let Some(child) = state.child.lock().unwrap().as_mut() {
            if let Ok(Some(status)) = child.try_wait() {
                return Err(format!("The Python backend exited during startup ({status}). Check logs/clipfactory.jsonl and docs/TROUBLESHOOTING.md."));
            }
        }
        tauri::async_runtime::spawn_blocking(|| std::thread::sleep(Duration::from_millis(250)))
            .await
            .ok();
    }
    Err("The Python backend did not start within 40 seconds.".into())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let port = free_port();
    let token = random_token();
    let (child, error) = match spawn_backend(port, &token) {
        Ok(c) => (Some(c), None),
        Err(e) => (None, Some(e)),
    };
    let backend = Backend {
        config: BackendConfig { url: format!("http://127.0.0.1:{port}"), token },
        port,
        child: Mutex::new(child),
        error: Mutex::new(error),
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(backend)
        .invoke_handler(tauri::generate_handler![backend_config])
        .build(tauri::generate_context!())
        .expect("error while building the application")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                let state = app.state::<Backend>();
                let mut guard = state.child.lock().unwrap();
                if let Some(mut child) = guard.take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        });
}
