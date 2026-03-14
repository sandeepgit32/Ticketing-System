from fastapi import HTTPException


def get_db_connection(db_pool):
    """Acquire a connection from the pool.

    Args:
        db_pool: A connection pool instance (e.g. mysql.connector.pooling.MySQLConnectionPool).

    Returns:
        A live database connection object.

    Notes:
        The caller is responsible for closing the connection when finished.
    """
    return db_pool.get_connection()


def require_db_pool(db_pool):
    """Ensure a DB pool is available.

    Args:
        db_pool: The current database pool instance (may be None).

    Returns:
        The same db_pool instance if it is truthy.

    Raises:
        fastapi.HTTPException: If the pool is not available.
    """

    if not db_pool:
        raise HTTPException(status_code=503, detail="database unavailable")
    return db_pool


def fetch_one(db_pool, query: str, params: tuple = None):
    """Execute a SELECT query and return a single row as a dict.

    This helper is intended for queries that return at most one row.

    Args:
        db_pool: A connection pool instance.
        query: The SQL SELECT query string.
        params: Optional tuple of parameters to bind to the query.

    Returns:
        A dict representing the first row of the result set, or None if no rows were returned.

    Notes:
        - The connection and cursor are closed before returning.
        - Exceptions from the DB driver are propagated to the caller.
    """
    conn = get_db_connection(db_pool)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params or ())
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def fetch_all(db_pool, query: str, params: tuple = None):
    """Execute a SELECT query and return all rows as a list of dicts.

    Args:
        db_pool: A connection pool instance.
        query: The SQL SELECT query string.
        params: Optional tuple of parameters to bind to the query.

    Returns:
        A list of dicts representing each row in the result set. Returns an empty list if no rows are returned.

    Notes:
        - The connection and cursor are closed before returning.
        - Exceptions from the DB driver are propagated to the caller.
    """
    conn = get_db_connection(db_pool)
    cursor = conn.cursor(dictionary=True)
    cursor.execute(query, params or ())
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def execute_query(db_pool, query: str, params: tuple = None):
    """Execute a DML statement (INSERT/UPDATE/DELETE) and commit the transaction.

    Args:
        db_pool: A connection pool instance.
        query: The SQL statement to execute.
        params: Optional tuple of parameters to bind to the statement.

    Notes:
        - This helper commits after executing the statement.
        - The connection and cursor are closed before returning.
        - Exceptions from the DB driver are propagated to the caller.
        - Depending on the driver, an exception may cause an implicit rollback when the connection is closed.
    """
    conn = get_db_connection(db_pool)
    cursor = conn.cursor()
    cursor.execute(query, params or ())
    conn.commit()
    cursor.close()
    conn.close()
