# CFD Sentinel

CFD Sentinel is an open-source safety layer for long-running CFD automation.
It audits an existing solver workflow, adds recoverable checkpoints when they
are missing, watches runtime logs, and sends timely alerts to researchers.

The first public release focuses on explicit ANSYS Fluent journal commands on
Windows. The design is adapter-based so other solvers can be added later.

> **Alpha software:** always review the generated journal on a small test case
> before using it for a long production solve.

## What problem does it solve?

Long CFD jobs can run for hours or days. A raw CSV or a zero process return code
does not prove that a recoverable solution exists. CFD Sentinel treats a
checkpoint as valid only when a non-empty Fluent case/data pair exists.

The Fluent adapter checks:

- an explicit Standard Initialization command exists;
- initialization is followed by a complete case/data snapshot;
- every configured interval, 1000 iterations by default, has a case/data pair;
- the final iteration is followed by a final case/data save;
- iteration commands are simple enough to rewrite safely.

If protection is missing, `harden` writes a separate journal that:

- leaves the user's source journal unchanged;
- saves a case/data pair immediately after initialization;
- splits long `/solve/iterate` commands at checkpoint boundaries;
- saves and verifies case/data after every 1000 iterations;
- saves and verifies a final case/data pair;
- deletes only its own same-name checkpoint before saving, avoiding Fluent's
  interactive overwrite dialog.

## Installation

Python 3.9 or newer is required.

```bash
git clone https://github.com/1760147165-lang/cfd-sentinel.git
cd cfd-sentinel
python -m pip install .
```

For development:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Quick start: protect a Fluent journal

Audit the existing journal:

```powershell
cfd-sentinel audit "D:\work\case01\run.jou" --interval 1000
```

Create the checkpoint directory:

```powershell
New-Item -ItemType Directory "D:\work\case01\checkpoints" -Force
```

Generate a hardened copy:

```powershell
cfd-sentinel harden "D:\work\case01\run.jou" `
  --output "D:\work\case01\run.sentinel.jou" `
  --checkpoint-dir "D:/work/case01/checkpoints" `
  --prefix "case01" `
  --interval 1000
```

Run the generated journal only after reviewing it:

```powershell
cfd-sentinel run `
  --log "D:\work\case01\sentinel.log" `
  --checkpoint-dir "D:\work\case01\checkpoints" `
  --checkpoint-prefix "case01_" `
  --email "researcher@example.com" `
  -- "C:\Program Files\ANSYS Inc\v231\fluent\ntbin\win64\fluent.exe" `
  3ddp -t22 -wait -i "D:\work\case01\run.sentinel.jou"
```

You can also supervise a log produced by an already-running workflow:

```powershell
cfd-sentinel watch "D:\work\case01\fluent_console.log" `
  --email "researcher@example.com" `
  --stale-seconds 1800
```

## Email configuration

Credentials are read only from environment variables. Never commit an SMTP
password or authorization code.

```powershell
$env:CFD_SENTINEL_SMTP_HOST = "smtp.example.com"
$env:CFD_SENTINEL_SMTP_PORT = "587"
$env:CFD_SENTINEL_SMTP_USERNAME = "alert@example.com"
$env:CFD_SENTINEL_SMTP_PASSWORD = "your-smtp-app-password"
$env:CFD_SENTINEL_SMTP_FROM = "alert@example.com"
$env:CFD_SENTINEL_SMTP_STARTTLS = "true"
```

Use `--dry-run-email` to preview alerts without connecting to SMTP.

## Verify recovery files

```powershell
cfd-sentinel verify "D:\work\case01\checkpoints" --prefix "case01_"
```

The command fails if:

- no complete pair exists;
- a `.cas.h5` file is missing its `.dat.h5` partner;
- a `.dat.h5` file is missing its `.cas.h5` partner;
- either file is empty.

## Current safety boundary

Automatic hardening intentionally accepts only standalone commands such as:

```text
/solve/initialize/initialize-flow
/solve/iterate 5000
```

Scheme-generated iteration commands, multiple initialization sequences, Python
journals, GUI transcripts, and solver-specific custom loops require an adapter
or manual review. CFD Sentinel reports them as unsupported instead of guessing.

It does not decide convergence, modify physics, initialize a recovery run, or
automatically stop a solver after an alert.

## Roadmap

- Fluent recovery-resume assistant and Windows desktop onboarding
- configurable convergence and residual policies
- disk-space and license-server monitoring
- OpenFOAM and STAR-CCM+ adapters
- optional local dashboard and additional notification channels

Release history is available in [CHANGELOG.md](CHANGELOG.md).

## Security and privacy

CFD Sentinel does not require uploading meshes, case/data files, results, or
email credentials. See [SECURITY.md](SECURITY.md) for reporting security issues.

## License

Apache License 2.0. See [LICENSE](LICENSE).
