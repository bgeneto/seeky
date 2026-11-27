> **Source document (Portuguese).** This is the original scope input kept for provenance. The active English product decisions are in [seeky-product-decisions.md](seeky-product-decisions.md) and the English scope summary is in [seeky-scope.md](seeky-scope.md).

Eu reduziria consideravelmente o escopo do Gety para construir um produto especializado em **busca semântica local de altíssimo desempenho**, em vez de uma plataforma de recuperação de contexto para agentes de IA.

A ideia seria investir praticamente toda a complexidade de engenharia em quatro métricas:

- **Qualidade de recuperação:** encontrar os arquivos e trechos realmente relevantes.
- **Latência de busca:** apresentar resultados em dezenas ou centenas de milissegundos.
- **Velocidade de indexação:** processar grandes volumes de arquivos eficientemente.
- **Eficiência computacional:** minimizar o consumo de RAM, VRAM, CPU e armazenamento.

O produto Seeky poderia ser conceitualmente definido como:

> A high-performance, local-first semantic file search engine. No cloud, no chatbots, no agents. Just search.

## **1. Features do Gety que podem ser eliminadas**

| Feature                                | Decisão         | Justificativa                                            |
| -------------------------------------- | --------------- | -------------------------------------------------------- |
| MCP Server                             | Remover         | Não haverá integração com agentes.                       |
| MCP Authentication                     | Remover         | Desnecessária sem servidor MCP.                          |
| REST API pública                       | Remover         | A comunicação interna do aplicativo é suficiente.        |
| CLI pública                            | Opcional        | Útil para usuários avançados, mas dispensável no MVP.    |
| Connector SDK                          | Remover         | A única fonte de dados será o filesystem.                |
| Gerenciamento de conectores            | Remover         | Não haverá fontes externas.                              |
| Sincronização com serviços externos    | Remover         | O filesystem será a fonte de verdade.                    |
| Sandbox de conectores                  | Remover         | Não haverá execução de código de terceiros.              |
| Gerenciamento de API keys              | Remover         | Desnecessário para inferência exclusivamente local.      |
| Acesso via LAN                         | Remover         | O aplicativo será exclusivamente local.                  |
| Integração com Claude, ChatGPT etc.    | Remover         | Fora do escopo.                                          |
| Permissões de compartilhamento com IA  | Remover         | Nenhum documento será enviado a agentes.                 |
| Formatação de contexto para LLMs       | Remover         | Os resultados serão apresentados diretamente ao usuário. |
| Token budgeting para LLMs              | Remover         | Não haverá context window de um modelo generativo.       |
| Endpoints de recuperação de documentos | Remover         | Substituir por acesso interno aos arquivos.              |
| Infraestrutura de plugins              | Remover         | Complexidade arquitetural desnecessária.                 |
| LLM generativo                         | Não implementar | Não é necessário para busca semântica.                   |
| Chat e histórico de conversas          | Não implementar | O produto é um buscador, não um chatbot.                 |
| Gerenciamento multiusuário             | Não implementar | Aplicativo desktop individual.                           |

Essa simplificação elimina uma parte significativa da superfície de segurança, manutenção, documentação e testes do produto, sem comprometer a qualidade da busca.

## **2. Features que podem ser simplificadas ou adiadas**

Algumas funcionalidades são úteis, mas não precisam ter a mesma abrangência que possuem no Gety.

| Feature                          | Recomendação                                                   |
| -------------------------------- | -------------------------------------------------------------- |
| OCR                              | Manter como módulo opcional, executado durante a indexação.    |
| Busca por nome de arquivo        | Manter, utilizando um índice leve e independente.              |
| Busca full-text                  | Manter como componente da busca híbrida.                       |
| Preview de documentos            | Simplificar: texto extraído e trechos relevantes inicialmente. |
| Visualizador PDF                 | Adiar; abrir no aplicativo padrão do sistema.                  |
| Visualizador Office              | Remover; abrir no aplicativo padrão do sistema.                |
| Suporte a centenas de formatos   | Começar pelos 20–30 formatos mais relevantes.                  |
| Busca semântica em imagens       | Adiar para uma segunda versão.                                 |
| Transcrição de áudio e vídeo     | Não implementar inicialmente.                                  |
| Pesquisa em arquivos compactados | Adiar.                                                         |
| Histórico de buscas              | Opcional, armazenado localmente.                               |
| Buscas salvas                    | Adiar.                                                         |
| Coleções de documentos           | Remover; utilizar pastas reais.                                |
| Tags personalizadas              | Remover; não é um gerenciador de documentos.                   |
| Miniaturas de arquivos           | Utilizar recursos nativos do sistema operacional.              |
| Busca em unidades de rede        | Adiar devido à complexidade do monitoramento.                  |
| Busca em discos removíveis       | Adiar ou implementar como índices independentes.               |
| Aceleração por NPU               | Adiar até validar os backends CPU e GPU.                       |
| Gerenciador de modelos           | Simplificar para alguns perfis predefinidos.                   |
| Suporte a modelos arbitrários    | Adiar; utilizar modelos selecionados e otimizados.             |

O aplicativo não precisa ser um gerenciador de documentos, visualizador universal de arquivos, assistente pessoal ou plataforma extensível.

## **3. Features essenciais que devem permanecer**

Estas são as funcionalidades que considero indispensáveis para um produto realmente competitivo.

**Semantic Search Engine**

Busca por linguagem natural, multilíngue, baseada no significado do conteúdo dos arquivos.

**Hybrid Retrieval**

Combinação de dense embeddings, BM25, filename matching e, opcionalmente, learned sparse retrieval.

**Neural Reranking**

Reclassificação dos candidatos mais relevantes utilizando um cross-encoder otimizado.

**Semantic Snippets / Pruning**

Seleção dos parágrafos e frases mais relevantes de cada documento, com destaque visual.

**Embedded Vector Database**

Banco vetorial persistente, sem servidor externo, com ANN, filtros e quantização.

**Incremental Indexing**

Monitoramento automático de criação, modificação, movimentação e exclusão de arquivos.

**Hardware Acceleration**

Inferência otimizada para CPU e GPU, batching, quantização e gerenciamento eficiente de memória.

**Document Extraction**

Extração eficiente de texto, metadados, títulos, páginas, seções e estrutura dos documentos.

**Metadata Filtering**

Filtros por pasta, extensão, tamanho, data de criação e modificação.

**Instant Search UI**

Resultados progressivos, cancelamento de buscas anteriores, atalhos de teclado e interface responsiva.


## **4. Onde investir para superar o Gety**

Em vez de investir em abrangência funcional, concentraria os esforços nos seguintes subsistemas.

| Subsistema             | Prioridade | Investimento                                      |
| ---------------------- | ---------- | ------------------------------------------------- |
| Embedding model        | Máxima     | Qualidade, multilingual, quantização e throughput |
| Neural reranker        | Máxima     | Relevância e baixa latência                       |
| Vector database        | Máxima     | ANN, SIMD, quantização e persistência             |
| Incremental indexing   | Máxima     | Processamento paralelo e deduplicação             |
| Document chunking      | Alta       | Segmentação estrutural e contextual               |
| Document-level ranking | Alta       | Agregação de múltiplos trechos por arquivo        |
| Hybrid retrieval       | Alta       | BM25, dense retrieval e rank fusion               |
| Inference runtime      | Alta       | Aceleração multiplataforma                        |
| Semantic pruner        | Alta       | Trechos relevantes e legíveis                     |
| Document parsing       | Alta       | Precisão da extração textual                      |
| OCR                    | Média      | Processamento assíncrono                          |
| Preview avançado       | Baixa      | Conveniência                                      |
| Personalização visual  | Baixa      | Experiência do usuário                            |

### **4.1. Embeddings melhores**

Gety's `gety-embed-v0` tem como vantagem o tamanho reduzido e a eficiência computacional.

Entretanto, você pode oferecer modelos mais sofisticados, selecionados de acordo com o hardware disponível.

| Perfil              | Modelo candidato        |
| ------------------- | ----------------------- |
| CPU ultraleve       | `gety-embed-v0`         |
| CPU equilibrado     | `multilingual-e5-small` |
| CPU/GPU equilibrado | `Qwen3-Embedding-0.6B`  |
| GPU alta precisão   | `Qwen3-Embedding-4B`    |
| GPU máxima precisão | `Qwen3-Embedding-8B`    |

Os modelos Qwen3 suportam Matryoshka Representation Learning (MRL), permitindo selecionar dimensões de saída menores sem necessariamente utilizar toda a dimensionalidade original.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://huggingface.co\&sz=32)

Hugging Face+2



Isso possibilita otimizar simultaneamente a qualidade de recuperação, o tamanho do índice vetorial e a velocidade de busca ANN.

Esses modelos são candidatos para benchmarking, não uma classificação SOTA comprovada para novembro de 2026.

### **4.2. Banco vetorial embedded**

Eu eliminaria qualquer dependência de um banco vetorial executado como servidor separado.

| Tecnologia            | Arquitetura             | Adequação                             |
| --------------------- | ----------------------- | ------------------------------------- |
| LanceDB               | Embedded                | Excelente                             |
| USearch               | Embedded ANN library    | Excelente                             |
| ObjectBox             | Embedded database       | Alta                                  |
| sqlite-vec            | Extensão SQLite         | Alta para índices menores             |
| FAISS                 | Biblioteca de indexação | Alta, exige persistência complementar |
| Qdrant Server         | Serviço separado        | Menor                                 |
| Milvus                | Serviço separado        | Menor                                 |
| PostgreSQL + pgvector | Serviço separado        | Menor                                 |

[LanceDB](https://github.com/lancedb/lancedb?utm_source=chatgpt.com) é particularmente interessante porque permite reunir busca vetorial, full-text search e filtragem em uma biblioteca embedded.&#x20;

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub+1



Entretanto, se o objetivo for extrair o máximo desempenho possível, eu também avaliaria uma combinação de **USearch + Tantivy + SQLite**.

A primeira abordagem simplifica a engenharia. A segunda permite maior controle sobre cada subsistema.

### **4.3. Dimensionalidade e quantização dos vetores**

Um milhão de chunks pode ocupar uma quantidade significativa de armazenamento apenas com seus embeddings.

### **Calculadora de armazenamento vetorial**

Quantidade de chunks indexados1 milhão

Dimensionalidade

2563845127681024

Precisão dos vetores

FP32 — 32 bits

FP16 — 16 bits

INT8 — 8 bits

Binária — 1 bit

Armazenamento bruto dos embeddings

# **768.00 MB**

FP32

1536 MB

FP16

768 MB

INT8

384 MB

Binária

48 MB

Não inclui overhead do índice ANN, metadados, texto extraído, índices lexicais ou estruturas auxiliares.

Uma arquitetura particularmente interessante seria utilizar vetores compactos para recuperar candidatos rapidamente e vetores de maior precisão para refinar os resultados antes do neural reranking.

## **5. Estratégia para buscas extremamente rápidas**

Eu não executaria todos os estágios de forma síncrona e bloqueante. Implementaria **progressive search rendering**.

### **Latency budget proposto**

Exemplo de busca com GPU e modelos previamente carregados

Primeiros resultados

# **30 ms**

Ranking refinado

# **90 ms**

Trechos semânticos

# **120 ms**

Metas ilustrativas de engenharia, não resultados de benchmark. Dependem do hardware, tamanho dos modelos, quantidade de candidatos e volume do índice.

Para alcançar esse comportamento, implementaria:

- Modelos residentes em memória, evitando cold starts.
- Query embedding e busca lexical em paralelo.
- Cache LRU de query embeddings.
- Dynamic batching no reranker.
- Reranking restrito aos melhores candidatos.
- Pruning somente dos resultados visíveis.
- Cancelamento imediato de buscas obsoletas.
- Adaptive debounce para busca durante a digitação.
- Suspensão ou redução da indexação durante buscas interativas.
- Quantização dos modelos e dos índices vetoriais.
- Memory-mapped indexes sempre que apropriado.
- Prefetch dos trechos dos primeiros resultados.

O neural reranker provavelmente será um dos maiores gargalos da pipeline. Um modelo com melhor resultado em benchmarks acadêmicos, mas com latência cinco vezes maior, não é necessariamente uma boa escolha para um buscador interativo.

## **6. Interface do aplicativo**

A interface também pode ser extremamente simplificada. Não vejo necessidade de mais do que três áreas principais.


## **7. Stack tecnológica recomendada**

Assumindo um aplicativo desktop multiplataforma, autocontido, sem dependências externas obrigatórias:

| Camada                | Tecnologia candidata                           |
| --------------------- | ---------------------------------------------- |
| Desktop framework     | Tauri 2                                        |
| Frontend              | Svelte ou React + TypeScript                   |
| Backend               | Rust                                           |
| Async runtime         | Tokio                                          |
| CPU parallelism       | Rayon                                          |
| Filesystem monitoring | `notify`                                       |
| Filesystem scanning   | `jwalk` / `ignore`                             |
| Embedding inference   | ONNX Runtime / llama.cpp                       |
| Reranker inference    | ONNX Runtime / llama.cpp, conforme o modelo    |
| Pruner inference      | ONNX Runtime                                   |
| Vector database       | LanceDB ou USearch                             |
| Full-text search      | Tantivy, se necessário                         |
| Metadata persistence  | SQLite                                         |
| Tokenization          | Hugging Face Tokenizers                        |
| PDF extraction        | PDFium                                         |
| OCR                   | PaddleOCR / ONNX                               |
| IPC                   | Tauri commands e channels                      |
| CPU optimization      | AVX2, AVX-512, ARM NEON                        |
| GPU optimization      | CUDA, DirectML, Metal/Core ML conforme runtime |
| Packaging             | Instaladores nativos                           |

Não utilizaria LangChain, LlamaIndex, Haystack ou frameworks de agentes. O problema é essencialmente de **Information Retrieval (IR)**, e não de orquestração de LLMs.

## **8. Metas mensuráveis do produto**

Para justificar a alegação de busca SOTA, estabeleceria objetivos verificáveis desde o início.

| Métrica                        | Meta inicial proposta                    |
| ------------------------------ | ---------------------------------------- |
| Primeiros resultados — GPU     | Inferior a 50 ms                         |
| Busca completa — GPU           | Inferior a 150 ms                        |
| Busca completa — CPU           | Inferior a 500 ms                        |
| Latência do ANN                | Inferior a 10 ms no corpus de referência |
| Recall\@100                    | Superior a 95% em corpus anotado         |
| nDCG\@10                       | Superior ao baseline do Gety             |
| MRR\@10                        | Superior ao baseline do Gety             |
| Capacidade de indexação        | Pelo menos 1 milhão de chunks            |
| Atualização do índice          | Incremental e automática                 |
| Operação offline               | 100% após instalação dos modelos         |
| Telemetria obrigatória         | Zero                                     |
| Serviços externos obrigatórios | Zero                                     |

Essas metas devem ser avaliadas em condições controladas, incluindo p50, p95 e p99, cache frio e quente, CPU e GPU, consultas em português e inglês e diferentes tipos de documentos.

## **9. Escopo final recomendado**

### **Dentro do escopo**

Local filesystem search

SOTA embeddings

Neural reranking

Semantic pruning

Hybrid retrieval

Vector quantization

Embedded vector DB

Incremental indexing

Document parsing

Optional OCR

Hardware acceleration

Metadata filters

Semantic snippets

Progressive results

Cross-platform desktop

### **&#x20;Fora do escopo**

AI agents

Generative LLMs

Chat interface

MCP server

REST API server

External connectors

Connector SDK

Cloud synchronization

External AI integrations

API key management

Multiuser management

Plugin marketplace

LAN sharing

RAG orchestration

LLM context budgeting
