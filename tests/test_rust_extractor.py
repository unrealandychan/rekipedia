"""Tests for RustExtractor — tree-sitter full symbol coverage (#132)."""
from __future__ import annotations

import textwrap
from pathlib import Path

from rekipedia.extractors.rust_extractor import RustExtractor

EXTRACTOR = RustExtractor()


def _extract(src: str, filename: str = "src/lib.rs") -> object:
    """Write src to a tmp file and extract."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        file_path = repo / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(textwrap.dedent(src), encoding="utf-8")
        return EXTRACTOR.extract(file_path, repo)


# ── can_handle ────────────────────────────────────────────────────────────────

def test_can_handle_rs():
    assert EXTRACTOR.can_handle(Path("foo.rs")) is True

def test_cannot_handle_py():
    assert EXTRACTOR.can_handle(Path("foo.py")) is False

def test_cannot_handle_go():
    assert EXTRACTOR.can_handle(Path("main.go")) is False


# ── functions ────────────────────────────────────────────────────────────────

def test_extracts_free_function():
    result = _extract("fn greet(name: &str) -> String { name.to_string() }")
    names = [s.name for s in result.symbols]
    assert "greet" in names

def test_function_kind():
    result = _extract("fn hello() {}")
    fn = next(s for s in result.symbols if s.name == "hello")
    assert fn.kind == "function"

def test_main_sets_entry_point():
    result = _extract("fn main() {}", filename="src/main.rs")
    assert result.entry_points == ["src/main.rs"]

def test_no_entry_point_without_main():
    result = _extract("fn helper() {}")
    assert result.entry_points == []

def test_function_line_numbers():
    src = "\nfn foo() {\n    let x = 1;\n}\n"
    result = _extract(src)
    fn = next(s for s in result.symbols if s.name == "foo")
    assert fn.line_start == 2
    assert fn.line_end >= 4


# ── structs ──────────────────────────────────────────────────────────────────

def test_extracts_struct():
    result = _extract("struct Point { x: f64, y: f64 }")
    names = [s.name for s in result.symbols]
    assert "Point" in names

def test_struct_kind_is_type():
    result = _extract("struct Rect { w: u32, h: u32 }")
    s = next(s for s in result.symbols if s.name == "Rect")
    assert s.kind == "type"

def test_struct_signature():
    result = _extract("struct Foo;")
    s = next(s for s in result.symbols if s.name == "Foo")
    assert "struct Foo" in s.signature


# ── enums ────────────────────────────────────────────────────────────────────

def test_extracts_enum():
    result = _extract("enum Color { Red, Green, Blue }")
    names = [s.name for s in result.symbols]
    assert "Color" in names

def test_enum_kind_is_type():
    result = _extract("enum Direction { North, South }")
    s = next(s for s in result.symbols if s.name == "Direction")
    assert s.kind == "type"

def test_enum_signature_contains_variants():
    result = _extract("enum Status { Ok, Err }")
    s = next(s for s in result.symbols if s.name == "Status")
    assert "Ok" in s.signature or "Status" in s.signature

def test_enum_with_tuple_variants():
    result = _extract("enum Shape { Circle(f64), Square(f64) }")
    names = [s.name for s in result.symbols]
    assert "Shape" in names


# ── type aliases ─────────────────────────────────────────────────────────────

def test_extracts_type_alias():
    result = _extract("type Meters = f64;")
    names = [s.name for s in result.symbols]
    assert "Meters" in names

def test_type_alias_kind():
    result = _extract("type Handler = fn(u32) -> u32;")
    s = next(s for s in result.symbols if s.name == "Handler")
    assert s.kind == "type"

def test_type_alias_signature():
    result = _extract("type Result<T> = std::result::Result<T, String>;")
    s = next(s for s in result.symbols if s.name == "Result")
    assert "type Result" in s.signature


# ── traits ───────────────────────────────────────────────────────────────────

def test_extracts_trait():
    result = _extract("trait Animal { fn sound(&self) -> &str; }")
    names = [s.name for s in result.symbols]
    assert "Animal" in names

def test_trait_kind_is_interface():
    result = _extract("trait Drawable { fn draw(&self); }")
    s = next(s for s in result.symbols if s.name == "Drawable")
    assert s.kind == "interface"

def test_trait_signature():
    result = _extract("trait Speak { fn speak(&self); }")
    s = next(s for s in result.symbols if s.name == "Speak")
    assert "trait Speak" in s.signature


# ── consts and statics ────────────────────────────────────────────────────────

def test_extracts_const():
    result = _extract("const MAX_SIZE: usize = 1024;")
    names = [s.name for s in result.symbols]
    assert "MAX_SIZE" in names

def test_const_kind():
    result = _extract("const PI: f64 = 3.14159;")
    s = next(s for s in result.symbols if s.name == "PI")
    assert s.kind == "variable"

def test_const_signature():
    result = _extract("const VERSION: &str = \"1.0\";")
    s = next(s for s in result.symbols if s.name == "VERSION")
    assert "const VERSION" in s.signature

def test_extracts_static():
    result = _extract("static COUNTER: u32 = 0;")
    names = [s.name for s in result.symbols]
    assert "COUNTER" in names

def test_static_kind():
    result = _extract("static BUFFER: [u8; 8] = [0; 8];")
    s = next(s for s in result.symbols if s.name == "BUFFER")
    assert s.kind == "variable"

def test_static_signature():
    result = _extract("static LOG: &str = \"log\";")
    s = next(s for s in result.symbols if s.name == "LOG")
    assert "static LOG" in s.signature


# ── macro_rules! ─────────────────────────────────────────────────────────────

def test_extracts_macro():
    result = _extract("macro_rules! say_hello { () => { println!(\"hello\"); } }")
    names = [s.name for s in result.symbols]
    assert "say_hello" in names

def test_macro_kind():
    result = _extract("macro_rules! vec_of_strings { ($($x:expr),*) => { vec![$($x.to_string()),*] }; }")
    s = next(s for s in result.symbols if s.name == "vec_of_strings")
    assert s.kind == "other"

def test_macro_signature():
    result = _extract("macro_rules! my_macro { () => {}; }")
    s = next(s for s in result.symbols if s.name == "my_macro")
    assert "macro_rules! my_macro" in s.signature


# ── mod items ────────────────────────────────────────────────────────────────

def test_extracts_mod():
    result = _extract("mod utils { pub fn helper() {} }")
    names = [s.name for s in result.symbols]
    assert "utils" in names

def test_mod_kind():
    result = _extract("mod config { pub const DEBUG: bool = false; }")
    s = next(s for s in result.symbols if s.name == "config")
    assert s.kind == "module"


# ── use declarations → import relationships ───────────────────────────────────

def test_extracts_use_import():
    result = _extract("use std::collections::HashMap;")
    kinds = [r.kind for r in result.relationships]
    assert "import" in kinds

def test_use_import_target():
    result = _extract("use std::io::Write;")
    imports = [r.to for r in result.relationships if r.kind == "import"]
    assert any("Write" in imp or "io" in imp for imp in imports)


# ── impl Trait for Type → uses relationship ───────────────────────────────────

def test_impl_trait_creates_uses_relationship():
    src = """\
        trait Greet { fn hello(&self); }
        struct Bot;
        impl Greet for Bot { fn hello(&self) {} }
    """
    result = _extract(src)
    uses_rels = [r for r in result.relationships if r.kind == "uses"]
    assert uses_rels, "Expected 'uses' relationship for impl Trait for Type"

def test_impl_trait_from_and_to():
    src = """\
        trait Display { fn fmt(&self); }
        struct MyType;
        impl Display for MyType { fn fmt(&self) {} }
    """
    result = _extract(src)
    uses = next((r for r in result.relationships if r.kind == "uses"), None)
    assert uses is not None
    assert "MyType" in uses.from_
    assert "Display" in uses.to


# ── call relationships ────────────────────────────────────────────────────────

def test_call_relationship_between_functions():
    src = """\
        fn add(a: i32, b: i32) -> i32 { a + b }
        fn compute() -> i32 { add(1, 2) }
    """
    result = _extract(src)
    calls = [r for r in result.relationships if r.kind == "calls"]
    assert calls, "Expected call relationship from compute -> add"
    callers = [r.from_ for r in calls]
    callees = [r.to for r in calls]
    assert "compute" in callers
    assert "add" in callees


# ── mixed file ────────────────────────────────────────────────────────────────

def test_mixed_rust_file():
    src = """\
        use std::fmt;

        const VERSION: &str = "1.0";
        static RUNNING: bool = true;

        macro_rules! log { ($msg:expr) => { println!("{}", $msg); }; }

        pub enum Level { Debug, Info, Warn, Error }

        pub struct Logger { level: Level }

        pub trait Sink { fn write(&self, msg: &str); }

        pub type BoxedSink = Box<dyn Sink>;

        mod backend { pub fn flush() {} }

        impl Sink for Logger { fn write(&self, msg: &str) { log!(msg); } }

        fn main() {}
    """
    result = _extract(src, "src/main.rs")
    names = {s.name for s in result.symbols}
    kinds = {s.kind for s in result.symbols}
    assert "VERSION" in names
    assert "RUNNING" in names
    assert "log" in names
    assert "Level" in names
    assert "Logger" in names
    assert "Sink" in names
    assert "BoxedSink" in names
    assert "backend" in names
    assert "main" in names
    assert result.entry_points == ["src/main.rs"]
    assert "function" in kinds
    assert "type" in kinds
    assert "interface" in kinds
    assert "variable" in kinds
    assert "other" in kinds
    assert "module" in kinds
    rel_kinds = {r.kind for r in result.relationships}
    assert "import" in rel_kinds
    assert "uses" in rel_kinds


# ── error handling ────────────────────────────────────────────────────────────

def test_missing_file_returns_empty_result(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    missing = repo / "ghost.rs"
    result = EXTRACTOR.extract(missing, repo)
    assert result.symbols == []
    assert result.relationships == []

def test_empty_file():
    result = _extract("")
    assert result.symbols == []
