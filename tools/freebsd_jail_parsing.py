"""Bundle the existing document parser for execution without controller imports."""
from pathlib import Path


def extraction_bootstrap():
    from tools import read_extract, ansi_strip
    modules = {"tools.ansi_strip": Path(ansi_strip.__file__).read_text(encoding="utf-8"),
               "tools.read_extract": Path(read_extract.__file__).read_text(encoding="utf-8")}
    # All parser code is installed application code. No source/configuration from
    # the document or workspace is evaluated during worker initialization.
    return '\n' + f'''
import types
package = types.ModuleType("tools")
package.__path__ = []
sys.modules["tools"] = package
lazy = types.ModuleType("tools.lazy_deps")
lazy.ensure = lambda *args, **kwargs: None
sys.modules[lazy.__name__] = lazy
for name, code in {modules!r}.items():
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(code, name, "exec"), module.__dict__)
parser = sys.modules["tools.read_extract"]
parser._hosted_ocr_config = lambda: (False, None, None)
extract_document_bytes = parser.extract_document_bytes
'''
