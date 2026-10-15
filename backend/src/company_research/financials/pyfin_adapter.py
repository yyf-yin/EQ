"""Optional Finance-Python (import PyFin), never the unrelated `pyfin` package.

Checked upstream release: 0.9.10, Jan 2023, Windows CPython 3.9 wheel only.
No corporate metrics are delegated to an undocumented third-party interface.
"""

from importlib import metadata, import_module
from .formulas import Calculator


class PyFinAdapter:
    def capability(self) -> dict:
        try:
            version = metadata.version('Finance-Python')
            module = import_module('PyFin')
            return {
                'available': True,
                'distribution': 'Finance-Python',
                'version': version,
                'import': module.__name__,
                'corporate_metrics': False,
                'engine': 'internal_decimal',
            }
        except (metadata.PackageNotFoundError, ImportError, OSError):
            return {
                'available': False,
                'distribution': 'Finance-Python',
                'verified_release': '0.9.10',
                'reason': '可选量化库未安装或二进制不兼容；公司公式使用独立确定性引擎',
                'engine': 'internal_decimal',
            }

    def calculator(self) -> Calculator:
        return Calculator()
