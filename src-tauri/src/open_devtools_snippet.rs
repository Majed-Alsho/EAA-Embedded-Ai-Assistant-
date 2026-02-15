// Paste this inside your .setup(|app| { ... }) block:
//
// #[cfg(debug_assertions)]
// {
//   if let Some(w) = app.get_webview_window("main") {
//     let _ = w.open_devtools();
//   }
// }
