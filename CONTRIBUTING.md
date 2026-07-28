# Contributing to Multi-Agent Research Assistant

Thanks for your interest in contributing! This guide will help you get started.

## Getting Started

1. **Fork** the repository and clone your fork
2. Copy `.env.example` to `.env` and fill in your API keys
3. Run `./start.sh` to bring up the full stack (requires Docker)
4. Run `./start.sh --fake` to use mock agents without API keys

## Development Setup

### Backend (Python 3.11+)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest
```

### Frontend (Node 18+)

```bash
cd frontend
npm install
npm run dev
```

## How to Contribute

### Reporting Bugs

- Use [GitHub Issues](https://github.com/adityamhaske/Multi-Agent-Research-Assistant/issues)
- Include steps to reproduce, expected vs. actual behavior, and your environment
- Check existing issues first to avoid duplicates

### Suggesting Features

- Open an issue with the **enhancement** label
- Describe the use case and why it's valuable

### Submitting Code

1. Create a branch from `main` (`git checkout -b feat/your-feature`)
2. Make your changes — keep diffs small and focused
3. Add or update tests for your changes
4. Ensure all checks pass:
   ```bash
   # Backend
   cd backend && pytest

   # Frontend
   cd frontend && npm run lint && npm run typecheck && npm run test
   ```
5. Open a pull request against `main`

### Pull Request Guidelines

- One logical change per PR
- Write a clear description of **what** and **why**
- Link related issues with `Fixes #123` or `Closes #123`
- All CI checks must pass before merge

## Code Style

- **Python**: Follow existing patterns, type hints encouraged
- **TypeScript/React**: Follow existing patterns, strict mode enabled
- No new dependencies unless necessary — prefer stdlib and existing deps

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
