# Local IUPAC conversion

The Compound structure editor sends the entered name to the authenticated local
API (`POST /api/v2/chemistry/resolve-iupac`). OPSIN 2.8.0 parses it locally; RDKit
validates the SMILES, preserves stereochemistry, and generates a 2D Molfile.
Names are never sent to a remote name-resolution service. Conversion only fills
the unsaved editor; reviewers must inspect the structure and save a Draft before
confirmation. Successful parsing does not establish scientific correctness.

The parser does not enable OPSIN's `allowUninterpretableStereo` option. Names
with unsupported stereochemistry or unsupported nomenclature may fail; reviewers
can continue with manual SMILES or Ketcher. Input is limited to one name of at
most 1,000 characters. Each Java process has an 8-second timeout and 128 MiB heap;
at most two conversions run concurrently per API worker.

## Installation

The backend Dockerfile installs a headless Java runtime and the pinned OPSIN CLI
JAR during image build. This provisioning step requires access to the upstream
GitHub release. Normal conversion does not download anything.

For development, install Java (a headless JRE, Java 8 or newer), then run from
`leadtrace/backend` with the backend virtual environment activated:

```bash
python -m app.chemistry.install_opsin --destination /absolute/local/runtime/opsin-cli-2.8.0-jar-with-dependencies.jar
export LEADTRACE_OPSIN_JAR=/absolute/local/runtime/opsin-cli-2.8.0-jar-with-dependencies.jar
```

The default path is `/opt/leadtrace/opsin/opsin-cli-2.8.0-jar-with-dependencies.jar`.
The installer verifies SHA-256 before replacing the destination atomically, and
the resolver verifies the installed file before execution. Do not commit the JAR
or runtime directories. An offline machine can use a separately downloaded copy
of the same verified artifact. OPSIN is distributed under the MIT license; its
bundled dependencies carry their own notices in the upstream JAR.

Pinned release:

- URL: https://github.com/dan2097/opsin/releases/download/2.8.0/opsin-cli-2.8.0-jar-with-dependencies.jar
- SHA-256: `d25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab`

## Verification and errors

With `LEADTRACE_OPSIN_JAR` set, run:

```bash
python -m pytest tests/chemistry/test_iupac.py tests/chemistry/test_iupac_api.py -q
```

The real-runtime tests cover ethanol, an R-configured chiral acid, and invalid
names. Without the environment variable those integration cases are explicitly
skipped; the API permission tests do not require PostgreSQL.

`IUPAC_UNAVAILABLE` means Java/JAR is absent, the digest differs, or the runtime
failed. `IUPAC_TIMEOUT` and `IUPAC_BUSY` are retryable. `IUPAC_UNPARSEABLE`,
`IUPAC_NAME_INVALID`, and `IUPAC_STRUCTURE_INVALID` require checking the input or
editing the structure manually. Errors expose fixed codes, not subprocess output
or user-entered chemical names.
