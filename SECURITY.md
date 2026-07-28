# Security Policy

## Supported versions

CFD Sentinel is currently an alpha release. Security fixes are applied to the
latest version on the default branch.

## Reporting a vulnerability

Please do not disclose credentials, private CFD data, or an exploitable issue in
a public GitHub issue. Contact the maintainer through the private contact method
listed on their GitHub profile and include only the minimum reproducible detail.

## Credential handling

SMTP passwords are read from environment variables and are never required in a
journal, command-line argument, or repository file. Users are responsible for
protecting their environment and using provider-issued application passwords.

CFD Sentinel does not upload meshes, case/data files, source temperature data,
or solver logs.
