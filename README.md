# RWX Blast Radius test selector

This candidate selects sqlglot tests for the Builders Buildathon RWX Blast Radius track. Each incoming patch is analyzed against clean sqlglot revision `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. The selector combines old-line and enclosing-function coverage with resource readers, shared fixture consumers, and process-owning test cohorts. Canonical pytest identities are resolved against each incoming manifest. The scheduler compares greedy partitions of up to eight workers using the official cost formula.

The selector falls back to all tests when evidence is insufficient, including many import, initialization, and structural changes. Coverage describes observed execution. Native resource reads, dynamic registration, previously untaken branches, and shared state across modules can hide dependencies. Adding or removing a file can also affect directory readers.

## Build and run

Use Docker, Make, and host Python 3.9 or newer for the scorer. The root Dockerfile builds for Linux amd64, uses the starter's pinned Python image, and downloads sqlglot at the revision above. It verifies the archive and the files copied into the image against SHA-256 hashes. Runtime needs no network. Input comes from `/data/tests.json` and `/data/commits/*.patch`. The selector writes one JSON result per patch to stdout and diagnostics to stderr.

```sh
docker build --no-cache --platform linux/amd64 --tag blast-radius-entry .
```

For local scoring, [download the official starter archive](https://www.joinbuilders.org/buildathon/tracks/blast-radius/files/blast-radius-sample.tar.gz) and extract only `sample/` in a separate directory. From this repository, point the official Make targets at that sample directory. The scorer reads the answers on the host. Docker receives only the manifest and patches.

```sh
make -o build check SAMPLE=/absolute/path/to/sample
make -o build sample SAMPLE=/absolute/path/to/sample
docker run --rm --platform linux/amd64 --network none \
  --volume "$PWD:/workspace:ro" --workdir /workspace blast-radius-entry \
  python -m unittest discover -s tests -v
```

The Make commands reuse the image built above and apply the track's runtime restrictions. Both targets can also build the image automatically if `-o build` is omitted.

## Evidence and local results

The committed maps come from clean-base pytest coverage, AST ranges, and a separate access-only run against the pinned revision. See the generation commands and provenance in [COVERAGE.md](docs/COVERAGE.md) and [STAGE5.md](docs/STAGE5.md). Competition labels are used only by local evaluation.

On the 30 official sample changes, the candidate cost **617.271 simulated seconds**, with **zero misses and zero penalties**. Across seven independent local changes, it accounted for the entire 1,620-test manifest per change and selected all 14 failing numbered tests. All 33 focused checks passed. These local results exclude the competition server's CPU charge and three-run median. The official cost and protocol are documented in [SCORING.md](SCORING.md).
