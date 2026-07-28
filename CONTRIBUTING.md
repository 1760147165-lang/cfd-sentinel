# Contributing

Contributions are welcome, especially new solver adapters and reproducible
tests for journal variants.

1. Open an issue describing the workflow and solver version.
2. Do not attach proprietary meshes, case/data files, credentials, or private
   research results.
3. Add tests for every parser or transformer change.
4. Run `python -m unittest discover -s tests -v`.
5. Submit a focused pull request.

Automatic rewriting must fail closed: when syntax is ambiguous, report that
manual review is required instead of guessing.
