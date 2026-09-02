from pathlib import Path

def test_runtime_security_imports_use_canonical_namespace():
    targets=list(Path('sra_api').rglob('*.py'))+list(Path('tests').glob('*.py'))
    legacy='sra_'+'api'
    forbidden=(f'from {legacy}.security',f'import {legacy}.security',f'{legacy}.services.auth_store',f'{legacy}.routers.editor_dependencies')
    assert not [(p,x) for p in targets for x in forbidden if x in p.read_text(encoding='utf-8')]
