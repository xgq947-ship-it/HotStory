// HotStory 桌面外壳。
//
// 后端是 Python，所以外壳要做三件事：挑一个空闲端口、用内嵌解释器把 FastAPI
// 拉起来、等它健康之后把窗口导航过去。退出时必须把子进程收掉，否则会留下孤儿进程。
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::fs::OpenOptions;
use std::io::{self, ErrorKind};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager, WebviewWindow};

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// 子进程句柄。窗口关闭和进程退出两条路径都要能收掉它。
struct Backend(Mutex<Option<Child>>);

impl Backend {
    fn stop(&self) {
        if let Ok(mut guard) = self.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

fn free_port() -> u16 {
    // 绑 0 号端口让系统分配，避免固定端口被别的程序占住。
    TcpListener::bind("127.0.0.1:0")
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .unwrap_or(8765)
}

fn interpreter(runtime: &Path) -> PathBuf {
    if cfg!(windows) {
        runtime.join("python").join("python.exe")
    } else {
        runtime.join("python").join("bin").join("python3")
    }
}

fn runtime_dir_for_executable(executable: &Path) -> io::Result<PathBuf> {
    let executable_dir = executable
        .parent()
        .ok_or_else(|| io::Error::new(ErrorKind::NotFound, "无法确定 HotStory 可执行文件目录"))?;

    #[cfg(target_os = "macos")]
    {
        // 安装包：HotStory.app/Contents/MacOS/hotstory
        // 调试：src-tauri/target/<profile>/hotstory
        if executable_dir
            .file_name()
            .is_some_and(|name| name == "MacOS")
        {
            let contents = executable_dir.parent().ok_or_else(|| {
                io::Error::new(ErrorKind::NotFound, "无法确定 HotStory.app/Contents 目录")
            })?;
            return Ok(contents.join("Resources").join("runtime"));
        }
    }

    Ok(executable_dir.join("runtime"))
}

fn bundled_runtime_dir() -> io::Result<PathBuf> {
    let runtime = runtime_dir_for_executable(&std::env::current_exe()?)?;
    let python = interpreter(&runtime);
    let backend = runtime.join("backend");
    if !python.is_file() {
        return Err(io::Error::new(
            ErrorKind::NotFound,
            format!("找不到内嵌 Python：{}", python.display()),
        ));
    }
    if !backend.is_dir() {
        return Err(io::Error::new(
            ErrorKind::NotFound,
            format!("找不到内嵌后端：{}", backend.display()),
        ));
    }
    Ok(runtime)
}

fn persistent_data_dir(handle: &AppHandle) -> Result<PathBuf, String> {
    if let Some(value) = std::env::var_os("HOTSTORY_DATA_DIR").filter(|value| !value.is_empty()) {
        let path = PathBuf::from(value);
        if !path.is_absolute() {
            return Err("HOTSTORY_DATA_DIR 必须是绝对路径".to_string());
        }
        return Ok(path);
    }

    #[cfg(target_os = "macos")]
    if let Some(home) = std::env::var_os("HOME").filter(|value| !value.is_empty()) {
        return Ok(PathBuf::from(home)
            .join("Library")
            .join("Application Support")
            .join("HotStory")
            .join("data"));
    }

    #[cfg(target_os = "windows")]
    if let Some(app_data) = std::env::var_os("APPDATA").filter(|value| !value.is_empty()) {
        return Ok(PathBuf::from(app_data).join("HotStory").join("data"));
    }

    handle
        .path()
        .data_dir()
        .map(|path| path.join("HotStory").join("data"))
        .map_err(|error| format!("无法确定 HotStory 数据目录：{error}"))
}

fn spawn_backend(runtime: &Path, data_dir: &Path, port: u16) -> std::io::Result<Child> {
    let python = interpreter(runtime);
    let backend = runtime.join("backend");
    let database = data_dir.join("hotstory.db");
    let log = OpenOptions::new()
        .create(true)
        .append(true)
        .open(data_dir.join("hotstory-app.log"))?;
    let error_log = log.try_clone()?;

    let mut command = Command::new(python);
    command
        .current_dir(&backend)
        .args([
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
        ])
        .env("DATA_DIR", data_dir)
        // sqlite:/// 后面接绝对路径，Windows 上还得把反斜杠换掉。
        .env(
            "DATABASE_URL",
            format!(
                "sqlite:///{}",
                database.to_string_lossy().replace('\\', "/")
            ),
        )
        .env("PYTHONUNBUFFERED", "1")
        .stdout(Stdio::from(log))
        .stderr(Stdio::from(error_log));

    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    command.spawn()
}

/// 轮询健康检查，直到后端起来或超时。
fn wait_ready(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    let url = format!("http://127.0.0.1:{port}/api/health");
    while Instant::now() < deadline {
        let reachable = std::net::TcpStream::connect_timeout(
            &format!("127.0.0.1:{port}").parse().expect("本地地址"),
            Duration::from_millis(600),
        )
        .is_ok();
        if reachable && tauri::async_runtime::block_on(probe(&url)) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(400));
    }
    false
}

async fn probe(url: &str) -> bool {
    match tauri_plugin_http::reqwest::Client::new()
        .get(url)
        .timeout(Duration::from_secs(3))
        .send()
        .await
    {
        Ok(response) => response.status().is_success(),
        Err(_) => false,
    }
}

fn show_failure(window: &WebviewWindow, message: &str) {
    let escaped = message.replace('\\', "\\\\").replace('\'', "\\'");
    let _ = window.eval(&format!(
        "window.__hotstoryStatus && window.__hotstoryStatus('{escaped}')"
    ));
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_http::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Backend(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            let window = app.get_webview_window("main").expect("缺少主窗口");
            let runtime = match bundled_runtime_dir() {
                Ok(path) => path,
                Err(error) => {
                    show_failure(&window, &format!("运行环境不完整：{error}"));
                    return Ok(());
                }
            };
            // 沿用旧版 HotStory.app 的数据目录，保证切换到 Tauri 原生窗口后，
            // 已有项目、设置和 .env 不会看起来像“丢失”了。
            // macOS: ~/Library/Application Support/HotStory/data
            // Windows: %APPDATA%/HotStory/data
            let data_dir = match persistent_data_dir(&handle) {
                Ok(path) => path,
                Err(error) => {
                    show_failure(&window, &error);
                    return Ok(());
                }
            };
            if let Err(error) = std::fs::create_dir_all(&data_dir) {
                show_failure(
                    &window,
                    &format!("无法创建数据目录 {}：{error}", data_dir.display()),
                );
                return Ok(());
            }

            let port = free_port();

            match spawn_backend(&runtime, &data_dir, port) {
                Ok(child) => {
                    if let Ok(mut guard) = app.state::<Backend>().0.lock() {
                        guard.replace(child);
                    }
                }
                Err(error) => {
                    show_failure(&window, &format!("无法启动本地服务：{error}"));
                    return Ok(());
                }
            }

            let ready_window = window.clone();
            let log_path = data_dir.join("hotstory-app.log");
            std::thread::spawn(move || {
                if wait_ready(port, Duration::from_secs(120)) {
                    let _ = ready_window.eval(&format!(
                        "window.location.replace('http://127.0.0.1:{port}/')"
                    ));
                } else {
                    show_failure(
                        &ready_window,
                        &format!(
                            "本地服务启动超时，请退出后重试。日志：{}",
                            log_path.display()
                        ),
                    );
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if matches!(event, tauri::WindowEvent::Destroyed) {
                window.app_handle().state::<Backend>().stop();
            }
        })
        .build(tauri::generate_context!())
        .expect("Tauri 初始化失败")
        .run(|handle, event| {
            if matches!(
                event,
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
            ) {
                handle.state::<Backend>().stop();
            }
        });
}

#[cfg(test)]
mod tests {
    use super::runtime_dir_for_executable;
    use std::path::Path;

    #[cfg(target_os = "macos")]
    #[test]
    fn resolves_runtime_inside_macos_app_bundle() {
        let executable = Path::new("/Applications/HotStory.app/Contents/MacOS/hotstory");
        assert_eq!(
            runtime_dir_for_executable(executable).unwrap(),
            Path::new("/Applications/HotStory.app/Contents/Resources/runtime")
        );
    }

    #[test]
    fn resolves_runtime_next_to_development_binary() {
        let executable = Path::new("/workspace/src-tauri/target/debug/hotstory");
        assert_eq!(
            runtime_dir_for_executable(executable).unwrap(),
            Path::new("/workspace/src-tauri/target/debug/runtime")
        );
    }
}
