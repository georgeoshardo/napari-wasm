//! A PyO3 extension for checking Rust in the threaded Pyodide: plain calls,
//! a panic turned into a Python exception (needs unwinding), and a counter
//! updated with atomics from several Python threads.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use std::sync::atomic::{AtomicU64, Ordering};

static COUNTER: AtomicU64 = AtomicU64::new(0);

#[pyfunction]
fn add(a: i64, b: i64) -> i64 {
    a + b
}

#[pyfunction]
fn fails() -> PyResult<()> {
    Err(PyValueError::new_err("raised from Rust"))
}

#[pyfunction]
fn panics() {
    panic!("panicked in Rust");
}

/// Adds `n` to a shared counter one at a time, without holding the GIL.
#[pyfunction]
fn count(py: Python<'_>, n: u64) -> u64 {
    py.allow_threads(|| {
        for _ in 0..n {
            COUNTER.fetch_add(1, Ordering::SeqCst);
        }
    });
    COUNTER.load(Ordering::SeqCst)
}

#[pymodule]
fn rust_threads_test(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(add, m)?)?;
    m.add_function(wrap_pyfunction!(fails, m)?)?;
    m.add_function(wrap_pyfunction!(panics, m)?)?;
    m.add_function(wrap_pyfunction!(count, m)?)?;
    Ok(())
}
