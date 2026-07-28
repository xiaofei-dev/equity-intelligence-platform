# Generated Evidence Policy

This directory may contain small, Git-safe, immutable contract and acceptance
artifacts that are required to reproduce repository tests and documented
decisions.

The following remain local and are ignored:

- high-volume `*-diagnostics.json` files;
- transient lock files; and
- explicitly invalid or superseded serialization artifacts listed in
  `.gitignore`.

Licensed provider observations, raw responses, credentials, and other
controlled values must remain under the ignored `storage/` boundary. A
generated summary is not safe to commit merely because it is JSON: it must
exclude raw licensed values and secrets, retain only sanitized references and
hashes, and pass the repository's publication audit.
