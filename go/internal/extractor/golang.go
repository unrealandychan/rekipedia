package extractor

import (
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"strings"

	"github.com/unrealandychan/rekipedia/internal/models"
)

// GoExtractor uses go/ast (stdlib) to parse .go files — no CGO or external deps.
// Extracts: packages, functions, methods, structs, interfaces, constants, variables,
// imports (internal vs external), entry points (main), and TODO/FIXME risks.
type GoExtractor struct{}

// NewGoExtractor returns a new GoExtractor.
func NewGoExtractor() *GoExtractor { return &GoExtractor{} }

// CanHandle returns true for .go files.
func (e *GoExtractor) CanHandle(ext string) bool {
	return strings.ToLower(ext) == ".go"
}

// Extract parses a Go source file and extracts symbols and relationships.
func (e *GoExtractor) Extract(absPath, relPath string) models.AnalysisResult {
	result := models.AnalysisResult{
		ShardID:   relPath,
		FilesSeen: []string{relPath},
		Evidence:  make(map[string]string),
	}

	fset := token.NewFileSet()
	f, err := parser.ParseFile(fset, absPath, nil, parser.ParseComments)
	if err != nil {
		result.Risks = append(result.Risks, "parse error: "+relPath+": "+err.Error())
		return result
	}

	pkgName := f.Name.Name

	// ── Imports ──────────────────────────────────────────────────────────────
	for _, imp := range f.Imports {
		path := strings.Trim(imp.Path.Value, `"`)
		result.Relationships = append(result.Relationships, models.Relationship{
			From: relPath,
			To:   path,
			Kind: models.RelImport,
			File: relPath,
		})
	}

	// ── Top-level declarations ────────────────────────────────────────────────
	for _, decl := range f.Decls {
		switch d := decl.(type) {

		case *ast.FuncDecl:
			name := funcDeclName(pkgName, d)
			pos := fset.Position(d.Pos())
			kind := models.SymbolFunction
			if d.Recv != nil {
				kind = models.SymbolMethod
			}
			// Entry point detection
			if d.Name.Name == "main" && pkgName == "main" {
				result.EntryPoints = append(result.EntryPoints, relPath+":main")
			}
			result.Symbols = append(result.Symbols, models.Symbol{
				Name:      name,
				Kind:      kind,
				File:      relPath,
				LineStart: pos.Line,
				Docstring: docString(d.Doc),
			})

		case *ast.GenDecl:
			for _, spec := range d.Specs {
				switch s := spec.(type) {

				case *ast.TypeSpec:
					kind := models.SymbolClass
					switch s.Type.(type) {
					case *ast.InterfaceType:
						kind = models.SymbolInterface
					}
					result.Symbols = append(result.Symbols, models.Symbol{
						Name:      pkgName + "." + s.Name.Name,
						Kind:      kind,
						File:      relPath,
						LineStart: fset.Position(s.Pos()).Line,
						Docstring: docString(d.Doc),
					})

				case *ast.ValueSpec:
					symKind := models.SymbolVariable
					if d.Tok == token.CONST {
						symKind = models.SymbolConstant
					}
					for _, name := range s.Names {
						result.Symbols = append(result.Symbols, models.Symbol{
							Name:      pkgName + "." + name.Name,
							Kind:      symKind,
							File:      relPath,
							LineStart: fset.Position(name.Pos()).Line,
						})
					}
				}
			}
		}
	}

	// ── TODO / FIXME risks from comments ─────────────────────────────────────
	for _, cg := range f.Comments {
		for _, c := range cg.List {
			text := strings.TrimLeft(c.Text, "/ ")
			upper := strings.ToUpper(text)
			if strings.Contains(upper, "TODO") || strings.Contains(upper, "FIXME") ||
				strings.Contains(upper, "HACK") || strings.Contains(upper, "XXX") {
				pos := fset.Position(c.Pos())
				result.Risks = append(result.Risks,
					fmt.Sprintf("%s:%d: %s", relPath, pos.Line, strings.TrimSpace(text)))
			}
		}
	}

	// ── Build/test command hints ──────────────────────────────────────────────
	if pkgName == "main" {
		result.BuildCommands = append(result.BuildCommands, "go build ./...")
		result.TestCommands = append(result.TestCommands, "go test ./...")
	}

	return result
}

// funcDeclName returns "pkg.ReceiverType.FuncName" or "pkg.FuncName".
func funcDeclName(pkg string, d *ast.FuncDecl) string {
	base := pkg + "." + d.Name.Name
	if d.Recv == nil || len(d.Recv.List) == 0 {
		return base
	}
	recv := d.Recv.List[0]
	switch t := recv.Type.(type) {
	case *ast.StarExpr:
		if id, ok := t.X.(*ast.Ident); ok {
			return pkg + "." + id.Name + "." + d.Name.Name
		}
	case *ast.Ident:
		return pkg + "." + t.Name + "." + d.Name.Name
	}
	return base
}

// docString extracts the text from an *ast.CommentGroup (may be nil).
func docString(cg *ast.CommentGroup) string {
	if cg == nil {
		return ""
	}
	var b strings.Builder
	for _, c := range cg.List {
		b.WriteString(strings.TrimLeft(c.Text, "/ "))
		b.WriteByte('\n')
	}
	return strings.TrimSpace(b.String())
}
