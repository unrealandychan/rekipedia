"""Tests for Go, Rust, and Java AST extractors."""
# Copyright 2026 Eddie Chan. All rights reserved.
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from rekipedia.extractors.go_extractor import GoExtractor
from rekipedia.extractors.java_extractor import JavaExtractor
from rekipedia.extractors.rust_extractor import RustExtractor


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _write(tmp: Path, name: str, content: str) -> Path:
    p = tmp / name
    p.write_text(content, encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────
# GoExtractor tests
# ─────────────────────────────────────────────────────────────

GO_CODE = '''\
package main

import "fmt"
import "os"

func main() {
    fmt.Println("hello")
}

func Add(a int, b int) int {
    return a + b
}

type Point struct {
    X float64
    Y float64
}

type Shape interface {
    Area() float64
}
'''


class TestGoExtractor:
    def setup_method(self):
        self.extractor = GoExtractor()

    def test_can_handle(self):
        assert self.extractor.can_handle(Path("foo.go"))
        assert not self.extractor.can_handle(Path("foo.py"))

    def test_basic_symbol_extraction(self, tmp_path):
        p = _write(tmp_path, "main.go", GO_CODE)
        result = self.extractor.extract(p, tmp_path)
        names = [s.name for s in result.symbols]
        assert "main" in names
        assert "Add" in names
        assert "Point" in names
        assert "Shape" in names

    def test_symbol_kinds(self, tmp_path):
        p = _write(tmp_path, "main.go", GO_CODE)
        result = self.extractor.extract(p, tmp_path)
        kinds = {s.name: s.kind for s in result.symbols}
        assert kinds["main"] == "function"
        assert kinds["Add"] == "function"
        assert kinds["Point"] == "type"
        assert kinds["Shape"] == "interface"

    def test_relationship_extraction(self, tmp_path):
        p = _write(tmp_path, "main.go", GO_CODE)
        result = self.extractor.extract(p, tmp_path)
        import_tos = {r.to for r in result.relationships if r.kind == "import"}
        assert "fmt" in import_tos
        assert "os" in import_tos

    def test_entry_point_detection(self, tmp_path):
        p = _write(tmp_path, "main.go", GO_CODE)
        result = self.extractor.extract(p, tmp_path)
        assert len(result.entry_points) == 1

    def test_empty_file(self, tmp_path):
        p = _write(tmp_path, "empty.go", "")
        result = self.extractor.extract(p, tmp_path)
        assert result.symbols == []
        assert result.relationships == []
        assert result.entry_points == []

    def test_line_numbers(self, tmp_path):
        p = _write(tmp_path, "main.go", GO_CODE)
        result = self.extractor.extract(p, tmp_path)
        fn_map = {s.name: s for s in result.symbols if s.kind == "function"}
        assert fn_map["main"].line_start is not None
        assert fn_map["main"].line_start >= 1

    def test_struct_embedding_inherits(self, tmp_path):
        """Embedded struct fields should produce 'inherits' relationships."""
        code = '''\
package main

type Animal struct {
    Name string
}

type Dog struct {
    Animal
    Breed string
}

type PoliceDog struct {
    *Dog
    Badge int
}
'''
        p = _write(tmp_path, "animals.go", code)
        result = self.extractor.extract(p, tmp_path)
        inherits = [(r.from_, r.to) for r in result.relationships if r.kind == "inherits"]
        assert ("Dog", "Animal") in inherits, f"Expected Dog→Animal, got {inherits}"
        assert ("PoliceDog", "Dog") in inherits, f"Expected PoliceDog→Dog, got {inherits}"

    def test_struct_no_embedding_no_inherits(self, tmp_path):
        """Plain struct fields must not produce inherits relationships."""
        code = '''\
package main

type Point struct {
    X float64
    Y float64
}
'''
        p = _write(tmp_path, "point.go", code)
        result = self.extractor.extract(p, tmp_path)
        inherits = [r for r in result.relationships if r.kind == "inherits"]
        assert inherits == [], f"Expected no inherits, got {inherits}"

# ─────────────────────────────────────────────────────────────
# RustExtractor tests
# ─────────────────────────────────────────────────────────────

RUST_CODE = '''\
use std::io;
use std::collections::HashMap;

fn main() {
    println!("hello");
}

fn add(a: i32, b: i32) -> i32 {
    a + b
}

struct Point {
    x: f64,
    y: f64,
}

trait Shape {
    fn area(&self) -> f64;
}

impl Shape for Point {
    fn area(&self) -> f64 {
        0.0
    }
}
'''


class TestRustExtractor:
    def setup_method(self):
        self.extractor = RustExtractor()

    def test_can_handle(self):
        assert self.extractor.can_handle(Path("lib.rs"))
        assert not self.extractor.can_handle(Path("lib.py"))

    def test_basic_symbol_extraction(self, tmp_path):
        p = _write(tmp_path, "main.rs", RUST_CODE)
        result = self.extractor.extract(p, tmp_path)
        names = [s.name for s in result.symbols]
        assert "main" in names
        assert "add" in names
        assert "Point" in names
        assert "Shape" in names

    def test_symbol_kinds(self, tmp_path):
        p = _write(tmp_path, "main.rs", RUST_CODE)
        result = self.extractor.extract(p, tmp_path)
        kinds = {s.name: s.kind for s in result.symbols}
        assert kinds["main"] == "function"
        assert kinds["add"] == "function"
        assert kinds["Point"] == "type"
        assert kinds["Shape"] == "interface"

    def test_relationship_import(self, tmp_path):
        p = _write(tmp_path, "main.rs", RUST_CODE)
        result = self.extractor.extract(p, tmp_path)
        import_tos = {r.to for r in result.relationships if r.kind == "import"}
        assert len(import_tos) >= 1

    def test_impl_uses_relationship(self, tmp_path):
        p = _write(tmp_path, "main.rs", RUST_CODE)
        result = self.extractor.extract(p, tmp_path)
        uses_rels = [r for r in result.relationships if r.kind == "uses"]
        assert len(uses_rels) >= 1
        assert any(r.to == "Shape" for r in uses_rels)

    def test_entry_point_detection(self, tmp_path):
        p = _write(tmp_path, "main.rs", RUST_CODE)
        result = self.extractor.extract(p, tmp_path)
        assert len(result.entry_points) == 1

    def test_empty_file(self, tmp_path):
        p = _write(tmp_path, "empty.rs", "")
        result = self.extractor.extract(p, tmp_path)
        assert result.symbols == []
        assert result.relationships == []


# ─────────────────────────────────────────────────────────────
# JavaExtractor tests
# ─────────────────────────────────────────────────────────────

JAVA_CODE = '''\
import java.util.List;
import java.io.IOException;

public class Animal {
    public void speak() {}
}

public class Dog extends Animal {
    public void speak() {
        System.out.println("Woof");
    }

    public static void main(String[] args) {
        System.out.println("start");
    }
}

public interface Runnable {
    void run();
}
'''


class TestJavaExtractor:
    def setup_method(self):
        self.extractor = JavaExtractor()

    def test_can_handle(self):
        assert self.extractor.can_handle(Path("Dog.java"))
        assert not self.extractor.can_handle(Path("Dog.go"))

    def test_basic_symbol_extraction(self, tmp_path):
        p = _write(tmp_path, "Dog.java", JAVA_CODE)
        result = self.extractor.extract(p, tmp_path)
        names = [s.name for s in result.symbols]
        assert "Animal" in names
        assert "Dog" in names
        assert "Runnable" in names

    def test_method_extraction(self, tmp_path):
        p = _write(tmp_path, "Dog.java", JAVA_CODE)
        result = self.extractor.extract(p, tmp_path)
        func_names = [s.name for s in result.symbols if s.kind == "function"]
        assert "speak" in func_names
        assert "main" in func_names

    def test_inheritance_relationship(self, tmp_path):
        p = _write(tmp_path, "Dog.java", JAVA_CODE)
        result = self.extractor.extract(p, tmp_path)
        inherits = [r for r in result.relationships if r.kind == "inherits"]
        assert any(r.from_ == "Dog" and r.to == "Animal" for r in inherits)

    def test_import_relationship(self, tmp_path):
        p = _write(tmp_path, "Dog.java", JAVA_CODE)
        result = self.extractor.extract(p, tmp_path)
        import_tos = {r.to for r in result.relationships if r.kind == "import"}
        assert len(import_tos) >= 1

    def test_interface_symbol(self, tmp_path):
        p = _write(tmp_path, "Dog.java", JAVA_CODE)
        result = self.extractor.extract(p, tmp_path)
        ifaces = [s for s in result.symbols if s.kind == "interface"]
        assert any(s.name == "Runnable" for s in ifaces)

    def test_empty_file(self, tmp_path):
        p = _write(tmp_path, "Empty.java", "")
        result = self.extractor.extract(p, tmp_path)
        assert result.symbols == []
        assert result.relationships == []
        assert result.entry_points == []
