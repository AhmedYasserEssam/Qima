# PDF Extraction Instructions with `opendataloader-pdf`

Extract text, tables, and headings from PDF files using Python and the `opendataloader-pdf` package.

---

## Requirements

- Python 3.10 or later
- Java 11+ available on the system `PATH`

Verify Java before installing:

```bash
java -version
```

If Java is not found, install a JDK:

| OS | Install Command |
|----|-----------------|
| macOS | `brew install --cask temurin` or download from [Adoptium](https://adoptium.net) |
| Ubuntu/Debian | `sudo apt install openjdk-17-jdk` |
| Windows | Download installer from [Adoptium](https://adoptium.net) (adds to PATH automatically) |

> **Windows PATH tip:** If `java -version` fails after installing, close and reopen your terminal. If it still fails, add `C:\Program Files\Eclipse Adoptium\jdk-<version>\bin` to your system PATH manually.

---

## Installation

```bash
pip install -U opendataloader-pdf
```

Upgrade regularly to pick up model, parser, and safety improvements.

---

## Python Usage

```python
import opendataloader_pdf

# Batch all files in one call — each convert() spawns a JVM process, so repeated calls are slow
opendataloader_pdf.convert(
    input_path=["file1.pdf", "file2.pdf", "folder/"],
    output_dir="output/",
    format="json,html,pdf,markdown",
)
```

### `convert()` Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `input_path` | `str \| list[str]` | required | One or more input PDF file paths or directories |
| `output_dir` | `str` | — | Directory where output files are written. Default: input file directory |
| `password` | `str` | — | Password for encrypted PDF files |
| `format` | `str \| list[str]` | — | Output formats (comma-separated). Values: `json`, `text`, `html`, `pdf`, `markdown`, `markdown-with-html`, `markdown-with-images`, `tagged-pdf`. Default: `json` |
| `quiet` | `bool` | `False` | Suppress console logging output |
| `content_safety_off` | `str \| list[str]` | — | Disable content safety filters. Values: `all`, `hidden-text`, `off-page`, `tiny`, `hidden-ocg` |
| `sanitize` | `bool` | `False` | Enable sensitive data sanitization. Replaces emails, phone numbers, IPs, credit cards, and URLs with placeholders |
| `keep_line_breaks` | `bool` | `False` | Preserve original line breaks in extracted text |
| `replace_invalid_chars` | `str` | `" "` | Replacement character for invalid/unrecognized characters |
| `use_struct_tree` | `bool` | `False` | Use PDF structure tree (tagged PDF) for reading order and semantic structure |
| `table_method` | `str` | `"default"` | Table detection method. Values: `default` (border-based), `cluster` (border + cluster) |
| `reading_order` | `str` | `"xycut"` | Reading order algorithm. Values: `off`, `xycut` |
| `markdown_page_separator` | `str` | — | Separator between pages in Markdown output. Use `%page-number%` for page numbers |
| `text_page_separator` | `str` | — | Separator between pages in text output. Use `%page-number%` for page numbers |
| `html_page_separator` | `str` | — | Separator between pages in HTML output. Use `%page-number%` for page numbers |
| `image_output` | `str` | `"external"` | Image output mode. Values: `off`, `embedded` (Base64), `external` (file references) |
| `image_format` | `str` | `"png"` | Output format for extracted images. Values: `png`, `jpeg` |
| `image_dir` | `str` | — | Directory for extracted images |
| `pages` | `str` | — | Pages to extract (e.g., `"1,3,5-7"`). Default: all pages |
| `include_header_footer` | `bool` | `False` | Include page headers and footers in output |
| `detect_strikethrough` | `bool` | `False` | Detect strikethrough text and wrap with `~~` in Markdown or `<del>` in HTML (experimental) |
| `hybrid` | `str` | `"off"` | Hybrid backend. Quick start: `pip install "opendataloader-pdf[hybrid]" && opendataloader-pdf-hybrid --port 5002`. Values: `off`, `docling-fast`, `hancom-ai` |
| `hybrid_mode` | `str` | `"auto"` | Hybrid triage mode. Values: `auto` (dynamic triage), `full` (skip triage, all pages to backend) |
| `hybrid_url` | `str` | — | Hybrid backend server URL (overrides default) |
| `hybrid_timeout` | `str` | `"0"` | Hybrid backend request timeout in milliseconds (`0` = no timeout) |
| `hybrid_fallback` | `bool` | `False` | Opt in to Java fallback on hybrid backend error |
| `to_stdout` | `bool` | `False` | Write output to stdout instead of file (single format only) |
| `threads` | `str` | `"1"` | Number of worker threads for per-page processing. Values >1 run pages in parallel (experimental). Capped at available CPU cores. Ignored in `--hybrid` mode |

---

## CLI Usage

```bash
# Batch all files in one call — each invocation spawns a JVM process, so repeated calls are slow
opendataloader-pdf file1.pdf file2.pdf folder/ \
  -o output/ \
  -f json,html,pdf,markdown
```

For all CLI options, refer to the CLI Options Reference.

---

## LangChain Integration

For RAG pipelines, use the official LangChain integration:

```bash
pip install -U langchain-opendataloader-pdf
```

```python
from langchain_opendataloader_pdf import OpenDataLoaderPDFLoader

loader = OpenDataLoaderPDFLoader(
    file_path=["file1.pdf", "file2.pdf", "folder/"],
    format="text"
)
documents = loader.load()
```

---

## Next Steps

- **Building a RAG pipeline?** See the RAG Integration Guide
- **Need schema details?** See the JSON Schema reference
- **Multi-column documents?** Learn about Reading Order configuration