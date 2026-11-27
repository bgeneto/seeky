use crate::{Context, Result};
use half::f16;
use openvino::{
    Core, DeviceType, ElementType, InferRequest, PartialShape, Shape, Tensor as OvTensor,
};
use ort::execution_providers::CUDAExecutionProvider;
use ort::session::Session;
use ort::value::Tensor;
use seeky_core::{Backend, EngineInfo, ModelIdentity};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use tokenizers::{PaddingParams, Tokenizer, TruncationParams};

pub const DIM: usize = 384;
const NPU_BUCKET: usize = 256;

/// Public model identifier. Never a filesystem path.
pub const MODEL_ID: &str = "gety-embed-v0";
/// Public model revision label until a model manifest lands.
pub const MODEL_REVISION: &str = "unversioned";
/// Public preprocessing recipe identifier.
pub const MODEL_PREPROCESSING: &str = "gety-tokenizer-v0/truncate-512/pad-1";

/// The embedding capability used by the engine facade. A trait so hardware-free
/// tests can supply a deterministic fake embedder (SPEC-0002 R20).
pub trait Embedder: Send {
    /// Deployment info for status.
    fn info(&self) -> EngineInfo;
    /// Public identity for telemetry and reports.
    fn identity(&self) -> ModelIdentity;
    /// Embed a batch of texts.
    fn embed(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
}

/// Public description of the active deployed model, including its content hash.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActiveModel {
    /// Task name.
    pub task: String,
    /// Public model identifier.
    pub id: String,
    /// Public revision label.
    pub revision: String,
    /// Deployed precision/provider variant.
    pub variant: String,
    /// Output dimension.
    pub dimension: u32,
    /// Execution provider label.
    pub provider: String,
    /// Preprocessing recipe identifier.
    pub preprocessing: String,
    /// Lowercase SHA-256 of the deployed model bytes.
    pub sha256: String,
}

/// Describe the deployed model for `backend` and hash its bytes.
pub fn describe_active_model(
    backend: Backend,
    model_root: &Path,
    npu_dir: &Path,
) -> Result<ActiveModel> {
    let backend = match backend {
        Backend::Auto => Backend::Cpu,
        other => other,
    };
    let (variant, files) = match backend {
        Backend::Cpu => (
            "int8-cpu",
            vec![model_root.join("onnx").join("model_uint8.onnx")],
        ),
        Backend::Cuda => (
            "fp16-cuda",
            vec![model_root.join("onnx_cuda").join("model_fp16.onnx")],
        ),
        Backend::Npu => (
            "int8-npu",
            vec![npu_dir.join("model.xml"), npu_dir.join("model.bin")],
        ),
        Backend::Auto => unreachable!("Auto resolves to CPU"),
    };
    let mut hasher = Sha256::new();
    for path in &files {
        ensure_file(path)?;
        let bytes = std::fs::read(path)?;
        hasher.update(&bytes);
    }
    Ok(ActiveModel {
        task: "embedder".into(),
        id: MODEL_ID.into(),
        revision: MODEL_REVISION.into(),
        variant: variant.into(),
        dimension: DIM as u32,
        provider: provider_label(backend).into(),
        preprocessing: MODEL_PREPROCESSING.into(),
        sha256: format!("{:x}", hasher.finalize()),
    })
}

fn provider_label(backend: Backend) -> &'static str {
    match backend {
        Backend::Auto => "cpu",
        Backend::Cpu => "cpu",
        Backend::Cuda => "cuda",
        Backend::Npu => "npu",
    }
}

fn identity_for(backend: Backend) -> ModelIdentity {
    let variant = match backend {
        Backend::Cpu | Backend::Auto => "int8-cpu",
        Backend::Cuda => "fp16-cuda",
        Backend::Npu => "int8-npu",
    };
    ModelIdentity {
        task: "embedder".into(),
        id: MODEL_ID.into(),
        revision: MODEL_REVISION.into(),
        variant: variant.into(),
        dimension: Some(DIM as u32),
    }
}

pub struct Engine {
    backend: Backend,
    tokenizer: Tokenizer,
    cpu_session: Option<Session>,
    cuda_session: Option<Session>,
    npu: Option<NpuEngine>,
    info: EngineInfo,
}

struct NpuEngine {
    request: InferRequest,
    bucket: usize,
    // Keep the core and compiled model alive for the request.
    _compiled: openvino::CompiledModel,
    _core: Core,
}

static ORT_INIT: OnceLock<std::result::Result<(), String>> = OnceLock::new();

fn init_ort(ort_dll: &Path) -> Result<()> {
    let result = ORT_INIT.get_or_init(|| {
        ort::init_from(ort_dll.to_string_lossy().to_string())
            .commit()
            .map(|_| ())
            .map_err(|e| e.to_string())
    });
    result
        .as_ref()
        .map(|_| ())
        .map_err(|e| error!("ONNX Runtime init failed: {e}"))
}

impl Engine {
    pub fn create(backend: Backend, model_root: &Path, npu_dir: &Path) -> Result<Self> {
        match backend {
            // ADR-0016: Auto selects only validated providers. The NPU path has
            // no parity check and truncates at 256 tokens (audit A5, A11), so
            // Auto is CPU-only until WP-5.1/WP-5.2 validate it. NPU and CUDA
            // run only when chosen explicitly (CUDA frozen, plan WP-5.7).
            Backend::Auto => Self::create_one(Backend::Cpu, model_root, npu_dir),
            other => Self::create_one(other, model_root, npu_dir),
        }
    }

    fn create_one(backend: Backend, model_root: &Path, npu_dir: &Path) -> Result<Self> {
        let tokenizer = load_tokenizer(model_root)?;
        match backend {
            Backend::Cpu => {
                let ort_dll = gety_ort_dll()?;
                init_ort(&ort_dll)?;
                let model_path = model_root.join("onnx").join("model_uint8.onnx");
                ensure_file(&model_path)?;
                let session = Session::builder()
                    .context("create CPU session builder")?
                    .commit_from_file(&model_path)
                    .with_context(|| format!("load CPU model {}", model_path.display()))?;
                Ok(Self {
                    backend,
                    tokenizer,
                    cpu_session: Some(session),
                    cuda_session: None,
                    npu: None,
                    info: EngineInfo {
                        backend: "CPU".into(),
                        model: "gety-embed-v0 · model_uint8.onnx".into(),
                        device: "ONNX Runtime CPU".into(),
                        detail: "384-d · 512 tokens".into(),
                    },
                })
            }
            Backend::Cuda => {
                let ort_dll = gety_ort_dll()?;
                init_ort(&ort_dll)?;
                prepare_cuda_paths()?;
                let model_path = model_root.join("onnx_cuda").join("model_fp16.onnx");
                ensure_file(&model_path)?;
                let session = Session::builder()
                    .context("create CUDA session builder")?
                    .with_execution_providers([CUDAExecutionProvider::default().build()])
                    .context("register CUDA execution provider")?
                    .commit_from_file(&model_path)
                    .with_context(|| format!("load CUDA model {}", model_path.display()))?;
                Ok(Self {
                    backend,
                    tokenizer,
                    cpu_session: None,
                    cuda_session: Some(session),
                    npu: None,
                    info: EngineInfo {
                        backend: "CUDA".into(),
                        model: "gety-embed-v0 · model_fp16.onnx".into(),
                        device: "NVIDIA GPU · CUDA EP".into(),
                        detail: "384-d · 512 tokens · FP16".into(),
                    },
                })
            }
            Backend::Npu => {
                prepare_openvino_path()?;
                let ov_dir = gety_openvino_dir()?;
                openvino_sys::library::load_from(ov_dir.join("openvino_c.dll"))
                    .map_err(|e| error!("load OpenVINO: {e}"))?;
                let mut core = Core::new().context("create OpenVINO core")?;
                let devices = core.available_devices().context("query OpenVINO devices")?;
                if !devices.iter().any(|d| matches!(d, DeviceType::NPU)) {
                    return Err(error!("OpenVINO NPU device not available: {devices:?}"));
                }
                let xml = npu_dir.join("model.xml");
                let bin = npu_dir.join("model.bin");
                ensure_file(&xml)?;
                ensure_file(&bin)?;
                let mut model = core
                    .read_model_from_file(
                        xml.to_string_lossy().as_ref(),
                        bin.to_string_lossy().as_ref(),
                    )
                    .with_context(|| format!("read OpenVINO IR {}", xml.display()))?;
                model
                    .reshape_single_input(&PartialShape::new_static(2, &[1, NPU_BUCKET as i64])?)
                    .context("reshape OpenVINO model for NPU")?;
                let compiled = core
                    .compile_model(&model, DeviceType::NPU)
                    .context("compile OpenVINO model for NPU")?;
                let request = compiled
                    .create_infer_request()
                    .context("create OpenVINO infer request")?;
                Ok(Self {
                    backend,
                    tokenizer,
                    cpu_session: None,
                    cuda_session: None,
                    npu: Some(NpuEngine {
                        request,
                        bucket: NPU_BUCKET,
                        _compiled: compiled,
                        _core: core,
                    }),
                    info: EngineInfo {
                        backend: "NPU".into(),
                        model: "gety-embed-v0 · OpenVINO IR".into(),
                        device: "Intel AI Boost · OpenVINO NPU".into(),
                        detail: format!("384-d · {NPU_BUCKET}-token bucket"),
                    },
                })
            }
            Backend::Auto => unreachable!("Auto handled by create"),
        }
    }

    pub fn info(&self) -> EngineInfo {
        self.info.clone()
    }

    /// Public identity of the deployed embedder.
    pub fn identity(&self) -> ModelIdentity {
        identity_for(self.backend)
    }

    pub fn embed(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        match self.backend {
            Backend::Cpu => self.embed_ort(texts, false),
            Backend::Cuda => self.embed_ort(texts, true),
            Backend::Npu => self.embed_npu(texts),
            Backend::Auto => unreachable!("engine always resolves Auto"),
        }
    }

    fn embed_ort(&mut self, texts: &[String], cuda: bool) -> Result<Vec<Vec<f32>>> {
        let batch_size = if cuda { 8 } else { 16 };
        let mut result = Vec::with_capacity(texts.len());
        for batch in texts.chunks(batch_size) {
            let encodings = self
                .tokenizer
                .encode_batch(batch.to_vec(), true)
                .map_err(|e| error!("tokenize: {e}"))?;
            let max_len = encodings
                .iter()
                .map(|e| e.get_ids().len())
                .max()
                .unwrap_or(1);
            let n = encodings.len();
            let ids: Vec<i64> = encodings
                .iter()
                .flat_map(|e| e.get_ids().iter().map(|x| *x as i64))
                .collect();
            let mask: Vec<i64> = encodings
                .iter()
                .flat_map(|e| e.get_attention_mask().iter().map(|x| *x as i64))
                .collect();
            let shape = vec![n, max_len];
            let session = if cuda {
                self.cuda_session.as_mut().expect("cuda session")
            } else {
                self.cpu_session.as_mut().expect("cpu session")
            };
            let outputs = session.run(ort::inputs![
                "input_ids" => Tensor::from_array((shape.clone(), ids))?,
                "attention_mask" => Tensor::from_array((shape.clone(), mask))?
            ])?;
            let output_name = if cuda {
                "embeddings"
            } else {
                "sentence_embedding"
            };
            let output = &outputs[output_name];
            if cuda {
                let (_, data) = output
                    .try_extract_tensor::<f16>()
                    .map_err(|e| error!("extract CUDA f16 output: {e}"))?;
                for row in data.chunks(DIM) {
                    result.push(normalize_row(row.iter().map(|v| v.to_f32()).collect()));
                }
            } else {
                let (_, data) = output
                    .try_extract_tensor::<f32>()
                    .map_err(|e| error!("extract CPU f32 output: {e}"))?;
                for row in data.chunks(DIM) {
                    result.push(normalize_row(row.to_vec()));
                }
            }
        }
        Ok(result)
    }

    fn embed_npu(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        let npu = self.npu.as_mut().expect("npu engine");
        let bucket = npu.bucket;
        let mut result = Vec::with_capacity(texts.len());
        for text in texts {
            let encoding = self
                .tokenizer
                .encode(text.as_str(), true)
                .map_err(|e| error!("tokenize: {e}"))?;
            let mut ids: Vec<i64> = encoding.get_ids().iter().map(|x| *x as i64).collect();
            ids.truncate(bucket);
            ids.resize(bucket, 1); // <pad> id 1; the IR computes its own attention mask
            let mut tensor = OvTensor::new(ElementType::I64, &Shape::new(&[1, bucket as i64])?)?;
            tensor.get_data_mut::<i64>()?.copy_from_slice(&ids);
            npu.request.set_input_tensor(&tensor)?;
            npu.request.infer()?;
            let output = npu.request.get_output_tensor_by_index(0)?;
            let data = output.get_data::<f32>()?;
            result.push(normalize_row(data.to_vec()));
        }
        Ok(result)
    }
}

impl Embedder for Engine {
    fn info(&self) -> EngineInfo {
        Engine::info(self)
    }

    fn identity(&self) -> ModelIdentity {
        Engine::identity(self)
    }

    fn embed(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
        Engine::embed(self, texts)
    }
}

fn normalize_row(mut row: Vec<f32>) -> Vec<f32> {
    let norm = row.iter().map(|v| v * v).sum::<f32>().sqrt();
    if norm > 1e-12 {
        for value in &mut row {
            *value /= norm;
        }
    }
    row
}

fn load_tokenizer(model_root: &Path) -> Result<Tokenizer> {
    let path = model_root.join("tokenizer.json");
    ensure_file(&path)?;
    let mut tokenizer = Tokenizer::from_file(&path)
        .map_err(|e| error!("load tokenizer {}: {e}", path.display()))?;
    tokenizer
        .with_truncation(Some(TruncationParams {
            max_length: 512,
            ..Default::default()
        }))
        .map_err(|e| error!("configure truncation: {e}"))?;
    tokenizer.with_padding(Some(PaddingParams {
        pad_id: 1,
        pad_token: "<pad>".to_string(),
        ..Default::default()
    }));
    Ok(tokenizer)
}

fn ensure_file(path: &Path) -> Result<()> {
    if path.is_file() {
        Ok(())
    } else {
        Err(error!("missing model file: {}", path.display()))
    }
}

pub fn gety_data_dir() -> Option<PathBuf> {
    std::env::var("APPDATA")
        .ok()
        .map(|p| PathBuf::from(p).join("ai.gety").join("data"))
}

pub fn gety_ort_dll() -> Result<PathBuf> {
    if let Ok(path) = std::env::var("SEEKY_ORT_DLL") {
        return Ok(PathBuf::from(path));
    }
    let path = gety_data_dir()
        .ok_or_else(|| error!("APPDATA is not set"))?
        .join("ep")
        .join("onnxruntime.dll");
    ensure_file(&path)?;
    Ok(path)
}

pub fn gety_openvino_dir() -> Result<PathBuf> {
    if let Ok(path) = std::env::var("SEEKY_OPENVINO_DIR") {
        return Ok(PathBuf::from(path));
    }
    let dir = gety_data_dir()
        .ok_or_else(|| error!("APPDATA is not set"))?
        .join("third_party_libs")
        .join("openvino");
    ensure_file(&dir.join("openvino_c.dll"))?;
    Ok(dir)
}

pub fn prepare_cuda_paths() -> Result<()> {
    let data = gety_data_dir().ok_or_else(|| error!("APPDATA is not set"))?;
    let ep = data.join("ep");
    let cuda = data.join("third_party_libs").join("cuda");
    ensure_file(&ep.join("onnxruntime_providers_cuda.dll"))?;
    prepend_path(&ep);
    if cuda.is_dir() {
        prepend_path(&cuda);
    }
    Ok(())
}

pub fn prepare_openvino_path() -> Result<()> {
    prepend_path(&gety_openvino_dir()?);
    Ok(())
}

// Audited exemption (SPEC-0001 section 5.3, audit A9); removed by WP-2.1,
// which loads provider libraries by explicit path.
#[allow(unsafe_code)]
fn prepend_path(dir: &Path) {
    let current = std::env::var_os("PATH").unwrap_or_default();
    let mut paths = vec![dir.to_path_buf()];
    paths.extend(std::env::split_paths(&current));
    if let Ok(joined) = std::env::join_paths(paths) {
        // SAFETY: `set_var` is unsound if another thread reads or writes the
        // environment at the same time. This runs while a CUDA or OpenVINO
        // backend is created, and other threads (Tauri, the watcher) may be
        // alive, so the residual risk is accepted only for the PoC: Seeky's
        // own code does not read PATH concurrently, but third-party code
        // might. WP-2.1 deletes this function.
        unsafe {
            std::env::set_var("PATH", joined);
        }
    }
}

pub fn find_gety_model_root() -> Result<PathBuf> {
    if let Ok(path) = std::env::var("SEEKY_GETY_MODEL_DIR") {
        let path = PathBuf::from(path);
        ensure_file(&path.join("tokenizer.json"))?;
        return Ok(path);
    }
    let base = gety_data_dir()
        .ok_or_else(|| error!("APPDATA is not set"))?
        .join("models")
        .join("gety-ai")
        .join("gety-embed-v0");
    let mut candidates = Vec::new();
    if base.is_dir() {
        for entry in std::fs::read_dir(&base)? {
            let entry = entry?;
            let path = entry.path();
            if path.join("tokenizer.json").is_file() {
                candidates.push(path);
            }
        }
    }
    candidates.sort();
    candidates
        .pop()
        .ok_or_else(|| error!("gety-embed-v0 not found under {}", base.display()))
}

fn strip_verbatim(path: PathBuf) -> PathBuf {
    let text = path.to_string_lossy();
    if let Some(rest) = text.strip_prefix(r"\\?\UNC\") {
        PathBuf::from(format!(r"\\{rest}"))
    } else if let Some(rest) = text.strip_prefix(r"\\?\") {
        PathBuf::from(rest)
    } else {
        path
    }
}

fn poc_shell_dir() -> PathBuf {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir
        .ancestors()
        .nth(2)
        .unwrap_or(Path::new("."))
        .join("apps")
        .join("desktop")
        .join("src-tauri")
}

pub fn resolve_npu_dir(resource_dir: Option<&Path>) -> PathBuf {
    let mut candidates = Vec::new();
    if let Ok(path) = std::env::var("SEEKY_NPU_DIR") {
        candidates.push(PathBuf::from(path));
    }
    if let Some(dir) = resource_dir {
        candidates.push(
            dir.join("resources")
                .join("models")
                .join("gety-embed-v0")
                .join("openvino"),
        );
        candidates.push(dir.join("models").join("gety-embed-v0").join("openvino"));
    }
    candidates.push(
        poc_shell_dir()
            .join("resources")
            .join("models")
            .join("gety-embed-v0")
            .join("openvino"),
    );
    if let Some(data) = gety_data_dir() {
        candidates.push(
            data.join("models")
                .join("gety-ai")
                .join("gety-embed-v0")
                .join("openvino"),
        );
    }
    candidates
        .into_iter()
        .find(|path| path.join("model.xml").is_file())
        .map(strip_verbatim)
        .unwrap_or_else(|| {
            poc_shell_dir()
                .join("resources")
                .join("models")
                .join("gety-embed-v0")
                .join("openvino")
        })
}

pub fn available_backends(model_root: Option<&Path>, npu_dir: &Path) -> Vec<String> {
    let mut backends = vec!["cpu".to_string()];
    if let Some(root) = model_root
        && root.join("onnx_cuda").join("model_fp16.onnx").is_file()
        && gety_data_dir()
            .map(|d| {
                d.join("ep")
                    .join("onnxruntime_providers_cuda.dll")
                    .is_file()
            })
            .unwrap_or(false)
    {
        backends.push("cuda".to_string());
    }
    if npu_dir.join("model.xml").is_file()
        && gety_data_dir()
            .map(|d| {
                d.join("third_party_libs")
                    .join("openvino")
                    .join("openvino_c.dll")
                    .is_file()
            })
            .unwrap_or(false)
    {
        backends.push("npu".to_string());
    }
    backends
}

#[cfg(test)]
mod tests {
    use super::*;

    fn roots() -> (PathBuf, PathBuf) {
        let model = find_gety_model_root().expect("gety model");
        let npu = resolve_npu_dir(None);
        (model, npu)
    }

    #[test]
    #[cfg_attr(
        not(feature = "hw-tests"),
        ignore = "needs local gety-embed-v0 and ONNX Runtime; run with --features hw-tests"
    )]
    fn cpu_embedding_works() {
        let (model, npu) = roots();
        let mut engine = Engine::create(Backend::Cpu, &model, &npu).expect("cpu engine");
        let vectors = engine
            .embed(&[
                "contract renewal terms".to_string(),
                "meeting notes about the budget".to_string(),
            ])
            .expect("embed");
        assert_eq!(vectors.len(), 2);
        assert_eq!(vectors[0].len(), DIM);
        let norm = vectors[0].iter().map(|v| v * v).sum::<f32>().sqrt();
        assert!((norm - 1.0).abs() < 0.01, "norm={norm}");
    }

    #[test]
    #[cfg_attr(
        not(feature = "hw-tests"),
        ignore = "needs an NVIDIA GPU and local CUDA assets; run with --features hw-tests"
    )]
    fn cuda_embedding_works() {
        let (model, npu) = roots();
        let mut engine = Engine::create(Backend::Cuda, &model, &npu).expect("cuda engine");
        let vectors = engine
            .embed(&["semantic search on the local disk".to_string()])
            .expect("embed");
        assert_eq!(vectors[0].len(), DIM);
    }

    #[test]
    #[cfg_attr(
        not(feature = "hw-tests"),
        ignore = "needs an Intel NPU and local OpenVINO assets; run with --features hw-tests"
    )]
    fn npu_embedding_works() {
        let (model, npu) = roots();
        let mut engine = Engine::create(Backend::Npu, &model, &npu).expect("npu engine");
        let vectors = engine
            .embed(&["search my documents by meaning".to_string()])
            .expect("embed");
        assert_eq!(vectors[0].len(), DIM);
    }
}
