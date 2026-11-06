use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::process::{Command, ExitCode};
use std::time::Duration;
use clap::{Parser, Subcommand};
use regex::Regex;
use serde::{Deserialize, Serialize};

const GENERATIVE_URL: &str = "http://127.0.0.1:8080/v1/chat/completions";

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Symbol {
    name: String,
    #[serde(rename = "type")]
    sym_type: String,
    start: usize,
    end: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct Outline {
    file: String,
    total_lines: usize,
    total_bytes: usize,
    symbols: Vec<Symbol>,
}

fn query_local_llm(
    prompt: &str,
    system_prompt: &str,
    max_tokens: u32,
) -> String {
    #[derive(Serialize)]
    struct Message<'a> {
        role: &'a str,
        content: &'a str,
    }

    #[derive(Serialize)]
    struct ChatRequest<'a> {
        messages: Vec<Message<'a>>,
        temperature: f32,
        max_tokens: u32,
    }

    #[derive(Deserialize)]
    struct ChoiceMessage {
        #[serde(default)]
        content: Option<String>,
    }

    #[derive(Deserialize)]
    struct Choice {
        #[serde(default)]
        message: Option<ChoiceMessage>,
    }

    #[derive(Deserialize)]
    struct ChatResponse {
        #[serde(default)]
        choices: Vec<Choice>,
    }

    let payload = ChatRequest {
        messages: vec![
            Message {
                role: "system",
                content: system_prompt,
            },
            Message {
                role: "user",
                content: prompt,
            },
        ],
        temperature: 0.1,
        max_tokens,
    };

    let agent = ureq::AgentBuilder::new()
        .timeout_read(Duration::from_secs(8))
        .timeout_write(Duration::from_secs(8))
        .build();

    let res = agent
        .post(GENERATIVE_URL)
        .set("Content-Type", "application/json")
        .send_json(&payload);

    if let Ok(resp) = res {
        if let Ok(parsed) = resp.into_json::<ChatResponse>() {
            if let Some(first) = parsed.choices.into_iter().next() {
                if let Some(msg) = first.message {
                    if let Some(c) = msg.content {
                        let trimmed = c.trim().to_string();
                        if !trimmed.is_empty() {
                            return trimmed;
                        }
                    }
                }
            }
        }
    }

    "Error: Could not reach the local LLM on :8080. Start it with the `local-llm` skill (`scripts/llm_client.py start`).".to_string()
}

fn count_indent(line: &str) -> usize {
    let mut count = 0;
    for ch in line.chars() {
        if ch == ' ' {
            count += 1;
        } else if ch == '\t' {
            count += 4;
        } else {
            break;
        }
    }
    count
}

fn extract_python_symbols(lines: &[&str]) -> Vec<Symbol> {
    let mut symbols = Vec::new();
    let def_re = Regex::new(r"^\s*(?:async\s+)?def\s+([A-Za-z0-9_]+)\b").unwrap();
    let class_re = Regex::new(r"^\s*class\s+([A-Za-z0-9_]+)\b").unwrap();

    let total = lines.len();
    for i in 0..total {
        let line = lines[i];
        let trimmed = line.trim();
        if trimmed.starts_with('#') || trimmed.is_empty() {
            continue;
        }

        let mut sym_type = None;
        let mut name = None;

        if let Some(caps) = def_re.captures(line) {
            sym_type = Some("function");
            name = caps.get(1).map(|m| m.as_str().to_string());
        } else if let Some(caps) = class_re.captures(line) {
            sym_type = Some("class");
            name = caps.get(1).map(|m| m.as_str().to_string());
        }

        if let (Some(stype), Some(sname)) = (sym_type, name) {
            let start = i + 1;
            let base_indent = count_indent(line);

            let mut sig_end = i;
            let mut paren_depth: i32 = 0;
            for k in i..total {
                for ch in lines[k].chars() {
                    if ch == '(' || ch == '[' || ch == '{' {
                        paren_depth += 1;
                    } else if ch == ')' || ch == ']' || ch == '}' {
                        paren_depth -= 1;
                    }
                }
                if paren_depth <= 0 && lines[k].trim_end().ends_with(':') {
                    sig_end = k;
                    break;
                }
            }

            let mut end = sig_end + 1;
            for j in (sig_end + 1)..total {
                let next_line = lines[j];
                let next_trimmed = next_line.trim();
                if next_trimmed.is_empty() || next_trimmed.starts_with('#') {
                    continue;
                }
                let next_indent = count_indent(next_line);
                if next_indent <= base_indent {
                    break;
                }
                end = j + 1;
            }

            symbols.push(Symbol {
                name: sname,
                sym_type: stype.to_string(),
                start,
                end,
            });
        }
    }

    symbols.sort_by_key(|s| s.start);
    symbols
}

fn extract_brace_symbols(lines: &[&str]) -> Vec<Symbol> {
    let mut symbols = Vec::new();
    let fn_re = Regex::new(r"^\s*(?:pub(?:\([^)]+\))?\s+)?(?:export\s+)?(?:default\s+)?(?:async\s+)?(?:function|fn|func)\s+([A-Za-z0-9_]+)").unwrap();
    let type_re = Regex::new(r"^\s*(?:pub(?:\([^)]+\))?\s+)?(?:export\s+)?(?:struct|class|enum|trait|interface|type)\s+([A-Za-z0-9_]+)").unwrap();

    let total = lines.len();
    for i in 0..total {
        let line = lines[i];
        let trimmed = line.trim();
        if trimmed.starts_with("//") || trimmed.starts_with('#') || trimmed.is_empty() {
            continue;
        }

        let mut sym_type = None;
        let mut name = None;

        if let Some(caps) = fn_re.captures(line) {
            sym_type = Some("function");
            name = caps.get(1).map(|m| m.as_str().to_string());
        } else if let Some(caps) = type_re.captures(line) {
            sym_type = Some("class");
            name = caps.get(1).map(|m| m.as_str().to_string());
        }

        if let (Some(stype), Some(sname)) = (sym_type, name) {
            let start = i + 1;
            let mut end = start;
            let mut depth = 0;
            let mut opened = false;

            for j in i..total {
                let l = lines[j];
                for ch in l.chars() {
                    if ch == '{' {
                        depth += 1;
                        opened = true;
                    } else if ch == '}' {
                        depth -= 1;
                        if opened && depth == 0 {
                            end = j + 1;
                            break;
                        }
                    }
                }
                if opened && depth == 0 {
                    break;
                }
            }

            symbols.push(Symbol {
                name: sname,
                sym_type: stype.to_string(),
                start,
                end,
            });
        }
    }

    symbols.sort_by_key(|s| s.start);
    symbols
}

fn extract_regex_symbols(lines: &[&str]) -> Vec<Symbol> {
    let mut symbols = Vec::new();
    let pat = Regex::new(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|def|class|interface|type)\s+([A-Za-z0-9_]+)").unwrap();

    for (idx, line) in lines.iter().enumerate() {
        if let Some(caps) = pat.captures(line) {
            if let Some(m) = caps.get(1) {
                symbols.push(Symbol {
                    name: m.as_str().to_string(),
                    sym_type: "symbol".to_string(),
                    start: idx + 1,
                    end: idx + 1,
                });
            }
        }
    }
    symbols
}

fn get_outline(target_file: &Path) -> Result<Outline, String> {
    let text = fs::read_to_string(target_file)
        .map_err(|e| format!("Error: File '{}' does not exist or unreadable: {}", target_file.display(), e))?;

    let lines: Vec<&str> = text.lines().collect();
    let ext = target_file
        .extension()
        .and_then(|e| e.to_str())
        .unwrap_or("")
        .to_lowercase();

    let symbols = match ext.as_str() {
        "py" => extract_python_symbols(&lines),
        "rs" | "ts" | "tsx" | "js" | "jsx" | "go" | "c" | "cpp" | "h" | "hpp" | "java" => {
            extract_brace_symbols(&lines)
        }
        _ => extract_regex_symbols(&lines),
    };

    let total_bytes = text.len();
    let total_lines = lines.len();

    let abs_path = fs::canonicalize(target_file)
        .unwrap_or_else(|_| target_file.to_path_buf())
        .to_string_lossy()
        .to_string();

    Ok(Outline {
        file: abs_path,
        total_lines,
        total_bytes,
        symbols,
    })
}

fn view_file_gated(
    file_path: &Path,
    symbol: Option<&str>,
    lines_range: Option<(usize, usize)>,
    max_preview: usize,
) -> String {
    if !file_path.is_file() {
        return format!("Error: File '{}' does not exist.", file_path.display());
    }

    let text = match fs::read_to_string(file_path) {
        Ok(t) => t,
        Err(_) => return format!("Error: File '{}' is not valid UTF-8.", file_path.display()),
    };

    let all_lines: Vec<&str> = text.lines().collect();
    let total_lines = all_lines.len();
    let file_name = file_path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("file");

    if let Some((start, end)) = lines_range {
        let s = start.max(1);
        let e = end.min(total_lines);
        if s > e || s > total_lines {
            return format!("Error: Line range {}-{} out of bounds (file has {} lines).", s, e, total_lines);
        }
        let sliced = &all_lines[s - 1..e];
        let mut out = Vec::new();
        out.push(format!("📄 {} (Lines {}-{} of {}):\n```", file_name, s, e, total_lines));
        for (idx, line) in sliced.iter().enumerate() {
            out.push(format!("{:4}: {}", s + idx, line));
        }
        out.push("```".to_string());
        return out.join("\n");
    }

    if let Some(sym_query) = symbol {
        let outline = match get_outline(file_path) {
            Ok(o) => o,
            Err(e) => return e,
        };

        let matching: Vec<&Symbol> = outline
            .symbols
            .iter()
            .filter(|s| s.name.eq_ignore_ascii_case(sym_query))
            .collect();

        if matching.is_empty() {
            let available: Vec<&str> = outline
                .symbols
                .iter()
                .take(30)
                .map(|s| s.name.as_str())
                .collect();
            return format!(
                "Symbol '{}' not found in {}. Available symbols:\n{}",
                sym_query,
                file_name,
                available.join(", ")
            );
        }

        let target_sym = matching[0];
        let s = target_sym.start.max(1);
        let e = target_sym.end.min(total_lines);
        let sliced = if s <= e && s <= total_lines {
            &all_lines[s - 1..e]
        } else {
            &all_lines[s - 1..s]
        };

        let mut out = Vec::new();
        out.push(format!(
            "🔍 Symbol `{}` ({}, lines {}-{} in {}):\n```",
            target_sym.name, target_sym.sym_type, target_sym.start, target_sym.end, file_name
        ));
        for (idx, line) in sliced.iter().enumerate() {
            out.push(format!("{:4}: {}", s + idx, line));
        }
        out.push("```".to_string());
        return out.join("\n");
    }

    if total_lines <= max_preview {
        let mut out = Vec::new();
        out.push(format!("📄 {} (All {} lines):\n```", file_name, total_lines));
        for (idx, line) in all_lines.iter().enumerate() {
            out.push(format!("{:4}: {}", idx + 1, line));
        }
        out.push("```".to_string());
        return out.join("\n");
    }

    let outline = match get_outline(file_path) {
        Ok(o) => o,
        Err(e) => return e,
    };

    let mut out = Vec::new();
    out.push(format!(
        "🛡️  [cgate] Context Protection Active for `{}` ({} lines, {} bytes)",
        file_name, total_lines, text.len()
    ));
    out.push("Dumping the full file would bloat your context window.".to_string());
    out.push("".to_string());
    out.push("### Key Symbols Defined in File:".to_string());

    if !outline.symbols.is_empty() {
        for s in outline.symbols.iter().take(25) {
            out.push(format!("- `{}` ({}): Lines {}-{}", s.name, s.sym_type, s.start, s.end));
        }
        if outline.symbols.len() > 25 {
            out.push(format!("- ... and {} more symbols", outline.symbols.len() - 25));
        }
    } else {
        out.push("_(No AST/regex top-level symbols detected)_".to_string());
    }

    out.push(format!("\n### Preview (First {} lines):\n```", max_preview));
    for (idx, line) in all_lines.iter().take(max_preview).enumerate() {
        out.push(format!("{:4}: {}", idx + 1, line));
    }
    out.push("```".to_string());
    out.push("\n👉 To view specific section without context bloat:".to_string());
    out.push(format!("   cgate view {} --symbol <symbol_name>", file_path.display()));
    out.push(format!("   cgate view {} --lines <start>-<end>", file_path.display()));
    out.push(format!("   cgate query {} \"<what you want to know>\"", file_path.display()));

    out.join("\n")
}

fn grep_gated(
    pattern: &str,
    search_path: &Path,
    max_hits_per_file: usize,
    max_total_files: usize,
) -> String {
    let output = Command::new("rg")
        .args(["-n", "--no-heading", pattern, &search_path.to_string_lossy()])
        .output()
        .or_else(|_| {
            Command::new("grep")
                .args(["-rn", pattern, &search_path.to_string_lossy()])
                .output()
        });

    let res = match output {
        Ok(o) => o,
        Err(_) => return format!("No matches found for '{}' in {}.", pattern, search_path.display()),
    };

    let stdout = String::from_utf8_lossy(&res.stdout);
    let lines: Vec<&str> = stdout.lines().filter(|l| !l.trim().is_empty()).collect();

    if lines.is_empty() {
        return format!("No matches found for '{}' in {}.", pattern, search_path.display());
    }

    let mut file_matches: BTreeMap<String, Vec<(usize, String)>> = BTreeMap::new();
    for line in &lines {
        let parts: Vec<&str> = line.splitn(3, ':').collect();
        if parts.len() >= 3 {
            let f_path = parts[0].to_string();
            if let Ok(line_no) = parts[1].parse::<usize>() {
                let match_text = parts[2].trim().to_string();
                file_matches.entry(f_path).or_default().push((line_no, match_text));
            }
        }
    }

    let total_occurrences = lines.len();
    let total_files = file_matches.len();

    let mut out = Vec::new();
    out.push(format!(
        "🔍 [cgate grep] Query: `{}` (Found {} total occurrences across {} files)\n",
        pattern, total_occurrences, total_files
    ));

    for (f_path, matches) in file_matches.iter().take(max_total_files) {
        out.push(format!("📄 **{}** ({} matches):", f_path, matches.len()));
        for (l_no, text) in matches.iter().take(max_hits_per_file) {
            let truncated = if text.len() > 100 {
                &text[..100]
            } else {
                text.as_str()
            };
            out.push(format!("  Line {:4}: `{}`", l_no, truncated));
        }
        if matches.len() > max_hits_per_file {
            out.push(format!(
                "  ... and {} more matches in this file.",
                matches.len() - max_hits_per_file
            ));
        }
        out.push("".to_string());
    }

    if total_files > max_total_files {
        out.push(format!(
            "⚠️  ... and {} additional files with matches omitted to protect context.",
            total_files - max_total_files
        ));
    }

    out.join("\n")
}

fn query_gated(file_path: &Path, question: &str) -> String {
    if !file_path.is_file() {
        return format!("Error: File '{}' does not exist.", file_path.display());
    }

    let file_name = file_path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("file");

    let text = match fs::read_to_string(file_path) {
        Ok(t) => t,
        Err(_) => return format!("Error: File '{}' is not valid UTF-8.", file_path.display()),
    };

    let content = if text.len() > 30000 {
        format!("{}\n\n... [truncated for local decision engine] ...", &text[..30000])
    } else {
        text
    };

    let prompt = format!(
        "File Content:\n```\n{}\n```\n\nQuestion: {}\n\nAnswer concisely and quote only the exact lines.",
        content, question
    );

    let answer = query_local_llm(
        &prompt,
        "You are a concise code analyst. Answer directly with minimal tokens and quote only the exact 2-5 relevant lines.",
        250,
    );

    format!("🤖 [cgate query: {}]\n**Question:** {}\n\n{}", file_name, question, answer)
}

#[derive(Parser)]
#[command(name = "cgate", version = "0.1.0", about = "cgate: Context-Gated Reader & Filter (Kem Glitch Architecture)")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    #[command(about = "View a file with automatic context guarding")]
    View {
        #[arg(help = "Path to file")]
        file: String,
        #[arg(long, help = "Extract only specific function/class symbol")]
        symbol: Option<String>,
        #[arg(long, help = "Extract specific line range, e.g. 50-80")]
        lines: Option<String>,
        #[arg(long, default_value = "35", help = "Max preview lines for un-gated display")]
        max_preview: usize,
    },
    #[command(about = "Display symbol outline and line spans of a file")]
    Outline {
        #[arg(help = "Path to file")]
        file: String,
    },
    #[command(about = "Context-gated ripgrep search")]
    Grep {
        #[arg(help = "Search pattern")]
        pattern: String,
        #[arg(default_value = ".", help = "Target directory or file (default: .)")]
        path: String,
        #[arg(long, default_value = "3", help = "Max hits per file")]
        limit: usize,
    },
    #[command(about = "Ask the local LLM (:8080) a question about a file without context bloat")]
    Query {
        #[arg(help = "Path to file")]
        file: String,
        #[arg(help = "Question about file")]
        question: String,
    },
}

fn main() -> ExitCode {
    let cli = Cli::parse();

    match cli.command {
        Commands::View {
            file,
            symbol,
            lines,
            max_preview,
        } => {
            let mut lines_range = None;
            if let Some(l_str) = lines {
                let parts: Vec<&str> = l_str.split('-').collect();
                if parts.len() == 2 {
                    if let (Ok(s), Ok(e)) = (parts[0].trim().parse::<usize>(), parts[1].trim().parse::<usize>()) {
                        lines_range = Some((s, e));
                    }
                }
                if lines_range.is_none() {
                    eprintln!("Invalid lines format '{}'. Expected format: 10-30", l_str);
                    return ExitCode::FAILURE;
                }
            }
            println!("{}", view_file_gated(Path::new(&file), symbol.as_deref(), lines_range, max_preview));
            ExitCode::SUCCESS
        }
        Commands::Outline { file } => {
            let p = Path::new(&file);
            if !p.is_file() {
                println!("Error: {} does not exist.", p.display());
                return ExitCode::FAILURE;
            }
            match get_outline(p) {
                Ok(out) => {
                    println!("\n📂 File: {} ({} lines)", out.file, out.total_lines);
                    println!("{}", "-".repeat(50));
                    for s in &out.symbols {
                        let tag = if s.sym_type.len() >= 4 {
                            s.sym_type[..4].to_uppercase()
                        } else {
                            s.sym_type.to_uppercase()
                        };
                        println!(
                            "  [{:4}] {:30} : Lines {:4} - {:4}",
                            tag, s.name, s.start, s.end
                        );
                    }
                    println!("{}\n", "-".repeat(50));
                    ExitCode::SUCCESS
                }
                Err(e) => {
                    eprintln!("{}", e);
                    ExitCode::FAILURE
                }
            }
        }
        Commands::Grep { pattern, path, limit } => {
            println!("{}", grep_gated(&pattern, Path::new(&path), limit, 8));
            ExitCode::SUCCESS
        }
        Commands::Query { file, question } => {
            println!("{}", query_gated(Path::new(&file), &question));
            ExitCode::SUCCESS
        }
    }
}
