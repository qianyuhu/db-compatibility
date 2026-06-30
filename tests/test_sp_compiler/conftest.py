"""
Shared test fixtures for sp_compiler tests.

Provides sample T-SQL stored procedures covering all control flow patterns
and edge cases.
"""

import pytest


# ---------------------------------------------------------------------------
# Simple T-SQL stored procedure samples
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_select_sp() -> str:
    """Simple SELECT procedure with SET NOCOUNT."""
    return """\
CREATE PROCEDURE get_product_count
AS
BEGIN
    SET NOCOUNT ON;
    SELECT COUNT(*) AS cnt FROM products WHERE is_active = 1;
END"""


@pytest.fixture
def declare_and_assign_sp() -> str:
    """Procedure with DECLARE and SET."""
    return """\
CREATE PROCEDURE calc_total
AS
BEGIN
    DECLARE @total DECIMAL(10,2);
    DECLARE @tax DECIMAL(10,2);
    SET @total = 100.50;
    SET @tax = @total * 0.08;
    SELECT @total + @tax AS final_amount;
END"""


@pytest.fixture
def if_else_sp() -> str:
    """Procedure with IF/ELSE control flow."""
    return """\
CREATE PROCEDURE check_stock
    @product_id INT,
    @min_qty INT
AS
BEGIN
    DECLARE @current_qty INT;
    SET @current_qty = 0;
    SELECT @current_qty = quantity FROM inventory WHERE product_id = @product_id;
    IF @current_qty < @min_qty
    BEGIN
        SELECT 'Low stock' AS status;
    END
    ELSE
    BEGIN
        SELECT 'OK' AS status;
    END
END"""


@pytest.fixture
def while_loop_sp() -> str:
    """Procedure with WHILE loop."""
    return """\
CREATE PROCEDURE process_batch
    @batch_size INT
AS
BEGIN
    DECLARE @counter INT;
    SET @counter = 1;
    WHILE @counter <= @batch_size
    BEGIN
        UPDATE orders SET status = 'processed' WHERE id = @counter;
        SET @counter = @counter + 1;
    END
END"""


@pytest.fixture
def transaction_sp() -> str:
    """Procedure with transaction control."""
    return """\
CREATE PROCEDURE transfer_funds
    @from_id INT,
    @to_id INT,
    @amount DECIMAL(10,2)
AS
BEGIN
    BEGIN TRANSACTION;
    UPDATE accounts SET balance = balance - @amount WHERE id = @from_id;
    UPDATE accounts SET balance = balance + @amount WHERE id = @to_id;
    COMMIT TRANSACTION;
END"""


@pytest.fixture
def exec_sp() -> str:
    """Procedure that executes another procedure."""
    return """\
CREATE PROCEDURE run_report
AS
BEGIN
    EXEC sp_update_stats;
    SELECT 'Report complete' AS result;
END"""


@pytest.fixture
def return_sp() -> str:
    """Procedure with RETURN."""
    return """\
CREATE PROCEDURE validate_input
    @value INT
AS
BEGIN
    IF @value IS NULL
    BEGIN
        RETURN 1;
    END
    IF @value < 0
    BEGIN
        RETURN 2;
    END
    SELECT 'Valid' AS result;
    RETURN 0;
END"""


@pytest.fixture
def nested_if_sp() -> str:
    """Procedure with nested IF blocks."""
    return """\
CREATE PROCEDURE classify_product
    @price DECIMAL(10,2),
    @quantity INT
AS
BEGIN
    DECLARE @category VARCHAR(20);
    IF @quantity = 0
    BEGIN
        SET @category = 'Out of stock';
    END
    ELSE
    BEGIN
        IF @price > 100
        BEGIN
            SET @category = 'Premium';
        END
        ELSE
        BEGIN
            SET @category = 'Standard';
        END
    END
    SELECT @category AS category;
END"""


@pytest.fixture
def print_sp() -> str:
    """Procedure with PRINT statement."""
    return """\
CREATE PROCEDURE log_message
    @msg VARCHAR(200)
AS
BEGIN
    PRINT @msg;
    SELECT 1 AS logged;
END"""


# ---------------------------------------------------------------------------
# Edge case fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def empty_sp() -> str:
    """Empty procedure body."""
    return """\
CREATE PROCEDURE noop
AS
BEGIN
    SELECT 1 AS result;
END"""


@pytest.fixture
def single_statement_if_sp() -> str:
    """IF with single-statement body (no BEGIN/END)."""
    return """\
CREATE PROCEDURE simple_check
    @x INT
AS
BEGIN
    IF @x > 0
        SELECT 'Positive' AS result;
    ELSE
        SELECT 'Non-positive' AS result;
END"""


@pytest.fixture
def multiple_declare_sp() -> str:
    """Procedure with multiple DECLARE statements."""
    return """\
CREATE PROCEDURE multi_declare
AS
BEGIN
    DECLARE @a INT;
    DECLARE @b VARCHAR(50);
    DECLARE @c DECIMAL(10,2);
    DECLARE @d DATETIME;
    SET @a = 1;
    SET @b = 'test';
    SET @c = 99.99;
    SELECT @a AS a, @b AS b, @c AS c;
END"""


# ---------------------------------------------------------------------------
# Expected output patterns (for assertion in tests)
# ---------------------------------------------------------------------------


def expect_plpgsql_header(name: str) -> str:
    """Expected PL/pgSQL function header."""
    return f"CREATE OR REPLACE FUNCTION {name}("


def expect_dm_header(name: str) -> str:
    """Expected DM procedure header."""
    return f"CREATE OR REPLACE PROCEDURE {name}"


def expect_plpgsql_assignment(var: str) -> str:
    """Expected PL/pgSQL assignment."""
    return f"{var} :="


def expect_if_then() -> str:
    """Expected IF THEN pattern."""
    return "IF "


def expect_while_loop() -> str:
    """Expected WHILE LOOP pattern."""
    return "WHILE "


def expect_end_if() -> str:
    """Expected END IF pattern."""
    return "END IF;"


def expect_end_loop() -> str:
    """Expected END LOOP pattern."""
    return "END LOOP;"
