# Contributing

## Development setup

```bash
make install
make check
make run
```

Mock mode must remain the default. Tests and pull requests must not require model credentials or spend tokens.

## Change expectations

- Add or update a focused test when behavior changes.
- Keep tools read-only unless the security model and approval flow are deliberately redesigned.
- Never commit incident secrets, AWS credentials, `.env` files, or raw production evidence.
- Keep commit subjects imperative, lowercase, and specific.

Use GitHub Issues for reproducible bugs and scoped feature proposals.
