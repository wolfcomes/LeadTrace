"""Explicit, frozen scientific runtimes. Credentials remain in local CLI configuration."""
from __future__ import annotations
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal
from pydantic import BaseModel, ConfigDict, model_validator

class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    adapter: Literal['dsh', 'codex'] = 'dsh'
    model: str | None = None
    reasoning_effort: str | None = None
    python_executable: str = sys.executable

    @model_validator(mode='after')
    def supported(self):
        if self.model is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', self.model):
            raise ValueError('Invalid model ID')
        allowed = {'dsh': {'none', 'low', 'medium', 'high', 'max'},
                   'codex': {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'}}
        if self.reasoning_effort is not None and self.reasoning_effort not in allowed[self.adapter]:
            raise ValueError('Reasoning effort is unsupported by the selected adapter')
        if self.adapter == 'codex' and self.model is None:
            raise ValueError('Codex tasks require an explicit model')
        if not Path(self.python_executable).is_absolute():
            raise ValueError('Scientific Python must be an absolute path')
        return self


def tool_preflight(python_executable: str) -> dict:
    probe = '''import json,sys,pymupdf as fitz,rdkit
from rdkit import Chem
from rdkit.Chem import Draw
m=Chem.MolFromSmiles("CNC1CCCCC1")
assert m is not None
assert "svg" in Draw.MolsToGridImage([m],useSVG=True)
p=fitz.open();p.new_page();assert len(p.tobytes())>0
print(json.dumps({"python":sys.executable,"rdkit_version":rdkit.__version__,"rdkit_parse_and_render":True,"pdf_tools":True}))'''
    try:
        r = subprocess.run([python_executable, '-c', probe], capture_output=True, text=True, timeout=30, check=True)
        return json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError('Scientific Python must provide working RDKit rendering and PyMuPDF') from None


def build_command(config: RuntimeConfig, directory: Path, executable: str, prompt: str) -> list[str]:
    if config.adapter == 'codex':
        args = [executable, 'exec', '--model', config.model, '--sandbox', 'workspace-write',
                '--skip-git-repo-check', '--json', '--color', 'never', '-C', str(directory)]
        if config.reasoning_effort is not None:
            args += ['-c', 'model_reasoning_effort=' + json.dumps(config.reasoning_effort)]
        # The writable task is the only output root. No bypass or native resume.
        return args + [prompt]
    patch = []
    if config.model:
        patch.append({'id': 'agent-default-model', 'config': {'provider': 'deepseek-official', 'model': config.model}})
    if config.reasoning_effort:
        values = {'thinking': 'disabled' if config.reasoning_effort == 'none' else 'enabled'}
        if config.reasoning_effort != 'none': values['reasoningEffort'] = config.reasoning_effort
        patch.append({'id': 'llm-deepseek', 'config': values})
    args = [executable]
    if patch:
        path = directory / 'runtime-patch.json'
        # JSON is a YAML subset accepted by dsh's patch loader.
        with path.open('x') as stream: json.dump(patch, stream)
        path.chmod(0o400)
        args += ['--patch', str(path)]
    return args + ['--profile', 'headless', prompt]


def runtime_environment(config: RuntimeConfig, env: dict[str, str]) -> dict[str, str]:
    result = dict(env)
    result['PATH'] = str(Path(config.python_executable).parent) + os.pathsep + env.get('PATH', '')
    result['LEADTRACE_SCIENTIFIC_PYTHON'] = config.python_executable
    if config.adapter == 'dsh':
        observer = Path(__file__).with_name('request_observer.cjs')
        result['NODE_OPTIONS'] = (env.get('NODE_OPTIONS', '') + ' --require=' + str(observer)).strip()
    return result


def observed_runtime(directory: Path, config: RuntimeConfig) -> dict:
    """Read only whitelisted request metadata; never parse model reasoning logs."""
    observations = []
    incomplete = False
    path = directory / 'runtime-requests.jsonl'
    if config.adapter == 'dsh' and path.is_file():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
                if not isinstance(row, dict): raise ValueError('Invalid metadata')
                for key in ('model', 'reasoning_effort', 'thinking'):
                    if row.get(key) is not None and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', str(row[key])):
                        raise ValueError('Invalid metadata value')
            except (ValueError, TypeError):
                incomplete = True
                continue
            # Ignore auxiliary 64-token naming requests; they are not the scientific model.
            if row.get('max_tokens') == 64: continue
            value = {k: row.get(k) for k in ('model', 'reasoning_effort', 'thinking')}
            if value not in observations: observations.append(value)
    mismatch = any((config.model and r['model'] != config.model) or
                   (config.reasoning_effort and (('none' if r['thinking']=='disabled' else r['reasoning_effort']) != config.reasoning_effort)) for r in observations)
    return {'requested': config.model_dump(exclude={'python_executable'}), 'observed': observations,
            'metadata_incomplete': incomplete, 'verification': 'mismatch' if mismatch else 'request_observed' if observations and not incomplete else 'requested_only'}
