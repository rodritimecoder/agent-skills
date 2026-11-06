use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode, Stdio};
use clap::{Parser, Subcommand};
use regex::{Regex, RegexBuilder};
use serde::{Deserialize, Serialize};

static EMBEDDED_CONFIG: &str = include_str!("../../config.json");

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
struct ForbiddenCommand {
    pattern: String,
    reason: String,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
struct Config {
    #[serde(default)]
    version: Option<String>,
    #[serde(default)]
    name: Option<String>,
    #[serde(default)]
    description: Option<String>,
    #[serde(default)]
    protected_files: Vec<String>,
    #[serde(default)]
    forbidden_commands: Vec<ForbiddenCommand>,
    #[serde(default)]
    secret_leak_patterns: Vec<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default)]
struct WorkspaceConfig {
    #[serde(default)]
    protected_files: Vec<String>,
    #[serde(default)]
    forbidden_commands: Vec<ForbiddenCommand>,
}

fn load_config() -> Config {
    let mut config: Config = serde_json::from_str(EMBEDDED_CONFIG).unwrap_or_default();

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(parent) = exe_path.parent() {
            let candidate = parent.join("../config.json");
            if candidate.is_file() {
                if let Ok(text) = fs::read_to_string(&candidate) {
                    if let Ok(disk_cfg) = serde_json::from_str::<Config>(&text) {
                        config = disk_cfg;
                    }
                }
            }
        }
    }

    let ws_cfg_path = Path::new(".guard-hooks.json");
    if ws_cfg_path.is_file() {
        if let Ok(text) = fs::read_to_string(ws_cfg_path) {
            if let Ok(ws_cfg) = serde_json::from_str::<WorkspaceConfig>(&text) {
                config.protected_files.extend(ws_cfg.protected_files);
                config.forbidden_commands.extend(ws_cfg.forbidden_commands);
            }
        }
    }

    config
}

fn is_protected_file(file_path: &str, config: &Config) -> bool {
    let path = Path::new(file_path);
    let file_name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or(file_path);

    for pattern in &config.protected_files {
        if glob_match::glob_match(pattern, file_name)
            || glob_match::glob_match(pattern, file_path)
            || file_name.eq_ignore_ascii_case(pattern)
            || file_path.eq_ignore_ascii_case(pattern)
        {
            return true;
        }
    }
    false
}

fn check_file_action(action: &str, file: &str, config: &Config) -> Result<(), String> {
    let act = action.to_lowercase();
    if act == "delete" || act == "remove" || act == "overwrite" || act == "truncate" {
        if is_protected_file(file, config) {
            return Err(format!(
                "🛑 [GUARD-HOOK ERROR] Protected file '{}' cannot be {}d! (Kem Glitch Law: hooks always run regardless of prompt)",
                file, action
            ));
        }
    }
    Ok(())
}

fn check_command(cmd: &str, config: &Config) -> Result<(), String> {
    for item in &config.forbidden_commands {
        if let Ok(re) = RegexBuilder::new(&item.pattern).case_insensitive(true).build() {
            if re.is_match(cmd) {
                return Err(format!(
                    "🛑 [GUARD-HOOK BLOCKED] Command halted by deterministic hook: {} (Pattern: '{}')",
                    item.reason, item.pattern
                ));
            }
        }
    }

    if let Ok(rm_re) = Regex::new(r"\brm\s+.*") {
        if rm_re.is_match(cmd) {
            for token in cmd.split_whitespace() {
                let cleaned = token.trim_matches(|c| c == '\'' || c == '"');
                if is_protected_file(cleaned, config) {
                    return Err(format!(
                        "🛑 [GUARD-HOOK BLOCKED] Attempting to delete protected file '{}'! Intercepted before execution.",
                        cleaned
                    ));
                }
            }
        }
    }

    for sec_pat in &config.secret_leak_patterns {
        if let Ok(re) = Regex::new(sec_pat) {
            if re.is_match(cmd) {
                return Err(
                    "🛑 [GUARD-HOOK BLOCKED] Command contains exposed plaintext API key or private key! (Masked by secret shield)".to_string(),
                );
            }
        }
    }

    Ok(())
}

fn wrap_execution(cmd_tokens: &[String], config: &Config) -> i32 {
    let cmd_str = cmd_tokens.join(" ");
    if let Err(msg) = check_command(&cmd_str, config) {
        eprintln!("{}", msg);
        return 1;
    }

    match Command::new("sh")
        .arg("-c")
        .arg(&cmd_str)
        .stdin(Stdio::inherit())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .status()
    {
        Ok(status) => status.code().unwrap_or(1),
        Err(e) => {
            eprintln!("[guard-hooks] Execution failed: {}", e);
            1
        }
    }
}

fn protect_file(file_name: &str) {
    let cfg_path = PathBuf::from(".guard-hooks.json");
    let mut ws_cfg = if cfg_path.is_file() {
        fs::read_to_string(&cfg_path)
            .ok()
            .and_then(|t| serde_json::from_str::<WorkspaceConfig>(&t).ok())
            .unwrap_or_default()
    } else {
        WorkspaceConfig::default()
    };

    if !ws_cfg.protected_files.iter().any(|f| f == file_name) {
        ws_cfg.protected_files.push(file_name.to_string());
    }

    if let Ok(json_str) = serde_json::to_string_pretty(&ws_cfg) {
        let _ = fs::write(&cfg_path, json_str);
        println!(
            "[guard-hooks] Added '{}' to local protection list at {}",
            file_name,
            cfg_path.display()
        );
    }
}

fn check_staged_git(config: &Config) -> i32 {
    let names_out = Command::new("git")
        .args(["diff", "--cached", "--name-only"])
        .output();

    if let Ok(out) = names_out {
        if !out.status.success() {
            return 0;
        }
        let stdout = String::from_utf8_lossy(&out.stdout);
        for line in stdout.lines() {
            let f = line.trim();
            if !f.is_empty() && is_protected_file(f, config) {
                eprintln!(
                    "🛑 [GUARD-HOOK REJECTED] Cannot commit protected file: '{}'!",
                    f
                );
                return 1;
            }
        }
    }

    let diff_out = Command::new("git").args(["diff", "--cached"]).output();

    if let Ok(out) = diff_out {
        let diff_text = String::from_utf8_lossy(&out.stdout);
        for sec_pat in &config.secret_leak_patterns {
            if let Ok(re) = Regex::new(sec_pat) {
                if re.is_match(&diff_text) {
                    eprintln!(
                        "🛑 [GUARD-HOOK REJECTED] Commit aborted: Secret key leak detected in staged diff!"
                    );
                    return 1;
                }
            }
        }
    }

    println!("✅ [guard-hooks] Staged changes passed all deterministic safety checks.");
    0
}

fn install_git_hook() -> i32 {
    let hooks_dir = Path::new(".git/hooks");
    if !hooks_dir.is_dir() {
        eprintln!("[guard-hooks] Error: current directory is not a git repository.");
        return 1;
    }

    let pre_commit_file = hooks_dir.join("pre-commit");
    let hook_script = r#"#!/usr/bin/env bash
# Installed by guard-hooks (Kem Glitch Deterministic Hook Architecture)
set -eo pipefail

echo "🔒 [guard-hooks] Running pre-commit deterministic audit..."
guard-hooks check-staged
"#;

    if let Err(e) = fs::write(&pre_commit_file, hook_script) {
        eprintln!("[guard-hooks] Failed to write hook: {}", e);
        return 1;
    }

    let mut perms = fs::metadata(&pre_commit_file)
        .and_then(|m| Ok(m.permissions()))
        .unwrap_or_else(|_| fs::Permissions::from_mode(0o755));
    perms.set_mode(0o755);
    let _ = fs::set_permissions(&pre_commit_file, perms);

    println!(
        "[guard-hooks] Successfully installed pre-commit hook at {}",
        pre_commit_file.display()
    );
    0
}

#[derive(Parser)]
#[command(name = "guard-hooks", version = "0.1.0", about = "Deterministic Guard Hooks (Kem Glitch Architecture)")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand)]
enum Commands {
    #[command(about = "Check command or file action against deterministic guardrails")]
    Check {
        #[arg(help = "Shell command to validate")]
        command: String,
    },
    #[command(about = "Check file action safety (delete/overwrite)")]
    CheckFile {
        #[arg(help = "Action type (delete, overwrite, truncate)")]
        action: String,
        #[arg(help = "Target file path")]
        file: String,
    },
    #[command(about = "Wrap and execute command with pre-execution safety gate")]
    Wrap {
        #[arg(trailing_var_arg = true, allow_hyphen_values = true, required = true, help = "Command to safely execute")]
        command: Vec<String>,
    },
    #[command(about = "Add file to protected targets in current repo")]
    Protect {
        #[arg(help = "Filename or pattern to lock (e.g. KeepMD, *.key)")]
        file: String,
    },
    #[command(about = "Audit git staged files and diffs for protected files and leaks")]
    CheckStaged,
    #[command(about = "Install pre-commit hook in current git repository")]
    InstallGitHook,
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let config = load_config();

    match cli.command {
        Commands::Check { command } => match check_command(&command, &config) {
            Ok(()) => {
                println!("✅ [guard-hooks] Command permitted.");
                ExitCode::SUCCESS
            }
            Err(msg) => {
                eprintln!("{}", msg);
                ExitCode::FAILURE
            }
        },
        Commands::CheckFile { action, file } => match check_file_action(&action, &file, &config) {
            Ok(()) => {
                println!("✅ [guard-hooks] Action '{}' permitted on {}.", action, file);
                ExitCode::SUCCESS
            }
            Err(msg) => {
                eprintln!("{}", msg);
                ExitCode::FAILURE
            }
        },
        Commands::Wrap { command } => {
            let code = wrap_execution(&command, &config);
            if code == 0 {
                ExitCode::SUCCESS
            } else {
                ExitCode::from(code as u8)
            }
        }
        Commands::Protect { file } => {
            protect_file(&file);
            ExitCode::SUCCESS
        }
        Commands::CheckStaged => {
            let code = check_staged_git(&config);
            if code == 0 {
                ExitCode::SUCCESS
            } else {
                ExitCode::from(code as u8)
            }
        }
        Commands::InstallGitHook => {
            let code = install_git_hook();
            if code == 0 {
                ExitCode::SUCCESS
            } else {
                ExitCode::from(code as u8)
            }
        }
    }
}
