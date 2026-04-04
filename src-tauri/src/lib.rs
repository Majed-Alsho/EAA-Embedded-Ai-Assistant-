// src-tauri/src/lib.rs
use std::{
  fs::{self, OpenOptions},
  net::{IpAddr, Ipv4Addr, SocketAddr, TcpStream},
  path::{Path, PathBuf},
  process::{Child, Command, Stdio},
  sync::Mutex,
  time::Duration,
};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use reqwest::blocking::Client;
use tauri::Manager;

mod comfyui_cmds;

// === Persistent settings ===
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
struct PersistedSettings {
  workspace_root: Option<String>,
  presets_root: Option<String>,
}

#[derive(Debug)]
struct AppState {
  workspace_root: Mutex<PathBuf>,
  presets_root: Mutex<PathBuf>,
  settings_path: PathBuf,
}

impl AppState {
  fn load_or_default(app: &tauri::AppHandle) -> Result<Self, String> {
    let cfg_dir = app
      .path()
      .app_config_dir()
      .map_err(|e| format!("failed to resolve config dir: {e}"))?;
    fs::create_dir_all(&cfg_dir)
      .map_err(|e| format!("failed to create config dir: {e}"))?;
    let settings_path = cfg_dir.join("eaa_settings.json");

    let default_ws = workspace_root()?;
    let default_presets = default_presets_root(&default_ws);

    let settings: PersistedSettings = match fs::read_to_string(&settings_path) {
      Ok(s) => serde_json::from_str(&s).unwrap_or_default(),
      Err(_) => PersistedSettings::default(),
    };

    let ws = settings
      .workspace_root
      .and_then(|p| if p.trim().is_empty() { None } else { Some(PathBuf::from(p)) })
      .unwrap_or(default_ws);

    let presets = settings
      .presets_root
      .and_then(|p| if p.trim().is_empty() { None } else { Some(PathBuf::from(p)) })
      .unwrap_or(default_presets);

    Ok(Self {
      workspace_root: Mutex::new(ws),
      presets_root: Mutex::new(presets),
      settings_path,
    })
  }

  fn persist(&self) -> Result<(), String> {
    let ws = self.workspace_root.lock().map_err(|_| "workspace_root lock poisoned")?;
    let pr = self.presets_root.lock().map_err(|_| "presets_root lock poisoned")?;
    let settings = PersistedSettings {
      workspace_root: Some(ws.to_string_lossy().to_string()),
      presets_root: Some(pr.to_string_lossy().to_string()),
    };
    let s = serde_json::to_string_pretty(&settings).map_err(|e| format!("serialize settings failed: {e}"))?;
    fs::write(&self.settings_path, s).map_err(|e| format!("write settings failed: {e}"))?;
    Ok(())
  }
}

use comfyui_cmds::ComfyUiState;

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;

#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x08000000;

// ✅ State to hold the EAA Agent process
struct AgentProcess {
  child: Mutex<Option<Child>>,
}

fn home_dir() -> Result<PathBuf, String> {
  let h = std::env::var("USERPROFILE")
    .or_else(|_| std::env::var("HOME"))
    .map_err(|_| "Could not find USERPROFILE/HOME env var".to_string())?;
  Ok(PathBuf::from(h))
}

fn project_root() -> Result<PathBuf, String> {
  Ok(home_dir()?.join("EAA"))
}

fn workspace_root() -> Result<PathBuf, String> {
  Ok(home_dir()?.join("EAA_Workspace"))
}

fn logs_root() -> Result<PathBuf, String> {
  Ok(home_dir()?.join("EAA_Data").join("logs"))
}

fn default_presets_root(workspace: &Path) -> PathBuf {
  // Prefer ~/EAA/presets if it exists (matches the user's expected layout),
  // otherwise fall back to <workspace>/presets.
  let home = std::env::var("USERPROFILE").ok().or_else(|| std::env::var("HOME").ok());
  if let Some(home) = home {
    let candidate = PathBuf::from(home).join("EAA").join("presets");
    if candidate.exists() { return candidate; }
  }
  workspace.join("presets")
}



fn validate_rel_path(rel: &str) -> Result<(), String> {
  if rel.trim().is_empty() {
    return Err("relPath is empty".to_string());
  }
  if rel.starts_with('\\') || rel.starts_with('/') {
    return Err("Absolute paths are not allowed. Use workspace-relative paths.".to_string());
  }
  if rel.contains(':') {
    return Err("Drive letters are not allowed. Use workspace-relative paths.".to_string());
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


/// Resolve an input path.
///
/// - If `input_path` is absolute, return it as-is.
/// - If it is relative, join it onto `base_root`.
///
/// We keep a simple traversal guard for relative paths only.
fn resolve_path(base_root: &Path, input_path: &str) -> Result<PathBuf, String> {
  let p = input_path.trim();
  if p.is_empty() {
    return Err("path is empty".to_string());
  }

  let pb = PathBuf::from(p);
  if pb.is_absolute() {
    return Ok(pb);
  }

  validate_rel_path(p)?;
  Ok(base_root.join(p))
}


fn resolve_tool_path(state: &AppState, input_path: &str) -> Result<PathBuf, String> {
  // Allow absolute paths anywhere on disk.
  let p = Path::new(input_path);
  if p.is_absolute() {
    return Ok(p.to_path_buf());
  }

  // Special-case internal sandbox/workspace paths so tools keep working even if the user
  // points the "Files" root at some other location (e.g. C:\).
  let norm = input_path.replace('\\', "/");
  if norm == "EAA_Sandbox"
    || norm.starts_with("EAA_Sandbox/")
    || norm == "EAA_Workspace"
    || norm.starts_with("EAA_Workspace/")
  {
    let internal = workspace_root()?;
    return Ok(internal.join(Path::new(input_path)));
  }

  // Default: resolve relative to the user-selected workspace root.
  let base = state
    .workspace_root
    .lock()
    .map_err(|_| "workspace_root lock poisoned")?
    .clone();

  resolve_path(&base, input_path)
}


fn open_folder(path: &Path) -> Result<(), String> {
  #[cfg(target_os = "windows")]
  {
    Command::new("explorer")
      .arg(path)
      .spawn()
      .map_err(|e| format!("Failed to open folder: {e}"))?;
    return Ok(());
  }

  #[cfg(target_os = "macos")]
  {
    Command::new("open")
      .arg(path)
      .spawn()
      .map_err(|e| format!("Failed to open folder: {e}"))?;
    return Ok(());
  }

  #[cfg(target_os = "linux")]
  {
    Command::new("xdg-open")
      .arg(path)
      .spawn()
      .map_err(|e| format!("Failed to open folder: {e}"))?;
    return Ok(());
  }
}

fn is_hidden_or_ignored(name: &str) -> bool {
  name == "node_modules" || name == "target"
}

fn tree_dir(root: &Path, max_depth: usize) -> Result<String, String> {
  let mut out = String::new();
  out.push_str(&format!("Workspace: {}\n\n", root.display()));

  if !root.exists() {
    out.push_str("[error] Workspace folder does not exist.\n");
    out.push_str("Create it: mkdir %USERPROFILE%\\EAA_Workspace\n");
    return Ok(out);
  }

  fn walk(dir: &Path, prefix: &str, depth: usize, max_depth: usize, out: &mut String) -> Result<(), String> {
    if depth > max_depth {
      return Ok(());
    }

    let mut entries: Vec<_> = fs::read_dir(dir)
      .map_err(|e| format!("Failed to read dir {}: {e}", dir.display()))?
      .filter_map(|e| e.ok())
      .collect();

    entries.sort_by_key(|e| {
      let ft = e.file_type().ok();
      let is_dir = ft.map(|t| t.is_dir()).unwrap_or(false);
      let name = e.file_name().to_string_lossy().to_string();
      (if is_dir { 0 } else { 1 }, name.to_lowercase())
    });

    for (i, e) in entries.iter().enumerate() {
      let name = e.file_name().to_string_lossy().to_string();
      if is_hidden_or_ignored(&name) {
        continue;
      }

      let ft = e.file_type().map_err(|e2| format!("Failed file_type for {name}: {e2}"))?;
      let is_last = i == entries.len() - 1;
      let branch = if is_last { "└─ " } else { "├─ " };
      let next_prefix = if is_last { "   " } else { "│  " };

      if ft.is_dir() {
        out.push_str(&format!("{prefix}{branch}📁 {name}  [{path}]\n", path = e.path().display()));
        walk(&e.path(), &format!("{prefix}{next_prefix}"), depth + 1, max_depth, out)?;
      } else {
        out.push_str(&format!("{prefix}{branch}📄 {name}  [{path}]\n", path = e.path().display()));
      }
    }

    Ok(())
  }

  walk(root, "", 0, max_depth, &mut out)?;
  Ok(out)
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_list_workspace(state: tauri::State<AppState>) -> Result<String, String> {
  let root = state.workspace_root.lock().map_err(|_| "workspace_root lock poisoned")?.clone();
  tree_dir(&root, 12)
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_list_workspace_files(state: tauri::State<AppState>, root: Option<String>) -> Result<Vec<String>, String> {
  // If a root is provided from the UI, allow absolute paths.
  // If it's relative, resolve against the configured workspace_root.
  let base = state.workspace_root.lock().map_err(|_| "workspace_root lock poisoned")?.clone();

  let effective_root: PathBuf = match root {
    Some(r) if !r.trim().is_empty() => resolve_path(&base, r.trim())?,
    _ => base,
  };

  let mut out: Vec<String> = Vec::new();
  if !effective_root.exists() {
    return Ok(out);
  }

  // List one level deep; enough for quick navigation without freezing on huge trees.
  let rd = std::fs::read_dir(&effective_root).map_err(|e| format!("read_dir failed: {e}"))?;
  for entry in rd {
    let entry = entry.map_err(|e| format!("read_dir entry error: {e}"))?;
    let p = entry.path();
    let name = p
      .file_name()
      .map(|s| s.to_string_lossy().to_string())
      .unwrap_or_else(|| p.to_string_lossy().to_string());
    if p.is_dir() {
      out.push(format!("{name}/"));
    } else {
      out.push(name);
    }
  }
  out.sort();
  Ok(out)
}

#[derive(Debug, Clone, Serialize)]
struct PathsInfo {
  workspace_root: String,
  presets_root: String,
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_get_paths(state: tauri::State<AppState>) -> Result<PathsInfo, String> {
  let ws = state.workspace_root.lock().map_err(|_| "workspace_root lock poisoned")?;
  let pr = state.presets_root.lock().map_err(|_| "presets_root lock poisoned")?;
  Ok(PathsInfo {
    workspace_root: ws.to_string_lossy().to_string(),
    presets_root: pr.to_string_lossy().to_string(),
  })
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_set_workspace_root(state: tauri::State<AppState>, path: String) -> Result<String, String> {
  let p = PathBuf::from(path.trim());
  if !p.exists() { return Err(format!("workspace root does not exist: {}", p.display())); }
  if !p.is_dir() { return Err(format!("workspace root is not a directory: {}", p.display())); }
  {
    let mut ws = state.workspace_root.lock().map_err(|_| "workspace_root lock poisoned")?;
    *ws = p.clone();
  }
  state.persist()?;
  Ok(format!("workspace_root set to {}", p.display()))
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_set_presets_root(state: tauri::State<AppState>, path: String) -> Result<String, String> {
  let p = PathBuf::from(path.trim());
  if !p.exists() { return Err(format!("presets root does not exist: {}", p.display())); }
  if !p.is_dir() { return Err(format!("presets root is not a directory: {}", p.display())); }
  {
    let mut pr = state.presets_root.lock().map_err(|_| "presets_root lock poisoned")?;
    *pr = p.clone();
  }
  state.persist()?;
  Ok(format!("presets_root set to {}", p.display()))
}

#[derive(Debug, Clone, Serialize)]
struct PresetEntry {
  name: String,
  path: String,
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_list_presets(state: tauri::State<AppState>) -> Result<Vec<PresetEntry>, String> {
  let dir = state.presets_root.lock().map_err(|_| "presets_root lock poisoned")?.clone();
  if !dir.exists() { return Ok(vec![]); }
  let mut out = vec![];
  let rd = fs::read_dir(&dir).map_err(|e| format!("read_dir failed: {e}\nDir: {}", dir.display()))?;
  for e in rd {
    let e = e.map_err(|e| format!("read_dir entry failed: {e}"))?;
    let p = e.path();
    if p.is_file() {
      if let Some(ext) = p.extension().and_then(|x| x.to_str()) {
        if ext.eq_ignore_ascii_case("json") {
          let name = p.file_name().and_then(|x| x.to_str()).unwrap_or("").to_string();
          out.push(PresetEntry { name, path: p.to_string_lossy().to_string() });
        }
      }
    }
  }
  out.sort_by(|a,b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
  Ok(out)
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_save_preset(state: tauri::State<AppState>, file_name: String, json_contents: String) -> Result<String, String> {
  let dir = state.presets_root.lock().map_err(|_| "presets_root lock poisoned")?.clone();
  fs::create_dir_all(&dir).map_err(|e| format!("create_dir_all failed: {e}\nDir: {}", dir.display()))?;
  let mut name = file_name.trim().to_string();
  if name.is_empty() { return Err("file_name is empty".to_string()); }
  if !name.to_lowercase().ends_with(".json") { name.push_str(".json"); }
  // Prevent path separators in the name
  if name.contains('/') || name.contains('\\') { return Err("file_name must not contain path separators".to_string()); }

  let path = dir.join(&name);
  fs::write(&path, json_contents).map_err(|e| format!("write preset failed: {e}\nPath: {}", path.display()))?;
  state.persist()?;
  Ok(path.to_string_lossy().to_string())
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_read_file(state: tauri::State<AppState>, rel_path: String) -> Result<String, String> {
  let path = resolve_tool_path(&state, &rel_path)?;
  let contents = fs::read_to_string(&path)
    .map_err(|e| format!("read file failed: {e}\nPath: {}", path.display()))?;

  Ok(contents)
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_write_file(state: tauri::State<AppState>, rel_path: String, content: String) -> Result<String, String> {
  let path = resolve_tool_path(&state, &rel_path)?;
  if let Some(parent) = path.parent() {
    fs::create_dir_all(parent).map_err(|e| format!("create_dir_all failed: {e}"))?;
  }

  fs::write(&path, content.as_bytes()).map_err(|e| format!("write failed: {e}"))?;

  Ok(format!(
    "[ok] Wrote {} ({} bytes)\nPath: {}",
    rel_path.replace('\\', "/"),
    content.as_bytes().len(),
    path.display()
  ))
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_patch_file(state: tauri::State<AppState>, rel_path: String, find: String, replace: String, replace_all: bool) -> Result<String, String> {
  if find.is_empty() {
    return Err("find is empty".to_string());
  }
  let path = resolve_tool_path(&state, &rel_path)?;

  // If a directory is provided, patch all UTF-8 text files under it.
  if path.is_dir() {
    let mut files_changed = 0usize;
    let mut total_replacements = 0usize;
    let mut files_scanned = 0usize;

    fn walk_dir(dir: &Path, out: &mut Vec<PathBuf>) -> Result<(), String> {
      for entry in fs::read_dir(dir).map_err(|e| format!("read_dir failed: {e}"))? {
        let entry = entry.map_err(|e| format!("read_dir entry failed: {e}"))?;
        let p = entry.path();
        if p.is_dir() {
          walk_dir(&p, out)?;
        } else {
          out.push(p);
        }
      }
      Ok(())
    }

    let mut all = Vec::<PathBuf>::new();
    walk_dir(&path, &mut all)?;

    for f in all {
      files_scanned += 1;
      let Ok(original) = fs::read_to_string(&f) else {
        // Skip binary / non-utf8 files.
        continue;
      };
      let occurrences = original.matches(&find).count();
      if occurrences == 0 {
        continue;
      }
      let updated = if replace_all {
        original.replace(&find, &replace)
      } else {
        original.replacen(&find, &replace, 1)
      };
      fs::write(&f, updated.as_bytes()).map_err(|e| format!("write failed: {e}\nPath: {}", f.display()))?;
      files_changed += 1;
      total_replacements += if replace_all { occurrences } else { 1 };
    }

    return Ok(format!(
      "[ok] Patched directory {}\nFiles scanned: {}\nFiles changed: {}\nTotal replacements: {}\nMode: {}",
      rel_path.replace('\\', "/"),
      files_scanned,
      files_changed,
      total_replacements,
      if replace_all { "replaceAll" } else { "firstOnly" }
    ));
  }
  let original = fs::read_to_string(&path)
    .map_err(|e| format!("read file failed: {e}\nPath: {}", path.display()))?;

  let occurrences = original.matches(&find).count();
  if occurrences == 0 {
    return Ok(format!(
      "[ok] No changes. Text not found.\nFile: {}\n(find occurrences: 0)",
      rel_path.replace('\\', "/")
    ));
  }

  let updated = if replace_all {
    original.replace(&find, &replace)
  } else {
    original.replacen(&find, &replace, 1)
  };

  fs::write(&path, updated.as_bytes()).map_err(|e| format!("write failed: {e}"))?;

  Ok(format!(
    "[ok] Patched {}\nReplaced: {} of {}\nMode: {}\nPath: {}",
    rel_path.replace('\\', "/"),
    if replace_all { occurrences } else { 1 },
    occurrences,
    if replace_all { "replaceAll" } else { "firstOnly" },
    path.display()
  ))
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_open_logs_folder() -> Result<(), String> {
  let logs = logs_root()?;
  fs::create_dir_all(&logs).map_err(|e| format!("create_dir_all failed: {e}"))?;
  open_folder(&logs)
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_run_tests() -> Result<String, String> {
  #[cfg(target_os = "windows")]
  let mut cmd = {
    let mut c = Command::new("cmd");
    c.args(["/C", "npm", "run", "check"]);
    c
  };

  #[cfg(not(target_os = "windows"))]
  let mut cmd = {
    let mut c = Command::new("npm");
    c.args(["run", "check"]);
    c
  };

  let output = cmd.output().map_err(|e| format!("Failed to run tests: {e}"))?;
  let stdout = String::from_utf8_lossy(&output.stdout);
  let stderr = String::from_utf8_lossy(&output.stderr);

  Ok(format!(
    "---- stdout ----\n{}\n\n---- stderr ----\n{}\n(exit code: {:?})",
    stdout,
    stderr,
    output.status.code()
  ))
}

// ===========================
// PYTHON RUNNER (New)
// ===========================
#[tauri::command(rename_all = "camelCase")]
fn eaa_run_python(state: tauri::State<'_, AppState>, code: String) -> Result<String, String> {
  let root = state
    .workspace_root
    .lock()
    .map_err(|_| "workspace_root lock poisoned")?
    .clone();
  if !root.exists() {
    fs::create_dir_all(&root).map_err(|e| format!("Failed to create workspace: {e}"))?;
  }

  let temp_file_name = ".eaa_temp_run.py";
  let file_path = root.join(temp_file_name);
  fs::write(&file_path, code.as_bytes()).map_err(|e| format!("Failed to write temp python file: {e}"))?;

  #[cfg(target_os = "windows")]
  let mut cmd = {
    let mut c = Command::new("python");
    c.arg(temp_file_name);
    c
  };

  #[cfg(not(target_os = "windows"))]
  let mut cmd = {
    let mut c = Command::new("python3"); 
    c.arg(temp_file_name);
    c
  };

  cmd.current_dir(&root);

  let output = cmd.output().map_err(|e| format!("Failed to execute python: {e}\n(Is python installed and in PATH?)"))?;
  
  let stdout = String::from_utf8_lossy(&output.stdout);
  let stderr = String::from_utf8_lossy(&output.stderr);

  let _ = fs::remove_file(file_path);

  Ok(format!(
    "---- stdout ----\n{}\n---- stderr ----\n{}\n(exit code: {:?})",
    stdout.trim(),
    stderr.trim(),
    output.status.code()
  ))
}

// =====================================================
// Preset loader helper
// =====================================================
#[tauri::command(rename_all = "camelCase")]
fn eaa_read_any_file(state: tauri::State<AppState>, 
  args: Option<Value>,
  rel_path: Option<String>,
  path: Option<String>,
  file_path: Option<String>,
  preset_path: Option<String>,
  workflow_path: Option<String>,
  name: Option<String>,
  preset: Option<String>,
) -> Result<String, String> {
  fn pick_obj_str(v: &Value, key: &str) -> Option<String> {
    v.get(key).and_then(|x| x.as_str()).map(|s| s.to_string())
  }

  fn extract_from_value(v: &Value) -> Option<String> {
    if v.is_string() {
      return v.as_str().map(|s| s.to_string());
    }
    if let Some(obj) = v.as_object() {
      let direct = pick_obj_str(v, "relPath")
        .or_else(|| pick_obj_str(v, "rel_path"))
        .or_else(|| pick_obj_str(v, "path"))
        .or_else(|| pick_obj_str(v, "filePath"))
        .or_else(|| pick_obj_str(v, "file_path"))
        .or_else(|| pick_obj_str(v, "presetPath"))
        .or_else(|| pick_obj_str(v, "preset_path"))
        .or_else(|| pick_obj_str(v, "workflowPath"))
        .or_else(|| pick_obj_str(v, "workflow_path"))
        .or_else(|| pick_obj_str(v, "name"))
        .or_else(|| pick_obj_str(v, "preset"));
      if direct.is_some() {
        return direct;
      }
      if let Some(nested) = obj.get("args") {
        return extract_from_value(nested);
      }
    }
    None
  }

  let mut p_str = rel_path
    .or(path)
    .or(file_path)
    .or(preset_path)
    .or(workflow_path)
    .or(name)
    .or(preset);

  if p_str.is_none() {
    if let Some(v) = args.as_ref() {
      p_str = extract_from_value(v);
    }
  }

  let p_str = p_str.ok_or_else(|| {
    "[error] Can't read that file from disk.\nReason: missing path. Expected relPath (or args containing relPath)."
      .to_string()
  })?;

  let p = PathBuf::from(&p_str);

  if p.is_absolute() || p_str.contains(':') {
    let abs = fs::canonicalize(&p).unwrap_or(p);
    return fs::read_to_string(&abs)
      .map_err(|e| format!("Read failed: {}\nPath: {}", e, abs.display()));
  }

  validate_rel_path(&p_str)?;

  fn try_read(p: &Path) -> Option<Result<String, String>> {
    if p.exists() && p.is_file() {
      return Some(fs::read_to_string(p).map_err(|e| format!("read failed: {e}\nPath: {}", p.display())));
    }
    None
  }

  let mut tried: Vec<PathBuf> = Vec::new();
  let ws = state.workspace_root.lock().map_err(|_| "workspace_root lock poisoned")?.clone();
  let _pr = state.presets_root.lock().map_err(|_| "presets_root lock poisoned")?.clone();

  let c1 = ws.join(&p_str);
  tried.push(c1.clone());
  if let Some(r) = try_read(&c1) { return r; }

  let c2 = ws.join("presets").join(&p_str);
  tried.push(c2.clone());
  if let Some(r) = try_read(&c2) { return r; }

  let c3 = ws.join("EAA_Sandbox").join(&p_str);
  tried.push(c3.clone());
  if let Some(r) = try_read(&c3) { return r; }

  let c4 = ws.join("EAA_Sandbox").join("presets").join(&p_str);
  tried.push(c4.clone());
  if let Some(r) = try_read(&c4) { return r; }

  if let Ok(comfy_dir) = std::env::var("EAA_COMFYUI_DIR").map(PathBuf::from) {
    let d2 = comfy_dir.join("workflows").join("presets").join(&p_str);
    tried.push(d2.clone());
    if let Some(r) = try_read(&d2) { return r; }
  }

  let mut msg =
    String::from("[error] Can't read that file from disk.\nReason: file not found in allowed locations.\nTried:\n");
  for p in tried {
    msg.push_str(&format!("- {}\n", p.display()));
  }
  Err(msg)
}

// ===========================
// Sandbox preview server
// ===========================

struct SandboxServerState {
  child: Mutex<Option<Child>>,
}

fn sandbox_dir() -> Result<PathBuf, String> {
  Ok(workspace_root()?.join("EAA_Sandbox"))
}

fn tcp_port_open_127(port: u16) -> bool {
  let addr = SocketAddr::new(IpAddr::V4(Ipv4Addr::new(127, 0, 0, 1)), port);
  TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
}

#[cfg(target_os = "windows")]
fn taskkill_tree(pid: u32) -> Result<(), String> {
  let _ = Command::new("taskkill")
    .args(["/PID", &pid.to_string(), "/T", "/F"])
    .stdout(Stdio::null())
    .stderr(Stdio::null())
    .status()
    .map_err(|e| format!("taskkill failed: {e}"))?;
  Ok(())
}

#[cfg(target_os = "windows")]
fn kill_processes_by_port(port: u16) -> Result<(), String> {
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

fn stop_sandbox_best_effort(app: &tauri::AppHandle) {
  if let Some(state) = app.try_state::<SandboxServerState>() {
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

  #[cfg(target_os = "windows")]
  {
    let _ = kill_processes_by_port(1421);
  }
}

fn cleanup_sandbox_leftovers_on_launch() {
  #[cfg(target_os = "windows")]
  {
    let _ = kill_processes_by_port(1421);
  }
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_start_sandbox_preview(state: tauri::State<SandboxServerState>) -> Result<String, String> {
  let dir = sandbox_dir()?;
  if !dir.exists() {
    return Err(format!(
      "Sandbox folder not found: {}\nExpected: %USERPROFILE%\\EAA_Workspace\\EAA_Sandbox",
      dir.display()
    ));
  }

  if tcp_port_open_127(1421) {
    return Ok("[ok] Sandbox preview already running.\nURL: http://127.0.0.1:1421/".to_string());
  }

  {
    let guard = state.child.lock().map_err(|_| "Mutex poisoned".to_string())?;
    if guard.is_some() {
      return Ok("[ok] Sandbox preview already running (tracked).\nURL: http://127.0.0.1:1421/".to_string());
    }
  }

  #[cfg(target_os = "windows")]
  {
    let install = Command::new("cmd")
      .args(["/C", "npm", "install"])
      .current_dir(&dir)
      .stdout(Stdio::piped())
      .stderr(Stdio::piped())
      .output()
      .map_err(|e| format!("Failed to run npm install: {e}"))?;

    if !install.status.success() {
      return Err(format!(
        "npm install failed\n---- stdout ----\n{}\n---- stderr ----\n{}\n(exit code: {:?})",
        String::from_utf8_lossy(&install.stdout),
        String::from_utf8_lossy(&install.stderr),
        install.status.code()
      ));
    }
  }

  #[cfg(not(target_os = "windows"))]
  {
    let install = Command::new("npm")
      .args(["install"])
      .current_dir(&dir)
      .stdout(Stdio::piped())
      .stderr(Stdio::piped())
      .output()
      .map_err(|e| format!("Failed to run npm install: {e}"))?;

    if !install.status.success() {
      return Err(format!(
        "npm install failed\n---- stdout ----\n{}\n---- stderr ----\n{}\n(exit code: {:?})",
        String::from_utf8_lossy(&install.stdout),
        String::from_utf8_lossy(&install.stderr),
        install.status.code()
      ));
    }
  }

  #[cfg(target_os = "windows")]
  let child = {
    let logs = logs_root()?;
    fs::create_dir_all(&logs).map_err(|e| format!("create logs dir failed: {e}"))?;
    let out_path = logs.join("sandbox.log");
    let err_path = logs.join("sandbox.err.log");

    let out_file = OpenOptions::new()
      .create(true)
      .append(true)
      .open(&out_path)
      .map_err(|e| format!("open sandbox.log failed: {e}"))?;

    let err_file = OpenOptions::new()
      .create(true)
      .append(true)
      .open(&err_path)
      .map_err(|e| format!("open sandbox.err.log failed: {e}"))?;

    let mut cmd = Command::new("cmd");
    cmd.args([
      "/C", "npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", "1421",
    ])
    .current_dir(&dir)
    .stdout(Stdio::from(out_file))
    .stderr(Stdio::from(err_file));

    cmd.creation_flags(CREATE_NO_WINDOW);

    cmd.spawn().map_err(|e| format!("Failed to start sandbox dev server: {e}"))?
  };

  #[cfg(not(target_os = "windows"))]
  let child = Command::new("npm")
    .args(["run", "dev", "--", "--host", "127.0.0.1", "--port", "1421"])
    .current_dir(&dir)
    .stdout(Stdio::null())
    .stderr(Stdio::null())
    .spawn()
    .map_err(|e| format!("Failed to start sandbox dev server: {e}"))?;

  {
    let mut guard = state.child.lock().map_err(|_| "Mutex poisoned".to_string())?;
    *guard = Some(child);
  }

  Ok("[ok] Started sandbox preview.\nURL: http://127.0.0.1:1421/".to_string())
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_stop_sandbox_preview(state: tauri::State<SandboxServerState>) -> Result<String, String> {
  let mut guard = state.child.lock().map_err(|_| "Mutex poisoned".to_string())?;
  if let Some(child) = guard.take() {
    #[cfg(target_os = "windows")]
    {
      let _ = taskkill_tree(child.id());
      let _ = kill_processes_by_port(1421);
    }
    #[cfg(not(target_os = "windows"))]
    {
      let mut c = child;
      let _ = c.kill();
    }
    return Ok("[ok] Stopped sandbox preview.".to_string());
  }

  #[cfg(target_os = "windows")]
  {
    let _ = kill_processes_by_port(1421);
  }

  Ok("[ok] Sandbox preview was not running (tracked).".to_string())
}

#[tauri::command(rename_all = "camelCase")]
fn eaa_open_url(url: String) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    {
        Command::new("cmd")
            .args(["/C", "start", "", &url])
            .spawn()
            .map_err(|e| format!("Failed to open URL: {e}"))?;
    }
    #[cfg(not(target_os = "windows"))]
    {
        Command::new("xdg-open")
            .arg(&url)
            .spawn()
            .map_err(|e| format!("Failed to open URL: {e}"))?;
    }
    Ok(())
}


#[tauri::command(rename_all = "camelCase")]
fn eaa_check_brain_health() -> Result<String, String> {
    let client = reqwest::blocking::Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build().map_err(|e| format!("HTTP client error: {}", e))?;
    let resp = client.get("http://127.0.0.1:8000/v1/health").send()
        .map_err(|e| format!("Brain not reachable: {}", e))?;
    if resp.status().is_success() {
        Ok(resp.text().map_err(|e| format!("Read error: {}", e))?)
    } else {
        Err(format!("Status: {}", resp.status()))
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .manage(SandboxServerState { child: Mutex::new(None) })
    .manage(ComfyUiState::default())
    .manage(AgentProcess { child: Mutex::new(None) })
    .setup(|app| {
    // Manage global app state (workspace_root, presets_root, etc.)
    let state = AppState::load_or_default(app.handle())
      .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
    app.manage(state);

      comfyui_cmds::cleanup_comfyui_leftovers_on_launch(app.handle());
      cleanup_sandbox_leftovers_on_launch();

      // ✅ AUTO-START: Launch Agent (Silent)
      let python_exe = r"C:\Users\offic\EAA\.venv-hf\Scripts\python.exe";
      let script_path = r"C:\Users\offic\EAA\run_eaa_agent.py";
      let working_dir = r"C:\Users\offic\EAA";

      let child = Command::new(python_exe)
          .arg(script_path)
          .current_dir(working_dir)
          .creation_flags(CREATE_NO_WINDOW) 
          .spawn();

      if let Ok(c) = child {
          let state = app.state::<AgentProcess>();
          *state.child.lock().unwrap() = Some(c);
      }

      Ok(())
    })
    .invoke_handler(tauri::generate_handler![
      eaa_list_workspace,
      eaa_list_workspace_files,
      eaa_read_file,
      eaa_write_file,
      eaa_patch_file,
      eaa_open_logs_folder,
      eaa_run_tests,
      eaa_start_sandbox_preview,
      eaa_stop_sandbox_preview,
      eaa_open_url,
      eaa_read_any_file,
      eaa_run_python,
      comfyui_cmds::eaa_start_comfyui,
      comfyui_cmds::eaa_stop_comfyui,
      comfyui_cmds::eaa_comfyui_ping,
      comfyui_cmds::eaa_read_app_text_file,
      eaa_get_paths,
      eaa_set_workspace_root,
      eaa_set_presets_root,
      eaa_list_presets,
      eaa_save_preset,
      eaa_check_brain_health
    ])
    // ✅ CHANGED: Manually build/run to catch the exit event cleanly
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            // ✅ KILL SWITCH: This stops the python process when you close the app
            let agent_state = app_handle.state::<AgentProcess>();
            if let Ok(mut guard) = agent_state.child.lock() {
                if let Some(child) = guard.take() {
                    #[cfg(target_os = "windows")]
                    let _ = taskkill_tree(child.id()); 
                    #[cfg(not(target_os = "windows"))]
                    let _ = child.kill();
                }
            }
            stop_sandbox_best_effort(app_handle);
            comfyui_cmds::stop_comfyui_best_effort(app_handle);
        }
    });
}
