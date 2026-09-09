"""Bundle the canonical harness into wheels AND sdists without maintaining a second copy."""
from pathlib import Path
import shutil
from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.command.sdist import sdist

HERE = Path(__file__).resolve().parent


def bundle(destination):
    source = HERE.parent if (HERE.parent / 'bin' / 'arc-close').is_file() else HERE / 'yeoul_mcp' / '_harness'
    for directory in ('bin', 'templates'):
        target = Path(destination) / directory
        target.mkdir(parents=True, exist_ok=True)
        for file in (source / directory).iterdir():
            if file.is_file() and not file.name.startswith('_t_'):
                shutil.copy2(file, target / file.name)
                if directory == 'bin':
                    (target / file.name).chmod(0o755)
    shutil.copy2(source / 'LICENSE', Path(destination) / 'LICENSE')


class BuildHarness(build_py):
    def run(self):
        super().run()
        bundle(Path(self.build_lib) / 'yeoul_mcp' / '_harness')


class SourceHarness(sdist):
    def make_release_tree(self, base_dir, files):
        super().make_release_tree(base_dir, files)
        bundle(Path(base_dir) / 'yeoul_mcp' / '_harness')


setup(cmdclass={'build_py': BuildHarness, 'sdist': SourceHarness})
