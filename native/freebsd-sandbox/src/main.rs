//! Unprivileged Hermes adapter. Only the shared daemon creates jails/mounts.
use anyhow::{Result, ensure};
use codex_freebsd_sandbox_client as client;
use serde::Deserialize;
use std::collections::BTreeMap;
use std::io::Read;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Specification {
    version: u32,
    argv: Vec<String>,
    cwd: PathBuf,
    policy: client::policy::Policy,
    env: BTreeMap<String, String>,
}

fn probe() -> Result<client::protocol::Capabilities> {
    let capabilities = client::capabilities()?;
    ensure!(
        capabilities
            .features
            .iter()
            .any(|f| f == "source-identities-v1"),
        "Hermes requires source-identities-v1"
    );
    Ok(capabilities)
}

#[cfg(unix)]
fn launch(request_fd: i32, death_fd: i32) -> Result<i32> {
    use std::os::fd::FromRawFd;
    ensure!(
        request_fd > 2 && death_fd > 2 && request_fd != death_fd,
        "invalid launch descriptors"
    );
    // These descriptors originate from the trusted controller, never from the
    // model's command. Drop the request pipe before opening the service socket.
    let request = unsafe { std::fs::File::from_raw_fd(request_fd) };
    let mut bytes = Vec::new();
    request
        .take(client::protocol::MAX_FRAME as u64 + 1)
        .read_to_end(&mut bytes)?;
    ensure!(
        bytes.len() <= client::protocol::MAX_FRAME,
        "launch request too large"
    );
    let spec: Specification =
        serde_json::from_slice(&bytes).map_err(|_| anyhow::anyhow!("invalid launch request"))?;
    ensure!(
        spec.version == 1 && !spec.argv.is_empty() && spec.cwd.is_absolute(),
        "invalid launch specification"
    );
    let permissions = spec.policy.permissions()?;
    probe()?;
    let mut death = unsafe { std::fs::File::from_raw_fd(death_fd) };
    std::thread::spawn(move || {
        let mut byte = [0];
        // EOF means the controller died. Exiting closes the service connection;
        // the daemon then kills the whole jail, including detached descendants.
        let _ = death.read(&mut byte);
        std::process::exit(125);
    });
    client::run(client::protocol::Launch {
        version: client::protocol::VERSION,
        argv: spec.argv,
        policy_cwd: spec.cwd.clone(),
        cwd: spec.cwd,
        permissions,
        env: spec.env,
        terminal: None,
    })
}

fn main() {
    let result = (|| -> Result<i32> {
        let args: Vec<String> = std::env::args().skip(1).collect();
        if args == ["--version"] {
            println!("hermes-freebsd-sandbox {}", env!("CARGO_PKG_VERSION"));
            return Ok(0);
        }
        if args == ["--probe"] {
            println!("{}", serde_json::to_string(&probe()?)?);
            return Ok(0);
        }
        #[cfg(unix)]
        if args.len() == 4 && args[0] == "--request-fd" && args[2] == "--parent-fd" {
            return launch(args[1].parse()?, args[3].parse()?);
        }
        anyhow::bail!("expected --probe or dedicated request/parent descriptors")
    })();
    match result {
        Ok(code) => std::process::exit(code),
        Err(error) => {
            eprintln!("Hermes jail execution refused: {error:#}");
            std::process::exit(125);
        }
    }
}
