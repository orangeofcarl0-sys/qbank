//! Minimal Tauri composition root.
//!
//! The webview receives no general filesystem or shell permission. The shell plugin
//! capability permits only the bundled `qbank-sidecar` binary with no arguments.

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("failed to run QBank Studio");
}

#[cfg(test)]
mod tests {
    #[test]
    fn product_identity_is_stable() {
        assert_eq!(env!("CARGO_PKG_NAME"), "qbank-studio");
        assert_eq!(env!("CARGO_PKG_VERSION"), "0.3.0-beta.2");
    }
}
