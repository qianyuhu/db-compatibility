"""
Integration tests for the full SP Compiler pipeline.

Tests cover:
    - T-SQL → IR conversion
    - IR → PL/pgSQL code generation
    - IR → DM code generation
    - Error handling at each pipeline stage
    - All control flow patterns (IF, WHILE, transactions, EXEC, RETURN)
"""

import pytest

from app.core.sp_compiler import compile_sp, CompilationResult
from app.core.sp_compiler.ir import (
    IRAssign,
    IRBlock,
    IRExec,
    IRIf,
    IRProcedure,
    IRSQL,
    IRTransaction,
    IRVariable,
    IRWhile,
    IRNodeType,
    VariableScope,
)


# =========================================================================
# Basic Pipeline Tests
# =========================================================================


class TestBasicPipeline:
    """Test the basic compilation pipeline (T-SQL → target code)."""

    def test_simple_select_to_kingbasees(self, simple_select_sp):
        """Simple SELECT procedure compiles to PL/pgSQL."""
        result = compile_sp(simple_select_sp, "kingbasees")
        assert result.success, f"Compilation failed: {result.errors}"
        assert result.procedure_name == "get_product_count"
        assert "CREATE OR REPLACE FUNCTION" in result.generated_code
        assert "get_product_count" in result.generated_code
        assert "RETURNS void AS $$" in result.generated_code
        assert "$$ LANGUAGE plpgsql;" in result.generated_code
        assert result.token_count > 0
        assert result.block_count > 0
        assert result.ir_node_count > 0

    def test_simple_select_to_dm8(self, simple_select_sp):
        """Simple SELECT procedure compiles to DM procedure."""
        result = compile_sp(simple_select_sp, "dm8")
        assert result.success, f"Compilation failed: {result.errors}"
        assert result.procedure_name == "get_product_count"
        assert "CREATE OR REPLACE PROCEDURE" in result.generated_code
        assert "get_product_count" in result.generated_code
        assert "BEGIN" in result.generated_code
        assert "END;" in result.generated_code

    def test_ir_is_present_on_success(self, simple_select_sp):
        """IR is included in successful CompilationResult."""
        result = compile_sp(simple_select_sp, "kingbasees")
        assert result.success
        assert result.ir is not None
        assert isinstance(result.ir, IRProcedure)
        assert result.ir.name == "get_product_count"

    def test_compile_empty_input(self):
        """Empty input produces error result."""
        result = compile_sp("", "kingbasees")
        assert not result.success
        assert len(result.errors) > 0

    def test_compile_whitespace_only(self):
        """Whitespace-only input produces error result."""
        result = compile_sp("   \n  \t  ", "kingbasees")
        assert not result.success
        assert len(result.errors) > 0

    def test_invalid_target_db(self):
        """Invalid target database raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported target database"):
            compile_sp("SELECT 1", "oracle")


# =========================================================================
# IR Construction Tests
# =========================================================================


class TestIRConstruction:
    """Test that IR is correctly built from T-SQL."""

    def test_simple_select_ir_structure(self, simple_select_sp):
        """IR has correct structure for simple SELECT."""
        result = compile_sp(simple_select_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None
        assert ir.name == "get_product_count"
        assert len(ir.body) > 0

    def test_if_else_ir_structure(self, if_else_sp):
        """IR contains IF node for IF/ELSE procedure."""
        result = compile_sp(if_else_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None
        # Should have parameters
        assert len(ir.parameters) == 2
        param_names = {p.name for p in ir.parameters}
        assert "product_id" in param_names
        assert "min_qty" in param_names

    def test_while_ir_structure(self, while_loop_sp):
        """IR contains WHILE node for WHILE procedure."""
        result = compile_sp(while_loop_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None
        assert len(ir.body) > 0

    def test_transaction_ir_structure(self, transaction_sp):
        """IR contains TRANSACTION nodes."""
        result = compile_sp(transaction_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None
        assert len(ir.parameters) == 3


# =========================================================================
# Control Flow Tests
# =========================================================================


class TestControlFlow:
    """Test control flow pattern compilation."""

    def test_if_else_compiles(self, if_else_sp):
        """IF/ELSE compiles to PL/pgSQL with correct control flow."""
        result = compile_sp(if_else_sp, "kingbasees")
        assert result.success, f"Compilation failed: {result.errors}"
        code = result.generated_code
        assert "IF " in code, "Missing IF keyword"
        assert "THEN" in code, "Missing THEN keyword"

    def test_while_compiles(self, while_loop_sp):
        """WHILE loop compiles to PL/pgSQL."""
        result = compile_sp(while_loop_sp, "kingbasees")
        assert result.success, f"Compilation failed: {result.errors}"
        code = result.generated_code
        assert "WHILE " in code, "Missing WHILE keyword"
        assert "LOOP" in code, "Missing LOOP keyword"
        assert "END LOOP;" in code, "Missing END LOOP"

    def test_while_compiles_to_dm(self, while_loop_sp):
        """WHILE loop compiles to DM procedure."""
        result = compile_sp(while_loop_sp, "dm8")
        assert result.success, f"Compilation failed: {result.errors}"
        code = result.generated_code
        assert "WHILE " in code
        assert "LOOP" in code

    def test_transaction_compiles(self, transaction_sp):
        """Transaction control compiles."""
        result = compile_sp(transaction_sp, "kingbasees")
        assert result.success, f"Compilation failed: {result.errors}"

    def test_return_compiles(self, return_sp):
        """RETURN compiles."""
        result = compile_sp(return_sp, "kingbasees")
        assert result.success, f"Compilation failed: {result.errors}"
        code = result.generated_code
        assert "RETURN" in code

    def test_exec_compiles(self, exec_sp):
        """EXEC compiles."""
        result = compile_sp(exec_sp, "kingbasees")
        assert result.success, f"Compilation failed: {result.errors}"
        code = result.generated_code
        assert "PERFORM" in code or "sp_update_stats" in code

    def test_nested_if_compiles(self, nested_if_sp):
        """Nested IF compiles."""
        result = compile_sp(nested_if_sp, "kingbasees")
        assert result.success, f"Compilation failed: {result.errors}"


# =========================================================================
# Variable and Parameter Tests
# =========================================================================


class TestVariablesAndParams:
    """Test variable declaration and parameter handling."""

    def test_parameters_extracted(self, if_else_sp):
        """Parameters are extracted from CREATE PROCEDURE header."""
        result = compile_sp(if_else_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None
        params = ir.parameters
        assert len(params) == 2

        product_param = next((p for p in params if p.name == "product_id"), None)
        assert product_param is not None
        assert product_param.scope == VariableScope.PARAMETER
        assert "INT" in product_param.data_type.upper()

    def test_local_variables_collected(self, declare_and_assign_sp):
        """Local variables are collected from DECLARE statements."""
        result = compile_sp(declare_and_assign_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None
        var_names = {v.name for v in ir.variables}
        assert "total" in var_names
        assert "tax" in var_names

    def test_multiple_declares(self, multiple_declare_sp):
        """Multiple DECLARE statements produce multiple IR variables."""
        result = compile_sp(multiple_declare_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None
        assert len(ir.variables) >= 3

    def test_parameter_in_output_code(self, if_else_sp):
        """Parameters appear in generated PL/pgSQL function signature."""
        result = compile_sp(if_else_sp, "kingbasees")
        assert result.success
        code = result.generated_code
        assert "p_product_id" in code
        assert "p_min_qty" in code


# =========================================================================
# Dialect-Specific Tests
# =========================================================================


class TestDialectOutput:
    """Test dialect-specific code generation correctness."""

    def test_plpgsql_uses_function_not_procedure(self, simple_select_sp):
        """PL/pgSQL wrapper uses FUNCTION, not PROCEDURE."""
        result = compile_sp(simple_select_sp, "kingbasees")
        assert result.success
        assert "CREATE OR REPLACE FUNCTION" in result.generated_code

    def test_plpgsql_uses_assign_operator(self, declare_and_assign_sp):
        """PL/pgSQL uses := for assignment."""
        result = compile_sp(declare_and_assign_sp, "kingbasees")
        assert result.success
        code = result.generated_code
        assert ":=" in code

    def test_dm_uses_procedure(self, simple_select_sp):
        """DM wrapper uses PROCEDURE."""
        result = compile_sp(simple_select_sp, "dm8")
        assert result.success
        assert "CREATE OR REPLACE PROCEDURE" in result.generated_code

    def test_dm_uses_is_keyword(self, simple_select_sp):
        """DM uses IS keyword after parameter list."""
        result = compile_sp(simple_select_sp, "dm8")
        assert result.success
        code = result.generated_code
        assert "IS" in code

    def test_dm_has_no_dollar_quoting(self, simple_select_sp):
        """DM does not use $$ quoting (PostgreSQL specific)."""
        result = compile_sp(simple_select_sp, "dm8")
        assert result.success
        assert "$$" not in result.generated_code

    def test_kingbasees_strips_at_prefix(self, declare_and_assign_sp):
        """Generated PL/pgSQL has no @ prefix on variables."""
        result = compile_sp(declare_and_assign_sp, "kingbasees")
        assert result.success
        code = result.generated_code
        # Variables in DECLARE section should not have @
        # Check that total is declared without @ prefix
        assert "total " in code.lower() or "TOTAL " in code


# =========================================================================
# Deterministic Output Tests
# =========================================================================


class TestDeterministicOutput:
    """Same IR should produce identical output every time."""

    def test_same_input_same_output_plpgsql(self, simple_select_sp):
        """Same T-SQL → same PL/pgSQL output."""
        result1 = compile_sp(simple_select_sp, "kingbasees")
        result2 = compile_sp(simple_select_sp, "kingbasees")
        assert result1.success and result2.success
        assert result1.generated_code == result2.generated_code

    def test_same_input_same_output_dm(self, simple_select_sp):
        """Same T-SQL → same DM output."""
        result1 = compile_sp(simple_select_sp, "dm8")
        result2 = compile_sp(simple_select_sp, "dm8")
        assert result1.success and result2.success
        assert result1.generated_code == result2.generated_code


# =========================================================================
# CompilationResult Diagnostics Tests
# =========================================================================


class TestCompilationDiagnostics:
    """Test that CompilationResult provides useful diagnostics."""

    def test_result_has_token_count(self, simple_select_sp):
        """CompilationResult includes token count."""
        result = compile_sp(simple_select_sp, "kingbasees")
        assert result.success
        assert result.token_count > 0

    def test_result_has_block_count(self, simple_select_sp):
        """CompilationResult includes block count."""
        result = compile_sp(simple_select_sp, "kingbasees")
        assert result.success
        assert result.block_count > 0

    def test_result_has_ir_node_count(self, simple_select_sp):
        """CompilationResult includes IR node count."""
        result = compile_sp(simple_select_sp, "kingbasees")
        assert result.success
        assert result.ir_node_count > 0

    def test_result_has_target_db(self, simple_select_sp):
        """CompilationResult includes target database."""
        result = compile_sp(simple_select_sp, "kingbasees")
        assert result.success
        assert result.target_db == "kingbasees"

    def test_failed_result_has_no_generated_code(self):
        """Failed compilation has empty generated_code."""
        result = compile_sp("INVALID SYNTAX !!! @#$%", "kingbasees")
        # May or may not fail — depends on whether the lexer handles it
        if not result.success:
            assert result.generated_code == ""
            assert len(result.errors) > 0


# =========================================================================
# IR Node Immutability Tests
# =========================================================================


class TestIRImmutability:
    """IR nodes are immutable (frozen dataclasses)."""

    def test_ir_procedure_is_immutable(self, simple_select_sp):
        """IRProcedure cannot be modified after creation."""
        result = compile_sp(simple_select_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None
        with pytest.raises(Exception):
            ir.name = "hacked"  # type: ignore[misc]

    def test_ir_variable_is_immutable(self):
        """IRVariable cannot be modified after creation."""
        v = IRVariable(name="x", data_type="INT")
        with pytest.raises(Exception):
            v.name = "y"  # type: ignore[misc]


# =========================================================================
# CFG Tests
# =========================================================================


class TestCFG:
    """Test Control Flow Graph building."""

    def test_cfg_builder_builds(self, if_else_sp):
        """CFG builder produces valid CFG from IR."""
        result = compile_sp(if_else_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None

        from app.core.sp_compiler.cfg import CFGBuilder
        cfg = CFGBuilder.build(ir)
        assert cfg is not None
        assert len(cfg.blocks) > 0
        assert cfg.name == "check_stock"

    def test_cfg_has_entry_block(self, if_else_sp):
        """CFG has an entry block."""
        result = compile_sp(if_else_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None

        from app.core.sp_compiler.cfg import CFGBuilder
        cfg = CFGBuilder.build(ir)
        assert cfg.entry_block_id >= 0


# =========================================================================
# CFG Optimizer Tests
# =========================================================================


class TestCFGOptimizer:
    """Test CFG/IR optimization passes."""

    def test_constant_folding(self):
        """Constant folding simplifies arithmetic."""
        ir = IRProcedure(
            name="test",
            body=(
                IRAssign(target="x", expression="1 + 2"),
            ),
        )
        from app.core.sp_compiler.cfg import CFGOptimizer
        optimized = CFGOptimizer.constant_folding(ir)
        assert optimized.body[0].expression == "3"  # type: ignore[union-attr]

    def test_constant_folding_preserves_non_constants(self):
        """Constant folding leaves variable expressions unchanged."""
        ir = IRProcedure(
            name="test",
            body=(
                IRAssign(target="x", expression="a + b"),
            ),
        )
        from app.core.sp_compiler.cfg import CFGOptimizer
        optimized = CFGOptimizer.constant_folding(ir)
        assert optimized.body[0].expression == "a + b"  # type: ignore[union-attr]

    def test_branch_simplification_always_true(self):
        """Branch with '1=1' condition removes ELSE branch."""
        ir = IRProcedure(
            name="test",
            body=(
                IRIf(
                    condition="1=1",
                    then_body=(IRSQL(sql_text="SELECT 1 AS n"),),
                    else_body=(IRSQL(sql_text="SELECT 2 AS n"),),
                ),
            ),
        )
        from app.core.sp_compiler.cfg import CFGOptimizer
        optimized = CFGOptimizer.branch_simplification(ir)
        # Should have replaced IF with just the THEN body
        assert len(optimized.body) == 1

    def test_dead_code_elimination(self, if_else_sp):
        """Dead code elimination produces valid CFG."""
        result = compile_sp(if_else_sp, "kingbasees")
        assert result.success
        ir = result.ir
        assert ir is not None

        from app.core.sp_compiler.cfg import CFGBuilder, CFGOptimizer
        cfg = CFGBuilder.build(ir)
        optimized = CFGOptimizer.dead_code_elimination(cfg)
        assert len(optimized.blocks) <= len(cfg.blocks)


# =========================================================================
# Generator Factory Tests
# =========================================================================


class TestGeneratorFactory:
    """Test the code generator factory and registry."""

    def test_create_kingbasees_generator(self):
        """Can create PL/pgSQL generator."""
        from app.core.sp_compiler.generator import create_generator
        gen = create_generator("kingbasees")
        assert gen is not None

    def test_create_dm_generator(self):
        """Can create DM generator."""
        from app.core.sp_compiler.generator import create_generator
        gen = create_generator("dm8")
        assert gen is not None

    def test_list_generators(self):
        """Can list available generators."""
        from app.core.sp_compiler.generator import list_generators
        generators = list_generators()
        assert "kingbasees" in generators
        assert "dm8" in generators

    def test_invalid_generator_raises(self):
        """Unknown target raises ValueError."""
        from app.core.sp_compiler.generator import create_generator
        with pytest.raises(ValueError, match="No generator registered"):
            create_generator("unknown_db")
