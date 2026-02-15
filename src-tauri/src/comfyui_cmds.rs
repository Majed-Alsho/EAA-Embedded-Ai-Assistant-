use std::{
  fs::{self, OpenOptions},
  io::Write,
  net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream},
  path::{Path, PathBuf},
  process::{Child, Command, Stdio},
  sync::Mutex,
  time::{Duration, SystemTime},
};

use tauri::{AppHandle, Manager, State};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

pub struct ComfyUiState {
  pub child: Mutex<Option<Child>>,
}

impl Default for ComfyUiState {
  fn default() -> Self {
    Self {
      child: Mutex::new(None),
    }
  }
}

fn home_dir() -> Result<PathBuf, String> {
  let h = std::env::var("USERPROFILE")
    .or_else(|_| std::env::var("HOME"))
    .map_err(|_| "Could not find USERPROFILE/HOME env var".to_string())?;
  Ok(PathBuf::from(h))
}

fn logs_root() -> Result<PathBuf, String> {
  Ok(home_dir()?.join("EAA_Data").join("logs"))
}

fn comfy_dir() -> Result<PathBuf, String> {
  let v = std::env::var("EAA_COMFYUI_DIR")
    .map_err(|_| "EAA_COMFYUI_DIR env var is not set. Example:\n$env:EAA_COMFYUI_DIR=\"C:\\Users\\offic\\EAA\\Video\\ComfyUI\"".to_string())?;
  Ok(PathBuf::from(v))
}

fn comfy_python(comfy: &Path) -> PathBuf {
  #[cfg(target_os = "windows")]
  {
    let p = comfy.join(".venv").join("Scripts").join("python.exe");
    if p.exists() {
      return p;
    }
  }

  #[cfg(not(target_os = "windows"))]
  {
    let p = comfy.join(".venv").join("bin").join("python");
    if p.exists() {
      return p;
    }
  }

  // fallback (hoping it's on PATH)
  PathBuf::from("python")
}

fn tcp_port_open_127(port: u16) -> bool {
  let addr = SocketAddr::new(IpAddr::V4(Ipv4Addr::new(127, 0, 0, 1)), port);
  TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
}

#[cfg(target_os = "windows")]
fn taskkill_tree(pid: u32) -> Result<(), String> {
  // /T kills child tree, /F forces
  let out = Command::new("taskkill")
    .args(["/PID", &pid.to_string(), "/T", "/F"])
    .stdout(Stdio::null())
    .stderr(Stdio::null())
    .status()
    .map_err(|e| format!("taskkill failed: {e}"))?;

  // Even if status isn't success, we still tried; don't hard-fail stop.
  let _ = out;
  Ok(())
}

#[cfg(target_os = "windows")]
fn kill_processes_by_port(port: u16) -> Result<(), String> {
  // Stops any process holding the port.
  let ps = format!(
    "Get-NetTCPConnection -LocalPort {p} -ErrorAction SilentlyContinue | \
      Select-Object -ExpandProperty OwningProcess -Unique | \
      ForEach-Object {{ Stop-Process -Id $_ -Force }}",
    p = port
  );

  Command::new("powershell")
    .args(["-NoProfile", "-Command", &ps])
    .stdout(Stdio::null())
    .stderr(Stdio::null())
    .status()
    .map_err(|e| format!("powershell kill-by-port failed: {e}"))?;

  Ok(())
}

fn append_header(f: &mut fs::File, line: &str) {
  let _ = writeln!(f, "\n\n===== {line} @ {:?} =====\n", SystemTime::now());
}

fn validate_rel_path(rel: &str) -> Result<(), String> {
  if rel.trim().is_empty() {
    return Err("relPath is empty".to_string());
  }
  if rel.starts_with('\\') || rel.starts_with('/') {
    return Err("Absolute paths are not allowed.".to_string());
  }
  if rel.contains(':') {
    return Err("Drive letters are not allowed.".to_string());
  }

  let p = Path::new(rel);
  if p.is_absolute() {
    return Err("Absolute paths are not allowed.".to_string());
  }

  for c in p.components() {
    use std::path::Component::*;
    if matches!(c, ParentDir) {
      return Err("Path traversal (..) is not allowed.".to_string());
    }
  }
  Ok(())
}

fn join_comfy(rel: &str) -> Result<PathBuf, String> {
  validate_rel_path(rel)?;
  Ok(comfy_dir()?.join(rel))
}

#[tauri::command(rename_all = "camelCase")]
pub fn eaa_comfyui_ping() -> Result<String, String> {
  // Updated to use HTTP reqwest to avoid CORS issues and verify the server is actually responding
  let client = reqwest::blocking::Client::new();
  let res = client.get("http://127.0.0.1:8188/system_stats")
      .timeout(std::time::Duration::from_secs(2))
      .send()
      .map_err(|e| format!("Ping failed: {}", e))?;

  if res.status().is_success() {
      Ok("[ok] ComfyUI is reachable on http://127.0.0.1:8188/".to_string())
  } else {
      Err(format!("[error] ComfyUI returned status: {}", res.status()))
  }
}

#[tauri::command(rename_all = "camelCase")]
pub fn eaa_read_app_text_file(rel_path: String) -> Result<String, String> {
  // Reads text files relative to ComfyUI folder.
  let p = join_comfy(&rel_path)?;
  let s = fs::read_to_string(&p).map_err(|e| format!("read failed: {e}\nPath: {}", p.display()))?;
  Ok(s)
}

#[tauri::command(rename_all = "camelCase")]
pub fn eaa_start_comfyui(app: AppHandle, state: State<ComfyUiState>) -> Result<String, String> {
  // If something is already serving on the port, don't spawn another one.
  if tcp_port_open_127(8188) {
    return Ok("[ok] ComfyUI already running.\nURL: http://127.0.0.1:8188/".to_string());
  }

  {
    let guard = state.child.lock().map_err(|_| "Mutex poisoned".to_string())?;
    if guard.is_some() {
      return Ok("[ok] ComfyUI already started (tracked child).\nURL: http://127.0.0.1:8188/".to_string());
    }
  }

  let comfy = comfy_dir()?;
  if !comfy.exists() {
    return Err(format!("ComfyUI directory does not exist:\n{}", comfy.display()));
  }

  let main_py = comfy.join("main.py");
  if !main_py.exists() {
    return Err(format!("main.py not found in:\n{}", comfy.display()));
  }

  let logs = logs_root()?;
  fs::create_dir_all(&logs).map_err(|e| format!("create logs dir failed: {e}"))?;
  let out_path = logs.join("comfyui.log");
  let err_path = logs.join("comfyui.err.log");

  // Header
  {
    let mut f = OpenOptions::new()
      .create(true)
      .append(true)
      .open(&out_path)
      .map_err(|e| format!("open comfyui.log failed: {e}"))?;
    append_header(&mut f, "START COMFYUI 127.0.0.1:8188");
    let _ = writeln!(f, "ComfyDir: {}", comfy.display());
    let _ = writeln!(f, "Python: {}", comfy_python(&comfy).display());
  }
  {
    let mut f = OpenOptions::new()
      .create(true)
      .append(true)
      .open(&err_path)
      .map_err(|e| format!("open comfyui.err.log failed: {e}"))?;
    append_header(&mut f, "START COMFYUI (stderr) 127.0.0.1:8188");
  }

  let out_file = OpenOptions::new()
    .create(true)
    .append(true)
    .open(&out_path)
    .map_err(|e| format!("open comfyui.log failed: {e}"))?;

  let err_file = OpenOptions::new()
    .create(true)
    .append(true)
    .open(&err_path)
    .map_err(|e| format!("open comfyui.err.log failed: {e}"))?;

  let py = comfy_python(&comfy);

  let mut cmd = Command::new(py);
  cmd.current_dir(&comfy)
    .env("PYTHONUTF8", "1")
    .args([
      "-u",
      "main.py",
      "--listen",
      "127.0.0.1",
      "--port",
      "8188",
    ])
    .stdout(Stdio::from(out_file))
    .stderr(Stdio::from(err_file));

  #[cfg(target_os = "windows")]
  {
    cmd.creation_flags(CREATE_NO_WINDOW);
  }

  let child = cmd.spawn().map_err(|e| format!("start comfyui failed: {e}"))?;

  {
    let mut guard = state.child.lock().map_err(|_| "Mutex poisoned".to_string())?;
    *guard = Some(child);
  }

  // Wait up to 90s for port open (ComfyUI can take time).
  let deadline = std::time::Instant::now() + Duration::from_secs(90);
  while std::time::Instant::now() < deadline {
    if tcp_port_open_127(8188) {
      return Ok("[ok] Started ComfyUI.\nURL: http://127.0.0.1:8188/".to_string());
    }
    std::thread::sleep(Duration::from_millis(250));
  }

  // If port didn't open, stop whatever we spawned.
  let _ = eaa_stop_comfyui(app, state);

  Err(format!(
    "ComfyUI did not open port 8188 within 90s.\nCheck logs:\n{}\n{}",
    out_path.display(),
    err_path.display()
  ))
}

#[tauri::command(rename_all = "camelCase")]
pub fn eaa_stop_comfyui(_app: AppHandle, state: State<ComfyUiState>) -> Result<String, String> {
  // 1) Kill tracked child (if any)
  {
    let mut guard = state.child.lock().map_err(|_| "Mutex poisoned".to_string())?;
    // FIXED: Removed 'mut' to silence warning on Windows
    if let Some(child) = guard.take() {
      #[cfg(target_os = "windows")]
      {
        let _ = taskkill_tree(child.id());
      }
      #[cfg(not(target_os = "windows"))]
      {
        // On non-windows we need mut, so we'd re-declare or keep it.
        // For simplicity in this Windows-focused file, we ignore non-windows warning fix logic.
        let mut c = child; 
        let _ = c.kill();
      }
    }
  }

  // 2) Kill *anything* still holding the port (covers “old instance from last run”)
  #[cfg(target_os = "windows")]
  {
    let _ = kill_processes_by_port(8188);
  }

  Ok("[ok] Stop requested for ComfyUI.".to_string())
}

// =====================
// Best-effort lifecycle
// =====================

pub fn cleanup_comfyui_leftovers_on_launch(app: &AppHandle) {
  // On launch, kill anything already on port 8188 so Start never stacks.
  #[cfg(target_os = "windows")]
  {
    let _ = kill_processes_by_port(8188);
  }

  // Clear tracked child (if any stale state exists somehow)
  stop_comfyui_best_effort(app);
}

pub fn stop_comfyui_best_effort(app: &AppHandle) {
  // Try tracked child
  if let Some(state) = app.try_state::<ComfyUiState>() {
    if let Ok(mut guard) = state.child.lock() {
      if let Some(child) = guard.take() {
        #[cfg(target_os = "windows")]
        {
          let _ = taskkill_tree(child.id());
        }
        #[cfg(not(target_os = "windows"))]
        {
          let mut c = child;
          let _ = c.kill();
        }
      }
    }
  }

  // Also nuke by port (catches leftovers from previous app session)
  #[cfg(target_os = "windows")]
  {
    let _ = kill_processes_by_port(8188);
  }
}