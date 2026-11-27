#![allow(clippy::unwrap_used)]

mod common;

use common::{TestDir, lexical_engine, write_documents};
use seeky_engine::SearchRequest;
use std::sync::{Arc, Mutex};
use tracing::field::{Field, Visit};
use tracing::span::{Attributes, Id};
use tracing::{Event, Metadata, Subscriber};
use tracing_subscriber::layer::{Context, Layer};
use tracing_subscriber::prelude::*;
use tracing_subscriber::registry::LookupSpan;

#[derive(Clone, Default)]
struct Capture {
    spans: Arc<Mutex<Vec<(String, String)>>>,
    events: Arc<Mutex<Vec<String>>>,
}

#[derive(Default)]
struct Fields(String);

impl Visit for Fields {
    fn record_debug(&mut self, field: &Field, value: &dyn std::fmt::Debug) {
        self.0.push_str(&format!("{}={value:?};", field.name()));
    }
}

impl Capture {
    fn record(metadata: &Metadata<'_>, fields: &mut Fields) -> (String, String) {
        (metadata.name().to_string(), std::mem::take(&mut fields.0))
    }
}

impl<S> Layer<S> for Capture
where
    S: Subscriber + for<'lookup> LookupSpan<'lookup>,
{
    fn on_new_span(&self, attributes: &Attributes<'_>, _id: &Id, _context: Context<'_, S>) {
        let mut fields = Fields::default();
        attributes.record(&mut fields);
        self.spans
            .lock()
            .unwrap()
            .push(Capture::record(attributes.metadata(), &mut fields));
    }

    fn on_event(&self, event: &Event<'_>, _context: Context<'_, S>) {
        let mut fields = Fields::default();
        event.record(&mut fields);
        self.events
            .lock()
            .unwrap()
            .push(Capture::record(event.metadata(), &mut fields).1);
    }
}

/// SPEC-0002-R13: stage spans contain counts/extensions, never content or paths.
#[test]
fn spans_carry_no_content_or_paths() -> common::TestResult {
    let test_dir = TestDir::new("spans")?;
    let corpus = test_dir.join("corpus");
    write_documents(&corpus, 1)?;
    let engine = lexical_engine(&test_dir, Arc::new(common::NoopEvents))?;
    let capture = Capture::default();
    let subscriber = tracing_subscriber::registry().with(capture.clone());
    let query = "private-query-token";
    tracing::subscriber::with_default(subscriber, || -> common::TestResult {
        engine.index_path(&corpus)?;
        engine.search(&SearchRequest {
            query: query.to_string(),
            limit: Some(5),
        })?;
        engine.shutdown()?;
        Ok(())
    })?;

    let spans = capture.spans.lock().unwrap();
    let names: Vec<&str> = spans.iter().map(|(name, _)| name.as_str()).collect();
    for expected in [
        "index.path",
        "index.scan",
        "index.file",
        "index.extract",
        "index.chunk",
        "index.embed",
        "index.store",
        "search",
        "search.lexical",
        "search.filename",
        "search.fuse",
        "search.snippets",
    ] {
        assert!(names.contains(&expected), "missing {expected}: {names:?}");
    }
    let canonical_root = std::fs::canonicalize(&corpus)?;
    let forbidden = [
        query,
        "private-document-token",
        &corpus.to_string_lossy(),
        &canonical_root.to_string_lossy(),
    ];
    for (name, fields) in spans.iter() {
        for value in forbidden {
            assert!(!fields.contains(value), "{name} leaked {value:?}: {fields}");
        }
    }
    for fields in capture.events.lock().unwrap().iter() {
        for value in forbidden {
            assert!(!fields.contains(value), "event leaked {value:?}: {fields}");
        }
    }
    Ok(())
}
