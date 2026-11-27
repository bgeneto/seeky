use anyhow::{Context, Result, anyhow};
use calamine::{Reader, open_workbook_auto};
use pdfium_render::prelude::*;
use regex::Regex;
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::sync::{LazyLock, OnceLock};
use zip::ZipArchive;

static PDFIUM: OnceLock<std::result::Result<Pdfium, String>> = OnceLock::new();

// Patterns are compiled once; `clippy::invalid_regex` validates them at build time.
// The `regex` crate has no backreferences, so script and style are matched explicitly.
static DOCX_PARAGRAPH_END: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?i)</w:p>").expect("valid DOCX paragraph regex"));
static DOCX_TEXT_RUN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)<w:t[^>]*>(.*?)</w:t>").expect("valid DOCX text regex"));
static PPTX_TEXT_RUN: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)<a:t[^>]*>(.*?)</a:t>").expect("valid PPTX text regex"));
static HTML_SCRIPT_STYLE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?is)<script\b[^>]*>.*?</script\s*>|<style\b[^>]*>.*?</style\s*>")
        .expect("valid HTML script/style regex")
});
static HTML_TAG: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(?s)<[^>]+>").expect("valid HTML tag regex"));
static NUMERIC_ENTITY: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"&#(x?[0-9a-fA-F]+);").expect("valid entity regex"));

fn pdfium_instance(dll: &Path) -> Result<&'static Pdfium> {
    let instance = PDFIUM.get_or_init(|| {
        Pdfium::bind_to_library(dll)
            .map(Pdfium::new)
            .map_err(|e| format!("bind pdfium {}: {e}", dll.display()))
    });
    instance.as_ref().map_err(|e| anyhow!("{e}"))
}

pub fn supported_ext(ext: &str) -> bool {
    matches!(
        ext,
        "txt"
            | "md"
            | "markdown"
            | "rst"
            | "log"
            | "pdf"
            | "docx"
            | "xlsx"
            | "xls"
            | "pptx"
            | "html"
            | "htm"
            | "csv"
            | "json"
            | "jsonl"
            | "xml"
            | "yaml"
            | "yml"
            | "rs"
            | "py"
            | "js"
            | "jsx"
            | "ts"
            | "tsx"
            | "go"
            | "java"
            | "c"
            | "h"
            | "cpp"
            | "hpp"
            | "cs"
            | "rb"
            | "php"
            | "sh"
            | "ps1"
            | "sql"
            | "toml"
    )
}

pub fn extract(path: &Path, pdfium_dll: &Path) -> Result<String> {
    let ext = path
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    match ext.as_str() {
        "pdf" => extract_pdf(path, pdfium_dll),
        "docx" => extract_docx(path),
        "pptx" => extract_pptx(path),
        "xlsx" | "xls" => extract_xlsx(path),
        "html" | "htm" => extract_html(path),
        _ => extract_text(path),
    }
}

fn extract_text(path: &Path) -> Result<String> {
    let bytes = std::fs::read(path).with_context(|| format!("read {}", path.display()))?;
    if bytes.is_empty() {
        return Ok(String::new());
    }
    let nul = bytes.iter().filter(|b| **b == 0).count();
    if nul * 100 / bytes.len() > 2 {
        return Err(anyhow!("binary file skipped"));
    }
    Ok(String::from_utf8_lossy(&bytes).to_string())
}

fn extract_pdf(path: &Path, pdfium_dll: &Path) -> Result<String> {
    let pdfium = pdfium_instance(pdfium_dll)?;
    let document = pdfium
        .load_pdf_from_file(path, None)
        .map_err(|e| anyhow!("load PDF {}: {e}", path.display()))?;
    let mut text = String::new();
    for page in document.pages().iter() {
        if let Ok(page_text) = page.text() {
            text.push_str(&page_text.all());
            text.push('\n');
        }
    }
    Ok(text)
}

fn extract_docx(path: &Path) -> Result<String> {
    let mut archive = open_zip(path)?;
    let mut xml = String::new();
    archive
        .by_name("word/document.xml")
        .context("docx missing word/document.xml")?
        .read_to_string(&mut xml)?;
    let xml = DOCX_PARAGRAPH_END.replace_all(&xml, "\n");
    let mut out = String::new();
    for cap in DOCX_TEXT_RUN.captures_iter(&xml) {
        out.push_str(&decode_entities(&cap[1]));
    }
    Ok(out)
}

fn extract_pptx(path: &Path) -> Result<String> {
    let mut archive = open_zip(path)?;
    let names: Vec<String> = archive
        .file_names()
        .filter_map(|s| s.ok().map(|s| s.to_string()))
        .collect();
    let mut out = String::new();
    for name in names {
        if !name.starts_with("ppt/slides/slide") || !name.ends_with(".xml") {
            continue;
        }
        let mut xml = String::new();
        if let Ok(mut file) = archive.by_name(&name)
            && file.read_to_string(&mut xml).is_ok()
        {
            for cap in PPTX_TEXT_RUN.captures_iter(&xml) {
                out.push_str(&decode_entities(&cap[1]));
                out.push(' ');
            }
            out.push('\n');
        }
    }
    Ok(out)
}

fn extract_xlsx(path: &Path) -> Result<String> {
    let mut workbook =
        open_workbook_auto(path).with_context(|| format!("open workbook {}", path.display()))?;
    let mut out = String::new();
    for sheet in workbook.sheet_names().clone() {
        if let Ok(range) = workbook.worksheet_range(&sheet) {
            out.push_str(&format!("# Sheet: {sheet}\n"));
            for row in range.rows() {
                let mut cells = Vec::new();
                for cell in row {
                    let value = cell.to_string();
                    if !value.is_empty() {
                        cells.push(value);
                    }
                }
                if !cells.is_empty() {
                    out.push_str(&cells.join("\t"));
                    out.push('\n');
                }
            }
        }
    }
    Ok(out)
}

fn extract_html(path: &Path) -> Result<String> {
    let raw = extract_text(path)?;
    let text = HTML_SCRIPT_STYLE.replace_all(&raw, " ");
    let text = HTML_TAG.replace_all(&text, " ");
    Ok(decode_entities(&text))
}

fn open_zip(path: &Path) -> Result<ZipArchive<File>> {
    let file = File::open(path).with_context(|| format!("open zip {}", path.display()))?;
    ZipArchive::new(file).with_context(|| format!("parse zip {}", path.display()))
}

fn decode_entities(input: &str) -> String {
    let mut out = input
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&apos;", "'")
        .replace("&#39;", "'");
    out = NUMERIC_ENTITY
        .replace_all(&out, |caps: &regex::Captures| {
            let raw = &caps[1];
            let code = if let Some(hex) = raw.strip_prefix('x') {
                u32::from_str_radix(hex, 16).ok()
            } else {
                raw.parse::<u32>().ok()
            };
            code.and_then(char::from_u32)
                .map(|c| c.to_string())
                .unwrap_or_else(|| caps[0].to_string())
        })
        .to_string();
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn fixture(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join(name)
    }

    fn pdfium() -> PathBuf {
        PathBuf::from(std::env::var("LOCALAPPDATA").unwrap_or_default())
            .join("Gety")
            .join("lib")
            .join("pdfium.dll")
    }

    #[test]
    #[cfg_attr(
        not(feature = "hw-tests"),
        ignore = "needs a local PDFium library; run with --features hw-tests"
    )]
    fn extracts_pdf_text() {
        let text = extract(&fixture("renewal.pdf"), &pdfium()).expect("pdf text");
        assert!(!text.trim().is_empty(), "empty pdf text");
    }

    #[test]
    fn extracts_docx_text() {
        let text = extract(&fixture("sample.docx"), &pdfium()).expect("docx text");
        assert!(text.contains("Renewal terms"), "text={text:?}");
    }

    #[test]
    fn skips_binary_text() {
        let dir = std::env::temp_dir().join(format!("seeky-binary-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("blob.txt");
        std::fs::write(&path, [0u8, 1, 2, 3, 0, 4, 5, 6, 0, 7]).unwrap();
        let result = extract(&path, &pdfium());
        assert!(result.is_err());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn extracts_html_text_without_scripts_and_styles() {
        let dir = std::env::temp_dir().join(format!("seeky-html-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("page.html");
        std::fs::write(
            &path,
            "<html><head><style>body { color: red; }</style>\
             <SCRIPT type=\"text/javascript\">var secret = 1;</SCRIPT></head>\
             <body><h1>Renova&#231;&#227;o</h1><p>Contract &amp; terms&#x21;</p>\
             <script>\nalert('x');\n</script ></body></html>",
        )
        .unwrap();
        let text = extract(&path, &pdfium()).expect("html text");
        let _ = std::fs::remove_dir_all(&dir);
        assert!(text.contains("Contract & terms!"), "text={text:?}");
        assert!(text.contains("Renovação"), "text={text:?}");
        assert!(!text.contains("color: red"), "style leaked: {text:?}");
        assert!(!text.contains("secret"), "script leaked: {text:?}");
        assert!(!text.contains("alert"), "script leaked: {text:?}");
        assert!(!text.contains('<'), "tag leaked: {text:?}");
    }
}
