"""Inspect the user's local Playwright + TypeScript framework."""
import json
import os
import re
from pathlib import Path

from contracts import FrameworkProfile, FrameworkScan

from .claude import run_agent

SKIP_DIRS = {'node_modules', '.git', 'dist', 'build', 'out', 'coverage', 'playwright-report', 'test-results',
             '.api-test-studio', '.idea', '.vscode', 'blob-report'}
SPEC_FILE = re.compile(r'\.(spec|test)\.(ts|mts|cts|tsx)$')


class FrameworkError(ValueError):
    """The folder cannot be used as a Playwright + TypeScript framework."""


def env_example_keys(root: Path) -> list[str]:
    """Variable names only; Claude is blocked from reading any .env* file directly."""
    keys = []
    for name in ('.env.example', '.env.sample', '.env.template'):
        path = root / name
        if path.is_file():
            for line in path.read_text(encoding='utf-8', errors='replace').splitlines()[:200]:
                match = re.match(r'\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=', line)
                if match and match.group(1) not in keys:
                    keys.append(match.group(1))
    return keys


def scan(folder: str) -> FrameworkScan:
    root = Path(folder)
    if not root.is_dir():
        raise FrameworkError(f'The folder "{folder}" does not exist on this computer. Check the path in the portal.')
    package_file = root / 'package.json'
    if not package_file.is_file():
        raise FrameworkError('No package.json found. Choose the root folder of your Playwright project.')
    try:
        package = json.loads(package_file.read_text(encoding='utf-8-sig'))
    except ValueError as exc:
        raise FrameworkError('package.json is not valid JSON.') from exc
    dependencies = {**package.get('dependencies', {}), **package.get('devDependencies', {})}
    if '@playwright/test' not in dependencies:
        raise FrameworkError('This folder is not a Playwright project: @playwright/test is missing from package.json.')
    if 'typescript' not in dependencies and not (root / 'tsconfig.json').is_file():
        raise FrameworkError('This folder does not look like a TypeScript project (no typescript dependency or tsconfig.json).')
    config_files = sorted(p.name for p in root.iterdir() if p.is_file() and (
        p.name.startswith('playwright.config.') or p.name in ('tsconfig.json', '.eslintrc.json', 'eslint.config.mjs',
                                                               'eslint.config.js', '.env.example')))
    if not any(name.startswith('playwright.config.') for name in config_files):
        raise FrameworkError('No playwright.config file found in this folder.')
    specs = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')]
        for name in files:
            if SPEC_FILE.search(name):
                specs.append((Path(current) / name).relative_to(root).as_posix())
    specs.sort(key=lambda p: ('api' not in p.lower(), len(p), p))
    return FrameworkScan(envExampleKeys=env_example_keys(root),playwrightVersion=str(dependencies.get('@playwright/test', '')),
                         typescriptVersion=str(dependencies.get('typescript', '')), configFiles=config_files,
                         specFileCount=len(specs), sampleSpecFiles=specs[:25],
                         scripts={k: str(v) for k, v in list(package.get('scripts', {}).items())[:30]})


def analyze(job_input: dict, report, submit=None, agent=run_agent) -> dict:
    folder = job_input['frameworkPath']
    report('Checking your framework folder', 5)
    facts = scan(folder)
    count = facts.specFileCount
    report(f'The AI is reading your framework ({count} existing test file{"" if count == 1 else "s"})', 15)
    task = {
        'goal': 'Build the framework profile that future test scripts must follow.',
        'frameworkRoot': 'The current working directory is the framework root. Use relative paths.',
        'projectName': job_input.get('projectName', ''),
        'scan': facts.model_dump(),
    }
    profile = agent('framework-analyzer', task, FrameworkProfile, cwd=folder, tools=('Read', 'Glob', 'Grep'), max_turns=60)
    report('Saving the framework profile', 95)
    return {'profile': profile, 'scan': facts.model_dump()}
