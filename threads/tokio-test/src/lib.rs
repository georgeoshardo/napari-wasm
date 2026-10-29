//! Checks that tokio's multi-threaded runtime works in the threaded Pyodide:
//! worker threads, timers (mio's poll with a timeout) and wake-ups across
//! threads (mio's waker, an eventfd or pipe).
use pyo3::prelude::*;
use std::time::{Duration, Instant};

#[pyfunction]
fn run(py: Python<'_>, tasks: usize) -> PyResult<String> {
    py.detach(|| {
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(4)
            .enable_all()
            .build()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(e.to_string()))?;
        let start = Instant::now();
        let (threads, slept) = runtime.block_on(async move {
            let (sender, mut receiver) = tokio::sync::mpsc::channel(tasks);
            for i in 0..tasks {
                let sender = sender.clone();
                tokio::spawn(async move {
                    tokio::time::sleep(Duration::from_millis(50)).await;
                    let _ = sender.send((i, format!("{:?}", std::thread::current().id()))).await;
                });
            }
            drop(sender);
            let mut threads = std::collections::BTreeSet::new();
            let mut count = 0;
            while let Some((_, thread)) = receiver.recv().await {
                threads.insert(thread);
                count += 1;
            }
            (threads.len(), count)
        });
        Ok(format!(
            "{slept} tasks slept 50 ms each on {threads} worker threads, all done in {:.0} ms",
            start.elapsed().as_secs_f64() * 1000.0
        ))
    })
}

#[pymodule]
fn tokio_threads_test(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(run, m)?)
}
