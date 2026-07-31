//! A directory of our own under the system temp dir, removed on drop.
//!
//! Shared by every loader's tests so they can touch the real filesystem —
//! which is what `Mesh::load` and `Library::load` actually do — without a
//! dev-dependency for it.

use std::path::PathBuf;

pub(crate) struct Scratch {
    pub(crate) path: PathBuf,
}

impl Scratch {
    /// A fresh directory. The process id and a counter keep two tests, or two
    /// concurrent `cargo test` runs, out of each other's files.
    pub(crate) fn new(tag: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
        let count = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let path =
            std::env::temp_dir().join(format!("dimentio-{tag}-{}-{count}", std::process::id()));
        std::fs::create_dir_all(&path).expect("scratch dir");
        Self { path }
    }

    pub(crate) fn write(&self, name: &str, bytes: impl AsRef<[u8]>) {
        std::fs::write(self.path.join(name), bytes).expect("scratch file");
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.path);
    }
}
